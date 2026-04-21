"""Feature engineering — the canonical pipeline.

The same ``build_features`` function is used by (a) the bootstrap training
script, (b) the periodic refit job, and (c) live inference. That single code
path is the only way to guarantee training/serving parity — every feature
must be computable from a DataFrame of candle bars with no extra context.

All rolling windows are *trailing-only*. Computing ``feature[t]`` may use
bars ``t`` and earlier; never ``t+1``. The target column ``target_logret``
is ``log(close_{t+1} / close_t)`` — that's the only forward-looking column,
and it's the target, not a predictor. At inference time the most recent
row's ``target_logret`` is NaN (the next bar hasn't closed yet) and we
simply drop that row when training.

Feature set ``v1`` excludes anything depending on ``trade_count``, since
Coinbase's public API doesn't expose it cheaply. A future ``v2`` can add
back ``count_z_20`` / ``volume_per_trade`` once we have a reliable source.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

FEATURE_SET_VERSION = "v1"


# ---------- helpers ---------------------------------------------------------


def _ema(series: pd.Series, span: int) -> pd.Series:
    """Standard exponential moving average with alpha = 2 / (span + 1)."""
    return series.ewm(span=span, adjust=False).mean()


def _rsi(close: pd.Series, window: int = 14) -> pd.Series:
    """Classic Wilder RSI. Returns a [0, 100] bounded series."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


# ---------- main entry point ------------------------------------------------


def build_features(candles: pd.DataFrame) -> pd.DataFrame:
    """Return a feature DataFrame (~37 cols) + target_logret from candles.

    Parameters
    ----------
    candles
        DataFrame with columns ``[bucket_start, open, high, low, close, volume]``
        sorted ASCENDING by ``bucket_start``. Any NaN rows are propagated;
        it's the caller's responsibility to drop them before fitting.

    Returns
    -------
    DataFrame indexed by ``bucket_start`` with all feature columns and
    ``target_logret`` appended. Feature columns survive in the order of
    :data:`FEATURE_COLUMNS`.
    """
    if candles.empty:
        return pd.DataFrame(columns=["bucket_start", *FEATURE_COLUMNS, "target_logret"])

    df = candles.sort_values("bucket_start").reset_index(drop=True).copy()

    # Ensure numeric (Supabase returns decimals as strings sometimes)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    open_, high, low, close, volume = df["open"], df["high"], df["low"], df["close"], df["volume"]

    # ---- Group A: raw OHLCV (no trade_count in v1) ------------------------
    df["f_open"] = open_
    df["f_high"] = high
    df["f_low"] = low
    df["f_close"] = close
    df["f_volume"] = volume

    # ---- Group B: log transforms ------------------------------------------
    df["f_log1p_volume"] = np.log1p(volume)
    df["f_log_close"] = np.log(close.replace(0, np.nan))

    # ---- Group C: returns and bar shape -----------------------------------
    df["f_ret"] = close.pct_change()
    df["f_logret"] = np.log(close / close.shift(1))
    df["f_range_pct"] = (high - low) / close
    df["f_body_pct"] = (close - open_) / close
    bar_top = np.maximum(open_.values, close.values)
    bar_bot = np.minimum(open_.values, close.values)
    df["f_wick_upper_pct"] = (high - bar_top) / close
    df["f_wick_lower_pct"] = (bar_bot - low) / close

    # ---- Group D: moving averages + ratios --------------------------------
    sma_5 = close.rolling(5, min_periods=5).mean()
    sma_20 = close.rolling(20, min_periods=20).mean()
    sma_50 = close.rolling(50, min_periods=50).mean()
    ema_12 = _ema(close, 12)
    ema_26 = _ema(close, 26)
    df["f_sma_5"] = sma_5
    df["f_sma_20"] = sma_20
    df["f_sma_50"] = sma_50
    df["f_ema_12"] = ema_12
    df["f_ema_26"] = ema_26
    df["f_close_over_sma20"] = close / sma_20 - 1
    df["f_sma5_over_sma20"] = sma_5 / sma_20 - 1

    # ---- Group E: volatility ----------------------------------------------
    vol_20 = df["f_logret"].rolling(20, min_periods=20).std()
    vol_50 = df["f_logret"].rolling(50, min_periods=50).std()
    df["f_vol_20"] = vol_20
    df["f_vol_50"] = vol_50
    df["f_atr14_proxy"] = ((high - low) / close).rolling(14, min_periods=14).mean()
    df["f_vol_ratio"] = vol_20 / vol_50.replace(0, np.nan)

    # ---- Group F: momentum / oscillators ----------------------------------
    df["f_rsi_14"] = _rsi(close, 14)
    df["f_momentum_10"] = close / close.shift(10) - 1
    df["f_momentum_50"] = close / close.shift(50) - 1
    macd_line = ema_12 - ema_26
    macd_signal = _ema(macd_line, 9)
    df["f_macd_hist"] = macd_line - macd_signal

    # ---- Group G: volume flow (count features dropped in v1) --------------
    vol_mean_20 = volume.rolling(20, min_periods=20).mean()
    vol_std_20 = volume.rolling(20, min_periods=20).std()
    df["f_vol_z_20"] = (volume - vol_mean_20) / vol_std_20.replace(0, np.nan)
    df["f_volume_change"] = volume.pct_change()

    # ---- Group H: calendar -------------------------------------------------
    ts = pd.to_datetime(df["bucket_start"], utc=True)
    hour = ts.dt.hour
    dow = ts.dt.dayofweek
    df["f_hour_sin"] = np.sin(2 * np.pi * hour / 24)
    df["f_hour_cos"] = np.cos(2 * np.pi * hour / 24)
    df["f_dow_sin"] = np.sin(2 * np.pi * dow / 7)
    df["f_dow_cos"] = np.cos(2 * np.pi * dow / 7)

    # ---- Group I: lagged log-returns --------------------------------------
    df["f_logret_lag_1"] = df["f_logret"].shift(1)
    df["f_logret_lag_3"] = df["f_logret"].shift(3)
    df["f_logret_lag_12"] = df["f_logret"].shift(12)

    # ---- Target: log-return of the NEXT bar -------------------------------
    df["target_logret"] = np.log(close.shift(-1) / close)

    # Return only the cols we care about, in a stable order
    out_cols = ["bucket_start", *FEATURE_COLUMNS, "target_logret"]
    return df[out_cols].copy()


# Canonical feature order. `model_versions.selected_features` will be a subset
# of this list after VIF elimination; the order of a model's coefficients
# matches the order of its `selected_features`.
FEATURE_COLUMNS: list[str] = [
    # Group A
    "f_open", "f_high", "f_low", "f_close", "f_volume",
    # Group B
    "f_log1p_volume", "f_log_close",
    # Group C
    "f_ret", "f_logret", "f_range_pct", "f_body_pct",
    "f_wick_upper_pct", "f_wick_lower_pct",
    # Group D
    "f_sma_5", "f_sma_20", "f_sma_50", "f_ema_12", "f_ema_26",
    "f_close_over_sma20", "f_sma5_over_sma20",
    # Group E
    "f_vol_20", "f_vol_50", "f_atr14_proxy", "f_vol_ratio",
    # Group F
    "f_rsi_14", "f_momentum_10", "f_momentum_50", "f_macd_hist",
    # Group G
    "f_vol_z_20", "f_volume_change",
    # Group H
    "f_hour_sin", "f_hour_cos", "f_dow_sin", "f_dow_cos",
    # Group I
    "f_logret_lag_1", "f_logret_lag_3", "f_logret_lag_12",
]
