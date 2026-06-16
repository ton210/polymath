#!/bin/bash
# Daily driver for the 7-day directional pilot: score yesterday's resolved bets,
# then place today's. Logs to pilot.log; uses a dedicated pilot.jsonl ledger.
set -u
REPO="/Users/tomernahumi/Documents/Plugins/polymath"
export PATH="/Users/tomernahumi/.local/bin:$PATH"   # ensure `claude` is found
cd "$REPO" || exit 1
source .venv/bin/activate

LEDGER="pilot.jsonl"
{
  echo "===== $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
  echo "--- settle ---"
  polymath settle --ledger "$LEDGER"
  echo "--- bet ---"
  polymath bet --ledger "$LEDGER"
  echo ""
} >> pilot.log 2>&1
