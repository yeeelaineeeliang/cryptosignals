"""Backfill realized returns onto past predictions + compute rolling performance.

This is what turns ``/model`` from a training report into a live scoreboard.
Every prediction we've emitted has a target bar — the 5-minute window that
starts after the prediction was written. Once that bar closes on Coinbase
and we've ingested it, we can compute the actual log-return and mark the
prediction a hit or a miss.

Two passes per invocation:

1. **Score**: for each prediction with ``realized_logret IS NULL``, find the
   first fully-closed candle whose ``bucket_start >= created_at``. That bar
   is the target. Compute ``realized_logret = log(candle.close / current_price)``
   and set ``hit = sign(predicted) == sign(realized)``.

2. **Aggregate**: for each active model, roll up the scored predictions in the
   trailing 24h into a single ``model_performance`` row containing:
   - hit_rate, confusion matrix, avg_predicted, avg_realized (original)
   - win_rate, sharpe_live, max_drawdown, avg_pnl_per_trade (trading quality)
   - feature_drift_pct (coefficient stability vs prior model)
   - diagnosis (structured one-line summary for the optimizer)

The job is idempotent — predictions already scored are skipped; aggregation
always reflects the current state of the table.
"""
from __future__ import annotations

import math
import statistics
from datetime import datetime, timedelta, timezone

from supabase import Client

from ..config import Settings
from ..logging_setup import get_logger

log = get_logger(__name__)

BATCH_SIZE = 500
MIN_SAMPLE_FOR_PERF = 5

# Crypto trades 24/7/365. 5-min bars: 12/h × 24h × 365d = 105,120 bars/year.
_ANNUALIZATION = math.sqrt(105_120)

# Sharpe uses a longer lookback to avoid sample-size artifacts from the hourly
# eval window.  24h of trades (~20–40 signals) multiplied by sqrt(105_120)≈324
# produces ±50–100 Sharpe swings from one eval to the next that are pure noise.
_SHARPE_LOOKBACK_DAYS = 30


async def evaluate_predictions(sb: Client, settings: Settings) -> None:
    """Top-level job: score unscored predictions, then write rolling perf."""
    try:
        scored = await _backfill_scores(sb, settings)
        log.info("evaluate_scored", new_rows=scored)

        for symbol in settings.pairs:
            await _write_performance(sb, symbol, settings)
    except Exception as e:  # noqa: BLE001
        log.exception("evaluate_failed", error=str(e))


async def _backfill_scores(sb: Client, settings: Settings) -> int:
    """Mark hit/miss on predictions whose target bar has now closed.

    With prediction_bars_ahead=3 (15-min horizon), a prediction at time T is
    scored against the close of the bar that ends 3 bars later. We only attempt
    scoring once 3 bars have fully closed (pred_cutoff), and we fetch the Nth
    candle in sequence using .range(N-1, N-1).
    """
    now = datetime.now(tz=timezone.utc)
    bars_ahead = settings.prediction_bars_ahead
    # Only score predictions where bars_ahead full bars have closed since creation
    pred_cutoff = (now - timedelta(seconds=bars_ahead * settings.candle_granularity)).isoformat()
    # Upper bound for candle queries: only use fully-ingested bars
    bar_cutoff = (now - timedelta(seconds=settings.candle_granularity)).isoformat()

    res = (
        sb.table("predictions")
        .select("id, symbol, created_at, current_price, predicted_logret")
        .is_("realized_logret", "null")
        .lte("created_at", pred_cutoff)
        .order("created_at", desc=False)
        .limit(BATCH_SIZE)
        .execute()
    )
    pending = res.data or []
    if not pending:
        return 0

    updated = 0
    for pred in pending:
        pred_time = pred["created_at"]
        # Fetch the bars_ahead-th candle after the prediction timestamp (0-indexed → bars_ahead-1)
        bar_res = (
            sb.table("candles")
            .select("close, bucket_start")
            .eq("symbol", pred["symbol"])
            .eq("granularity", settings.candle_granularity)
            .gte("bucket_start", pred_time)
            .lt("bucket_start", bar_cutoff)
            .order("bucket_start", desc=False)
            .range(bars_ahead - 1, bars_ahead - 1)
            .execute()
        )
        if not bar_res.data:
            continue

        close_target = float(bar_res.data[0]["close"])
        current = float(pred["current_price"])
        if current <= 0 or close_target <= 0:
            continue

        realized = math.log(close_target / current)
        predicted = float(pred["predicted_logret"])
        hit = (predicted > 0 and realized > 0) or (predicted < 0 and realized < 0)

        sb.table("predictions").update({
            "realized_logret": realized,
            "hit": hit,
        }).eq("id", pred["id"]).execute()
        updated += 1

    return updated


