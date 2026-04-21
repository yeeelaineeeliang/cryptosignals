#!/usr/bin/env bash
# Daily checkup: backfill any unscored predictions, then print the
# backtest-vs-live gap per active model.
#
# Usage:  ./bin/daily.sh
#
# Takes ~30 seconds (most of it is the eval loop chewing through any
# queued predictions). Safe to run multiple times -- idempotent.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKER_DIR="$REPO_ROOT/apps/worker"

cd "$WORKER_DIR"

echo ">> Backfilling scored predictions + rolling up performance..."
echo

uv run --quiet python <<'PYEOF'
import asyncio

from dotenv import load_dotenv
load_dotenv(".env")

from worker.config import Settings
from worker.supabase_client import make_supabase
from worker.ml.evaluate import evaluate_predictions

async def main():
    s = Settings()
    sb = make_supabase(s)

    # Run up to 3 times to clear a deep backlog (each call caps at 500)
    for _ in range(3):
        await evaluate_predictions(sb, s)

    active = (
        sb.table("model_versions")
        .select("*")
        .eq("is_active", True)
        .execute()
        .data
    )
    perfs = (
        sb.table("model_performance")
        .select("*")
        .order("evaluated_at", desc=True)
        .limit(20)
        .execute()
        .data
    )
    latest_by_model = {}
    for p in perfs:
        if p["model_version_id"] not in latest_by_model:
            latest_by_model[p["model_version_id"]] = p

    print(f"{'SYMBOL':<10} {'TEST HIT':<10} {'LIVE HIT':<10} {'GAP':<10} {'N (24h)':<10}")
    print("-" * 55)
    for m in sorted(active, key=lambda m: m["symbol"]):
        test = float(m["hit_rate"] or 0)
        p = latest_by_model.get(m["id"])
        if not p:
            print(f"{m['symbol']:<10} {test:<10.4f} -          -          -          (no live data yet)")
            continue
        live = float(p["hit_rate"] or 0)
        gap = test - live
        n = sum(p["confusion"].values())
        if gap > 0.08:
            tag = "overfit"
        elif gap > 0.03:
            tag = "mild overfit"
        elif gap < -0.03:
            tag = "regime luck"
        else:
            tag = "honest"
        print(
            f"{m['symbol']:<10} {test:<10.4f} {live:<10.4f} {gap:+.4f}    {n:<6}   {tag}"
        )

asyncio.run(main())
PYEOF

echo
echo ">> Daily check complete."
