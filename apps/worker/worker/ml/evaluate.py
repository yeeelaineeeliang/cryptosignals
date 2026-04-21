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
   trailing 24h into a single ``model_performance`` row with hit rate, a
   confusion matrix, and average predicted vs average realized.

The job is idempotent — predictions already scored are skipped; aggregation
always reflects the current state of the table.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from supabase import Client

from ..config import Settings
from ..logging_setup import get_logger

log = get_logger(__name__)

# How many unscored predictions to backfill per tick. Bounded so a single
# invocation doesn't hammer Supabase when the queue is deep.
BATCH_SIZE = 500

# Require this many scored predictions before we bother writing a
# model_performance row — below this, the confusion matrix is noise.
MIN_SAMPLE_FOR_PERF = 5


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
    """Mark hit/miss on predictions whose target bar has now closed."""
    now = datetime.now(tz=timezone.utc)
    # Only consider bars that have fully closed
    cutoff = (now - timedelta(seconds=settings.candle_granularity)).isoformat()

    res = (
        sb.table("predictions")
        .select("id, symbol, created_at, current_price, predicted_logret")
        .is_("realized_logret", "null")
        .lte("created_at", cutoff)
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
        # First fully-closed candle whose bucket starts at or after the prediction
        bar_res = (
            sb.table("candles")
            .select("close, bucket_start")
            .eq("symbol", pred["symbol"])
            .eq("granularity", settings.candle_granularity)
            .gte("bucket_start", pred_time)
            .lt("bucket_start", cutoff)
            .order("bucket_start", desc=False)
            .limit(1)
            .execute()
        )
        if not bar_res.data:
            continue

        close_next = float(bar_res.data[0]["close"])
        current = float(pred["current_price"])
        if current <= 0 or close_next <= 0:
            continue

        realized = math.log(close_next / current)
        predicted = float(pred["predicted_logret"])
        # Hit iff both signs align; zero is conservatively "not a hit"
        hit = (predicted > 0 and realized > 0) or (predicted < 0 and realized < 0)

        sb.table("predictions").update({
            "realized_logret": realized,
            "hit": hit,
        }).eq("id", pred["id"]).execute()
        updated += 1

    return updated


async def _write_performance(sb: Client, symbol: str, settings: Settings) -> None:
    """Roll up last 24h of scored predictions per active model."""
    # Identify the active model for this symbol
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
        .select("predicted_logret, realized_logret")
        .eq("model_version_id", model_id)
        .gte("created_at", cutoff)
        .not_.is_("realized_logret", "null")
        .execute()
    )
    scored = preds_res.data or []
    if len(scored) < MIN_SAMPLE_FOR_PERF:
        log.info("evaluate_skip_perf", symbol=symbol, n=len(scored))
        return

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
        # predicted == 0 cases (HOLD with a zero prediction) land nowhere; rare

    n = tp + tn + fp + fn
    hit_rate = (tp + tn) / n if n else None

    sb.table("model_performance").insert({
        "model_version_id": model_id,
        "window_hours": 24,
        "hit_rate": hit_rate,
        "confusion": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
        "avg_predicted": sum_pred / len(scored),
        "avg_realized": sum_real / len(scored),
    }).execute()

    log.info(
        "evaluate_perf_written",
        symbol=symbol,
        model_id=model_id,
        n=n,
        hit_rate=round(hit_rate, 4) if hit_rate is not None else None,
    )
