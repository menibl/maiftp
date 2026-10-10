import base64
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address, ip_network
from pathlib import Path
from shutil import which
from typing import Any
from urllib.parse import quote, urlparse


if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "cameras.json"


class Camera:
    def __init__(self, name: str, ip: str, rtsp_url: str, camera_id: str | None = None):
        self.name = name
        self.ip = ip
        self.rtsp_url = rtsp_url
        self.camera_id = camera_id


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


CONFIG = load_config()
CONFIG.setdefault("relay", {})
CONFIG["relay"].setdefault("rtmp_base_url", "")
CONFIG["relay"].setdefault("default_duration_seconds", 300)
CONFIG["relay"].setdefault("max_duration_seconds", 1800)
CONFIG.setdefault("warm_capture", {})
CONFIG["warm_capture"].setdefault("enabled", True)
CONFIG["warm_capture"].setdefault("max_streams", 2)
CONFIG["warm_capture"].setdefault("idle_timeout_seconds", 120)
CONFIG["warm_capture"].setdefault("frame_max_age_seconds", 5)
CONFIG["warm_capture"].setdefault("first_frame_timeout_seconds", 2.0)
CONFIG["warm_capture"].setdefault("fps", 1)
CONFIG.setdefault("security", {})
CONFIG["security"].setdefault("allowed_camera_ip_cidrs", ["192.168.0.0/16", "10.0.0.0/8", "172.16.0.0/12"])
if os.environ.get("MAIFOCUS_RTSP_USERNAME"):
    CONFIG["rtsp"]["username"] = os.environ["MAIFOCUS_RTSP_USERNAME"]
if os.environ.get("MAIFOCUS_RTSP_PASSWORD"):
    CONFIG["rtsp"]["password"] = os.environ["MAIFOCUS_RTSP_PASSWORD"]
if os.environ.get("MAIFOCUS_EDGE_TOKEN"):
    CONFIG["server"]["api_token"] = os.environ["MAIFOCUS_EDGE_TOKEN"]
if os.environ.get("MAIFOCUS_EDGE_PORT"):
    CONFIG["server"]["port"] = int(os.environ["MAIFOCUS_EDGE_PORT"])
if os.environ.get("MAIFOCUS_RTMP_BASE_URL"):
    CONFIG["relay"]["rtmp_base_url"] = os.environ["MAIFOCUS_RTMP_BASE_URL"]
CAPTURE_LOCK = threading.Lock()
JOBS_LOCK = threading.Lock()
RELAY_LOCK = threading.Lock()
WARM_LOCK = threading.RLock()
JOBS: dict[str, dict[str, Any]] = {}
RELAY: dict[str, Any] = {
    "id": None,
    "process": None,
    "camera_name": None,
    "camera_id": None,
    "ip": None,
    "rtmp_url": None,
    "rtmp_code": None,
    "started_at": None,
    "expires_at_monotonic": None,
    "duration_seconds": None,
    "status": "idle",
    "last_error": None,
    "stderr_tail": [],
}
WARM_STREAMS: dict[str, "WarmRtspStream"] = {}


def camera_key(camera: Camera) -> str:
    return camera.camera_id or camera.name.casefold() or camera.ip


def build_rtsp_url(ip: str, camera_config: dict[str, Any] | None = None) -> str:
    rtsp = CONFIG["rtsp"]
    camera_config = camera_config or {}
    username = quote(str(camera_config.get("username", rtsp["username"])), safe="")
    password = quote(str(camera_config.get("password", rtsp["password"])), safe="")
    port = int(camera_config.get("port", rtsp.get("port", 554)))
    path = str(camera_config.get("path", rtsp["path"]))
    if not path.startswith("/"):
        path = "/" + path
    return f"rtsp://{username}:{password}@{ip}:{port}{path}"


def build_camera_map() -> dict[str, Camera]:
    cameras = {}
    for item in CONFIG["cameras"]:
        name = str(item["name"])
        ip = str(item["ip"])
        camera_id = str(item.get("camera_id") or "") or None
        cameras[name.casefold()] = Camera(
            name=name,
            ip=ip,
            rtsp_url=build_rtsp_url(ip, item),
            camera_id=camera_id,
        )
    return cameras


CAMERAS = build_camera_map()


def public_cameras() -> list[dict[str, str | None]]:
    return [{"name": camera.name, "ip": camera.ip, "camera_id": camera.camera_id} for camera in CAMERAS.values()]


def get_camera(camera_name: str) -> Camera | None:
    return CAMERAS.get(str(camera_name).casefold())


def get_camera_by_id(camera_id: str | None) -> Camera | None:
    if not camera_id:
        return None
    normalized = str(camera_id).strip()
    for camera in CAMERAS.values():
        if camera.camera_id and camera.camera_id == normalized:
            return camera
    return None


