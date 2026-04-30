"""Periodic model refit — rolls the training window forward.

Runs every N hours (default 6). Same code path as bootstrap_train, but:
  - loads only the rolling ROLLING_TRAIN_DAYS window from Supabase candles
  - accepts an overrides dict so the optimizer can experiment with VIF thresholds
    and lookback windows without redeploying
  - only promotes the new model to active if it beats the current model on OSR²,
    OR if the current model has no measurable edge (OSR² ≤ 0)

Called by both the APScheduler job in main.py and by optimize.py when a
refit action is triggered immediately (outside the regular schedule).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
from supabase import Client

from ..config import Settings
from ..features import FEATURE_COLUMNS, build_features
from ..logging_setup import get_logger
from .persistence import insert_and_activate, load_active
from .train import VIF_DROP_HARD, VIF_DROP_SOFT, SOFT_OSR2_TOLERANCE, train_with_vif

log = get_logger(__name__)

MIN_CLEAN_ROWS = 80


def _load_rolling_candles(
    sb: Client, symbol: str, granularity: int, days: int
) -> pd.DataFrame:
    cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=days)).isoformat()
    page_size = 1000
    offset = 0
    all_rows: list[dict] = []
    while True:
        res = (
            sb.table("candles")
            .select("*")
            .eq("symbol", symbol)
            .eq("granularity", granularity)
            .gte("bucket_start", cutoff)
            .order("bucket_start", desc=False)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        rows = res.data or []
        all_rows.extend(rows)
        if len(rows) < page_size:
            break
        offset += page_size

    if not all_rows:
        return pd.DataFrame()
    df = pd.DataFrame(all_rows)
    df["bucket_start"] = pd.to_datetime(df["bucket_start"], utc=True)
    return df


def _should_activate(new_osr2: float, current_model: dict | None) -> bool:
    """Promote the new model if it's better than current, or current has no edge."""
    if current_model is None:
        return True
    current_osr2 = current_model.get("osr2")
    if current_osr2 is None or float(current_osr2) <= 0:
        return True
    return new_osr2 > float(current_osr2)


async def refit_one(
    sb: Client,
    settings: Settings,
    symbol: str,
    overrides: dict[str, Any] | None = None,
    hypothesis: str | None = None,
) -> int | None:
    """Refit a single symbol. Returns the new model_version id, or None if skipped."""
    overrides = overrides or {}
    days = int(overrides.get("lookback_days", settings.rolling_train_days))
    vif_hard = float(overrides.get("vif_hard", settings.vif_hard_threshold))
    vif_soft = float(overrides.get("vif_soft", VIF_DROP_SOFT))
    soft_osr2_tol = float(overrides.get("soft_osr2_tolerance", settings.soft_osr2_tolerance))

    candles = _load_rolling_candles(sb, symbol, settings.candle_granularity, days)
    if candles.empty or len(candles) < MIN_CLEAN_ROWS:
        log.warning("refit_skip_insufficient_candles", symbol=symbol, n=len(candles))
        return None

    feats = build_features(candles)
    clean = feats.dropna(subset=[*FEATURE_COLUMNS, "target_logret"])
    if len(clean) < MIN_CLEAN_ROWS:
        log.warning("refit_skip_insufficient_features", symbol=symbol, n=len(clean))
        return None

    current_model = load_active(sb, symbol, settings.candle_granularity, "v1")

    log.info(
        "refit_training",
        symbol=symbol,
        days=days,
        rows=len(clean),
        vif_hard=vif_hard,
        vif_soft=vif_soft,
    )

    try:
        model = train_with_vif(
            clean,
            feature_cols=list(FEATURE_COLUMNS),
            verbose=False,
            vif_hard=vif_hard,
            vif_soft=vif_soft,
            soft_osr2_tolerance=soft_osr2_tol,
        )
    except Exception:
        log.exception("refit_train_failed", symbol=symbol)
        return None

    if not _should_activate(model.metrics.osr2, current_model):
        log.info(
            "refit_skipped_no_improvement",
            symbol=symbol,
            new_osr2=round(model.metrics.osr2, 4),
            current_osr2=round(float(current_model["osr2"]), 4) if current_model else None,
            selected_features=model.selected_features,
            n_features=len(model.selected_features),
        )
        return None

    window_start = clean["bucket_start"].min()
    window_end = clean["bucket_start"].max()

    model_id = insert_and_activate(
        sb,
        symbol=symbol,
        granularity=settings.candle_granularity,
        feature_set="v1",
        model=model,
        train_window_start=window_start.to_pydatetime(),
        train_window_end=window_end.to_pydatetime(),
    )

    # Annotate the model row with the hypothesis that triggered this refit
    if hypothesis:
        sb.table("model_versions").update({"hypothesis": hypothesis}).eq("id", model_id).execute()

    # VIF drop sequence: compact list of {iter, dropped, vif_at_drop, osr2_after}
    vif_drops = [
        {
            "iter": e["iter"],
            "dropped": e["dropped"],
            "vif": round(e["vif_max"], 2),
            "osr2": round(e["osr2"], 4),
        }
        for e in model.vif_trace
        if e["dropped"] is not None
    ]

    # Feature set diff vs the prior active model
    prior_features: set[str] = set(current_model["selected_features"]) if current_model else set()
    new_features: set[str] = set(model.selected_features)
    features_added = sorted(new_features - prior_features)
    features_removed = sorted(prior_features - new_features)

    log.info(
        "refit_complete",
        symbol=symbol,
        model_id=model_id,
        selected_features=model.selected_features,
        n_features=len(model.selected_features),
        n_vif_drops=len(vif_drops),
        vif_drops=vif_drops,
        feature_set_changed=bool(features_added or features_removed),
        features_added=features_added,
        features_removed=features_removed,
        final_vif_max=round(model.vif_trace[-1]["vif_max"], 2),
        r2=round(model.metrics.r2, 4),
        osr2=round(model.metrics.osr2, 4),
        hit_rate=round(model.metrics.hit_rate, 4),
        days=days,
        vif_hard=vif_hard,
    )
    return model_id


async def refit_models(
    sb: Client,
    settings: Settings,
    symbol_filter: str | None = None,
    overrides: dict[str, Any] | None = None,
    hypothesis: str | None = None,
) -> dict[str, int | None]:
    """Refit all watched pairs (or just symbol_filter). Returns {symbol: model_id}."""
    symbols = [symbol_filter] if symbol_filter else settings.pairs
    results: dict[str, int | None] = {}
    for symbol in symbols:
        try:
            model_id = await refit_one(sb, settings, symbol, overrides=overrides, hypothesis=hypothesis)
            results[symbol] = model_id
        except Exception:
            log.exception("refit_models_failed", symbol=symbol)
            results[symbol] = None
    return results
