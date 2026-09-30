#!/usr/bin/env bash

set -euo pipefail

BASE_URL="http://localhost:7000"

LIMIT="${1:-25}"
PER_SCREEN="${2:-40}"

echo "Starting quant scan..."
echo

START_JSON="$(
  curl -s -X POST \
    "$BASE_URL/quant/run?limit=$LIMIT&per_screen=$PER_SCREEN"
)"

RUN_ID="$(
  printf '%s' "$START_JSON" \
  | python3 -c '
import sys, json
data = json.load(sys.stdin)
print(data["run_id"])
'
)"

echo "Run ID: $RUN_ID"
echo

while true; do

  PROGRESS="$(
    curl -s \
      "$BASE_URL/quant/progress/$RUN_ID"
  )"

  STATUS="$(
    printf '%s' "$PROGRESS" \
    | python3 -c '
import sys, json
d = json.load(sys.stdin)
print(d.get("status", "UNKNOWN"))
'
  )"

  clear

  PROGRESS_JSON="$PROGRESS" python3 - <<'PY'
import os
import json

d = json.loads(
    os.environ["PROGRESS_JSON"]
)

percent = float(
    d.get("percent") or 0
)

width = 40

filled = int(
    width * percent / 100
)

bar = (
    "█" * filled
    + "░" * (width - filled)
)

print("CEREBRO QUANT SCAN")
print("=" * 58)
print()

print(
    f"[{bar}] "
    f"{percent:5.1f}%"
)

print()

print(
    f"Status:           {d.get('status')}"
)
print(
    f"Stage:            {d.get('stage')}"
)
print(
    f"Message:          {d.get('message')}"
)

print()

print(
    f"Processed:        "
    f"{d.get('processed', 0)} / "
    f"{d.get('total', 0)}"
)

print(
    f"Current symbol:   "
    f"{d.get('current_symbol') or '-'}"
)

print()

print(
    f"Discovered:       "
    f"{d.get('discovered', 0)}"
)

print(
    f"Snapshot success: "
    f"{d.get('snapshot_success', 0)}"
)

print(
    f"Snapshot failed:  "
    f"{d.get('snapshot_failed', 0)}"
)

print()

print(
    f"Cache hits:       "
    f"{d.get('cache_hits', 0)}"
)

print(
    f"History fetched:  "
    f"{d.get('history_fetched', 0)}"
)

print()

print(
    f"Analysis success: "
    f"{d.get('analysis_success', 0)}"
)

print(
    f"Analysis skipped: "
    f"{d.get('analysis_skipped', 0)}"
)

print(
    f"Analysis failures:"
    f" {d.get('analysis_failures', 0)}"
)

print()

print(
    f"Elapsed:          "
    f"{d.get('elapsed_seconds', 0)} sec"
)

if d.get("error"):
    print()
    print(
        f"ERROR: {d['error']}"
    )
PY

  if [ "$STATUS" = "COMPLETE" ]; then
    echo
    echo "Quant scan complete."
    echo
    break
  fi

  if [ "$STATUS" = "FAILED" ]; then
    echo
    echo "Quant scan failed."
    echo
    break
  fi

  sleep 1

done

echo "Fetching final result..."
echo

curl -s \
  "$BASE_URL/quant/result/$RUN_ID" \
  > /tmp/quant-result.json

python3 -m json.tool \
  /tmp/quant-result.json