def get_camera_by_ip(local_ip: str | None) -> Camera | None:
    if not local_ip:
        return None
    normalized = str(local_ip).strip()
    for camera in CAMERAS.values():
        if camera.ip == normalized:
            return camera
    return None


def validate_local_ip(local_ip: str) -> tuple[bool, str | None]:
    try:
        parsed_ip = ip_address(local_ip)
    except ValueError:
        return False, "invalid_local_ip"
    if parsed_ip.is_loopback or parsed_ip.is_multicast or parsed_ip.is_unspecified:
        return False, "disallowed_local_ip"

    cidrs = CONFIG.get("security", {}).get("allowed_camera_ip_cidrs") or []
    for cidr in cidrs:
        try:
            if parsed_ip in ip_network(str(cidr), strict=False):
                return True, None
        except ValueError:
            continue
    return False, "local_ip_not_in_allowed_ranges"


def camera_from_request(data: dict[str, Any]) -> tuple[Camera | None, dict[str, Any] | None]:
    local_ip = str(data.get("local_ip") or data.get("ip") or "").strip()
    camera_name = str(data.get("camera_name") or "").strip()
    camera_id = str(data.get("camera_id") or "").strip() or None
    configured_camera = (
        get_camera_by_id(camera_id)
        or (get_camera(camera_name) if camera_name else None)
        or get_camera_by_ip(local_ip)
    )

    if local_ip:
        ok, error = validate_local_ip(local_ip)
        if not ok:
            return None, {"status": 400, "error": error, "local_ip": local_ip}
        if configured_camera:
            return configured_camera, None
        display_name = camera_name or camera_id or local_ip
        return Camera(name=display_name, ip=local_ip, rtsp_url=build_rtsp_url(local_ip), camera_id=camera_id), None

    if not camera_name:
        return None, {"status": 400, "error": "camera_name_or_local_ip_required"}
    camera = configured_camera
    if not camera:
        return None, {"status": 404, "error": "camera_not_found", "camera_name": camera_name, "camera_id": camera_id}
    return camera, None


def auth_ok(headers) -> bool:
    expected = str(CONFIG.get("server", {}).get("api_token") or "")
    if not expected:
        return True
    authorization = headers.get("Authorization", "")
    webhook_token = headers.get("X-Webhook-Token", "")
    bearer = ""
    if authorization.lower().startswith("bearer "):
        bearer = authorization[7:].strip()
    return webhook_token == expected or bearer == expected


def classify_capture_error(stderr: str, returncode: int | None, timed_out: bool) -> str:
    text = (stderr or "").lower()
    if timed_out:
        return "timeout_or_no_rtsp_response"
    if "401" in text or "unauthorized" in text:
        return "bad_username_or_password"
    if "403" in text or "forbidden" in text:
        return "forbidden_check_permissions"
    if "connection refused" in text:
        return "connection_refused"
    if "no route to host" in text or "network is unreachable" in text:
        return "network_unreachable"
    if "could not resolve hostname" in text:
        return "dns_error"
    if "invalid data found" in text:
        return "rtsp_path_or_stream_error"
    if returncode:
        return "ffmpeg_capture_failed"
    return "unknown_capture_error"


def get_ffmpeg_command() -> str:
    configured = os.environ.get("MAIFOCUS_FFMPEG_PATH")
    if configured:
        return configured
    bundled = APP_DIR / "ffmpeg.exe"
    if bundled.exists():
        return str(bundled)
    return which("ffmpeg") or "ffmpeg"


