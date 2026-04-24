"""One-time bootstrap training script — the pedagogical VIF walkthrough.

Run this ONCE before first deploy (and any time you want a fresh model from
scratch). It pulls candles from Supabase, computes features, runs logistic
regression with iterative VIF elimination, prints the full trace, saves artifacts under
``artifacts/``, and inserts a new row into ``model_versions`` marked
``is_active = TRUE`` so the live inference loop can pick it up.

Usage (from ``apps/worker``):

    uv run python -m worker.ml.bootstrap_train                 # all pairs
    uv run python -m worker.ml.bootstrap_train --pair BTC-USD  # one pair

Artifacts written (gitignored):

    artifacts/vif_trace__{pair}.csv        # one row per elimination iteration
    artifacts/coefficients__{pair}.csv     # final coefficients with std-errors
    artifacts/summary__{pair}.md           # human-readable report

The script is intentionally verbose and self-contained — it is the
reference document for how VIF elimination works in this project. Read it
top-to-bottom, don't just run it.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from worker.config import Settings
from worker.features import FEATURE_COLUMNS, build_features
from worker.ml.persistence import insert_and_activate
from worker.ml.train import train_with_vif
from worker.supabase_client import make_supabase

ARTIFACTS_DIR = Path(__file__).resolve().parents[2] / "artifacts"


# ---------- data loading ---------------------------------------------------

def load_candles(sb, symbol: str, granularity: int) -> pd.DataFrame:
    """Fetch all candles for (symbol, granularity) from Supabase."""
    print(f"\n[load] fetching candles for {symbol} at granularity={granularity}s")
    page_size = 1000
    offset = 0
    all_rows: list[dict] = []
    while True:
        res = (
            sb.table("candles")
            .select("*")
            .eq("symbol", symbol)
            .eq("granularity", granularity)
            .order("bucket_start", desc=False)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        rows = res.data or []
        all_rows.extend(rows)
        if len(rows) < page_size:
            break
        offset += page_size
    print(f"[load] got {len(all_rows)} candles")
    df = pd.DataFrame(all_rows)
    if df.empty:
        return df
    df["bucket_start"] = pd.to_datetime(df["bucket_start"], utc=True)
    return df


# ---------- artifact writers ------------------------------------------------

def write_artifacts(symbol: str, features_df: pd.DataFrame, model, window_start, window_end):
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    slug = symbol.replace("-", "_").lower()

    # VIF trace as CSV (flatten remaining_features to a pipe-joined string)
    trace_rows = []
    for entry in model.vif_trace:
        trace_rows.append({
            "iter": entry["iter"],
            "dropped": entry["dropped"] or "",
            "vif_max": entry["vif_max"],
            "r2": entry["r2"],
            "osr2": entry["osr2"],
            "hit_rate": entry["hit_rate"],
            "rmse": entry["rmse"],
            "n_remaining": len(entry["remaining_features"]),
            "remaining": "|".join(entry["remaining_features"]),
        })
    pd.DataFrame(trace_rows).to_csv(ARTIFACTS_DIR / f"vif_trace__{slug}.csv", index=False)

    # Coefficients as CSV
    coef_rows = [{"feature": "const", "coef": model.intercept}]
    for feat, coef in model.coefficients.items():
        coef_rows.append({"feature": feat, "coef": coef})
    pd.DataFrame(coef_rows).to_csv(ARTIFACTS_DIR / f"coefficients__{slug}.csv", index=False)

    # Summary as markdown
    top_feats = sorted(model.coefficients.items(), key=lambda kv: abs(kv[1]), reverse=True)[:5]
    dropped_features = [e["dropped"] for e in model.vif_trace if e["dropped"]]
    with (ARTIFACTS_DIR / f"summary__{slug}.md").open("w") as f:
        f.write(f"# {symbol} bootstrap model\n\n")
        f.write(f"- trained_at: `{datetime.now(tz=timezone.utc).isoformat()}`\n")
        f.write(f"- train_window: `{window_start.isoformat()}` to `{window_end.isoformat()}`\n")
        f.write(f"- total rows ingested for features: {len(features_df)}\n")
        f.write(f"- features surviving VIF: **{len(model.selected_features)}** ")
        f.write(f"(started with {len(FEATURE_COLUMNS)})\n\n")
        f.write("## Test-set metrics\n\n")
        f.write(f"- train+val accuracy: `{model.metrics.r2:.4f}`\n")
        f.write(f"- test accuracy: `{model.metrics.osr2:.4f}`\n")
        f.write(f"- test log-loss: `{model.metrics.rmse:.6f}`\n")
        f.write(f"- direction hit rate on test: `{model.metrics.hit_rate:.4f}` ")
        f.write(f"({model.metrics.tp}+{model.metrics.tn}={model.metrics.tp + model.metrics.tn}")
        f.write(f" correct / {model.metrics.n} total)\n\n")
        f.write("## Top 5 features by |coefficient|\n\n")
        for feat, coef in top_feats:
            f.write(f"- `{feat}` = `{coef:+.6f}`\n")
        f.write("\n## Features dropped by VIF (in order)\n\n")
        if dropped_features:
            for feat in dropped_features:
                f.write(f"- `{feat}`\n")
        else:
            f.write("_(none — VIF was already acceptable at start)_\n")

    print(f"[artifacts] wrote {ARTIFACTS_DIR}/{{vif_trace,coefficients,summary}}__{slug}.*")


# ---------- main flow -------------------------------------------------------

def bootstrap_one_pair(sb, settings: Settings, symbol: str) -> None:
    candles = load_candles(sb, symbol, settings.candle_granularity)
    if candles.empty or len(candles) < 100:
        print(f"[skip] {symbol}: only {len(candles)} candles. Run the worker longer first.")
        return

    print(f"[features] building feature matrix for {symbol}")
    feats = build_features(candles)
    clean = feats.dropna(subset=[*FEATURE_COLUMNS, "target_logret"])
    print(f"[features] {len(feats)} raw rows -> {len(clean)} clean rows after dropping NaN warmup")
    if len(clean) < 80:
        print(f"[skip] {symbol}: only {len(clean)} clean rows. Need more history.")
        return

    window_start = clean["bucket_start"].min()
    window_end = clean["bucket_start"].max()

    print(f"\n[vif-elimination] training on {symbol}")
    print(f"[vif-elimination] feature pool: {len(FEATURE_COLUMNS)} candidates")
    print("-" * 70)

    model = train_with_vif(clean, feature_cols=list(FEATURE_COLUMNS), verbose=True)

    print("\n" + "=" * 70)
    print(f"[persist] inserting model_versions row for {symbol}")
    model_id = insert_and_activate(
        sb,
        symbol=symbol,
        granularity=settings.candle_granularity,
        feature_set="v1",
        model=model,
        train_window_start=window_start.to_pydatetime() if isinstance(window_start, pd.Timestamp) else window_start,
        train_window_end=window_end.to_pydatetime() if isinstance(window_end, pd.Timestamp) else window_end,
    )
    print(f"[persist] model_versions.id = {model_id}  (is_active = TRUE)")

    write_artifacts(symbol, clean, model, window_start, window_end)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pair", help="Only bootstrap this pair (e.g. BTC-USD). Default: all watched pairs.")
    args = parser.parse_args()

    load_dotenv()
    settings = Settings()
    sb = make_supabase(settings)

    pairs = [args.pair] if args.pair else settings.pairs
    for symbol in pairs:
        print("\n" + "#" * 70)
        print(f"# BOOTSTRAP: {symbol}")
        print("#" * 70)
        try:
            bootstrap_one_pair(sb, settings, symbol)
        except Exception as exc:
            print(f"[error] {symbol}: {exc!r}")
            raise


if __name__ == "__main__":
    main()
