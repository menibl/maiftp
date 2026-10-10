# Build and End-to-End Test

## 1. Edge Device

Copy this folder to the Edge Device:

```text
C:\ftpropin\rtsp_snapshot_service
```

Run the EXE:

```powershell
MaiFocusRtspSnapshotService.exe
```

Open from the Edge Device:

```text
http://127.0.0.1:8088
```

Open from another computer on the same LAN:

```text
http://EDGE_DEVICE_LAN_IP:8088
```

Example:

```text
http://192.168.90.100:8088
```

If Windows Firewall blocks it, allow TCP port `8088`.

The Edge Device also needs FFmpeg. Either install FFmpeg globally, or place
`ffmpeg.exe` in the same folder as `MaiFocusRtspSnapshotService.exe`.

Check FFmpeg from the browser:

```text
http://127.0.0.1:8088/api/ffmpeg
```

## 2. Direct API Request From GCP

The GCP server must be able to reach the Edge Device address. Use VPN, Tailscale,
WireGuard, Cloudflare Tunnel, or port forwarding with firewall rules.

Set the Edge URL:

```bash
export EDGE_BASE_URL="http://EDGE_DEVICE_REACHABLE_ADDRESS:8088"
```

Request one image:

```bash
curl -sS -X POST "$EDGE_BASE_URL/api/snapshot" \
  -H "Content-Type: application/json" \
  --data '{"camera_name":"Rahava 24","count":1,"interval_ms":0}' \
  -o response.json
```

Decode the first image:

```bash
python3 - <<'PY'
import base64, json
data = json.load(open("response.json", encoding="utf-8"))
print(data["ok"], data["camera_name"])
img = data["images"][0]
if not img["ok"]:
    print(img)
    raise SystemExit(1)
open("rahava_24.jpg", "wb").write(base64.b64decode(img["base64"]))
print("saved rahava_24.jpg")
PY
```

## 3. Helper Script From GCP

Copy `gcp_request_snapshot.sh` to the Linux server.

Run:

```bash
chmod +x gcp_request_snapshot.sh
export EDGE_BASE_URL="http://EDGE_DEVICE_REACHABLE_ADDRESS:8088"
./gcp_request_snapshot.sh "Rahava 24"
```

Output images are saved under:

```text
snapshots/
```

Multiple images from one camera:

```bash
COUNT=3 INTERVAL_MS=1000 ./gcp_request_snapshot.sh "Rahava 24"
```

## 4. GCP Webhook Test Server

This script receives a webhook on GCP, calls the Edge service, saves the images,
and returns JSON.

Run on GCP:

```bash
export EDGE_BASE_URL="http://EDGE_DEVICE_REACHABLE_ADDRESS:8088"
export PORT=8090
python3 gcp_webhook_server.py
```

Call the GCP webhook:

```bash
curl -sS -X POST "http://127.0.0.1:8090/snapshot" \
  -H "Content-Type: application/json" \
  --data '{"camera_name":"Rahava 24","count":1}' | python3 -m json.tool
```

Saved images are under:

```text
snapshots/
```

## 5. Optional Token

On the Edge Device:

```powershell
$env:MAIFOCUS_EDGE_TOKEN="CHANGE_ME_LONG_RANDOM_TOKEN"
.\MaiFocusRtspSnapshotService.exe
```

From GCP:

```bash
export EDGE_TOKEN="CHANGE_ME_LONG_RANDOM_TOKEN"
```

The helper scripts will send:

```http
Authorization: Bearer CHANGE_ME_LONG_RANDOM_TOKEN
```
