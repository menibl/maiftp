# MaiFocus customer PC installation settings.
# Edit this file once before running the numbered scripts.

$MaiFocusConfig = [ordered]@{
    # Main image webhook. Images are sent here.
    # Multiple webhooks are supported: separate URLs with comma, semicolon, or newline.
    WebhookUrl = ""

    # Token for image webhook and heartbeat.
    # Multiple tokens are supported in the same order as WebhookUrl.
    # If one token is set, it is used for all webhooks.
    WebhookToken = ""

    # Heartbeat control endpoint. Leave empty if config.json already contains the customer value.
    HeartbeatUrl = ""

    # Optional remote command endpoint. Leave empty if not used.
    RemoteCommandUrl = ""

    # Customer/site name shown in payloads and heartbeat.
    SourceName = "customer-site-1"

    # Agent mode: ftp-webhook, ftp-yolo-webhook, ftp-ai-image-webhook.
    Mode = "ftp-yolo-webhook"

    # Model: yolo26n.pt or yolov8n.pt.
    YoloModel = "yolo26n.pt"

    # FTP settings for camera.
    FtpPort = "2121"
    PassiveStart = "50000"
    PassiveEnd = "50100"
    FtpUser = "hikvision"
    FtpPassword = "CHANGE_ME_FTP_PASSWORD"

    # Heartbeat interval in minutes. Use 1 for fast mission status changes.
    HeartbeatMinutes = "1"

    # When pending images reach this count, skip YOLO and send images quickly.
    MaxYoloQueueSize = "10"

    # Images older than this are deleted and not sent after a backlog/restart.
    MaxFileAgeSeconds = "120"

    # On service start, do not process images that already existed in the folder.
    IgnoreExistingOnStart = "1"

    # Number of local YOLO workers to run in parallel. Use 2 for i5/8GB PCs.
    YoloWorkerCount = "2"

    # When backlog is high, send newest images first to avoid hours of delay.
    NewestFirstWhenBacklogged = "1"

    # RTSP Snapshot Service local API port, only if installing RTSP service too.
    RtspServicePort = "8088"

    # RTSP defaults used for all cameras unless a camera entry overrides them.
    RtspUsername = "admin"
    RtspPassword = "CHANGE_ME"
    RtspPort = 554
    RtspPath = "/Streaming/Channels/101"
    RtspTransport = "tcp"

    # Optional token for the local RTSP Snapshot API. Leave empty for LAN-only no-token access.
    RtspApiToken = ""

    # Customer camera CSV for RTSP Snapshot Service.
    # Edit rtsp-cameras.csv per customer. Required columns:
    # enabled, edge_camera_name, edge_ip
    # Optional per-camera override columns:
    # username / rtsp_username, password / rtsp_password, port / rtsp_port, path / rtsp_path
    RtspCameraCsv = "rtsp-cameras.csv"

    # Fallback camera list if RtspCameraCsv is empty or missing.
    RtspCameras = @(
        @{ Name = "Camera-1"; Ip = "192.168.90.10" },
        @{ Name = "Camera-2"; Ip = "192.168.90.11" }
    )
}
