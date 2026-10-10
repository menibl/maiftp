# Fast Lane Queue Behavior

The Edge Agent normally processes each FTP image like this:

```text
FTP image -> YOLO -> Webhook
```

When many new images are waiting, YOLO can create a long delay. The Fast Lane
mode prevents this. Only pending unsent images are counted, not every old image
still stored in the folder.

Default behavior:

```text
If queue_backlog > 10:
  skip YOLO and mark the image as sent
  send newest images first
  send image to webhook quickly
```

The GCP webhook receives a clear indication:

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

When YOLO did run:

```json
{
  "alert": true,
  "yolo_skipped": false,
  "requires_server_ai": false,
  "fast_lane": false
}
```

Use these fields on the GCP side:

```text
yolo_skipped=false -> YOLO already ran on the Edge PC.
yolo_skipped=true  -> alert=true and requires_server_ai=true; run AI/YOLO on GCP if needed.
```

Skipped images are not sent back to local YOLO later. Once the pending queue
drops to Max YOLO Queue or below, local YOLO resumes automatically.

Old backlog protection:

```text
Images that existed before Agent startup are dropped.
Images older than MaxFileAgeSeconds are dropped.
```

This prevents a Stop/Start or Windows restart from sending images that waited in
the folder for many minutes or hours.

Configuration file:

```text
00-MASTER-CONFIG.ps1
```

Relevant settings:

```powershell
YoloWorkerCount = "2"
MaxYoloQueueSize = "10"
MaxFileAgeSeconds = "120"
IgnoreExistingOnStart = "1"
NewestFirstWhenBacklogged = "1"
```

Use `2` YOLO workers for most i5/8GB PCs. Increase carefully only after checking
the `PERF` log lines; too many workers can overload CPU/RAM and slow everything
down.

Mission status polling is controlled by:

```powershell
HeartbeatMinutes = "1"
```

Use `1` so the Edge Agent detects RUNNING/PAUSED changes quickly.
