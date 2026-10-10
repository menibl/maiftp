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

## Security

Set `server.api_token` in `cameras.json`. Then send one of:

```http
Authorization: Bearer YOUR_TOKEN
X-Webhook-Token: YOUR_TOKEN
```

The web dashboard is intended for local LAN use.
