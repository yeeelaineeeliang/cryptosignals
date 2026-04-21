#!/usr/bin/env bash
# Quick sanity check: is the worker alive? are models active?
#
# Usage:  ./bin/status.sh
#
# Takes ~2 seconds. Run whenever you want to confirm the system is healthy
# without pulling up a dashboard.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKER_DIR="$REPO_ROOT/apps/worker"

cd "$WORKER_DIR"

uv run --quiet python <<'PYEOF'
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
load_dotenv(".env")

from worker.config import Settings
from worker.supabase_client import make_supabase

s = Settings()
sb = make_supabase(s)

# --- heartbeat ---
hb = sb.table("worker_heartbeats").select("*").eq("id", 1).maybe_single().execute()
if hb and hb.data:
    last = datetime.fromisoformat(hb.data["last_poll_at"].replace("Z", "+00:00"))
    age = (datetime.now(timezone.utc) - last).total_seconds()
    if age < 15:
        status = "live"
    elif age < 120:
        status = "stale"
    else:
        status = "DOWN"
    print(f"worker: {status}  (last poll {age:.0f}s ago, errors: {hb.data['error_count']})")
    if hb.data.get("last_error"):
        print(f"        last error: {hb.data['last_error'][:100]}")
else:
    print("worker: no heartbeat row at all")

# --- active models ---
models = (
    sb.table("model_versions")
    .select("id,symbol,hit_rate,osr2,trained_at")
    .eq("is_active", True)
    .order("symbol")
    .execute()
    .data
)
print()
print("active models:")
if not models:
    print("  (none -- run bootstrap_train first)")
for m in models:
    tr = datetime.fromisoformat(m["trained_at"].replace("Z", "+00:00"))
    age_h = (datetime.now(timezone.utc) - tr).total_seconds() / 3600
    hit = float(m["hit_rate"] or 0)
    osr2 = float(m["osr2"] or 0)
    print(
        f"  {m['symbol']:<10} v{m['id']:<4}  "
        f"test_hit={hit:.3f}  test_osr2={osr2:+.3f}  "
        f"trained {age_h:.1f}h ago"
    )

# --- prediction rate (last 5 min) ---
cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
recent = sb.table("predictions").select("id").gte("created_at", cutoff).execute().data
print()
print(f"predictions in last 5 min: {len(recent)}  (expect ~20 at full cadence)")
PYEOF
