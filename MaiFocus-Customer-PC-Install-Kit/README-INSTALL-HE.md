# MaiFocus Customer PC Install Kit

Version: 3.18

Version files:

```text
VERSION.txt
CHANGELOG.md
```

RTSP camera settings per customer:

Persistent customer file to edit on the Edge PC:

```text
C:\ProgramData\MaiFocusEdgeAgent\rtsp-cameras.csv
```

The kit also includes a starter copy:

```text
rtsp-cameras.csv
```

The starter copy is a disabled template only. On first setup,
`04-Configure-RTSP-Cameras.ps1` copies it to
`C:\ProgramData\MaiFocusEdgeAgent\rtsp-cameras.csv`. Future software updates do
not overwrite the persistent customer file.

For each customer, edit only:

```text
C:\ProgramData\MaiFocusEdgeAgent\rtsp-cameras.csv
```

Required columns:

```text
enabled, edge_camera_name, edge_ip
```

Optional per-camera override columns:

```text
rtsp_username, rtsp_password, rtsp_port, rtsp_path
```

Default RTSP username/password/path are configured in:

```text
00-MASTER-CONFIG.ps1
```

Then run:

```powershell
.\04-Configure-RTSP-Cameras.ps1
```

This creates the actual RTSP service config:

```text
02-RTSP-Snapshot-Service\cameras.json
```

RTSP warm capture:

The RTSP Snapshot Service can keep only a small number of recent RTSP
connections warm, so repeated snapshots from the same camera can return much
faster. It does not open RTSP connections to all cameras.

Default limits:

```json
{
  "enabled": true,
  "max_streams": 2,
  "idle_timeout_seconds": 120,
  "frame_max_age_seconds": 5,
  "first_frame_timeout_seconds": 2.0,
  "fps": 1
}
```

Useful API calls:

```text
GET  http://EDGE_IP:8088/api/warm-capture/status
POST http://EDGE_IP:8088/api/warm-capture/start
POST http://EDGE_IP:8088/api/warm-capture/stop
```

`/api/snapshot` automatically uses a warm frame when one is fresh enough, and
falls back to normal one-shot FFmpeg capture when needed.

חבילת התקנה מסודרת למחשב לקוח שמריץ:

- MaiFocus Edge Agent - שרת FTP מקומי, YOLO/AI, שליחה ל-Webhook, Heartbeat ל-GCP.
- MaiFocus RTSP Snapshot Service - שירות נפרד לדגימת RTSP לפי בקשה.
- Camera Simulator - כלי בדיקה שמדמה מצלמה ושולח תמונות ל-FTP.
- Source Code - קוד מקור מלא וסקריפטי build.
- GCP Helpers - קבצי עזר לצד GCP עבור RTSP snapshot.

## סדר התקנה מומלץ

להרצה מלאה אוטומטית:

1. לפתוח PowerShell או CMD בתור Administrator.
2. להריץ:

```bat
RUN-ALL-AS-ADMIN.bat
```

Autostart after reboot:

`RUN-ALL-AS-ADMIN.bat` now installs boot-time startup tasks, not only user-logon
tasks. After Windows starts, the kit will automatically start:

- Tailscale Windows service, if Tailscale is installed.
- MaiFocus Edge Agent FTP server.
- MaiFocus RTSP Snapshot Service.
- MaiFocus Services Watchdog, which checks every 5 minutes and restarts missing
  services/processes.
- MaiFocus Daily Image Cleanup, which deletes only image/video files older than
  7 days from the Edge Agent image folder.
- MaiFocus Edge Agent Live Log Viewer, which opens a live log window after user
  login so the operator can see that FTP, heartbeat, YOLO, and webhook activity
  are running. This viewer does not start another FTP server.
- MaiFocus Edge Agent GUI At Logon, which opens the Edge Agent GUI after user
  login for viewing settings and making changes. The GUI opens without
  `--auto-start`, so it does not start a second FTP server.
  The GUI also shows the live background service log.

The shared Edge Agent config is saved here:

```text
C:\ProgramData\MaiFocusEdgeAgent\config.json
```

Older installations used a per-user config path such as:

```text
C:\Users\user\MaiFocusEdgeAgent\config.json
```

The installer migrates/preserves that file automatically when ProgramData config
does not exist yet.

The boot-safe Edge Agent executable is copied here during installation:

```text
C:\ProgramData\MaiFocusEdgeAgent\bin\MaiFocusEdgeAgent.exe
```

Watchdog log:

```text
C:\ProgramData\MaiFocusEdgeAgent\logs\service-watchdog.log
```

Edge Agent health file used by the watchdog:

```text
C:\ProgramData\MaiFocusEdgeAgent\agent_health.json
```

The watchdog runs every 1 minute and restarts the Edge Agent if:

- the health file is stale for more than 3 minutes;
- the health file is missing more than 3 minutes after the Agent process starts;
- images are waiting in the local pipeline for more than 3 minutes without
  being processed or sent;
- YOLO appears to be stuck while processing an image.

When YOLO is skipped because the PC is busy or the queue is too large, the Edge
Agent sends the image directly to the webhook with:

```json
{
  "alert": true,
  "yolo_skipped": true,
  "requires_server_ai": true
}
```

Headless Edge Agent boot log:

```text
C:\ProgramData\MaiFocusEdgeAgent\logs\edge-agent-service.log
```

Live log viewer script:

```text
C:\ProgramData\MaiFocusEdgeAgent\bin\Open-EdgeAgent-Live-Log.ps1
```

GUI launcher script:

