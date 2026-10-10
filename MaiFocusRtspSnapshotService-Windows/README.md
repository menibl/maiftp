# MaiFocus RTSP Snapshot Service

Local LAN service for pulling one JPEG snapshot from Hikvision RTSP cameras.

## Requirements

- Python 3.10+
- FFmpeg installed and available in `PATH`
- No Python package dependencies

If FFmpeg is not installed globally, put `ffmpeg.exe` in the same folder as
`MaiFocusRtspSnapshotService.exe`.

Check FFmpeg:

```text
http://127.0.0.1:8088/api/ffmpeg
```

Run:

```powershell
.\run_service.ps1
```

Or run the Windows package:

```powershell
MaiFocusRtspSnapshotService.exe
```

The EXE must stay in the same folder as `cameras.json`.

Open:

```text
http://localhost:8088
```

## API

Single camera snapshot:

```http
POST /api/snapshot
Content-Type: application/json
```

```json
{
  "camera_name": "Rahava 24",
  "count": 1,
  "interval_ms": 0
}
```

Response contains base64 JPEG images.

The server can also send the camera IP directly. In that mode the Edge builds
the RTSP URL from `local_ip` and the shared RTSP settings in `cameras.json`:

```json
{
  "camera_id": "cam_123",
  "camera_name": "Main Entrance",
  "local_ip": "192.168.90.42",
  "count": 1,
  "interval_ms": 0
}
```

`local_ip` must be inside `security.allowed_camera_ip_cidrs`.

Start sequential health test for all cameras:

```http
POST /api/test-all
```

Start sequential capture from all cameras:

```http
POST /api/capture-all
```

Poll job status:

```http
GET /api/jobs/{job_id}
```

Start one time-limited RTSP to RTMP relay:

```http
POST /api/rtmp-relay/start
Content-Type: application/json
```

With a full RTMP URL:

```json
{
  "camera_id": "cam_123",
  "camera_name": "Rahava 24",
  "local_ip": "192.168.90.42",
  "rtmp_url": "rtmp://your-server/live/CAMERA_CODE",
  "duration_seconds": 300
}
```

Or set `relay.rtmp_base_url` in `cameras.json`, then send only the stream code:

```json
{
  "camera_name": "Rahava 24",
  "rtmp_code": "CAMERA_CODE",
  "duration_seconds": 300
}
```

Only one relay can run at a time. Starting a new relay stops the previous one.
The relay uses FFmpeg stream copy (`-c:v copy`) for low CPU usage.

Relay status:

```http
GET /api/rtmp-relay/status
```

Stop relay:

```http
POST /api/rtmp-relay/stop
```

## Security

Set `server.api_token` in `cameras.json`. Then send one of:

```http
Authorization: Bearer YOUR_TOKEN
X-Webhook-Token: YOUR_TOKEN
```

The web dashboard is intended for local LAN use.
