#!/bin/sh
# Pull every city in data/cities.json. Usage: sh pipeline/fetch_all.sh [max_locations]
cd "$(dirname "$0")/.." || exit 1
python3 -c 'import json;[print(c["city"]+"|"+c["state"]) for c in json.load(open("data/cities.json"))]' |
while IFS='|' read -r city state; do
  python3 -I pipeline/fetch.py --city "$city" --state "$state" --payers cigna,uhc --max-locations "${1:-1500}" || echo "fetch failed: $city"
done
