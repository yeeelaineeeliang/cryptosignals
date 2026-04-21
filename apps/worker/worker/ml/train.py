"""The shared training pipeline: OLS + iterative VIF elimination.

Called by BOTH the one-time bootstrap script and the periodic refit job. Same
inputs in, same outputs out — the only difference is the training window.

VIF elimination rules (see docs/VIF.md for the pedagogical walkthrough):

1. Fit standardizer on train fold only. Transform val/test with train stats.
2. Compute VIF on the standardized training feature matrix (with an intercept).
3. Fit OLS and record metrics on val.
4. Decision:
     max VIF > 10         -> drop unconditionally
     5 < max VIF <= 10    -> drop only if val OSR² does not degrade by > 0.005
     max VIF <= 5         -> STOP
5. Also stop when any further drop would cost > 0.01 val OSR² or < 3 features remain.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.outliers_influence import variance_inflation_factor

from .metrics import BacktestMetrics, full_backtest

VIF_DROP_HARD = 10.0
VIF_DROP_SOFT = 5.0
SOFT_OSR2_TOLERANCE = 0.005
HARD_OSR2_TOLERANCE = 0.01
MIN_FEATURES = 3


@dataclass(slots=True)
class TrainedModel:
    selected_features: list[str]
    intercept: float
    coefficients: dict[str, float]      # feature name -> coef
    scaler_means: dict[str, float]
    scaler_stds: dict[str, float]
    vif_trace: list[dict[str, Any]]     # one entry per iteration
    metrics: BacktestMetrics            # test-set metrics on held-out tail
    val_metrics: BacktestMetrics        # val-set metrics at stopping point


@dataclass(slots=True)
class _IterState:
    features: list[str]
    vif: dict[str, float]
    r2: float
    osr2: float
    hit_rate: float
    rmse: float
    intercept: float
    coefs: dict[str, float]


def _compute_vif(x: pd.DataFrame) -> dict[str, float]:
    """Compute VIF for every column in x (assumed already z-scored).

    Prepends a constant column so statsmodels can compute the variance
    inflation for each predictor relative to all the others. Drops the
    constant from the returned dict.
    """
    with_const = sm.add_constant(x, has_constant="add")
    vals = with_const.values
    return {
        col: float(variance_inflation_factor(vals, i + 1))  # +1 skips intercept
        for i, col in enumerate(x.columns)
    }


def _fit_ols(
    x_train: pd.DataFrame, y_train: pd.Series,
    x_val: pd.DataFrame, y_val: pd.Series,
) -> _IterState:
    model = sm.OLS(y_train, sm.add_constant(x_train, has_constant="add")).fit()
    y_pred_val = model.predict(sm.add_constant(x_val, has_constant="add"))
    metrics = full_backtest(y_train, y_val, y_pred_val, r2_train=float(model.rsquared))
    params = model.params
    intercept = float(params.get("const", 0.0))
    coefs = {col: float(params[col]) for col in x_train.columns if col in params}
    vif = _compute_vif(x_train)
    return _IterState(
        features=list(x_train.columns),
        vif=vif,
        r2=float(model.rsquared),
        osr2=metrics.osr2,
        hit_rate=metrics.hit_rate,
        rmse=metrics.rmse,
        intercept=intercept,
        coefs=coefs,
    )


def _standardize(
    x_train: pd.DataFrame, x_val: pd.DataFrame, x_test: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, float], dict[str, float]]:
    means = {c: float(x_train[c].mean()) for c in x_train.columns}
    stds = {c: float(x_train[c].std(ddof=0)) or 1.0 for c in x_train.columns}
    def _apply(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        for c in df.columns:
            out[c] = (df[c] - means[c]) / stds[c]
        return out
    return _apply(x_train), _apply(x_val), _apply(x_test), means, stds


def _step_drop(
    features: list[str], x_train: pd.DataFrame, y_train: pd.Series,
    x_val: pd.DataFrame, y_val: pd.Series,
    current: _IterState, verbose: bool,
) -> tuple[str | None, _IterState]:
    """Given the current state, pick the next feature to drop (or return None
    to stop). Returns (dropped_feature, new_state). dropped=None means stop.
    """
    if len(features) <= MIN_FEATURES:
        if verbose:
            print(f"  -> stopping: {MIN_FEATURES} features reached")
        return None, current

    max_vif = max(current.vif.values())
    worst = max(current.vif, key=current.vif.get)

    if max_vif <= VIF_DROP_SOFT:
        if verbose:
            print(f"  -> stopping: max VIF {max_vif:.2f} <= {VIF_DROP_SOFT}")
        return None, current

    if max_vif > VIF_DROP_HARD:
        # Unconditional drop
        kept = [c for c in features if c != worst]
        new_state = _fit_ols(x_train[kept], y_train, x_val[kept], y_val)
        if verbose:
            print(f"  -> dropping {worst} (VIF {max_vif:.2f} > {VIF_DROP_HARD})")
        return worst, new_state

    # Soft zone: 5 < VIF <= 10. Check OSR² would not degrade too much.
    kept = [c for c in features if c != worst]
    candidate = _fit_ols(x_train[kept], y_train, x_val[kept], y_val)
    degradation = current.osr2 - candidate.osr2
    if degradation <= SOFT_OSR2_TOLERANCE:
        if verbose:
            print(f"  -> dropping {worst} (VIF {max_vif:.2f}, OSR² change {-degradation:+.4f})")
        return worst, candidate
    if degradation > HARD_OSR2_TOLERANCE:
        if verbose:
            print(f"  -> stopping: dropping {worst} would cost {degradation:.4f} OSR²")
        return None, current
    # Between tolerance bands: defer and stop.
    if verbose:
        print(f"  -> stopping: {worst} in soft zone but OSR² cost {degradation:.4f}")
    return None, current


def train_with_vif(
    features_df: pd.DataFrame,
    *,
    feature_cols: list[str],
    target_col: str = "target_logret",
    train_frac: float = 0.70,
    val_frac: float = 0.15,
    verbose: bool = True,
) -> TrainedModel:
    """Run the full VIF-pruned OLS training pipeline.

    Parameters
    ----------
    features_df
        DataFrame sorted ascending by time, with all feature columns and the
        target. NaN rows are dropped first (caller may want to do this outside
        to know how many rows it cost).
    feature_cols
        Columns to treat as candidate predictors (typically FEATURE_COLUMNS).
    """
    df = features_df.dropna(subset=[*feature_cols, target_col]).reset_index(drop=True)
    if verbose:
        print(f"[train_with_vif] clean rows: {len(df)} (features: {len(feature_cols)})")

    n = len(df)
    train_end = int(n * train_frac)
    val_end = int(n * (train_frac + val_frac))
    train, val, test = df.iloc[:train_end], df.iloc[train_end:val_end], df.iloc[val_end:]
    assert len(train) > 0 and len(val) > 0 and len(test) > 0, "splits too small"

    x_train, x_val, x_test, scaler_means, scaler_stds = _standardize(
        train[feature_cols], val[feature_cols], test[feature_cols],
    )
    y_train, y_val, y_test = train[target_col], val[target_col], test[target_col]

    # ---- iterative elimination ------------------------------------------------
    state = _fit_ols(x_train, y_train, x_val, y_val)
    vif_trace: list[dict[str, Any]] = [{
        "iter": 0, "dropped": None, "vif_max": max(state.vif.values()),
        "r2": state.r2, "osr2": state.osr2, "hit_rate": state.hit_rate,
        "rmse": state.rmse, "remaining_features": list(state.features),
    }]
    if verbose:
        print(f"[iter 0] n={len(x_train.columns)} max_vif={max(state.vif.values()):.2f} "
              f"r2={state.r2:.4f} osr2={state.osr2:.4f} hit={state.hit_rate:.4f}")

    it = 1
    while True:
        dropped, new_state = _step_drop(
            state.features, x_train[state.features], y_train,
            x_val[state.features], y_val, state, verbose=verbose,
        )
        if dropped is None:
            break
        state = new_state
        vif_trace.append({
            "iter": it, "dropped": dropped, "vif_max": max(state.vif.values()),
            "r2": state.r2, "osr2": state.osr2, "hit_rate": state.hit_rate,
            "rmse": state.rmse, "remaining_features": list(state.features),
        })
        if verbose:
            print(f"[iter {it}] dropped={dropped} remaining={len(state.features)} "
                  f"max_vif={max(state.vif.values()):.2f} r2={state.r2:.4f} "
                  f"osr2={state.osr2:.4f} hit={state.hit_rate:.4f}")
        it += 1

    # ---- refit on train+val, score on test ------------------------------------
    final_feats = state.features
    tv_x = pd.concat([x_train[final_feats], x_val[final_feats]])
    tv_y = pd.concat([y_train, y_val])
    final_model = sm.OLS(tv_y, sm.add_constant(tv_x, has_constant="add")).fit()
    y_pred_test = final_model.predict(sm.add_constant(x_test[final_feats], has_constant="add"))
    test_metrics = full_backtest(tv_y, y_test, y_pred_test, r2_train=float(final_model.rsquared))

    params = final_model.params
    intercept = float(params.get("const", 0.0))
    coefficients = {c: float(params[c]) for c in final_feats if c in params}
    val_metrics = BacktestMetrics(
        r2=state.r2, osr2=state.osr2, rmse=state.rmse,
        hit_rate=state.hit_rate, tp=0, fp=0, tn=0, fn=0, n=len(y_val),
    )

    if verbose:
        print()
        print(f"[FINAL] features={len(final_feats)} train_r2={test_metrics.r2:.4f} "
              f"test_osr2={test_metrics.osr2:.4f} test_hit={test_metrics.hit_rate:.4f} "
              f"test_rmse={test_metrics.rmse:.6f}")

    return TrainedModel(
        selected_features=final_feats,
        intercept=intercept,
        coefficients=coefficients,
        scaler_means={c: scaler_means[c] for c in final_feats},
        scaler_stds={c: scaler_stds[c] for c in final_feats},
        vif_trace=vif_trace,
        metrics=test_metrics,
        val_metrics=val_metrics,
    )