def _compute_trading_metrics(
    scored: list[dict],
) -> tuple[float | None, float | None, float | None, float | None, float | None]:
    """Return (win_rate, sharpe_live, max_drawdown, avg_pnl_per_trade, hit_rate)
    computed from scored prediction rows that include a ``signal`` field.
    """
    # Direction-adjusted PnL: LONG profits when realized > 0; SHORT when realized < 0
    traded = [r for r in scored if r.get("signal") in ("LONG", "SHORT")]
    if not traded:
        return None, None, None, None, None

    pnls = []
    for r in traded:
        realized = float(r["realized_logret"])
        pnls.append(realized if r["signal"] == "LONG" else -realized)

    wins = sum(1 for p in pnls if p > 0)
    win_rate = wins / len(pnls)
    avg_pnl = sum(pnls) / len(pnls)

    sharpe: float | None = None
    if len(pnls) > 1:
        std = statistics.stdev(pnls)
        sharpe = (avg_pnl / std) * _ANNUALIZATION if std > 0 else 0.0

    # Max peak-to-trough drawdown over the ordered sequence
    cumulative = peak = 0.0
    max_dd = 0.0
    for p in pnls:
        cumulative += p
        peak = max(peak, cumulative)
        max_dd = max(max_dd, peak - cumulative)
    max_drawdown = -max_dd  # reported as a negative number

    # hit_rate on the traded subset (directional accuracy)
    correct = sum(1 for r in traded
                  if (r["signal"] == "LONG" and float(r["realized_logret"]) > 0)
                  or (r["signal"] == "SHORT" and float(r["realized_logret"]) < 0))
    hit_rate_traded = correct / len(traded)

    return win_rate, sharpe, max_drawdown, avg_pnl, hit_rate_traded


def _compute_sharpe_live(sb: Client, model_id: int) -> float | None:
    """Sharpe over up to 30 days of LONG/SHORT predictions for model_id.

    Queried separately from the 24h eval window so the sample size is large
    enough that the annualization factor doesn't amplify noise into ±100 swings.
    Uses all available predictions when the model is newer than 30 days.
    """
    cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=_SHARPE_LOOKBACK_DAYS)).isoformat()
    res = (
        sb.table("predictions")
        .select("realized_logret, signal")
        .eq("model_version_id", model_id)
        .gte("created_at", cutoff)
        .in_("signal", ["LONG", "SHORT"])
        .not_.is_("realized_logret", "null")
        .order("created_at", desc=False)
        .execute()
    )
    rows = res.data or []
    if len(rows) < 2:
        return None

    pnls = [
        float(r["realized_logret"]) if r["signal"] == "LONG" else -float(r["realized_logret"])
        for r in rows
    ]
    avg = sum(pnls) / len(pnls)
    std = statistics.stdev(pnls)
    return (avg / std) * _ANNUALIZATION if std > 0 else 0.0


def _compute_feature_drift(
    sb: Client, model_id: int, symbol: str, granularity: int
) -> float | None:
    """Max |Δcoef| / |coef_prior| across features shared with the prior model."""
    prior_res = (
        sb.table("model_versions")
        .select("coefficients")
        .eq("symbol", symbol)
        .eq("granularity", granularity)
        .eq("feature_set", "v1")
        .eq("is_active", False)
        .order("trained_at", desc=True)
        .limit(1)
        .execute()
    )
    if not prior_res.data:
        return None

    current_res = (
        sb.table("model_versions")
        .select("coefficients")
        .eq("id", model_id)
        .execute()
    )
    if not current_res.data:
        return None

    prior_coefs: dict = prior_res.data[0]["coefficients"] or {}
    curr_coefs: dict = current_res.data[0]["coefficients"] or {}

    drifts = []
    for feat, curr_val in curr_coefs.items():
        if feat == "const" or feat not in prior_coefs or prior_coefs[feat] is None:
            continue
        prior_val = float(prior_coefs[feat])
        drift = abs(float(curr_val) - prior_val) / (abs(prior_val) + 1e-8)
        drifts.append(drift)

    return max(drifts) if drifts else None


def _build_diagnosis(
    hit_rate: float | None,
    win_rate: float | None,
    sharpe: float | None,
    max_drawdown: float | None,
    avg_pnl: float | None,
    feature_drift_pct: float | None,
    prior_hit_rate: float | None,
    n: int,
) -> str:
    parts: list[str] = []

    if hit_rate is not None:
        hr_str = f"Hit {hit_rate:.1%}"
        if prior_hit_rate is not None:
            delta = hit_rate - prior_hit_rate
            arrow = "↑" if delta > 0 else "↓"
            hr_str += f" ({arrow}{abs(delta) * 100:.1f}pp)"
        parts.append(hr_str)

    if win_rate is not None:
        parts.append(f"Win {win_rate:.1%}")

    if sharpe is not None:
        parts.append(f"Sharpe {sharpe:.2f}")

    if max_drawdown is not None:
        parts.append(f"MaxDD {max_drawdown * 100:.2f}%")

    if avg_pnl is not None:
        sign = "+" if avg_pnl >= 0 else ""
        parts.append(f"AvgPnL {sign}{avg_pnl * 100:.3f}%")

    if feature_drift_pct is not None and feature_drift_pct > 0.05:
        parts.append(f"CoefDrift {feature_drift_pct:.0%}")

    parts.append(f"n={n}")
    return ". ".join(parts) + "."


