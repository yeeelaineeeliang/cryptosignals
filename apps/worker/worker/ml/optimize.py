"""Optimization loop — applies plans from analyze.py and tracks outcomes.

Runs after every evaluate_models cycle (hourly). Two-phase design:

Phase A — Confirm pending plans:
  Plans written in the prior cycle have model_version_id pointing to the new
  model. If that model now has a model_performance row, compare metric_after
  to metric_before and mark confirmed=TRUE/FALSE.

Phase B — Analyze and act:
  For each watched pair:
    1. Check stop condition (win_rate > 0.55 AND sharpe > 1.5 for N runs).
    2. Call analyze.analyze_model() for an OptimizationPlan.
    3. Snapshot metric_before, write optimization_history row.
    4. Apply the plan:
       - 'signal_threshold' : no refit needed (threshold is per-symbol advisory)
       - 'refit_now'         : trigger refit with current settings
       - 'vif_threshold'     : trigger refit with tightened VIF_HARD override
       - 'lookback_window'   : trigger refit with shortened lookback_days override
    5. After refit, record new_model_version_id inside the plan JSONB so Phase A
       can resolve it on the next tick.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from supabase import Client

from ..config import Settings
from ..logging_setup import get_logger
from ..ml.persistence import load_active
from .analyze import (
    OptimizationPlan,
    _STOP_CONSECUTIVE_RUNS,
    _STOP_SHARPE,
    _STOP_WIN_RATE,
    _safe_float,
    analyze_model,
)
from .refit import refit_models

log = get_logger(__name__)


# ---------- helpers ----------------------------------------------------

def _latest_perf(sb: Client, model_id: int) -> dict[str, Any] | None:
    res = (
        sb.table("model_performance")
        .select(
            "id, hit_rate, win_rate, sharpe_live, max_drawdown, "
            "avg_pnl_per_trade, feature_drift_pct, evaluated_at"
        )
        .eq("model_version_id", model_id)
        .order("evaluated_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def _first_perf_after(sb: Client, model_id: int, after_ts: str) -> dict[str, Any] | None:
    """Return the earliest model_performance row for model_id with evaluated_at > after_ts."""
    res = (
        sb.table("model_performance")
        .select(
            "id, hit_rate, win_rate, sharpe_live, max_drawdown, "
            "avg_pnl_per_trade, feature_drift_pct, evaluated_at"
        )
        .eq("model_version_id", model_id)
        .gt("evaluated_at", after_ts)
        .order("evaluated_at", desc=False)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def _record_plan(
    sb: Client,
    plan: OptimizationPlan,
    symbol: str,
    old_model_id: int,
    metric_before: dict[str, Any],
) -> int:
    res = sb.table("optimization_history").insert({
        "symbol": symbol,
        "model_version_id": old_model_id,
        "plan": plan.as_dict(),
        "hypothesis": plan.hypothesis,
        "metric_before": metric_before,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }).execute()
    return int(res.data[0]["run_id"])


def _plan_to_overrides(plan: OptimizationPlan) -> dict[str, Any]:
    """Translate plan fields into kwargs accepted by refit_models."""
    if plan.change_type == "vif_threshold":
        return {"vif_hard": float(plan.new_value)}
    if plan.change_type == "lookback_window":
        return {"lookback_days": int(plan.new_value)}
    return {}  # 'refit_now' uses default settings


def _is_target_reached(sb: Client, model_id: int) -> bool:
    """Return True if stop condition met (N consecutive runs above targets)."""
    res = (
        sb.table("model_performance")
        .select("win_rate, sharpe_live")
        .eq("model_version_id", model_id)
        .order("evaluated_at", desc=True)
        .limit(_STOP_CONSECUTIVE_RUNS)
        .execute()
    )
    rows = res.data or []
    if len(rows) < _STOP_CONSECUTIVE_RUNS:
        return False
    return all(
        _safe_float(r.get("win_rate")) is not None
        and _safe_float(r["win_rate"]) > _STOP_WIN_RATE
        and _safe_float(r.get("sharpe_live")) is not None
        and _safe_float(r["sharpe_live"]) > _STOP_SHARPE
        for r in rows
    )


# ---------- Phase A: confirm pending plans -----------------------------

def _confirm_pending(sb: Client) -> None:
    """Resolve any optimization_history rows where confirmed IS NULL."""
    res = (
        sb.table("optimization_history")
        .select("run_id, symbol, model_version_id, plan, metric_before, timestamp")
        .is_("confirmed", "null")
        .execute()
    )
    for row in (res.data or []):
        plan_dict: dict = row["plan"]
        symbol: str = row["symbol"]
        change_type: str = plan_dict.get("change_type", "")
        old_model_id: int = int(row["model_version_id"])
        plan_ts: str = row["timestamp"]

        # Determine which model to score against.
        # Refit-based changes record new_model_version_id in the plan JSONB when
        # _apply_plan succeeds.  If it's absent (refit returned no improvement, or
        # a signal_threshold change that never triggers a refit), fall back:
        #   - signal_threshold: score the same model — the threshold is advisory and
        #     takes effect immediately in inference without changing the model.
        #   - all other refit types where recording failed: use the current active
        #     model for the symbol, which may have been promoted by a later refit.
        recorded_new = plan_dict.get("new_model_version_id")
        if recorded_new:
            target_model_id = int(recorded_new)
        elif change_type == "signal_threshold":
            target_model_id = old_model_id
        else:
            active_res = (
                sb.table("model_versions")
                .select("id")
                .eq("symbol", symbol)
                .eq("is_active", True)
                .maybe_single()
                .execute()
            )
            if not active_res or not active_res.data:
                continue
            target_model_id = int(active_res.data["id"])

        # Use the first eval AFTER the plan was written so we are measuring the
        # post-change state, not a pre-change snapshot.
        metric_after = _first_perf_after(sb, target_model_id, plan_ts)
        if metric_after is None:
            continue  # not evaluated yet; check again next tick

        metric_before: dict = row["metric_before"]
        expected_metric: str = plan_dict.get("expected_metric", "hit_rate")
        expected_delta: float = float(plan_dict.get("expected_delta", 0))

        before_val = _safe_float(metric_before.get(expected_metric)) or 0.0
        after_val = _safe_float(metric_after.get(expected_metric)) or 0.0
        actual_delta = after_val - before_val

        # Confirmed if the change moved at least 50% as far as expected, in the
        # right direction.  expected_delta can be negative (e.g. feature_drift_pct
        # should decrease), so we normalise by the ratio instead of using >= which
        # is directionally wrong for negative targets.
        if expected_delta != 0:
            confirmed = (actual_delta / expected_delta) >= 0.5
        else:
            confirmed = actual_delta >= 0

        sb.table("optimization_history").update({
            "confirmed": confirmed,
            "metric_after": metric_after,
        }).eq("run_id", row["run_id"]).execute()

        log.info(
            "optimize_confirmed",
            run_id=row["run_id"],
            confirmed=confirmed,
            symbol=symbol,
            change_type=change_type,
            target_model_id=target_model_id,
            expected_metric=expected_metric,
            expected_delta=expected_delta,
            actual_delta=round(actual_delta, 5),
        )


# ---------- Phase B: analyze and act -----------------------------------

async def _apply_plan(
    sb: Client,
    settings: Settings,
    plan: OptimizationPlan,
    run_id: int,
    old_model_id: int,
) -> None:
    """Execute the plan and, if a refit was triggered, record the new model id."""
    if plan.change_type == "signal_threshold":
        # No refit — the threshold is advisory (logged; the user can act or the
        # evaluate loop will detect improvement/no-improvement next cycle).
        log.info(
            "optimize_threshold_advisory",
            symbol=plan.symbol,
            parameter=plan.parameter,
            new_value=plan.new_value,
            run_id=run_id,
        )
        return

    # All other change_types trigger a targeted refit
    overrides = _plan_to_overrides(plan)
    results = await refit_models(
        sb, settings,
        symbol_filter=plan.symbol,
        overrides=overrides,
        hypothesis=plan.hypothesis,
    )
    new_model_id = results.get(plan.symbol)

    if new_model_id and new_model_id != old_model_id:
        # Patch the plan JSONB with the new model id so _confirm_pending can resolve it
        updated_plan = {**plan.as_dict(), "new_model_version_id": new_model_id}
        sb.table("optimization_history").update({
            "plan": updated_plan,
            "model_version_id": new_model_id,  # point to new model
        }).eq("run_id", run_id).execute()
        log.info(
            "optimize_refit_triggered",
            symbol=plan.symbol,
            change_type=plan.change_type,
            old_model_id=old_model_id,
            new_model_id=new_model_id,
            run_id=run_id,
        )
    else:
        log.info(
            "optimize_refit_no_new_model",
            symbol=plan.symbol,
            change_type=plan.change_type,
            run_id=run_id,
        )


async def analyze_and_optimize(sb: Client, settings: Settings) -> None:
    """Top-level hourly job: confirm prior results then generate and apply new plans."""
    try:
        # Phase A
        _confirm_pending(sb)

        # Phase B
        for symbol in settings.pairs:
            current = load_active(sb, symbol, settings.candle_granularity, "v1")
            if not current:
                log.info("optimize_no_active_model", symbol=symbol)
                continue

            model_id = int(current["id"])

            # Stop condition check
            if _is_target_reached(sb, model_id):
                latest = _latest_perf(sb, model_id)
                log.warning(
                    "optimization_paused",
                    symbol=symbol,
                    model_id=model_id,
                    reason="target_metrics_reached",
                    win_rate=latest.get("win_rate") if latest else None,
                    sharpe_live=latest.get("sharpe_live") if latest else None,
                    target_win_rate=_STOP_WIN_RATE,
                    target_sharpe=_STOP_SHARPE,
                    consecutive_runs=_STOP_CONSECUTIVE_RUNS,
                )
                continue

            plan = analyze_model(sb, symbol, settings)
            if plan is None:
                log.info("optimize_no_action", symbol=symbol)
                continue

            metric_before = _latest_perf(sb, model_id) or {}
            run_id = _record_plan(sb, plan, symbol, model_id, metric_before)

            await _apply_plan(sb, settings, plan, run_id, model_id)

    except Exception:  # noqa: BLE001
        log.exception("optimize_cycle_failed")
