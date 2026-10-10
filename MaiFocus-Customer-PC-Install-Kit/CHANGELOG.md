# MaiFocus Customer PC Install Kit Changelog

## 3.18 - 2026-08-24

- Hardened recovery after power loss / cold boot before Windows login.
- Edge Agent, RTSP Snapshot Service, and watchdog startup tasks continue to run
  as `SYSTEM`, independent of user login, with no execution time limit.
- RTSP Snapshot Service is now installed and started from
  `C:\ProgramData\MaiFocusRtspSnapshotService` instead of depending on the kit
  folder location.
- RTSP runtime `cameras.json` is written to ProgramData during camera
  configuration.
- Watchdog now uses the ProgramData RTSP start script when available, so it can
  recover services before any user signs in.

## 3.17 - 2026-07-29

- Improved Edge Agent startup diagnostics after `RUN-ALL-AS-ADMIN`.
- `Start-EdgeAgent-From-Saved-Config.ps1` now waits for FTP TCP 2121 and writes
  `C:\ProgramData\MaiFocusEdgeAgent\logs\edge-agent-start-script.log`.
- The service watchdog now waits after restarting Edge Agent and logs whether
  FTP really became available.
- Validation now prints a clear `[FAIL]` when FTP TCP 2121 is not listening.
- Daily image cleanup is now only scheduled during install and is not run
  immediately during `RUN-ALL-AS-ADMIN`, reducing startup-time interference.

## 3.16 - 2026-07-26

- Fixed an Edge Agent image worker crash when a pending image file is deleted or
  disappears while the worker is scanning the FTP image folder.
- The image scan now collects file timestamps safely before sorting, skips files
  that vanish during the scan, and retries cleanly on scan errors.
- This prevents the FTP server from continuing to receive images while the image
  worker has stopped and no YOLO/Webhook processing occurs.

## 3.15 - 2026-07-22

- Added efficient RTSP warm capture cache to RTSP Snapshot Service.
- Snapshot requests now try to use a warm RTSP connection first. If a fresh
  frame is already available, the response is almost immediate.
- Warm capture is limited by default to 2 concurrent RTSP streams, 1 FPS, and
  120 seconds idle timeout, so it does not open 80 camera streams at once.
- Added warm capture config to generated `cameras.json`:
  `warm_capture.enabled`, `max_streams`, `idle_timeout_seconds`,
  `frame_max_age_seconds`, `first_frame_timeout_seconds`, and `fps`.
- Added API endpoints:
  `GET /api/warm-capture/status`,
  `POST /api/warm-capture/start`,
  `POST /api/warm-capture/stop`.
- Rebuilt `MaiFocusRtspSnapshotService.exe`.

## 3.14 - 2026-07-21

- The Edge Agent GUI now tails
  `C:\ProgramData\MaiFocusEdgeAgent\logs\edge-agent-service.log` when opened as
  a management window, so the GUI shows the live background service log.
- `09-Install-Log-Viewer-At-Logon.ps1` now opens the PowerShell live log viewer
  immediately after installation, not only on the next Windows login.
- The live log viewer still does not start another FTP server.

## 3.13 - 2026-07-21

- Fixed a false watchdog restart immediately after `RUN-ALL-AS-ADMIN.bat`.
- Edge Agent now writes `agent_health.json` immediately when the image worker
  starts, before YOLO model loading.
- Health now also reports `loading_yolo` and how many YOLO workers are loaded.
- Startup scripts delete stale `agent_health.json` before launching the
  headless Agent.
- Watchdog now gives a newly-started Edge Agent a grace window before acting on
  a stale health file from a previous run.

## 3.12 - 2026-07-21

- `02-Configure-And-Start-EdgeAgent.ps1` now writes a dedicated install/start
  log to `C:\ProgramData\MaiFocusEdgeAgent\logs\edge-agent-install-start.log`.
- If FTP does not listen after the first headless start, the installer retries
  using the saved ProgramData start script.
- If startup still fails, the installer prints current Edge Agent processes and
  recent service log lines.
- Added `11-Diagnose-EdgeAgent-Startup.ps1/.bat` for one-click startup
  diagnosis and manual retry on customer PCs.

## 3.11 - 2026-07-20

- Watchdog now runs every 1 minute instead of every 5 minutes.
- Edge Agent health stale threshold lowered from 15 minutes to 3 minutes.
- Pending image / stuck YOLO threshold lowered from 5 minutes to 3 minutes.
- If `agent_health.json` is missing more than 3 minutes after the Edge Agent
  process started, watchdog restarts the Edge Agent.
- This specifically targets the case where FTP keeps receiving images and
  heartbeat keeps working, but the image worker/YOLO pipeline stopped moving.

## 3.10 - 2026-07-20

- Added Edge Agent health reporting to
  `C:\ProgramData\MaiFocusEdgeAgent\agent_health.json`.
- The health file tracks poll activity, pending image count, oldest pending
  image age, YOLO start/finish, YOLO skipped state, webhook attempts, webhook
  success, and last processed image.
