"""Read/write helpers for the model_versions table.

The active model is identified by (symbol, granularity, feature_set) +
is_active=TRUE. Only one row per (pair, granularity, feature_set) can be
active at a time — enforced by the partial unique index in migration 002.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isinf, isnan
from typing import Any

from supabase import Client

from .train import TrainedModel


def _sanitize(value: Any) -> Any:
    """Replace inf/nan with JSON-safe sentinels. Postgres JSONB can hold any
    number, but Python's `json.dumps` refuses non-finite floats by default.
    inf gets clipped to 1e12 (enough to read as "huge" in the UI); nan → None.
    """
    if isinstance(value, float):
        if isnan(value):
            return None
        if isinf(value):
            return 1e12 if value > 0 else -1e12
        return value
    if isinstance(value, dict):
        return {k: _sanitize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    return value


def insert_and_activate(
    sb: Client,
    *,
    symbol: str,
    granularity: int,
    feature_set: str,
    model: TrainedModel,
    train_window_start: datetime,
    train_window_end: datetime,
) -> int:
    """Insert a new model_versions row and flip is_active atomically.

    We demote any currently-active model for the same key FIRST, then insert
    the new row as active. A failed insert leaves the old row demoted, which
    is a minor inconvenience but not a correctness issue — the next refit
    will re-promote whichever fresh model it builds.
    """
    sb.table("model_versions").update({"is_active": False}).match({
        "symbol": symbol,
        "granularity": granularity,
        "feature_set": feature_set,
        "is_active": True,
    }).execute()

    payload: dict[str, Any] = {
        "symbol": symbol,
        "granularity": granularity,
        "feature_set": feature_set,
        "selected_features": model.selected_features,
        "coefficients": _sanitize({"const": model.intercept, **model.coefficients}),
        "scaler_means": _sanitize(model.scaler_means),
        "scaler_stds": _sanitize(model.scaler_stds),
        "vif_trace": _sanitize(model.vif_trace),
        "r_squared": _sanitize(model.metrics.r2),
        "osr2": _sanitize(model.metrics.osr2),
        "hit_rate": _sanitize(model.metrics.hit_rate),
        "rmse": _sanitize(model.metrics.rmse),
        "train_window_start": train_window_start.isoformat(),
        "train_window_end": train_window_end.isoformat(),
        "trained_at": datetime.now(tz=timezone.utc).isoformat(),
        "is_active": True,
    }
    res = sb.table("model_versions").insert(payload).execute()
    return int(res.data[0]["id"])


def load_active(
    sb: Client, symbol: str, granularity: int, feature_set: str,
) -> dict[str, Any] | None:
    """Return the currently-active model dict for a given pair or None."""
    res = (
        sb.table("model_versions")
        .select("*")
        .match({
            "symbol": symbol,
            "granularity": granularity,
            "feature_set": feature_set,
            "is_active": True,
        })
        .maybe_single()
        .execute()
    )
    return res.data if res and res.data else None
