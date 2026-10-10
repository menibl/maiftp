#!/usr/bin/env bash
set -euo pipefail

EDGE_BASE_URL="${EDGE_BASE_URL:-http://127.0.0.1:8088}"
EDGE_TOKEN="${EDGE_TOKEN:-}"
CAMERA_NAME="${1:?Usage: gcp_start_rtmp_relay.sh CAMERA_NAME RTMP_CODE_OR_URL [DURATION_SECONDS]}"
RTMP_TARGET="${2:?Usage: gcp_start_rtmp_relay.sh CAMERA_NAME RTMP_CODE_OR_URL [DURATION_SECONDS]}"
DURATION_SECONDS="${3:-300}"
CAMERA_ID="${CAMERA_ID:-}"
LOCAL_IP="${LOCAL_IP:-}"

auth_args=()
if [[ -n "$EDGE_TOKEN" ]]; then
  auth_args=(-H "Authorization: Bearer $EDGE_TOKEN")
fi

if [[ "$RTMP_TARGET" == rtmp://* || "$RTMP_TARGET" == rtmps://* ]]; then
  payload="{\"camera_name\":\"$CAMERA_NAME\",\"rtmp_url\":\"$RTMP_TARGET\",\"duration_seconds\":$DURATION_SECONDS"
else
  payload="{\"camera_name\":\"$CAMERA_NAME\",\"rtmp_code\":\"$RTMP_TARGET\",\"duration_seconds\":$DURATION_SECONDS"
fi
if [[ -n "$CAMERA_ID" ]]; then
  payload="$payload,\"camera_id\":\"$CAMERA_ID\""
fi
if [[ -n "$LOCAL_IP" ]]; then
  payload="$payload,\"local_ip\":\"$LOCAL_IP\""
fi
payload="$payload}"

curl -sS \
  -X POST "$EDGE_BASE_URL/api/rtmp-relay/start" \
  -H "Content-Type: application/json" \
  "${auth_args[@]}" \
  --data "$payload" | python3 -m json.tool