```text
C:\ProgramData\MaiFocusEdgeAgent\bin\Open-EdgeAgent-GUI.ps1
```

Important: before Windows login, the headless service runs the real FTP, YOLO,
heartbeat, and webhook flow. After login, the GUI is opened for management. If
you change settings in the GUI and press Save, the values are saved to
`C:\ProgramData\MaiFocusEdgeAgent\config.json`. Restart the Edge Agent service
or restart Windows for running background settings to reload.

When running `RUN-ALL-AS-ADMIN.bat`, the GUI is also opened immediately at the
end of setup, not only on the next Windows login.

Daily image cleanup log:

```text
C:\ProgramData\MaiFocusEdgeAgent\logs\image-cleanup.log
```

Windows does not need to auto-login for the background tasks. The boot tasks run
as `SYSTEM`. In version 3.0 the Edge Agent boot task runs with
`--headless-service`, so FTP, heartbeat, and image processing start without a
visible GUI and without waiting for user login. If you need to edit settings or
see the visible Edge Agent window, login and open the GUI manually. FTP/RTSP
health should be checked by ports/processes, not only by whether a window is
visible.

To repair an existing installed PC after a reboot/autostart problem, run as
Administrator:

```bat
08-Repair-Boot-Autostart.bat
```

If the Edge Agent does not start after `RUN-ALL-AS-ADMIN.bat`, run as
Administrator:

```bat
11-Diagnose-EdgeAgent-Startup.bat
```

This checks installed files, config, processes, port `2121`, scheduled tasks,
logs, and then tries a manual background start.

או להריץ ידנית לפי סדר:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\01-Install-Windows-Firewall.ps1
.\02-Configure-And-Start-EdgeAgent.ps1
.\03-Install-Startup-Autostart.ps1
.\04-Start-RTSP-Snapshot-Service.ps1
.\04-Install-RTSP-Startup-Autostart.ps1
.\06-Install-Service-Watchdog-Autostart.ps1
.\07-Install-Daily-Image-Cleanup.ps1
.\05-Validate-Installation.ps1
```

אם צריך גם RTSP Snapshot Service:

```powershell
.\04-Start-RTSP-Snapshot-Service.ps1
```

## קובץ ההגדרות המרכזי

לפני התקנה על מחשב לקוח, לערוך:

```text
00-MASTER-CONFIG.ps1
```

שם מגדירים:

- `WebhookUrl` - default only. Customer value should be saved in `C:\ProgramData\MaiFocusEdgeAgent\config.json`.
- `WebhookToken` - default only. Customer value should be saved in `C:\ProgramData\MaiFocusEdgeAgent\config.json`.
- `HeartbeatUrl` - default only. Customer value should be saved in `C:\ProgramData\MaiFocusEdgeAgent\config.json`.
- `SourceName` - שם אתר/לקוח.
- `Mode` - מצב עבודה.
- `YoloModel` - מודל YOLO.
- `HeartbeatMinutes` - כל כמה דקות לבדוק סטטוס משימה.

## הגדרות מצלמה ל-FTP

ברירת מחדל:

```text
FTP Server: IP address of this PC
Port: 2121
Username: hikvision
Password: CHANGE_ME_FTP_PASSWORD
Passive ports: 50000-50100
```

את כתובת ה-IP המקומית אפשר לראות בתוך חלון ה-Edge Agent או להריץ:

```powershell
ipconfig
```

## מה נפתח ב-Windows Firewall

הסקריפט `01-Install-Windows-Firewall.ps1` פותח:

```text
TCP 2121
TCP 50000-50100
TCP 8088
```

`8088` נדרש רק אם משתמשים ב-RTSP Snapshot Service.

## בדיקת תקינות

להריץ:

```powershell
.\05-Validate-Installation.ps1
```

הבדיקה מציגה:

- האם config קיים.
- האם token מוגדר.
- האם פורטים מאזינים.
- האם חוקי Firewall קיימים.
- האם Heartbeat מול GCP מחזיר תשובה.

בלוג תקין ב-Edge Agent יראה כך:

```text
[+] Heartbeat OK: HTTP 200; mission_status=RUNNING; agent_action=PROCESS_IMAGES
```

כאשר המשימה PAUSED:

```text
[+] Heartbeat OK: HTTP 200; mission_status=PAUSED; agent_action=PAUSE_IMAGE_PROCESSING
```

במצב PAUSED/STOPPED שרת ה-FTP נשאר פעיל ומאפשר חיבור, אבל העלאת קבצים נדחית בשלב
FTP STOR. כלומר התמונות לא נשמרות בתיקייה המקומית ולא נשלחות לשרת.

## מבנה הספרייה

```text
01-EdgeAgent-FTP
  MaiFocusEdgeAgent.exe
  סקריפטים מקוריים של ה-Agent

02-RTSP-Snapshot-Service
  MaiFocusRtspSnapshotService.exe
  cameras.json
  סקריפטים לפתיחת Firewall והרצה

03-Camera-Simulator
  כלי בדיקה לשליחת תמונות ל-FTP

04-Source-Code
  קוד מקור מלא

05-GCP-Helpers
  קבצי עזר ל-GCP עבור RTSP snapshot
```

## הערות חשובות

- יש להריץ את Firewall script בתור Administrator.
- התקנת Startup היא לפי המשתמש הנוכחי ב-Windows ומופעלת בזמן Logon.
- אם רוצים שהתוכנה תרוץ עוד לפני Login, צריך להמיר אותה לשירות Windows ייעודי.
- אין צורך לפתוח פורטים החוצה ל-GCP. ה-Agent יוזם חיבור HTTPS החוצה לשרת.