- `MaiFocus Services Watchdog` now checks the health file. If images are stuck
  in the pipeline for more than 5 minutes, YOLO appears stuck, or the health
  file is stale for more than 15 minutes, it restarts the Edge Agent.
- Rebuilt `MaiFocusEdgeAgent.exe` with health reporting.
- Confirmed default fast-lane behavior: when YOLO is skipped because the PC is
  busy or the queue is over the limit, the image is sent immediately with
  `alert=true`, `yolo_skipped=true`, and `requires_server_ai=true`.

## 3.9 - 2026-07-19

- `10-Install-GUI-At-Logon.ps1` now opens the Edge Agent GUI immediately after
  installing the logon task.
- The GUI still opens without `--auto-start`, so the background FTP service
  remains the only active FTP server.
- The logon task remains installed for future Windows logins after restart.

## 3.8 - 2026-07-19

- Added `Open-EdgeAgent-GUI.ps1`, which opens the Edge Agent GUI from the
  boot-safe ProgramData installation path.
- Added `10-Install-GUI-At-Logon.ps1/.bat`.
- `RUN-ALL-AS-ADMIN.ps1` now installs a user-logon task named
  `MaiFocus Edge Agent GUI At Logon`.
- After Windows login, the operator sees both the live log window and the GUI.
  The GUI opens without `--auto-start`, so the boot-time headless service keeps
  running and no second FTP server is started.

## 3.7 - 2026-07-14

- Added `Open-EdgeAgent-Live-Log.ps1`, a read-only live log viewer for
  `C:\ProgramData\MaiFocusEdgeAgent\logs\edge-agent-service.log`.
- Added `09-Install-Log-Viewer-At-Logon.ps1/.bat`.
- `RUN-ALL-AS-ADMIN.ps1` now installs a user-logon task named
  `MaiFocus Edge Agent Live Log Viewer`, so after Windows login the operator
  immediately sees a running log window without starting a second FTP server.
- `08-Repair-Boot-Autostart.ps1` and validation now include the log viewer task.

## 3.6 - 2026-07-14

- `02-Configure-And-Start-EdgeAgent.ps1` now migrates legacy per-user config
  files such as `C:\Users\user\MaiFocusEdgeAgent\config.json` into the
  boot-safe ProgramData location.
- This preserves older customer webhook/token/settings when upgrading to the
  headless boot service.

## 3.5 - 2026-07-14

- Fixed `taskkill` returning "process not found" and stopping the installer.
- No running Edge Agent process is now treated as a normal installation state.

## 3.4 - 2026-07-14

- Fixed `02-Configure-And-Start-EdgeAgent.ps1` failing when the installed
  ProgramData Edge Agent EXE is already running and locked.
- The installer now stops/kills existing Edge Agent processes before copying the
  EXE, and if Windows still keeps the EXE locked it reuses the installed copy
  instead of aborting the full install.

## 3.3 - 2026-07-14

- Fixed `03-Install-Startup-Autostart.ps1` trying to overwrite
  `C:\ProgramData\MaiFocusEdgeAgent\bin\MaiFocusEdgeAgent.exe` while the Edge
  Agent is already running.
- The startup installer now reuses the already-installed EXE and only copies it
  when missing.

## 3.2 - 2026-07-14

- Edge Agent EXE and startup script are now copied to
  `C:\ProgramData\MaiFocusEdgeAgent\bin`.
- Boot Scheduled Task now points to the fixed ProgramData start script instead
  of depending on the original install/ZIP folder path.
- Watchdog now prefers the ProgramData start script, so Edge Agent startup keeps
  working even if the install folder is moved after setup.

## 3.1 - 2026-07-14

- `02-Configure-And-Start-EdgeAgent.ps1` now starts the Edge Agent immediately
  in `--headless-service` mode instead of GUI `--auto-start`.
- The install script now waits up to 90 seconds for FTP port `2121` to listen
  and prints a warning with the headless log path if it is not ready.
- `Start-EdgeAgent-From-Saved-Config.ps1` now restarts a stuck Edge process when
  the process exists but the FTP port is not listening.

## 3.0 - 2026-07-14

- Edge Agent boot startup now uses `--headless-service`, so FTP, heartbeat,
  and image processing can run before Windows user login.
- Startup/watchdog delays were shortened so services recover faster after
  restart or power loss.
- Watchdog now validates listening ports, not only process names; if a process
  exists but FTP/RTSP is not listening, it restarts the process.
- Tailscale startup handling now supports both `Tailscale` and
  `TailscaleService` service names and forces automatic startup.
- Added `08-Repair-Boot-Autostart.ps1/.bat` to reinstall boot tasks and verify
  ports on an already-installed customer PC.
- Added persistent headless Edge log:
  `C:\ProgramData\MaiFocusEdgeAgent\logs\edge-agent-service.log`.

## 2.10 - 2026-07-11

- Added an Edge Agent backlog guard so old images are not sent after Stop/Start
  or Windows restart.
