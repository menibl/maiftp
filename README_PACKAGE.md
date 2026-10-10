# MaiFocus Edge Agent for Windows

## What it does

The app runs inside the camera LAN and avoids inbound network requirements.

Modes:

- `ftp-webhook`: camera -> local FTP -> webhook
- `ftp-yolo-webhook`: camera -> local FTP -> local YOLO -> webhook
- `ftp-ai-image-webhook`: camera -> local FTP -> AI image model endpoint -> webhook

It also supports:

- hourly heartbeat
- outbound remote command polling
- remote status
- remote file list
- remote file deletion inside the image folder

## Camera FTP settings

Use the local IP shown in the app.

```text
Server Address: local IP of this PC
Port: 2121
Username: hikvision
Password: CHANGE_ME_FTP_PASSWORD
Path: /
Passive Mode: ON
```

## Auto start with default settings

First-time setup, run:

```text
Install Startup Autostart.bat
```

This asks for the Webhook URL once, saves the config, starts the app, and creates
a Windows Scheduled Task. After that, the PC can reboot unattended and the Agent
will start without asking anything.

To start manually from saved settings without prompts, run:

```text
Start Silent From Saved Settings.bat
```

This file never asks for input and never waits for Enter. It uses the saved
config and starts the FTP server immediately.

Old interactive start:

```text
Start Auto Default Settings.bat
```

The script asks for the Webhook URL, saves default settings, opens firewall
rules when it has permission, and starts the app with `--auto-start`.

Default auto-start settings:

```text
Mode: ftp-yolo-webhook
YOLO Model: yolo26n.pt
Alert Labels: person,car
Min Confidence: 0.6
Send only matching alerts: ON
Skip YOLO when PC is busy: ON
Max CPU: 85
YOLO Workers: 2
Compress image before webhook: ON
Upload Max Width: 1280
Upload JPEG Quality: 80
FTP Port: 2121
```

For protected webhooks, set:

```text
Webhook Token: your token
```

The Agent sends it as:

```text
X-Webhook-Token: your token
```

Multiple image webhooks can be configured in the same Webhook URL field by
separating URLs with commas, semicolons, or new lines:

```text
https://server/api/mission-webhooks/mission-a/ingest,
https://server/api/mission-webhooks/mission-b/ingest
```

Heartbeat is checked per webhook mission. If one mission is `RUNNING` and another
is paused, the image is sent only to the running mission's webhook. If no
configured webhook mission is running, the pending local image buffer is cleared.

Webhook tokens support the same pattern. If one token is entered, it is used for
all webhooks. If multiple tokens are entered, they are matched by order:

```text
Webhook URL(s):   url-a, url-b
Webhook Token(s): token-a, token-b
```

## Webhook endpoint

By default, the image webhook receives `POST application/json`:

```json
{
  "source": "customer-site-1",
  "camera_name": "SharRashy",
  "message": "image alert",
  "filename": "camera_001.jpg",
  "relative_path": "SharRashy\\camera_001.jpg",
  "alert": true,
  "detections": [
    {
      "label": "person",
      "confidence": 0.91,
      "xyxy": [120.0, 80.0, 340.0, 520.0]
    }
  ],
  "image_annotated": true,
  "annotated_filename": "camera_001_annotated.jpg",
  "image": {
    "filename": "camera_001_annotated_upload.jpg",
    "content_type": "image/jpeg",
    "size": 123456,
    "base64": "/9j/..."
  }
}
```

When YOLO runs and matching alert objects are found, the Agent saves an image
with red bounding boxes under `_annotated` and sends that annotated image to the
webhook. If YOLO is skipped because the queue is overloaded, no local boxes are
drawn and the payload includes `requires_server_ai: true`.

If your receiver expects file upload forms, set `Format` to `multipart`.
In multipart mode, the webhook receives `POST multipart/form-data`:

```text
image   = image file
payload = JSON metadata, including detections in YOLO mode
```

In `ftp-ai-image-webhook` mode, the app first calls the AI Image Model URL using
the same `multipart/form-data` shape:

```text
image   = image file
payload = JSON metadata
model   = optional AI model name
```

The AI image endpoint should return JSON. That JSON is added to the final webhook
payload under:

```json
{
  "ai_image_model": {
    "model": "your-model-name",
    "result": {}
  }
}
```

## Heartbeat endpoint

The heartbeat URL receives `POST application/json` once per configured interval.
Default interval is 1 minute so mission status changes such as `RUNNING` or
`PAUSED` are picked up quickly.
If Heartbeat URL is empty, the Agent derives it from the image webhook URL:

```text
https://server/api/mission-webhooks/<mission_id>/ingest
becomes
https://server/api/mission-webhooks/<mission_id>/heartbeat
```

For `gcpdev1.maifocus.com`, the image webhook can remain under `/api`, while
heartbeat is normalized to `/maia/api`:

```text
Images:
https://gcpdev1.maifocus.com/api/mission-webhooks/<mission_id>/ingest

Heartbeat:
https://gcpdev1.maifocus.com/maia/api/mission-webhooks/<mission_id>/heartbeat
```

Payload includes:

