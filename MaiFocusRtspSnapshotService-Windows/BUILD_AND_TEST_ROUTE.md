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

Request one image while the server sends the local camera IP:

```bash
curl -sS -X POST "$EDGE_BASE_URL/api/snapshot" \
  -H "Content-Type: application/json" \
  --data '{
    "camera_id": "cam_123",
    "camera_name": "Main Entrance",
    "local_ip": "192.168.90.42",
    "count": 1,
    "interval_ms": 0
  }' \
  -o response.json
```

The Edge will build:

```text
rtsp://RTSP_USERNAME:RTSP_PASSWORD@192.168.90.42:554/Streaming/Channels/101
```

Allowed camera IP ranges are controlled in `cameras.json`:

```json
{
  "security": {
    "allowed_camera_ip_cidrs": ["192.168.0.0/16", "10.0.0.0/8", "172.16.0.0/12"]
  }
}
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

## 6. RTSP to RTMP Relay

The Edge service supports one time-limited RTSP to RTMP relay at a time.
When a new relay request arrives, the previous relay is stopped first.

Most efficient mode is used:

```text
ffmpeg ... -c:v copy -f flv RTMP_URL
```

That means the Edge Device does not transcode video when the camera stream is
already H.264.

Start relay with full RTMP URL:

```bash
curl -sS -X POST "$EDGE_BASE_URL/api/rtmp-relay/start" \
  -H "Content-Type: application/json" \
  --data '{
    "camera_id": "cam_123",
    "camera_name": "Rahava 24",
    "local_ip": "192.168.90.42",
    "rtmp_url": "rtmp://YOUR_RTMP_SERVER/live/CAMERA_CODE",
    "duration_seconds": 300
  }' | python3 -m json.tool
```

Or configure this on the Edge in `cameras.json`:

```json
{
  "relay": {
    "rtmp_base_url": "rtmp://YOUR_RTMP_SERVER/live",
    "default_duration_seconds": 300,
    "max_duration_seconds": 1800
  }
}
```

Then send only the RTMP code:

```bash
curl -sS -X POST "$EDGE_BASE_URL/api/rtmp-relay/start" \
  -H "Content-Type: application/json" \
  --data '{
    "camera_name": "Rahava 24",
    "rtmp_code": "CAMERA_CODE",
    "duration_seconds": 300
  }' | python3 -m json.tool
```

Check relay status:

```bash
curl -sS "$EDGE_BASE_URL/api/rtmp-relay/status" | python3 -m json.tool
```

Stop relay:

```bash
curl -sS -X POST "$EDGE_BASE_URL/api/rtmp-relay/stop" | python3 -m json.tool
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
