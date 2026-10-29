#!/bin/sh
# Pull every city in data/cities.json, a few at a time so the weekly refresh
# stays well inside the CI time limit. Usage: sh pipeline/fetch_all.sh [max_locations] [parallel]
cd "$(dirname "$0")/.." || exit 1
MAX="${1:-1500}"
JOBS="${2:-3}"
python3 -c 'import json;[print(c["city"]+"|"+c["state"]) for c in json.load(open("data/cities.json"))]' |
while IFS='|' read -r city state; do
  printf '%s\0%s\0' "$city" "$state"
done |
xargs -0 -n 2 -P "$JOBS" sh -c 'python3 -I pipeline/fetch.py --city "$0" --state "$1" --payers "${PAYERS:-cigna,uhc,humana}" --max-locations '"$MAX"' || echo "fetch failed: $0"'