def ffmpeg_status() -> dict[str, Any]:
    command = get_ffmpeg_command()
    try:
        completed = subprocess.run(
            [command, "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            check=False,
        )
    except FileNotFoundError as exc:
        return {
            "ok": False,
            "path": command,
            "error": "ffmpeg_not_found",
            "detail": str(exc),
        }
    except Exception as exc:
        return {
            "ok": False,
            "path": command,
            "error": "ffmpeg_check_failed",
            "detail": str(exc),
        }

    output = completed.stdout.decode("utf-8", errors="replace").splitlines()
    return {
        "ok": completed.returncode == 0,
        "path": command,
        "first_line": output[0] if output else "",
        "returncode": completed.returncode,
    }


def _read_pipe_exactly(pipe, size: int) -> bytes:
    chunks = []
    remaining = size
    while remaining > 0:
        chunk = pipe.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


class WarmRtspStream:
    def __init__(self, camera: Camera):
        self.camera = camera
        self.key = camera_key(camera)
        self.process: subprocess.Popen | None = None
        self.lock = threading.Lock()
        self.frame = b""
        self.frame_at_monotonic = 0.0
        self.frame_at_utc = ""
        self.last_used_monotonic = time.monotonic()
        self.started_at_utc = ""
        self.status = "new"
        self.last_error = None
        self.frames = 0
        self.stderr_tail: list[str] = []
        self.stop_event = threading.Event()

    def start(self) -> None:
        warm_cfg = CONFIG.get("warm_capture", {})
        rtsp = CONFIG["rtsp"]
        capture = CONFIG["capture"]
        fps = max(0.2, float(warm_cfg.get("fps") or 1))
        jpeg_quality = str(capture.get("jpeg_quality", 2))
        command = [
            get_ffmpeg_command(),
            "-hide_banner",
            "-loglevel",
            "warning",
            "-rtsp_transport",
            str(rtsp.get("transport", "tcp")),
            "-i",
            self.camera.rtsp_url,
            "-an",
            "-vf",
            f"fps={fps}",
            "-q:v",
            jpeg_quality,
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "pipe:1",
        ]
        try:
            self.process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
            self.started_at_utc = utc_now()
            self.status = "warming"
            threading.Thread(target=self._read_stdout, daemon=True).start()
            threading.Thread(target=self._read_stderr, daemon=True).start()
            threading.Thread(target=self._watch_process, daemon=True).start()
        except FileNotFoundError as exc:
            self.status = "failed"
            self.last_error = f"ffmpeg_not_found: {exc}"
        except Exception as exc:
            self.status = "failed"
            self.last_error = str(exc)

    def _read_stdout(self) -> None:
        if not self.process or not self.process.stdout:
            return
        buffer = bytearray()
        while not self.stop_event.is_set():
            chunk = self.process.stdout.read(4096)
            if not chunk:
                break
            buffer.extend(chunk)
            while True:
                start = buffer.find(b"\xff\xd8")
                if start < 0:
                    if len(buffer) > 1024 * 1024:
                        del buffer[:-2]
                    break
                end = buffer.find(b"\xff\xd9", start + 2)
                if end < 0:
                    if start > 0:
                        del buffer[:start]
                    break
                frame = bytes(buffer[start : end + 2])
                del buffer[: end + 2]
                with self.lock:
                    self.frame = frame
                    self.frame_at_monotonic = time.monotonic()
                    self.frame_at_utc = utc_now()
                    self.frames += 1
                    self.status = "ready"

    def _read_stderr(self) -> None:
        if not self.process or not self.process.stderr:
            return
        for raw_line in iter(self.process.stderr.readline, b""):
            if self.stop_event.is_set():
                return
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            with self.lock:
                self.stderr_tail.append(line)
                self.stderr_tail = self.stderr_tail[-20:]
                self.last_error = line

    def _watch_process(self) -> None:
        if not self.process:
            return
        returncode = self.process.wait()
        with self.lock:
            if not self.stop_event.is_set():
                self.status = "exited"
                self.last_error = f"ffmpeg_exited_{returncode}"

    def touch(self) -> None:
        with self.lock:
            self.last_used_monotonic = time.monotonic()

    def get_frame(self, max_age_seconds: float) -> tuple[bytes | None, dict[str, Any]]:
        with self.lock:
            self.last_used_monotonic = time.monotonic()
            frame_age = time.monotonic() - self.frame_at_monotonic if self.frame else None
            meta = {
                "status": self.status,
                "warm": True,
                "frames": self.frames,
                "frame_age_seconds": round(frame_age, 3) if frame_age is not None else None,
                "frame_at": self.frame_at_utc,
                "last_error": self.last_error,
            }
            if self.frame and frame_age is not None and frame_age <= max_age_seconds:
                return self.frame, meta
            return None, meta

    def stop(self, reason: str = "stopped") -> None:
        self.stop_event.set()
        process = self.process
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        with self.lock:
            self.status = "stopped"
            self.last_error = reason

    def public_status(self) -> dict[str, Any]:
        with self.lock:
            frame_age = time.monotonic() - self.frame_at_monotonic if self.frame else None
            idle_seconds = time.monotonic() - self.last_used_monotonic
            running = bool(self.process and self.process.poll() is None)
            return {
                "key": self.key,
                "camera_name": self.camera.name,
                "camera_id": self.camera.camera_id,
                "ip": self.camera.ip,
                "status": self.status,
                "running": running,
                "frames": self.frames,
                "frame_age_seconds": round(frame_age, 3) if frame_age is not None else None,
                "idle_seconds": round(idle_seconds, 3),
                "started_at": self.started_at_utc,
                "last_error": self.last_error,
                "stderr_tail": list(self.stderr_tail)[-10:],
            }


def warm_capture_enabled() -> bool:
    return bool(CONFIG.get("warm_capture", {}).get("enabled", True))


def get_or_start_warm_stream(camera: Camera) -> WarmRtspStream | None:
    if not warm_capture_enabled():
        return None
    key = camera_key(camera)
    with WARM_LOCK:
        cleanup_warm_streams_locked()
        stream = WARM_STREAMS.get(key)
        if stream:
            stream.touch()
            return stream

        warm_cfg = CONFIG.get("warm_capture", {})
        max_streams = max(0, int(warm_cfg.get("max_streams") or 0))
        if max_streams <= 0:
            return None
        while len(WARM_STREAMS) >= max_streams:
            oldest_key, oldest_stream = min(
                WARM_STREAMS.items(),
                key=lambda item: item[1].last_used_monotonic,
            )
            oldest_stream.stop("evicted_by_warm_stream_limit")
            WARM_STREAMS.pop(oldest_key, None)

        stream = WarmRtspStream(camera)
        WARM_STREAMS[key] = stream
        stream.start()
        return stream


def cleanup_warm_streams_locked() -> None:
    warm_cfg = CONFIG.get("warm_capture", {})
    idle_timeout = float(warm_cfg.get("idle_timeout_seconds") or 120)
    now = time.monotonic()
    for key, stream in list(WARM_STREAMS.items()):
        process_dead = bool(stream.process and stream.process.poll() is not None)
        idle_too_long = now - stream.last_used_monotonic > idle_timeout
        if process_dead or idle_too_long:
            stream.stop("idle_timeout" if idle_too_long else "process_exited")
            WARM_STREAMS.pop(key, None)


def warm_capture_status() -> dict[str, Any]:
    with WARM_LOCK:
        cleanup_warm_streams_locked()
        return {
            "ok": True,
            "enabled": warm_capture_enabled(),
            "config": CONFIG.get("warm_capture", {}),
            "count": len(WARM_STREAMS),
            "streams": [stream.public_status() for stream in WARM_STREAMS.values()],
        }


def stop_warm_stream(camera: Camera | None = None, reason: str = "manual_stop") -> dict[str, Any]:
    with WARM_LOCK:
        if camera is None:
            count = len(WARM_STREAMS)
            for stream in list(WARM_STREAMS.values()):
                stream.stop(reason)
            WARM_STREAMS.clear()
            return {"ok": True, "stopped": count}
        key = camera_key(camera)
        stream = WARM_STREAMS.pop(key, None)
        if stream:
            stream.stop(reason)
            return {"ok": True, "stopped": 1, "camera_name": camera.name, "camera_id": camera.camera_id}
        return {"ok": True, "stopped": 0, "camera_name": camera.name, "camera_id": camera.camera_id}


def clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(number, maximum))