async def _write_performance(sb: Client, symbol: str, settings: Settings) -> None:
    """Roll up last 24h of scored predictions per active model."""
    model_res = (
        sb.table("model_versions")
        .select("id")
        .match({
            "symbol": symbol,
            "granularity": settings.candle_granularity,
            "feature_set": "v1",
            "is_active": True,
        })
        .maybe_single()
        .execute()
    )
    if not model_res or not model_res.data:
        return
    model_id = int(model_res.data["id"])

    cutoff = (datetime.now(tz=timezone.utc) - timedelta(hours=24)).isoformat()
    preds_res = (
        sb.table("predictions")
        .select("predicted_logret, realized_logret, signal")
        .eq("model_version_id", model_id)
        .gte("created_at", cutoff)
        .not_.is_("realized_logret", "null")
        .execute()
    )
    scored = preds_res.data or []
    if len(scored) < MIN_SAMPLE_FOR_PERF:
        log.info("evaluate_skip_perf", symbol=symbol, n=len(scored))
        return

    # --- original confusion matrix (all signals including HOLD) ---
    tp = tn = fp = fn = 0
    sum_pred = sum_real = 0.0
    for row in scored:
        p = float(row["predicted_logret"])
        r = float(row["realized_logret"])
        sum_pred += p
        sum_real += r
        if p > 0 and r > 0:
            tp += 1
        elif p < 0 and r < 0:
            tn += 1
        elif p > 0 and r < 0:
            fp += 1
        elif p < 0 and r > 0:
            fn += 1

    n = tp + tn + fp + fn
    hit_rate = (tp + tn) / n if n else None

    # --- new trading-quality metrics ---
    # win_rate / drawdown / avg_pnl: 24h window (reflects recent regime)
    # sharpe_live: 30-day rolling window (24h sample is too small — annualizing
    #              ~20–40 trades by sqrt(105_120) causes ±100 swings from noise)
    win_rate, _, max_drawdown, avg_pnl, _ = _compute_trading_metrics(scored)
    sharpe = _compute_sharpe_live(sb, model_id)
    feature_drift_pct = _compute_feature_drift(sb, model_id, symbol, settings.candle_granularity)
    # NUMERIC(6,4) can hold at most 99.9999; clamp before insert
    if feature_drift_pct is not None:
        feature_drift_pct = min(feature_drift_pct, 99.0)

    # --- prior snapshot for trend annotation in diagnosis ---
    prior_res = (
        sb.table("model_performance")
        .select("hit_rate")
        .eq("model_version_id", model_id)
        .order("evaluated_at", desc=True)
        .limit(1)
        .execute()
    )
    prior_hit_rate: float | None = None
    if prior_res.data:
        raw = prior_res.data[0].get("hit_rate")
        prior_hit_rate = float(raw) if raw is not None else None

    diagnosis = _build_diagnosis(
        hit_rate, win_rate, sharpe, max_drawdown, avg_pnl,
        feature_drift_pct, prior_hit_rate, n,
    )

    sb.table("model_performance").insert({
        "model_version_id": model_id,
        "window_hours": 24,
        "hit_rate": hit_rate,
        "confusion": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
        "avg_predicted": sum_pred / len(scored),
        "avg_realized": sum_real / len(scored),
        "win_rate": win_rate,
        "sharpe_live": sharpe,
        "max_drawdown": max_drawdown,
        "avg_pnl_per_trade": avg_pnl,
        "feature_drift_pct": feature_drift_pct,
        "diagnosis": diagnosis,
    }).execute()

    log.info(
        "evaluate_perf_written",
        symbol=symbol,
        model_id=model_id,
        n=n,
        hit_rate=round(hit_rate, 4) if hit_rate is not None else None,
        win_rate=round(win_rate, 4) if win_rate is not None else None,
        sharpe=round(sharpe, 3) if sharpe is not None else None,
        max_drawdown=round(max_drawdown, 5) if max_drawdown is not None else None,
        feature_drift_pct=round(feature_drift_pct, 3) if feature_drift_pct is not None else None,
        diagnosis=diagnosis,
    )
