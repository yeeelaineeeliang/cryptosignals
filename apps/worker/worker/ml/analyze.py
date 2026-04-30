"""Model performance analyzer — produces an OptimizationPlan from recent metrics.

Reads the last N model_performance rows and the active model_versions record,
then applies a priority-ordered rule set to decide what to change next.

Rule priority (first match wins):
  1. Stop condition: win_rate > 0.55 AND sharpe > 1.5 for 3 consecutive runs
     → return None (caller logs the achievement warning)
  2. Sustained low hit rate (< 0.51 for 3 runs) → raise signal_threshold
  3. Consecutive negative Sharpe (2 runs) → trigger immediate refit
  4. High feature coefficient drift (> 40%) → tighten VIF threshold + refit
  5. R² declined > 10% vs prior model → shorten lookback window + refit
  6. avg_pnl_per_trade negative for 3 runs → raise signal_threshold (no edge)

When ENABLE_LLM_FEATURES is true the rule-based plan is enriched with a
Claude-generated hypothesis sentence. The plan structure is still rule-derived
— the LLM only writes the human-readable hypothesis text.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from supabase import Client

from ..config import Settings
from ..logging_setup import get_logger

log = get_logger(__name__)

# ---- thresholds -------------------------------------------------------
_STOP_WIN_RATE = 0.55
_STOP_SHARPE = 1.5
_STOP_CONSECUTIVE_RUNS = 3

_LOW_HIT_THRESHOLD = 0.51      # raise signal_threshold below this
_LOW_HIT_RUNS = 3

_NEG_SHARPE_RUNS = 2           # consecutive negative Sharpe triggers refit

_DRIFT_TRIGGER = 0.40          # max coef drift fraction that triggers VIF tighten
_VIF_HARD_TIGHTENED = 7.0      # hard VIF limit when drift is detected
_VIF_HARD_DEFAULT = 10.0

_R2_DECLINE_TRIGGER = 0.10     # relative R² decline that triggers shorter lookback
_LOOKBACK_SHORTENED = 21       # days to try (vs default 30)
_LOOKBACK_DEFAULT = 30

_NEG_PNL_RUNS = 3              # consecutive negative avg_pnl triggers threshold raise
_SIGNAL_THRESHOLD_DEFAULT = 0.002
_SIGNAL_THRESHOLD_RAISED = 0.005

_HISTORY_WINDOW = 10           # how many recent perf rows to read
_REFIT_COOLDOWN = 3            # consecutive failed refit_now before escalating to lookback_window


@dataclass(slots=True)
class OptimizationPlan:
    symbol: str
    change_type: str            # 'refit_now' | 'vif_threshold' | 'lookback_window' | 'signal_threshold'
    parameter: str
    old_value: float | int | str
    new_value: float | int | str
    hypothesis: str
    expected_metric: str        # which metric this should improve
    expected_delta: float       # expected absolute improvement in expected_metric

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_float(val: Any) -> float | None:
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _last_n_plans(sb: Client, symbol: str, n: int) -> list[dict]:
    """Return the n most recent optimization_history rows for symbol, newest first."""
    res = (
        sb.table("optimization_history")
        .select("change_type, confirmed, plan")
        .eq("symbol", symbol)
        .order("timestamp", desc=True)
        .limit(n)
        .execute()
    )
    return res.data or []


def _refit_on_cooldown(recent_plans: list[dict]) -> bool:
    """True when the last _REFIT_COOLDOWN plans are all refit_now with no confirmed success.

    Requires at least one confirmed=False (not just pending nulls) so a brand-new
    deployment doesn't immediately skip to the escalation path.
    """
    if len(recent_plans) < _REFIT_COOLDOWN:
        return False
    window = recent_plans[:_REFIT_COOLDOWN]
    return (
        all(p.get("change_type") == "refit_now" for p in window)
        and not any(p.get("confirmed") is True for p in window)
        and any(p.get("confirmed") is False for p in window)
    )


def _advisory_already_issued(
    recent_plans: list[dict], change_type: str, new_value: object
) -> bool:
    """True if the most recent plan is the same advisory and was not confirmed.

    Blocks re-issue when confirmed=False (tried, didn't work) OR confirmed=None
    (still pending — the threshold is advisory and won't change win_rate until
    enough new trades accumulate, so waiting one more cycle is not useful).
    """
    if not recent_plans:
        return False
    last = recent_plans[0]
    plan_dict = last.get("plan") or {}
    return (
        last.get("change_type") == change_type
        and plan_dict.get("new_value") == new_value
        and last.get("confirmed") is not True
    )


def _recent_perf(sb: Client, model_id: int, n: int) -> list[dict]:
    res = (
        sb.table("model_performance")
        .select(
            "hit_rate, win_rate, sharpe_live, max_drawdown, "
            "avg_pnl_per_trade, feature_drift_pct, evaluated_at"
        )
        .eq("model_version_id", model_id)
        .order("evaluated_at", desc=True)
        .limit(n)
        .execute()
    )
    return res.data or []


def _active_model(sb: Client, symbol: str, granularity: int) -> dict | None:
    res = (
        sb.table("model_versions")
        .select("id, r_squared, osr2, hit_rate")
        .match({"symbol": symbol, "granularity": granularity, "feature_set": "v1", "is_active": True})
        .maybe_single()
        .execute()
    )
    return res.data if res and res.data else None


def _prior_model(sb: Client, symbol: str, granularity: int) -> dict | None:
    res = (
        sb.table("model_versions")
        .select("id, r_squared, osr2")
        .eq("symbol", symbol)
        .eq("granularity", granularity)
        .eq("feature_set", "v1")
        .eq("is_active", False)
        .order("trained_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def _is_stop_condition(perf_rows: list[dict]) -> bool:
    """Return True if win_rate and sharpe targets met for N consecutive runs."""
    if len(perf_rows) < _STOP_CONSECUTIVE_RUNS:
        return False
    recent = perf_rows[:_STOP_CONSECUTIVE_RUNS]
    return all(
        _safe_float(r.get("win_rate")) is not None
        and _safe_float(r["win_rate"]) > _STOP_WIN_RATE
        and _safe_float(r.get("sharpe_live")) is not None
        and _safe_float(r["sharpe_live"]) > _STOP_SHARPE
        for r in recent
    )


def _rule_based_plan(
    symbol: str,
    perf_rows: list[dict],
    current_model: dict,
    prior_model: dict | None,
    recent_plans: list[dict],
) -> OptimizationPlan | None:
    """Apply priority-ordered rules. Return the first matching plan, or None."""
    if not perf_rows:
        return None

    hit_rates  = [_safe_float(r.get("hit_rate"))          for r in perf_rows]
    sharpes    = [_safe_float(r.get("sharpe_live"))        for r in perf_rows]
    avg_pnls   = [_safe_float(r.get("avg_pnl_per_trade")) for r in perf_rows]
    drifts     = [_safe_float(r.get("feature_drift_pct")) for r in perf_rows]

    # Rule 1 — sustained low hit rate
    valid_hits = [h for h in hit_rates[:_LOW_HIT_RUNS] if h is not None]
    if len(valid_hits) >= _LOW_HIT_RUNS and all(h < _LOW_HIT_THRESHOLD for h in valid_hits):
        if _advisory_already_issued(recent_plans, "signal_threshold", _SIGNAL_THRESHOLD_RAISED):
            # Advisory was issued last cycle (confirmed=False or still pending) and
            # win_rate hasn't improved — escalate to a refit instead of repeating.
            return OptimizationPlan(
                symbol=symbol,
                change_type="refit_now",
                parameter="rolling_train_days",
                old_value=_LOOKBACK_DEFAULT,
                new_value=_LOOKBACK_DEFAULT,
                hypothesis=(
                    f"signal_threshold={_SIGNAL_THRESHOLD_RAISED} advisory issued last cycle "
                    f"with no win_rate improvement. Escalating to refit to address structural "
                    "underperformance."
                ),
                expected_metric="win_rate",
                expected_delta=0.04,
            )
        return OptimizationPlan(
            symbol=symbol,
            change_type="signal_threshold",
            parameter="signal_threshold",
            old_value=_SIGNAL_THRESHOLD_DEFAULT,
            new_value=_SIGNAL_THRESHOLD_RAISED,
            hypothesis=(
                f"Hit rate below {_LOW_HIT_THRESHOLD:.0%} for {_LOW_HIT_RUNS} consecutive runs "
                f"(latest {valid_hits[0]:.1%}). Raising signal_threshold to {_SIGNAL_THRESHOLD_RAISED} "
                "to trade only high-conviction bars."
            ),
            expected_metric="win_rate",
            expected_delta=0.04,
        )

    # Rule 2 — consecutive negative Sharpe
    valid_sharpes = [s for s in sharpes[:_NEG_SHARPE_RUNS] if s is not None]
    if len(valid_sharpes) >= _NEG_SHARPE_RUNS and all(s < 0 for s in valid_sharpes):
        if _refit_on_cooldown(recent_plans):
            # refit_now triggered _REFIT_COOLDOWN times in a row without a confirmed
            # Sharpe improvement — escalate to a shorter lookback window.
            return OptimizationPlan(
                symbol=symbol,
                change_type="lookback_window",
                parameter="lookback_days",
                old_value=_LOOKBACK_DEFAULT,
                new_value=_LOOKBACK_SHORTENED,
                hypothesis=(
                    f"refit_now attempted {_REFIT_COOLDOWN} consecutive times without confirmed "
                    f"Sharpe improvement. Escalating to {_LOOKBACK_SHORTENED}-day lookback to "
                    "adapt to the current market regime."
                ),
                expected_metric="sharpe_live",
                expected_delta=0.30,
            )
        return OptimizationPlan(
            symbol=symbol,
            change_type="refit_now",
            parameter="rolling_train_days",
            old_value=_LOOKBACK_DEFAULT,
            new_value=_LOOKBACK_DEFAULT,
            hypothesis=(
                f"Sharpe negative for {_NEG_SHARPE_RUNS} consecutive runs "
                f"(latest {valid_sharpes[0]:.2f}). Triggering refit to recalibrate "
                "coefficients against recent price action."
            ),
            expected_metric="sharpe_live",
            expected_delta=0.30,
        )

    # Rule 3 — high feature coefficient drift
    recent_drift = next((d for d in drifts if d is not None), None)
    if recent_drift is not None and recent_drift > _DRIFT_TRIGGER:
        return OptimizationPlan(
            symbol=symbol,
            change_type="vif_threshold",
            parameter="vif_hard",
            old_value=_VIF_HARD_DEFAULT,
            new_value=_VIF_HARD_TIGHTENED,
            hypothesis=(
                f"Max coefficient drift at {recent_drift:.0%} (>{_DRIFT_TRIGGER:.0%} trigger). "
                f"Tightening VIF hard threshold to {_VIF_HARD_TIGHTENED} to drop more "
                "collinear features and improve coefficient stability."
            ),
            expected_metric="feature_drift_pct",
            expected_delta=-0.15,
        )

    # Rule 4 — R² decline between current and prior model
    if prior_model:
        curr_r2 = _safe_float(current_model.get("r_squared"))
        prev_r2 = _safe_float(prior_model.get("r_squared"))
        if curr_r2 is not None and prev_r2 is not None and prev_r2 > 0:
            decline = (prev_r2 - curr_r2) / prev_r2
            if decline > _R2_DECLINE_TRIGGER:
                return OptimizationPlan(
                    symbol=symbol,
                    change_type="lookback_window",
                    parameter="lookback_days",
                    old_value=_LOOKBACK_DEFAULT,
                    new_value=_LOOKBACK_SHORTENED,
                    hypothesis=(
                        f"Train R² declined {decline:.1%} vs prior model "
                        f"({prev_r2:.4f} → {curr_r2:.4f}). Shortening lookback to "
                        f"{_LOOKBACK_SHORTENED} days to focus on the current market regime."
                    ),
                    expected_metric="r_squared",
                    expected_delta=decline * 0.4,
                )

    # Rule 5 — sustained negative average PnL per trade
    valid_pnls = [p for p in avg_pnls[:_NEG_PNL_RUNS] if p is not None]
    if len(valid_pnls) >= _NEG_PNL_RUNS and all(p < 0 for p in valid_pnls):
        if _advisory_already_issued(recent_plans, "signal_threshold", _SIGNAL_THRESHOLD_RAISED):
            return OptimizationPlan(
                symbol=symbol,
                change_type="refit_now",
                parameter="rolling_train_days",
                old_value=_LOOKBACK_DEFAULT,
                new_value=_LOOKBACK_DEFAULT,
                hypothesis=(
                    f"signal_threshold={_SIGNAL_THRESHOLD_RAISED} advisory issued last cycle "
                    f"with no avg_pnl improvement. Escalating to refit."
                ),
                expected_metric="avg_pnl_per_trade",
                expected_delta=0.0002,
            )
        return OptimizationPlan(
            symbol=symbol,
            change_type="signal_threshold",
            parameter="signal_threshold",
            old_value=_SIGNAL_THRESHOLD_DEFAULT,
            new_value=_SIGNAL_THRESHOLD_RAISED,
            hypothesis=(
                f"avg_pnl_per_trade negative for {_NEG_PNL_RUNS} consecutive runs "
                f"(latest {valid_pnls[0]*100:.3f}%). Model producing losing trades — "
                "raising threshold to filter low-conviction noise."
            ),
            expected_metric="avg_pnl_per_trade",
            expected_delta=0.0002,
        )

    return None


def _enrich_with_llm(plan: OptimizationPlan, diagnosis: str, settings: Settings) -> OptimizationPlan:
    """Replace hypothesis with an LLM-generated version (gated by ENABLE_LLM_FEATURES)."""
    try:
        import anthropic  # optional dep
    except ImportError:
        log.warning("analyze_llm_skipped", reason="anthropic package not installed")
        return plan

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=120,
            system=[{
                "type": "text",
                "text": (
                    "You analyze crypto OLS trading model performance. "
                    "Given a diagnosis and proposed optimization, write a single concise hypothesis sentence "
                    "that explains the root cause and expected outcome. Under 40 words. No markdown."
                ),
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{
                "role": "user",
                "content": (
                    f"Symbol: {plan.symbol}\n"
                    f"Diagnosis: {diagnosis}\n"
                    f"Proposed change: {plan.change_type} — set {plan.parameter} "
                    f"from {plan.old_value} to {plan.new_value}\n"
                    f"Expected improvement: {plan.expected_delta:+.4f} in {plan.expected_metric}\n"
                    "Write the hypothesis."
                ),
            }],
        )
        enriched_hypothesis = response.content[0].text.strip()
        log.info("analyze_llm_hypothesis", symbol=plan.symbol, hypothesis=enriched_hypothesis)
        return OptimizationPlan(
            symbol=plan.symbol,
            change_type=plan.change_type,
            parameter=plan.parameter,
            old_value=plan.old_value,
            new_value=plan.new_value,
            hypothesis=enriched_hypothesis,
            expected_metric=plan.expected_metric,
            expected_delta=plan.expected_delta,
        )
    except Exception:
        log.exception("analyze_llm_failed", symbol=plan.symbol)
        return plan  # fall back to rule-based hypothesis


def analyze_model(
    sb: Client,
    symbol: str,
    settings: Settings,
) -> OptimizationPlan | None:
    """Main entry point. Returns a plan or None (no action needed / stop condition met)."""
    current = _active_model(sb, symbol, settings.candle_granularity)
    if not current:
        log.info("analyze_no_active_model", symbol=symbol)
        return None

    model_id = int(current["id"])
    perf_rows = _recent_perf(sb, model_id, _HISTORY_WINDOW)

    if _is_stop_condition(perf_rows):
        log.info("analyze_stop_condition_met", symbol=symbol)
        return None  # caller handles the warning

    prior = _prior_model(sb, symbol, settings.candle_granularity)
    recent_plans = _last_n_plans(sb, symbol, _REFIT_COOLDOWN)
    plan = _rule_based_plan(symbol, perf_rows, current, prior, recent_plans)

    if plan is None:
        return None

    # Optionally enrich hypothesis via LLM
    if settings.enable_llm_features and perf_rows:
        latest_diagnosis = perf_rows[0].get("diagnosis") or ""  # from evaluate.py
        # Re-read from model_performance if available
        diag_res = (
            sb.table("model_performance")
            .select("diagnosis")
            .eq("model_version_id", model_id)
            .order("evaluated_at", desc=True)
            .limit(1)
            .execute()
        )
        if diag_res.data and diag_res.data[0].get("diagnosis"):
            latest_diagnosis = diag_res.data[0]["diagnosis"]
        plan = _enrich_with_llm(plan, latest_diagnosis, settings)

    log.info(
        "analyze_plan_generated",
        symbol=symbol,
        change_type=plan.change_type,
        parameter=plan.parameter,
        old_value=plan.old_value,
        new_value=plan.new_value,
        expected_metric=plan.expected_metric,
        expected_delta=plan.expected_delta,
    )
    return plan