- Added `max_file_age_seconds` default `120`: images older than this are
  deleted locally and not sent to the webhook.
- Added `ignore_existing_on_start` default `1`: files that already existed
  before the Agent started are dropped, so processing begins from new FTP
  arrivals only.
- Added `Max Image Age sec` to the GUI and preserved it in `config.json`.

## 2.9 - 2026-07-07

- Removed real customer Webhook URL, Webhook Token, and Heartbeat URL from
  `00-MASTER-CONFIG.ps1`.
- Edge customer webhook settings are now expected to live in
  `C:\ProgramData\MaiFocusEdgeAgent\config.json`.
- `02-Configure-And-Start-EdgeAgent.ps1` preserves existing `config.json`
  customer values and warns if webhook settings are empty.
- `05-Validate-Installation.ps1` now tests heartbeat using values from the
  actual Edge `config.json`, not `00-MASTER-CONFIG.ps1`.

## 2.8 - 2026-07-07

- Removed customer-specific RTSP camera data from the install kit CSV.
- `rtsp-cameras.csv` in the kit is now a disabled template only.
- Customer RTSP camera data must live in
  `C:\ProgramData\MaiFocusEdgeAgent\rtsp-cameras.csv`.
- The install kit no longer ships another customer's camera list as default data.

## 2.7 - 2026-07-05

- RTSP `/api/snapshot` now also matches `local_ip` against
  `rtsp-cameras.csv`.
- Backend can send only the camera local IP, and Edge will still use
  per-camera CSV credentials when that IP exists in the table.
- Rebuilt `MaiFocusRtspSnapshotService.exe`.

## 2.6 - 2026-07-05

- RTSP `/api/snapshot` now tries to match `camera_id` or `camera_name` from
  `rtsp-cameras.csv` before using a direct `local_ip` fallback.
- This allows per-camera CSV credentials to be used when Backend sends
  `camera_id`/`camera_name` together with `local_ip`.
- Rebuilt `MaiFocusRtspSnapshotService.exe`.

## 2.5 - 2026-07-05

- RTSP camera CSV discovery now also checks the legacy user config folder:
  `C:\Users\<user>\MaiFocusEdgeAgent`.
- Supports common CSV names such as `rtsp-cameras.csv`, `RTSP_CAMERAS.CSV`,
  and `RTSP_CSMERAS.CSV`.
- If found there, the file is copied once to the persistent location:
  `C:\ProgramData\MaiFocusEdgeAgent\rtsp-cameras.csv`.

## 2.4 - 2026-07-05

- RTSP customer camera CSV is now persisted outside the install kit at
  `C:\ProgramData\MaiFocusEdgeAgent\rtsp-cameras.csv`.
- `04-Configure-RTSP-Cameras.ps1` copies the kit CSV there only on first setup.
- Future software updates no longer overwrite the customer's RTSP camera table.
- `cameras.json` remains generated output next to the RTSP service EXE.

## 2.3 - 2026-07-05

- Fixed RTSP Snapshot Service crash when `cameras.json` contains a UTF-8 BOM.
- RTSP service now reads camera config using `utf-8-sig`.
- `04-Configure-RTSP-Cameras.ps1` now writes `cameras.json` as UTF-8 without BOM.

## 2.2 - 2026-07-05

- Fixed Edge Agent settings persistence across upgrades.
- Edge Agent now defaults to `C:\ProgramData\MaiFocusEdgeAgent` even when opened
  manually, so GUI Save and Auto Startup use the same config.
- Existing `config.json` values are preserved by
  `02-Configure-And-Start-EdgeAgent.ps1` instead of being overwritten by
  `00-MASTER-CONFIG.ps1`.
- Config file values now override older Registry values when loading settings.

## 2.1 - 2026-07-05

- Added customer RTSP camera table: `rtsp-cameras.csv`.
- `04-Configure-RTSP-Cameras.ps1` now generates
  `02-RTSP-Snapshot-Service\cameras.json` from the CSV.
- CSV supports global RTSP credentials from `00-MASTER-CONFIG.ps1`.
- CSV also supports per-camera overrides:
  `rtsp_username`, `rtsp_password`, `rtsp_port`, `rtsp_path`.
- Rebuilt RTSP Snapshot Service to support per-camera RTSP credential/path
  overrides.

## 2.0 - 2026-07-05

Baseline release for managed versioning.

Includes:

- MaiFocus Edge Agent FTP/Yolo/Webhook package.
- RTSP Snapshot Service package.
- Camera Simulator package.
- Windows Firewall setup for FTP, passive FTP, and RTSP.
- Boot-time startup tasks for Edge Agent and RTSP.
- User-logon fallback tasks for Edge Agent and RTSP.
- MaiFocus Services Watchdog for Tailscale, Edge Agent, and RTSP.
- Daily image cleanup task for files older than 7 days.
- Stop-all script for safe folder deletion or reinstall.
- Validation script with task/process/port checks.

Versioning from here:

- Next small update: 2.1.
- Continue through 2.10 if needed.
- Move to 3.0 for a large or breaking change.