```json
{
  "agent_id": "PC-NAME",
  "source": "customer-site-1",
  "mission_id": "000000000000000000000000",
  "mode": "ftp-webhook",
  "status": "running",
  "mission_status": "RUNNING",
  "agent_action": "PROCESS_IMAGES",
  "image_processing_enabled": true,
  "hostname": "PC-NAME",
  "local_ips": ["192.168.1.10"],
  "ftp_port": 2121,
  "image_folder": {
    "files": 10,
    "bytes": 123456,
    "newest_file_utc": "2026-05-19T10:00:00+00:00"
  }
}
```

When mission status is not `RUNNING`, the FTP server stays online but new uploads
are rejected/ignored, and the local pending image buffer is cleared. This avoids
sending old images when a new mission starts later.

The heartbeat response can control image processing:

```json
{
  "success": true,
  "mission_status": "PAUSED",
  "agent_action": "PAUSE_IMAGE_PROCESSING"
}
```

When the response is `RUNNING` or `PROCESS_IMAGES`, images are processed.
For `PAUSED`, `STOPPED`, `MAINTENANCE`, or `PAUSE_IMAGE_PROCESSING`, FTP stays
online but new FTP uploads are rejected before they are saved and are not sent
to the webhook.

The heartbeat response can also assign new mission webhooks dynamically. The
agent saves them to `config.json`, so they remain configured after Windows
restart and Auto Startup.

```json
{
  "success": true,
  "webhooks": [
    {
      "mission_id": "000000000000000000000000",
      "ingest_url": "https://gcpdev1.maifocus.com/api/mission-webhooks/000000000000000000000000/ingest",
      "heartbeat_url": "https://gcpdev1.maifocus.com/maia/api/mission-webhooks/000000000000000000000000/heartbeat",
      "token": "TOKEN_FOR_THIS_MISSION",
      "mission_status": "RUNNING",
      "agent_action": "PROCESS_IMAGES"
    },
    {
      "mission_id": "another-mission-id",
      "ingest_url": "https://gcpdev1.maifocus.com/api/mission-webhooks/another-mission-id/ingest",
      "heartbeat_url": "https://gcpdev1.maifocus.com/maia/api/mission-webhooks/another-mission-id/heartbeat",
      "token": "TOKEN_FOR_SECOND_MISSION",
      "mission_status": "PAUSED",
      "agent_action": "PAUSE_IMAGE_PROCESSING"
    }
  ]
}
```

If the Edge PC is installed before any mission exists, configure only a fixed
Heartbeat URL and token. The first successful heartbeat can return the list
above, and the agent will add the image webhook URLs automatically.

## Remote command endpoint

The app polls the Remote Command URL with:

```json
{
  "agent": { "status": "..." },
  "result": null
}
```

The server can respond:

```json
{
  "commands": [
    { "id": "cmd-1", "action": "status" },
    { "id": "cmd-2", "action": "list_files", "limit": 50 },
    { "id": "cmd-3", "action": "delete_file", "path": "camera1/test.jpg" },
    { "id": "cmd-4", "action": "delete_all_images" },
    { "id": "cmd-5", "action": "restart_ftp" }
  ]
}
```

The app posts command results back to the same URL.

For full remote desktop access, install a tool such as RustDesk, AnyDesk, TeamViewer, or your RMM. This app provides outbound operational control and file cleanup, not interactive desktop control.

## YOLO

To send only images that contain a person or car, use:

```text
Mode: ftp-yolo-webhook
YOLO Model: yolo26n.pt or yolov8n.pt
Alert Labels: person,car
Min Confidence: 0.6
Send only matching alerts: checked
Skip YOLO when PC is busy and send image directly: checked
Max CPU: 85
Compress image before webhook: checked
Upload Max Width: 1280
JPEG Quality: 80
Webhook Format: json-base64
```

The final webhook payload includes:

```json
{
  "alert": true,
  "alert_labels": ["person", "car"],
  "alert_detections": [],
  "yolo_skipped": false,
  "yolo_skip_reason": null,
  "queue_backlog": 1,
  "fast_lane": false
}
```

When the pending unsent image queue is backlogged, the Agent skips YOLO and
sends the newest images to the webhook quickly. Old files that were already
sent are not counted. Images skipped in Fast Lane are marked as sent and are
not returned to local YOLO later.

```json
{
  "alert": true,
  "yolo_skipped": true,
  "yolo_skip_reason": "queue_backlog=25 > 10",
  "requires_server_ai": true,
  "queue_backlog": 25,
  "fast_lane": true
}
```

Once the pending queue drops back to `Max YOLO Queue` or below, local YOLO
resumes automatically.

`YOLO Workers` controls how many local YOLO processors run in parallel. Use `2`
for typical i5/8GB PCs. Higher values can reduce delay only if the CPU and RAM
can handle it; too many workers can overload the PC and make processing slower.

When `Send only matching alerts` is enabled and YOLO does not find a matching
label above the configured confidence, the image is marked as handled and is not
sent. The log prints the decision clearly, for example:

```text
YOLO result for cam1\image.jpg: detections=1, matches=0, alert=False, filter=car,person, min_confidence=0.60, found=dog:0.88
Skipped cam1\image.jpg: alert=False, no matching alert
```

`Max YOLO Queue` controls when this fast lane starts. `Newest first when
backlogged` sends the newest images first so fresh events do not wait behind a
large old backlog.

For YOLO mode on a packaged PC, install dependencies before packaging:

```powershell
python -m pip install -r requirements-yolo.txt
```

Then build:

```powershell
.\build_windows_package.ps1
```
