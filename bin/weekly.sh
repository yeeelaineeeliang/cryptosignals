#!/usr/bin/env bash
# Weekly retrain: stash old training artifacts, retrain on fresh data,
# diff the summaries so you can decide whether to keep the new model.
#
# Usage:  ./bin/weekly.sh
#
# What it does:
#   1. Backs up apps/worker/artifacts/ to apps/worker/artifacts.YYYYMMDD_HHMMSS/
#   2. Runs `uv run python -m worker.ml.bootstrap_train`
#      (this inserts a new model_versions row and marks it active;
#       previous active models are demoted automatically)
#   3. Prints a diff of the summary markdown before/after per pair
#
# If you don't like the new model, rollback via Supabase SQL:
#   BEGIN;
#   UPDATE model_versions SET is_active = FALSE WHERE is_active;
#   UPDATE model_versions SET is_active = TRUE WHERE id = <previous_id>;
#   COMMIT;

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKER_DIR="$REPO_ROOT/apps/worker"
ARTIFACTS_DIR="$WORKER_DIR/artifacts"

cd "$WORKER_DIR"

STAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="$WORKER_DIR/artifacts.$STAMP"

if [ -d "$ARTIFACTS_DIR" ] && [ -n "$(ls -A "$ARTIFACTS_DIR" 2>/dev/null)" ]; then
  echo "▶ Backing up existing artifacts to $(basename "$BACKUP_DIR")"
  cp -r "$ARTIFACTS_DIR" "$BACKUP_DIR"
else
  echo "▶ No previous artifacts to back up (first training run)"
  BACKUP_DIR=""
fi

echo
echo "▶ Running bootstrap_train on all watched pairs..."
echo "  (this takes ~30s per pair; output is verbose — VIF iterations print)"
echo

uv run python -m worker.ml.bootstrap_train

echo
echo "▶ Training complete."
echo

# ---- diffs ----
if [ -n "$BACKUP_DIR" ]; then
  for summary in "$ARTIFACTS_DIR"/summary__*.md; do
    [ -e "$summary" ] || continue
    name=$(basename "$summary")
    old="$BACKUP_DIR/$name"
    if [ -f "$old" ]; then
      echo "─── Diff: $name ───────────────────────────────"
      diff -u "$old" "$summary" || true
      echo
    else
      echo "─── New: $name (no previous version to diff) ───"
      cat "$summary"
      echo
    fi
  done
else
  for summary in "$ARTIFACTS_DIR"/summary__*.md; do
    [ -e "$summary" ] || continue
    echo "─── $(basename "$summary") ───────────────────────"
    cat "$summary"
    echo
  done
fi

echo "✓ Weekly retrain complete."
echo
echo "Decision rule after the diff:"
echo "  test OSR² up     → keep the new model (no action — it's already active)"
echo "  test OSR² down   → consider rollback (see header of this script)"
echo "  features < 5     → model is shrinking; market may have become noisier"
