#!/usr/bin/env bash
set -euo pipefail

EDGE_BASE_URL="${EDGE_BASE_URL:-http://127.0.0.1:8088}"
EDGE_TOKEN="${EDGE_TOKEN:-}"
CAMERA_NAME="${1:-Rahava 24}"
OUTPUT_DIR="${OUTPUT_DIR:-snapshots}"
COUNT="${COUNT:-1}"
INTERVAL_MS="${INTERVAL_MS:-0}"

mkdir -p "$OUTPUT_DIR"
response_file="$(mktemp)"

auth_args=()
if [[ -n "$EDGE_TOKEN" ]]; then
  auth_args=(-H "Authorization: Bearer $EDGE_TOKEN")
fi

curl -sS \
  -X POST "$EDGE_BASE_URL/api/snapshot" \
  -H "Content-Type: application/json" \
  "${auth_args[@]}" \
  --data "{\"camera_name\":\"$CAMERA_NAME\",\"count\":$COUNT,\"interval_ms\":$INTERVAL_MS}" \
  > "$response_file"

python3 - "$response_file" "$OUTPUT_DIR" <<'PY'
import base64
import json
import pathlib
import re
import sys
from datetime import datetime, timezone

response_file = pathlib.Path(sys.argv[1])
output_dir = pathlib.Path(sys.argv[2])
data = json.loads(response_file.read_text(encoding="utf-8"))
print(json.dumps({"ok": data.get("ok"), "camera_name": data.get("camera_name"), "count": data.get("count")}, indent=2))

if not data.get("ok"):
    print(json.dumps(data, indent=2, ensure_ascii=False))
    sys.exit(1)

camera = re.sub(r"[^A-Za-z0-9_-]+", "_", data.get("camera_name", "camera")).strip("_") or "camera"
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

for image in data.get("images", []):
    if not image.get("ok"):
        print(json.dumps(image, indent=2, ensure_ascii=False))
        continue
    index = image.get("index", 1)
    path = output_dir / f"{stamp}_{camera}_{index}.jpg"
    path.write_bytes(base64.b64decode(image["base64"]))
    print(f"saved {path} ({path.stat().st_size} bytes)")
PY

rm -f "$response_file"
