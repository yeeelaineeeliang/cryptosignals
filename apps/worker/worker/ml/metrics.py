"""Evaluation metrics shared by training, refit, and live evaluation.

Keeps the math in one place so the number reported during backtest training
and the number computed from live predictions use identical definitions.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(slots=True)
class BacktestMetrics:
    """Summary of a model's behavior on a held-out chunk of history."""

    r2: float
    osr2: float            # out-of-sample R² vs train-mean baseline
    rmse: float
    hit_rate: float        # fraction of predictions with sign matching realized
    tp: int
    fp: int
    tn: int
    fn: int
    n: int                 # number of predictions scored

    def as_confusion_dict(self) -> dict[str, int]:
        return {"tp": self.tp, "fp": self.fp, "tn": self.tn, "fn": self.fn}


def osr2(y_train: pd.Series, y_true: pd.Series, y_pred: pd.Series) -> float:
    """Out-of-sample R² = 1 - SSE / SST, where SST is measured against the
    TRAIN-SET mean. A naive model that always predicts the train mean scores
    0; the "perfect" model scores 1. Can be negative if the model is worse
    than the baseline.
    """
    sse = np.sum((y_true - y_pred) ** 2)
    sst = np.sum((y_true - y_train.mean()) ** 2)
    if sst == 0:
        return float("nan")
    return 1.0 - sse / sst


def rmse(y_true: pd.Series, y_pred: pd.Series) -> float:
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def direction_confusion(y_true: pd.Series, y_pred: pd.Series) -> BacktestMetrics:
    """Binarize by sign and score direction accuracy.

    Positive realized return = "up", positive prediction = "up". We do NOT
    score HOLD (abs(pred) < threshold) separately here — the calling code
    applies any threshold first and passes only LONG/SHORT predictions.
    """
    true_up = (y_true > 0).values
    pred_up = (y_pred > 0).values
    tp = int(np.sum(true_up & pred_up))
    tn = int(np.sum(~true_up & ~pred_up))
    fp = int(np.sum(~true_up & pred_up))
    fn = int(np.sum(true_up & ~pred_up))
    n = tp + tn + fp + fn
    hit_rate = (tp + tn) / n if n else float("nan")
    return BacktestMetrics(
        r2=float("nan"), osr2=float("nan"), rmse=float("nan"),
        hit_rate=hit_rate, tp=tp, fp=fp, tn=tn, fn=fn, n=n,
    )


def full_backtest(
    y_train: pd.Series,
    y_true: pd.Series,
    y_pred: pd.Series,
    r2_train: float,
) -> BacktestMetrics:
    conf = direction_confusion(y_true, y_pred)
    return BacktestMetrics(
        r2=r2_train,
        osr2=osr2(y_train, y_true, y_pred),
        rmse=rmse(y_true, y_pred),
        hit_rate=conf.hit_rate,
        tp=conf.tp, fp=conf.fp, tn=conf.tn, fn=conf.fn, n=conf.n,
    )
