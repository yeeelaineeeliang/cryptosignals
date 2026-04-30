"""The shared training pipeline: logistic regression + iterative VIF elimination.

Called by BOTH the one-time bootstrap script and the periodic refit job. Same
inputs in, same outputs out — the only difference is the training window.

VIF elimination rules (see docs/VIF.md for the pedagogical walkthrough):

1. Fit standardizer on train fold only. Transform val/test with train stats.
2. Compute VIF on the standardized training feature matrix (with an intercept).
3. Fit logistic regression and record val accuracy.
4. Decision:
     max VIF > 10         -> drop unconditionally
     5 < max VIF <= 10    -> drop only if val accuracy does not degrade by > 0.005
     max VIF <= 5         -> STOP
5. Also stop when any further drop would cost > 0.01 val accuracy or < 3 features remain.

Coefficients are stored in the same JSONB format as before. Inference uses
sign(intercept + X @ coefs) to determine direction — the dot product now
produces log-odds instead of a predicted log-return, but the sign semantics
are identical: positive = LONG, negative = SHORT.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
import statsmodels.api as sm
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss as _log_loss
from statsmodels.stats.outliers_influence import variance_inflation_factor

from .metrics import BacktestMetrics, direction_confusion

VIF_DROP_HARD = 10.0
VIF_DROP_SOFT = 5.0
SOFT_OSR2_TOLERANCE = 0.01    # max val-accuracy drop allowed in the soft zone
HARD_OSR2_TOLERANCE = 0.01    # hard stop: costs more than this → don't drop
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
    r2: float        # train accuracy
    osr2: float      # val accuracy (used for VIF drop decisions)
    hit_rate: float  # val directional accuracy (same as osr2 here)
    rmse: float      # val log-loss
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


def _fit_logistic(
    x_train: pd.DataFrame, y_train: pd.Series,
    x_val: pd.DataFrame, y_val: pd.Series,
) -> _IterState:
    y_tr = (y_train > 0).astype(int)
    y_vl = (y_val > 0).astype(int)

    model = LogisticRegression(C=1.0, max_iter=1000, random_state=42)
    model.fit(x_train, y_tr)

    vif = _compute_vif(x_train)
    intercept = float(model.intercept_[0])
    coefs = {col: float(c) for col, c in zip(x_train.columns, model.coef_[0])}
    train_acc = float(model.score(x_train, y_tr))
    val_acc = float(model.score(x_val, y_vl))
    val_loss = float(_log_loss(y_vl, model.predict_proba(x_val)))

    return _IterState(
        features=list(x_train.columns),
        vif=vif,
        r2=train_acc,
        osr2=val_acc,
        hit_rate=val_acc,
        rmse=val_loss,
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
    vif_hard: float = VIF_DROP_HARD,
    vif_soft: float = VIF_DROP_SOFT,
    soft_osr2_tolerance: float = SOFT_OSR2_TOLERANCE,
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

    if max_vif <= vif_soft:
        if verbose:
            print(f"  -> stopping: max VIF {max_vif:.2f} <= {vif_soft}")
        return None, current

    if max_vif > vif_hard:
        kept = [c for c in features if c != worst]
        new_state = _fit_logistic(x_train[kept], y_train, x_val[kept], y_val)
        if verbose:
            print(f"  -> dropping {worst} (VIF {max_vif:.2f} > {vif_hard})")
        return worst, new_state

    # Soft zone: vif_soft < VIF <= vif_hard. Check val accuracy would not degrade too much.
    kept = [c for c in features if c != worst]
    candidate = _fit_logistic(x_train[kept], y_train, x_val[kept], y_val)
    degradation = current.osr2 - candidate.osr2
    if degradation <= soft_osr2_tolerance:
        if verbose:
            print(f"  -> dropping {worst} (VIF {max_vif:.2f}, val_acc change {-degradation:+.4f})")
        return worst, candidate
    if degradation > HARD_OSR2_TOLERANCE:
        if verbose:
            print(f"  -> stopping: dropping {worst} would cost {degradation:.4f} val_acc")
        return None, current
    if verbose:
        print(f"  -> stopping: {worst} in soft zone but val_acc cost {degradation:.4f}")
    return None, current


def train_with_vif(
    features_df: pd.DataFrame,
    *,
    feature_cols: list[str],
    target_col: str = "target_logret",
    train_frac: float = 0.70,
    val_frac: float = 0.15,
    verbose: bool = True,
    vif_hard: float = VIF_DROP_HARD,
    vif_soft: float = VIF_DROP_SOFT,
    soft_osr2_tolerance: float = SOFT_OSR2_TOLERANCE,
) -> TrainedModel:
    """Run the full VIF-pruned logistic regression training pipeline.

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
    state = _fit_logistic(x_train, y_train, x_val, y_val)
    vif_trace: list[dict[str, Any]] = [{
        "iter": 0, "dropped": None, "vif_max": max(state.vif.values()),
        "r2": state.r2, "osr2": state.osr2, "hit_rate": state.hit_rate,
        "rmse": state.rmse, "remaining_features": list(state.features),
    }]
    if verbose:
        print(f"[iter 0] n={len(x_train.columns)} max_vif={max(state.vif.values()):.2f} "
              f"train_acc={state.r2:.4f} val_acc={state.osr2:.4f}")

    it = 1
    while True:
        dropped, new_state = _step_drop(
            state.features, x_train[state.features], y_train,
            x_val[state.features], y_val, state, verbose=verbose,
            vif_hard=vif_hard, vif_soft=vif_soft,
            soft_osr2_tolerance=soft_osr2_tolerance,
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
                  f"max_vif={max(state.vif.values()):.2f} train_acc={state.r2:.4f} "
                  f"val_acc={state.osr2:.4f}")
        it += 1

    # ---- refit on train+val, score on test ------------------------------------
    final_feats = state.features
    tv_x = pd.concat([x_train[final_feats], x_val[final_feats]])
    tv_y = pd.concat([y_train, y_val])
    tv_y_bin = (tv_y > 0).astype(int)
    y_test_bin = (y_test > 0).astype(int)

    final_model = LogisticRegression(C=1.0, max_iter=1000, random_state=42)
    final_model.fit(tv_x[final_feats], tv_y_bin)

    y_pred_test_logodds = pd.Series(
        final_model.decision_function(x_test[final_feats]),
        index=y_test.index,
    )
    test_conf = direction_confusion(y_test, y_pred_test_logodds)
    tv_acc = float(final_model.score(tv_x[final_feats], tv_y_bin))
    test_acc = float(final_model.score(x_test[final_feats], y_test_bin))
    test_loss = float(_log_loss(y_test_bin, final_model.predict_proba(x_test[final_feats])))

    test_metrics = BacktestMetrics(
        r2=tv_acc,        # train+val accuracy
        osr2=test_acc,    # test accuracy
        rmse=test_loss,   # test log-loss
        hit_rate=test_conf.hit_rate,
        tp=test_conf.tp, fp=test_conf.fp, tn=test_conf.tn, fn=test_conf.fn,
        n=test_conf.n,
    )

    intercept = float(final_model.intercept_[0])
    coefficients = {c: float(v) for c, v in zip(final_feats, final_model.coef_[0])}

    # val metrics from the last VIF-elimination iteration state
    y_pred_val = pd.Series(
        state.intercept + x_val[final_feats].values @ [state.coefs.get(c, 0.0) for c in final_feats],
        index=y_val.index,
    )
    val_conf = direction_confusion(y_val, y_pred_val)
    val_metrics = BacktestMetrics(
        r2=state.r2, osr2=state.osr2, rmse=state.rmse,
        hit_rate=state.hit_rate,
        tp=val_conf.tp, fp=val_conf.fp, tn=val_conf.tn, fn=val_conf.fn,
        n=val_conf.n,
    )

    if verbose:
        print()
        print(f"[FINAL] features={len(final_feats)} train_acc={tv_acc:.4f} "
              f"test_acc={test_acc:.4f} test_hit={test_conf.hit_rate:.4f} "
              f"test_logloss={test_loss:.6f}")

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