def rtmp_url_from_request(data: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    rtmp_url = str(data.get("rtmp_url") or "").strip()
    rtmp_code = str(data.get("rtmp_code") or data.get("stream_key") or "").strip()
    if rtmp_url:
        return rtmp_url, rtmp_code or None, None

    base_url = str(CONFIG.get("relay", {}).get("rtmp_base_url") or "").strip().rstrip("/")
    if not base_url:
        return None, rtmp_code or None, "rtmp_url_required"
    if not rtmp_code:
        return None, None, "rtmp_code_required"
    return f"{base_url}/{rtmp_code}", rtmp_code, None


def relay_public_status() -> dict[str, Any]:
    with RELAY_LOCK:
        process = RELAY.get("process")
        running = bool(process and process.poll() is None)
        remaining_seconds = None
        if running and RELAY.get("expires_at_monotonic"):
            remaining_seconds = max(0, int(RELAY["expires_at_monotonic"] - time.monotonic()))
        return {
            "ok": True,
            "running": running,
            "id": RELAY.get("id"),
            "status": "running" if running else RELAY.get("status", "idle"),
            "camera_name": RELAY.get("camera_name"),
            "camera_id": RELAY.get("camera_id"),
            "ip": RELAY.get("ip"),
            "rtmp_url": RELAY.get("rtmp_url"),
            "rtmp_code": RELAY.get("rtmp_code"),
            "started_at": RELAY.get("started_at"),
            "duration_seconds": RELAY.get("duration_seconds"),
            "remaining_seconds": remaining_seconds,
            "last_error": RELAY.get("last_error"),
            "stderr_tail": list(RELAY.get("stderr_tail") or [])[-20:],
        }


def stop_relay_locked(reason: str) -> dict[str, Any]:
    process = RELAY.get("process")
    was_running = bool(process and process.poll() is None)
    if was_running:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    RELAY["process"] = None
    RELAY["status"] = "stopped"
    RELAY["last_error"] = reason
    RELAY["expires_at_monotonic"] = None
    return {"stopped": was_running, "reason": reason}


def stop_relay(reason: str = "manual_stop") -> dict[str, Any]:
    with RELAY_LOCK:
        result = stop_relay_locked(reason)
        return {"ok": True, **result, "relay": relay_public_status_without_lock()}


def relay_public_status_without_lock() -> dict[str, Any]:
    process = RELAY.get("process")
    running = bool(process and process.poll() is None)
    remaining_seconds = None
    if running and RELAY.get("expires_at_monotonic"):
        remaining_seconds = max(0, int(RELAY["expires_at_monotonic"] - time.monotonic()))
    return {
        "running": running,
        "id": RELAY.get("id"),
        "status": "running" if running else RELAY.get("status", "idle"),
        "camera_name": RELAY.get("camera_name"),
        "camera_id": RELAY.get("camera_id"),
        "ip": RELAY.get("ip"),
        "rtmp_url": RELAY.get("rtmp_url"),
        "rtmp_code": RELAY.get("rtmp_code"),
        "started_at": RELAY.get("started_at"),
        "duration_seconds": RELAY.get("duration_seconds"),
        "remaining_seconds": remaining_seconds,
        "last_error": RELAY.get("last_error"),
        "stderr_tail": list(RELAY.get("stderr_tail") or [])[-20:],
    }


def read_relay_stderr(relay_id: str, process: subprocess.Popen) -> None:
    if not process.stderr:
        return
    for raw_line in iter(process.stderr.readline, b""):
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        with RELAY_LOCK:
            if RELAY.get("id") != relay_id:
                return
            RELAY.setdefault("stderr_tail", []).append(line)
            RELAY["stderr_tail"] = RELAY["stderr_tail"][-30:]


def monitor_relay(relay_id: str, process: subprocess.Popen) -> None:
    returncode = process.wait()
    with RELAY_LOCK:
        if RELAY.get("id") != relay_id:
            return
        RELAY["process"] = None
        RELAY["status"] = "exited"
        RELAY["last_error"] = None if returncode == 0 else f"ffmpeg_exited_{returncode}"
        RELAY["expires_at_monotonic"] = None


def expire_relay(relay_id: str, duration_seconds: int) -> None:
    time.sleep(duration_seconds)
    with RELAY_LOCK:
        if RELAY.get("id") == relay_id:
            stop_relay_locked("duration_expired")


def start_relay(camera: Camera, rtmp_url: str, rtmp_code: str | None, duration_seconds: int) -> dict[str, Any]:
    relay_id = str(uuid.uuid4())
    command = [
        get_ffmpeg_command(),
        "-hide_banner",
        "-loglevel",
        "warning",
        "-rtsp_transport",
        str(CONFIG["rtsp"].get("transport", "tcp")),
        "-i",
        camera.rtsp_url,
        "-an",
        "-c:v",
        "copy",
        "-f",
        "flv",
        rtmp_url,
    ]

    with RELAY_LOCK:
        previous = stop_relay_locked("replaced_by_new_relay")
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            RELAY["status"] = "failed"
            RELAY["last_error"] = f"ffmpeg_not_found: {exc}"
            return {"ok": False, "error": "ffmpeg_not_found", "detail": str(exc), "previous": previous}
        except Exception as exc:
            RELAY["status"] = "failed"
            RELAY["last_error"] = str(exc)
            return {"ok": False, "error": "relay_start_failed", "detail": str(exc), "previous": previous}

        RELAY.update(
            {
                "id": relay_id,
                "process": process,
                "camera_name": camera.name,
                "camera_id": camera.camera_id,
                "ip": camera.ip,
                "rtmp_url": rtmp_url,
                "rtmp_code": rtmp_code,
                "started_at": utc_now(),
                "expires_at_monotonic": time.monotonic() + duration_seconds,
                "duration_seconds": duration_seconds,
                "status": "running",
                "last_error": None,
                "stderr_tail": [],
            }
        )

    threading.Thread(target=read_relay_stderr, args=(relay_id, process), daemon=True).start()
    threading.Thread(target=monitor_relay, args=(relay_id, process), daemon=True).start()
    threading.Thread(target=expire_relay, args=(relay_id, duration_seconds), daemon=True).start()

    time.sleep(1)
    with RELAY_LOCK:
        if RELAY.get("id") == relay_id and process.poll() is not None:
            RELAY["process"] = None
            RELAY["status"] = "failed"
            RELAY["last_error"] = f"ffmpeg_exited_{process.returncode}"
            return {
                "ok": False,
                "error": "relay_exited_immediately",
                "returncode": process.returncode,
                "relay": relay_public_status_without_lock(),
                "previous": previous,
            }
        return {"ok": True, "relay": relay_public_status_without_lock(), "previous": previous}


def capture_frame(camera: Camera) -> dict[str, Any]:
    rtsp = CONFIG["rtsp"]
    capture = CONFIG["capture"]
    warm_cfg = CONFIG.get("warm_capture", {})
    timeout_seconds = int(capture.get("timeout_seconds", 12))
    jpeg_quality = str(capture.get("jpeg_quality", 2))
    transport = str(rtsp.get("transport", "tcp"))
    warm_meta: dict[str, Any] | None = None

    if warm_capture_enabled():
        warm_started = time.monotonic()
        stream = get_or_start_warm_stream(camera)
        if stream:
            max_age = float(warm_cfg.get("frame_max_age_seconds") or 5)
            first_frame_timeout = float(warm_cfg.get("first_frame_timeout_seconds") or 2.0)
            while time.monotonic() - warm_started <= first_frame_timeout:
                frame, warm_meta = stream.get_frame(max_age)
                if frame:
                    elapsed_ms = int((time.monotonic() - warm_started) * 1000)
                    return {
                        "camera_id": camera.camera_id,
                        "camera_name": camera.name,
                        "ip": camera.ip,
                        "ok": True,
                        "elapsed_ms": elapsed_ms,
                        "captured_at": utc_now(),
                        "content_type": "image/jpeg",
                        "size": len(frame),
                        "base64": base64.b64encode(frame).decode("ascii"),
                        "capture_mode": "warm",
                        "warm_capture": warm_meta,
                    }
                time.sleep(0.05)

    command = [
        get_ffmpeg_command(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-rtsp_transport",
        transport,
        "-i",
        camera.rtsp_url,
        "-frames:v",
        "1",
        "-q:v",
        jpeg_quality,
        "-f",
        "image2pipe",
        "-vcodec",
        "mjpeg",
        "pipe:1",
    ]

    started = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
        image = completed.stdout
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        ok = completed.returncode == 0 and image.startswith(b"\xff\xd8")
        error = None if ok else classify_capture_error(stderr, completed.returncode, False)
    except FileNotFoundError as exc:
        image = b""
        stderr = str(exc)
        ok = False
        error = "ffmpeg_not_found"
    except subprocess.TimeoutExpired as exc:
        image = b""
        stderr = (exc.stderr or b"").decode("utf-8", errors="replace").strip()
        ok = False
        timed_out = True
        error = classify_capture_error(stderr, None, True)

    elapsed_ms = int((time.monotonic() - started) * 1000)
    result: dict[str, Any] = {
        "camera_id": camera.camera_id,
        "camera_name": camera.name,
        "ip": camera.ip,
        "ok": ok,
        "elapsed_ms": elapsed_ms,
        "captured_at": utc_now(),
        "capture_mode": "cold",
    }
    if warm_meta:
        result["warm_capture"] = warm_meta
    if ok:
        result["content_type"] = "image/jpeg"
        result["size"] = len(image)
        result["base64"] = base64.b64encode(image).decode("ascii")
    else:
        result["error"] = error
        result["detail"] = stderr[-800:] if stderr else error
        result["timed_out"] = timed_out
    return result


def create_job(kind: str) -> dict[str, Any]:
    job_id = str(uuid.uuid4())
    job = {
        "id": job_id,
        "kind": kind,
        "status": "queued",
        "created_at": utc_now(),
        "started_at": None,
        "finished_at": None,
        "total": len(CAMERAS),
        "completed": 0,
        "current_camera": None,
        "ok_count": 0,
        "failed_count": 0,
        "results": [],
    }
    with JOBS_LOCK:
        JOBS[job_id] = job
    thread = threading.Thread(target=run_all_job, args=(job_id, kind), daemon=True)
    thread.start()
    return {"ok": True, "job_id": job_id, "status_url": f"/api/jobs/{job_id}"}


def run_all_job(job_id: str, kind: str) -> None:
    gap = float(CONFIG["capture"].get("gap_seconds_between_cameras", 0.5))
    include_images = kind == "capture_all"
    job = JOBS[job_id]
    job["status"] = "running"
    job["started_at"] = utc_now()

    with CAPTURE_LOCK:
        for camera in CAMERAS.values():
            job["current_camera"] = camera.name
            result = capture_frame(camera)
            if not include_images:
                result.pop("base64", None)
            job["results"].append(result)
            job["completed"] = len(job["results"])
            if gap > 0:
                time.sleep(gap)

    job["current_camera"] = None
    job["finished_at"] = utc_now()
    job["status"] = "finished"
    job["ok_count"] = sum(1 for item in job["results"] if item["ok"])
    job["failed_count"] = sum(1 for item in job["results"] if not item["ok"])


def read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    return json.loads(raw.decode("utf-8"))


def dashboard_html() -> str:
    return """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MaiFocus RTSP Snapshot Service</title>
  <style>
    body { margin: 0; font-family: Arial, sans-serif; background: #f5f7fb; color: #18202c; }
    header { background: #17324d; color: white; padding: 18px 24px; }
    main { padding: 24px; max-width: 1200px; margin: 0 auto; }
    button { border: 0; border-radius: 6px; background: #1f6feb; color: white; padding: 10px 14px; cursor: pointer; font-weight: 700; }
    button.secondary { background: #59636e; }
    button:disabled { opacity: .6; cursor: wait; }
    .toolbar { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; margin-bottom: 18px; }
    .status { margin: 12px 0; font-weight: 700; }
    table { width: 100%; border-collapse: collapse; background: white; border: 1px solid #d8dee8; }
    th, td { padding: 9px 10px; border-bottom: 1px solid #e6eaf0; text-align: left; vertical-align: top; }
    th { background: #eef3f8; }
    .ok { color: #067647; font-weight: 700; }
    .bad { color: #b42318; font-weight: 700; }
    img { width: 180px; max-height: 120px; object-fit: contain; background: #eef3f8; }
    code { font-family: Consolas, monospace; font-size: 12px; white-space: pre-wrap; }
  </style>
</head>
<body>
  <header><h1>MaiFocus RTSP Snapshot Service</h1></header>
  <main>
    <div class="toolbar">
      <button id="testBtn" onclick="startJob('/api/test-all')">Test all cameras</button>
      <button id="captureBtn" onclick="startJob('/api/capture-all')">Capture one image from each camera</button>
      <button class="secondary" onclick="loadCameras()">Refresh camera list</button>
    </div>
    <div id="status" class="status">Ready</div>
    <table>
      <thead>
        <tr>
          <th>Camera</th>
          <th>IP</th>
          <th>Status</th>
          <th>Time</th>
          <th>Image</th>
          <th>Details</th>
        </tr>
      </thead>
      <tbody id="rows"></tbody>
    </table>
  </main>
  <script>
    let pollTimer = null;
    async function loadCameras() {
      const res = await fetch('/api/cameras');
      const data = await res.json();
      const rows = document.getElementById('rows');
      rows.innerHTML = data.cameras.map(c => `
        <tr>
          <td>${escapeHtml(c.name)}</td>
          <td>${escapeHtml(c.ip)}</td>
          <td>Not tested</td>
          <td></td>
          <td></td>
          <td></td>
        </tr>
      `).join('');
    }
    async function startJob(url) {
      document.getElementById('testBtn').disabled = true;
      document.getElementById('captureBtn').disabled = true;
      document.getElementById('status').textContent = 'Queued...';
      const res = await fetch(url, {method: 'POST'});
      const data = await res.json();
      pollJob(data.job_id);
    }
    async function pollJob(jobId) {
      if (pollTimer) clearTimeout(pollTimer);
      const res = await fetch(`/api/jobs/${jobId}`);
      const job = await res.json();
      document.getElementById('status').textContent =
        `${job.status}: ${job.completed}/${job.total}` + (job.current_camera ? ` - ${job.current_camera}` : '');
      renderResults(job.results || []);
      if (job.status === 'finished') {
        document.getElementById('testBtn').disabled = false;
        document.getElementById('captureBtn').disabled = false;
        document.getElementById('status').textContent =
          `Finished. OK: ${job.ok_count}, Failed: ${job.failed_count}`;
        return;
      }
      pollTimer = setTimeout(() => pollJob(jobId), 1500);
    }
    function renderResults(results) {
      const rows = document.getElementById('rows');
      rows.innerHTML = results.map(r => `
        <tr>
          <td>${escapeHtml(r.camera_name)}</td>
          <td>${escapeHtml(r.ip)}</td>
          <td class="${r.ok ? 'ok' : 'bad'}">${r.ok ? 'OK' : 'FAILED'}</td>
          <td>${r.elapsed_ms || ''} ms</td>
          <td>${r.base64 ? `<img src="data:image/jpeg;base64,${r.base64}">` : ''}</td>
          <td><code>${escapeHtml(r.ok ? `${r.size} bytes` : `${r.error || ''}\\n${r.detail || ''}`)}</code></td>
        </tr>
      `).join('');
    }
    function escapeHtml(value) {
      return String(value ?? '').replace(/[&<>"']/g, ch => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
      }[ch]));
    }
    loadCameras();
  </script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type,Authorization,X-Webhook-Token")
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self.send_html(dashboard_html())
            return
        if path == "/api/health":
            self.send_json(200, {"ok": True, "camera_count": len(CAMERAS), "time": utc_now()})
            return
        if path == "/api/ffmpeg":
            self.send_json(200, ffmpeg_status())
            return
        if path == "/api/cameras":
            self.send_json(200, {"count": len(CAMERAS), "cameras": public_cameras()})
            return
        if path == "/api/rtmp-relay/status":
            self.send_json(200, relay_public_status())
            return
        if path == "/api/warm-capture/status":
            self.send_json(200, warm_capture_status())
            return
        if path.startswith("/api/jobs/"):
            job_id = path.rsplit("/", 1)[-1]
            with JOBS_LOCK:
                job = JOBS.get(job_id)
            if not job:
                self.send_json(404, {"ok": False, "error": "job_not_found"})
                return
            self.send_json(200, job)
            return
        self.send_json(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/api/snapshot":
                self.handle_snapshot()
                return
            if path == "/api/rtmp-relay/start":
                self.handle_relay_start()
                return
            if path == "/api/rtmp-relay/stop":
                self.handle_relay_stop()
                return
            if path == "/api/warm-capture/start":
                self.handle_warm_start()
                return
            if path == "/api/warm-capture/stop":
                self.handle_warm_stop()
                return
            if path == "/api/test-all":
                self.send_json(200, create_job("test_all"))
                return
            if path == "/api/capture-all":
                self.send_json(200, create_job("capture_all"))
                return
            self.send_json(404, {"ok": False, "error": "not_found"})
        except json.JSONDecodeError as exc:
            self.send_json(400, {"ok": False, "error": "invalid_json", "detail": str(exc)})
        except Exception as exc:
            self.send_json(500, {"ok": False, "error": "server_error", "detail": str(exc)})

    def handle_snapshot(self) -> None:
        if not auth_ok(self.headers):
            self.send_json(401, {"ok": False, "error": "invalid_or_missing_api_token"})
            return
        data = read_json_body(self)
        count = max(1, min(int(data.get("count") or 1), 10))
        interval_ms = max(0, min(int(data.get("interval_ms") or 0), 10000))
        camera, error = camera_from_request(data)
        if error:
            status = int(error.pop("status"))
            self.send_json(status, {"ok": False, **error})
            return

        images = []
        with CAPTURE_LOCK:
            for index in range(count):
                result = capture_frame(camera)
                result["index"] = index + 1
                images.append(result)
                if index + 1 < count and interval_ms:
                    time.sleep(interval_ms / 1000)

        self.send_json(
            200,
            {
                "ok": all(item["ok"] for item in images),
                "camera_id": camera.camera_id,
                "camera_name": camera.name,
                "local_ip": camera.ip,
                "count": len(images),
                "images": images,
            },
        )

    def handle_relay_start(self) -> None:
        if not auth_ok(self.headers):
            self.send_json(401, {"ok": False, "error": "invalid_or_missing_api_token"})
            return
        data = read_json_body(self)
        camera, error = camera_from_request(data)
        if error:
            status = int(error.pop("status"))
            self.send_json(status, {"ok": False, **error})
            return

        relay_cfg = CONFIG.get("relay", {})
        default_duration = int(relay_cfg.get("default_duration_seconds") or 300)
        max_duration = int(relay_cfg.get("max_duration_seconds") or 1800)
        duration_seconds = clamp_int(data.get("duration_seconds"), default_duration, 10, max_duration)
        rtmp_url, rtmp_code, error = rtmp_url_from_request(data)
        if error:
            self.send_json(400, {"ok": False, "error": error})
            return

        result = start_relay(camera, str(rtmp_url), rtmp_code, duration_seconds)
        self.send_json(200 if result.get("ok") else 500, result)

    def handle_relay_stop(self) -> None:
        if not auth_ok(self.headers):
            self.send_json(401, {"ok": False, "error": "invalid_or_missing_api_token"})
            return
        with RELAY_LOCK:
            result = stop_relay_locked("manual_stop")
            status = relay_public_status_without_lock()
        self.send_json(200, {"ok": True, **result, "relay": status})

    def handle_warm_start(self) -> None:
        if not auth_ok(self.headers):
            self.send_json(401, {"ok": False, "error": "invalid_or_missing_api_token"})
            return
        data = read_json_body(self)
        camera, error = camera_from_request(data)
        if error:
            status = int(error.pop("status"))
            self.send_json(status, {"ok": False, **error})
            return
        stream = get_or_start_warm_stream(camera)
        if not stream:
            self.send_json(400, {"ok": False, "error": "warm_capture_disabled_or_max_streams_zero"})
            return
        self.send_json(200, {"ok": True, "stream": stream.public_status(), "warm_capture": warm_capture_status()})

    def handle_warm_stop(self) -> None:
        if not auth_ok(self.headers):
            self.send_json(401, {"ok": False, "error": "invalid_or_missing_api_token"})
            return
        data = read_json_body(self)
        if not data:
            self.send_json(200, stop_warm_stream(None, "manual_stop_all"))
            return
        camera, error = camera_from_request(data)
        if error:
            status = int(error.pop("status"))
            self.send_json(status, {"ok": False, **error})
            return
        self.send_json(200, stop_warm_stream(camera, "manual_stop"))

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} - {fmt % args}")


def main() -> None:
    server_cfg = CONFIG.get("server", {})
    host = str(server_cfg.get("host") or "0.0.0.0")
    port = int(server_cfg.get("port") or 8088)
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"MaiFocus RTSP Snapshot Service running on http://{host}:{port}")
    print(f"Loaded {len(CAMERAS)} cameras. Captures are serialized with one shared lock.")
    print(
        "Warm capture: enabled={enabled}, max_streams={max_streams}, idle_timeout={idle}s".format(
            enabled=warm_capture_enabled(),
            max_streams=CONFIG.get("warm_capture", {}).get("max_streams"),
            idle=CONFIG.get("warm_capture", {}).get("idle_timeout_seconds"),
        )
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
