"""Live inference: load active model, predict, write a predictions row.

Runs every N seconds. Cheap — OLS inference is a dot product. The hot path
is:

    latest_candles  -> build_features -> take last row
                    -> standardize with scaler_means/stds
                    -> intercept + dot(coefs, standardized)
                    -> signal = LONG / SHORT / HOLD
                    -> INSERT predictions row

Paper trading (executing simulated trades per user based on signals) is not
in this Phase 2 scope — it's Phase 3. For now we just persist signals; the
dashboard subscribes to `predictions` via Realtime to show them live.
"""
from __future__ import annotations

import math

import pandas as pd
from supabase import Client

from .config import Settings
from .features import FEATURE_COLUMNS, build_features
from .logging_setup import get_logger
from .ml.persistence import load_active

log = get_logger(__name__)

# A prediction whose magnitude is below this threshold is reported as HOLD
# rather than LONG/SHORT. Keeps noise out of the rolling signal feed. Users
# can override with a higher threshold in settings — that's applied later,
# in the paper-trade engine, not here.
HOLD_THRESHOLD_LOGRET = 1e-5  # ≈ 0.1 bp


def _fetch_recent_candles(sb: Client, symbol: str, granularity: int, limit: int) -> pd.DataFrame:
    res = (
        sb.table("candles")
        .select("*")
        .eq("symbol", symbol)
        .eq("granularity", granularity)
        .order("bucket_start", desc=True)
        .limit(limit)
        .execute()
    )
    rows = res.data or []
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["bucket_start"] = pd.to_datetime(df["bucket_start"], utc=True)
    return df.sort_values("bucket_start").reset_index(drop=True)


def _current_price(sb: Client, symbol: str) -> float | None:
    res = sb.table("prices").select("price").eq("symbol", symbol).maybe_single().execute()
    if not res or not res.data:
        return None
    return float(res.data["price"])


def _predict_logret(
    latest_features: pd.Series,
    *,
    selected: list[str],
    coefficients: dict[str, float],
    scaler_means: dict[str, float],
    scaler_stds: dict[str, float],
) -> float | None:
    """Dot-product inference on the most recent bar's feature vector.

    Returns None if any required feature is NaN (the rolling windows haven't
    warmed up yet or the row has missing data).
    """
    intercept = float(coefficients.get("const", 0.0))
    total = intercept
    for feat in selected:
        val = latest_features.get(feat)
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return None
        std = scaler_stds.get(feat, 1.0) or 1.0
        mean = scaler_means.get(feat, 0.0)
        standardized = (float(val) - mean) / std
        total += coefficients.get(feat, 0.0) * standardized
    return total


def _signal_for(predicted_logret: float) -> str:
    if predicted_logret > HOLD_THRESHOLD_LOGRET:
        return "LONG"
    if predicted_logret < -HOLD_THRESHOLD_LOGRET:
        return "SHORT"
    return "HOLD"


async def infer_and_record(sb: Client, settings: Settings) -> None:
    """For each watched pair, emit one predictions row if we have an active model."""
    try:
        for symbol in settings.pairs:
            model = load_active(sb, symbol, settings.candle_granularity, "v1")
            if not model:
                log.warning("infer_no_active_model", symbol=symbol)
                continue

            # Enough candles to populate 50-bar rolling windows + breathing room
            candles = _fetch_recent_candles(sb, symbol, settings.candle_granularity, limit=120)
            if len(candles) < 60:
                log.warning("infer_insufficient_candles", symbol=symbol, n=len(candles))
                continue

            feats = build_features(candles)
            if feats.empty:
                log.warning("infer_no_features", symbol=symbol)
                continue
            latest = feats.iloc[-1]

            prediction = _predict_logret(
                latest,
                selected=model["selected_features"],
                coefficients=model["coefficients"],
                scaler_means=model["scaler_means"],
                scaler_stds=model["scaler_stds"],
            )
            if prediction is None:
                log.warning("infer_features_incomplete", symbol=symbol)
                continue

            price = _current_price(sb, symbol) or float(latest["f_close"])
            signal = _signal_for(prediction)

            sb.table("predictions").insert({
                "symbol": symbol,
                "model_version_id": model["id"],
                "current_price": price,
                "predicted_logret": prediction,
                "signal": signal,
            }).execute()

            log.info(
                "predicted",
                symbol=symbol,
                model_id=model["id"],
                predicted_logret=round(prediction, 6),
                signal=signal,
                price=price,
            )
    except Exception as e:  # noqa: BLE001
        log.exception("infer_and_record_failed", error=str(e))
