# -*- coding: utf-8 -*-
import json
import os
import queue
import shutil
import socket
import sys
import threading
import time
import argparse
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse, urlunparse
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import requests

from local_agent import run_agent
from local_agent import auth_headers

try:
    import winreg
except ImportError:
    winreg = None

try:
    from pyftpdlib.authorizers import DummyAuthorizer
    from pyftpdlib.handlers import FTPHandler
    from pyftpdlib.servers import FTPServer
except ImportError:
    FTPServer = None


APP_NAME = "MaiFocus Edge Agent"
APP_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
DEFAULT_RUNTIME_DIR = Path(os.environ.get("PROGRAMDATA", Path.home())) / "MaiFocusEdgeAgent"
LEGACY_RUNTIME_DIR = Path.home() / "MaiFocusEdgeAgent"
RUNTIME_DIR = Path(os.environ.get("MAIFOCUS_AGENT_HOME", DEFAULT_RUNTIME_DIR))
CONFIG_PATH = RUNTIME_DIR / "config.json"
STATE_DB = RUNTIME_DIR / "agent_state.sqlite3"
HEALTH_FILE = RUNTIME_DIR / "agent_health.json"
SERVICE_LOG_FILE = RUNTIME_DIR / "logs" / "edge-agent-service.log"
DEFAULT_IMAGE_DIR = RUNTIME_DIR / "hikvision_images"
REGISTRY_KEY = r"Software\MaiFocus\EdgeAgent"


DEFAULT_CONFIG = {
    "agent_id": socket.gethostname(),
    "source_name": "customer-site-1",
    "mode": "ftp-webhook",
    "webhook_url": "",
    "webhook_token": "",
    "ai_model_url": "",
    "ai_model_name": "",
    "heartbeat_url": "",
    "remote_command_url": "",
    "ftp_user": "hikvision",
    "ftp_password": "CHANGE_ME_FTP_PASSWORD",
    "ftp_port": "2121",
    "passive_start": "50000",
    "passive_end": "50100",
    "watch_dir": str(DEFAULT_IMAGE_DIR),
    "poll_seconds": "2",
    "stable_seconds": "2",
    "webhook_timeout": "30",
    "heartbeat_minutes": "1",
    "command_poll_seconds": "60",
    "yolo_model": "yolo26n.pt",
    "alert_labels": "person,car",
    "alert_min_confidence": "0.6",
    "send_only_alerts": "1",
    "skip_yolo_when_busy": "1",
    "max_cpu_percent": "85",
    "yolo_worker_count": "2",
    "max_yolo_queue_size": "10",
    "max_file_age_seconds": "120",
    "ignore_existing_on_start": "1",
    "newest_first_when_backlogged": "1",
    "compress_before_upload": "1",
    "upload_max_width": "1280",
    "upload_jpeg_quality": "80",
    "webhook_format": "json-base64",
}


class QueueWriter:
    def __init__(self, output_queue):
        self.output_queue = output_queue

    def write(self, text):
        if text:
            self.output_queue.put(text)

    def flush(self):
        pass


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def mission_id_from_webhook_url(webhook_url):
    try:
        parts = [part for part in urlparse(webhook_url).path.split("/") if part]
    except Exception:
        return ""

    for marker in ("mission-webhooks", "mission-webhook"):
        if marker in parts:
            index = parts.index(marker)
            if index + 1 < len(parts):
                return parts[index + 1]
    return ""


def split_webhook_urls(value):
    urls = []
    for item in (value or "").replace(";", "\n").replace(",", "\n").splitlines():
        url = item.strip()
        if url:
            urls.append(url)
    return urls


def split_webhook_tokens(value, count=0):
    tokens = split_webhook_urls(value)
    if not tokens:
        return [""] * count
    if len(tokens) == 1 and count > 1:
        return tokens * count
    if count > 0 and len(tokens) < count:
        tokens.extend([tokens[-1]] * (count - len(tokens)))
    return tokens


def join_config_list(items):
    return ", ".join(item.strip() for item in items if item and item.strip())


def primary_webhook_url(value):
    urls = split_webhook_urls(value)
    return urls[0] if urls else ""


def heartbeat_url_from_webhook_url(webhook_url):
    webhook_url = primary_webhook_url(webhook_url)
    if not webhook_url:
        return ""
    if "/ingest" in webhook_url:
        return normalize_heartbeat_url(webhook_url.rsplit("/ingest", 1)[0] + "/heartbeat")
    return ""


def heartbeat_url_for_webhook(webhook_url, index, heartbeat_urls):
    if index < len(heartbeat_urls) and heartbeat_urls[index]:
        return normalize_heartbeat_url(heartbeat_urls[index])
    return heartbeat_url_from_webhook_url(webhook_url)


def normalize_heartbeat_url(url):
    try:
        parsed = urlparse(url)
    except Exception:
        return url

    if parsed.netloc.lower() != "gcpdev1.maifocus.com":
        return url
    if parsed.path.startswith("/api/mission-webhooks/"):
        parsed = parsed._replace(path="/maia" + parsed.path)
        return urlunparse(parsed)
    return url


def local_ipv4_addresses():
    addresses = []
    try:
        hostname = socket.gethostname()
        for item in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = item[4][0]
            if ip != "127.0.0.1" and ip not in addresses:
                addresses.append(ip)
    except OSError:
        pass
    return addresses


def load_config():
    config = DEFAULT_CONFIG.copy()
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    if winreg is not None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY) as key:
                for name in DEFAULT_CONFIG:
                    try:
                        value, _ = winreg.QueryValueEx(key, name)
                    except FileNotFoundError:
                        continue
                    config[name] = value
        except OSError:
            pass

    for path in (LEGACY_RUNTIME_DIR / "config.json", CONFIG_PATH):
        if path.exists():
            try:
                config.update(json.loads(path.read_text(encoding="utf-8-sig")))
            except (OSError, json.JSONDecodeError):
                pass

    return config


def save_config(config):
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")

    if winreg is not None:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY) as key:
            for name, value in config.items():
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(value))


def safe_child_path(root, relative_path):
    root = Path(root).resolve()
    candidate = (root / relative_path).resolve()
    if root == candidate or root in candidate.parents:
        return candidate
    raise ValueError("Path is outside image folder")


def folder_stats(path):
    total_files = 0
    total_bytes = 0
    newest = None
    root = Path(path)
    if not root.exists():
        return {"files": 0, "bytes": 0, "newest_file_utc": None}

    for item in root.rglob("*"):
        if not item.is_file():
            continue
        total_files += 1
        try:
            stat = item.stat()
        except OSError:
            continue
        total_bytes += stat.st_size
        if newest is None or stat.st_mtime > newest:
            newest = stat.st_mtime

    return {
        "files": total_files,
        "bytes": total_bytes,
        "newest_file_utc": datetime.fromtimestamp(newest, timezone.utc).isoformat() if newest else None,
    }


class LocalFtpService:
    def __init__(self, config, output_queue, should_accept_files=None):
        self.config = config
        self.output_queue = output_queue
        self.should_accept_files = should_accept_files
        self.server = None
        self.thread = None

    def start(self):
        if FTPServer is None:
            raise RuntimeError("pyftpdlib is not installed")
        if self.thread and self.thread.is_alive():
            return

        watch_dir = Path(self.config["watch_dir"])
        watch_dir.mkdir(parents=True, exist_ok=True)

        authorizer = DummyAuthorizer()
        authorizer.add_user(
            self.config["ftp_user"],
            self.config["ftp_password"],
            str(watch_dir),
            perm="elradfmwMT",
        )

        should_accept_files = self.should_accept_files
        output_queue = self.output_queue

        class MissionAwareFTPHandler(FTPHandler):
            def ftp_STOR(self, file, mode="w"):
                if callable(should_accept_files) and not should_accept_files():
                    output_queue.put(f"[*] FTP upload rejected while mission is not RUNNING: {file}\n")
                    self.respond("550 Mission is not RUNNING; upload ignored.")
                    return
                return super().ftp_STOR(file, mode)

            def on_file_received(self, file):
                if callable(should_accept_files) and not should_accept_files():
                    try:
                        Path(file).unlink(missing_ok=True)
                        output_queue.put(f"[*] FTP upload removed after paused status: {file}\n")
                    except OSError as exc:
                        output_queue.put(f"[!] Could not remove paused FTP upload {file}: {exc}\n")

        handler = MissionAwareFTPHandler
        handler.authorizer = authorizer
        handler.banner = "MaiFocus Edge FTP Ready."
        handler.passive_ports = range(int(self.config["passive_start"]), int(self.config["passive_end"]) + 1)

        port = int(self.config["ftp_port"])
        self.server = FTPServer(("0.0.0.0", port), handler)
        self.thread = threading.Thread(target=self._serve, name="ftp-server", daemon=True)
        self.thread.start()
        self.output_queue.put(f"[+] FTP listening on 0.0.0.0:{port}; folder={watch_dir}\n")

    def _serve(self):
        writer = QueueWriter(self.output_queue)
        try:
            with redirect_stdout(writer), redirect_stderr(writer):
                self.server.serve_forever(timeout=1, blocking=True)
        except Exception as exc:
            self.output_queue.put(f"[!] FTP server stopped: {exc}\n")

    def stop(self):
        if self.server:
            self.server.close_all()
            self.server = None
            self.output_queue.put("[*] FTP stopped.\n")


class HeartbeatWorker:
    def __init__(self, app, output_queue):
        self.app = app
        self.output_queue = output_queue
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, name="heartbeat", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def _run(self):
        while not self.stop_event.is_set():
            self.send_once()
            interval = max(1, int(float(self.app.config["heartbeat_minutes"]) * 60))
            self.stop_event.wait(interval)

    def send_once(self):
        webhook_urls = self.app.configured_webhook_urls()
        heartbeat_urls = split_webhook_urls(self.app.config.get("heartbeat_url", "").strip())
        if not webhook_urls and not heartbeat_urls:
            return

        target_count = max(len(webhook_urls), len(heartbeat_urls), 1)
        tokens = split_webhook_tokens(self.app.config.get("webhook_token", "").strip(), target_count)
        if not any(tokens):
            self.output_queue.put("[!] Heartbeat token is empty. Authorization headers will not be sent.\n")

        if webhook_urls:
            targets = [
                (index, webhook_url, heartbeat_url_for_webhook(webhook_url, index, heartbeat_urls))
                for index, webhook_url in enumerate(webhook_urls)
            ]
        else:
            targets = [(0, None, normalize_heartbeat_url(heartbeat_urls[0]))]

        for index, webhook_url, url in targets:
            if not url:
                continue

            payload = self.app.status_payload(webhook_url)
            try:
                response = requests.post(
                    url,
                    json=payload,
                    headers=auth_headers(tokens[index] if index < len(tokens) else ""),
                    timeout=float(self.app.config["webhook_timeout"]),
                )
                mission_id = mission_id_from_webhook_url(webhook_url)
                if 200 <= response.status_code < 300:
                    self.app.apply_heartbeat_control(response, webhook_url)
                    self.app.apply_dynamic_webhooks(response)
                    state = self.app.webhook_controls.get(webhook_url, {})
                    self.output_queue.put(
                        f"[+] Heartbeat OK [{mission_id}]: HTTP {response.status_code}; "
                        f"mission_status={state.get('mission_status')}; agent_action={state.get('agent_action')}\n"
                    )
                else:
                    self.output_queue.put(f"[!] Heartbeat failed [{mission_id}]: HTTP {response.status_code} {response.text[:200]}\n")
            except Exception as exc:
                self.output_queue.put(f"[!] Heartbeat error [{mission_id_from_webhook_url(webhook_url)}]: {exc}\n")


class RemoteCommandWorker:
    def __init__(self, app, output_queue):
        self.app = app
        self.output_queue = output_queue
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, name="remote-commands", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def _run(self):
        while not self.stop_event.is_set():
            self.poll_once()
            interval = max(5, int(float(self.app.config["command_poll_seconds"])))
            self.stop_event.wait(interval)

    def poll_once(self):
        url = self.app.config.get("remote_command_url", "").strip()
        if not url:
            return

        request_payload = {"agent": self.app.status_payload(), "result": None}
        try:
            response = requests.post(
                url,
                json=request_payload,
                headers=auth_headers(self.app.config.get("webhook_token", "")),
                timeout=float(self.app.config["webhook_timeout"]),
            )
            if not (200 <= response.status_code < 300):
                self.output_queue.put(f"[!] Remote command poll failed: HTTP {response.status_code}\n")
                return
            data = response.json() if response.text else {}
        except Exception as exc:
            self.output_queue.put(f"[!] Remote command poll error: {exc}\n")
            return

        commands = data.get("commands") or []
        for command in commands:
            result = self.execute(command)
            try:
                requests.post(
                    url,
                    json={"agent": self.app.status_payload(), "result": result},
                    headers=auth_headers(self.app.config.get("webhook_token", "")),
                    timeout=float(self.app.config["webhook_timeout"]),
                )
            except Exception as exc:
                self.output_queue.put(f"[!] Could not report command result: {exc}\n")

    def execute(self, command):
        command_id = command.get("id")
        action = command.get("action")
        result = {"id": command_id, "action": action, "ok": False, "at_utc": utc_now()}
        watch_dir = Path(self.app.config["watch_dir"])

        try:
            if action == "status":
                result.update({"ok": True, "status": self.app.status_payload()})
            elif action == "list_files":
                limit = int(command.get("limit", 50))
                files = []
                for item in sorted(watch_dir.rglob("*"), key=lambda p: p.stat().st_mtime if p.is_file() else 0, reverse=True):
                    if item.is_file():
                        stat = item.stat()
                        files.append({
                            "path": str(item.relative_to(watch_dir)),
                            "size": stat.st_size,
                            "modified_at_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                        })
                    if len(files) >= limit:
                        break
                result.update({"ok": True, "files": files})
            elif action == "delete_file":
                target = safe_child_path(watch_dir, command.get("path", ""))
                target.unlink()
                result.update({"ok": True, "deleted": str(target.relative_to(watch_dir))})
            elif action == "delete_all_images":
                deleted = 0
                for item in watch_dir.rglob("*"):
                    if item.is_file():
                        item.unlink()
                        deleted += 1
                result.update({"ok": True, "deleted": deleted})
            elif action == "restart_ftp":
                self.app.restart_ftp()
                result.update({"ok": True})
            else:
                result["error"] = f"Unknown action: {action}"
        except Exception as exc:
            result["error"] = str(exc)

        self.output_queue.put(f"[*] Remote command {action}: {'OK' if result['ok'] else result.get('error')}\n")
        return result


class EdgeAgentGui(tk.Tk):
    def __init__(self, auto_start=False):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("980x720")
        self.minsize(860, 620)

        self.config = load_config()
        self.vars = {}
        self.output_queue = queue.Queue()
        self.agent_stop_event = None
        self.agent_thread = None
        self.ftp_service = None
        self.heartbeat = HeartbeatWorker(self, self.output_queue)
        self.remote_commands = RemoteCommandWorker(self, self.output_queue)
        self.image_processing_enabled = True
        self.mission_status = "RUNNING"
        self.agent_action = "PROCESS_IMAGES"
        self.webhook_controls = {}
        self.mission_status_var = tk.StringVar(value="Mission: UNKNOWN | Action: UNKNOWN")
        self.config_lock = threading.Lock()
        self.service_log_path = SERVICE_LOG_FILE
        self.service_log_pos = 0
        self.service_log_announced = False

        self._build_ui()
        self._load_vars()
        self._drain_output()
        self._tail_service_log()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        if auto_start:
            self.after(700, self.start_all)

    def _build_ui(self):
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(15, weight=1)

        for key in DEFAULT_CONFIG:
            self.vars[key] = tk.StringVar()

        ttk.Label(root, text="Agent ID").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Entry(root, textvariable=self.vars["agent_id"]).grid(row=0, column=1, sticky="ew", pady=3)

        ttk.Label(root, text="Source / Site").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(root, textvariable=self.vars["source_name"]).grid(row=1, column=1, sticky="ew", pady=3)

        ttk.Label(root, text="Mode").grid(row=2, column=0, sticky="w", pady=3)
        mode = ttk.Combobox(
            root,
            textvariable=self.vars["mode"],
            values=["ftp-webhook", "ftp-yolo-webhook", "ftp-ai-image-webhook"],
            state="readonly",
        )
        mode.grid(row=2, column=1, sticky="ew", pady=3)

        ttk.Label(root, text="Webhook URL(s)").grid(row=3, column=0, sticky="w", pady=3)
        ttk.Entry(root, textvariable=self.vars["webhook_url"]).grid(row=3, column=1, columnspan=2, sticky="ew", pady=3)

        ttk.Label(root, text="Webhook Token(s)").grid(row=4, column=0, sticky="w", pady=3)
        ttk.Entry(root, textvariable=self.vars["webhook_token"], show="*").grid(row=4, column=1, columnspan=2, sticky="ew", pady=3)

        ttk.Label(root, text="AI Image Model URL").grid(row=5, column=0, sticky="w", pady=3)
        ttk.Entry(root, textvariable=self.vars["ai_model_url"]).grid(row=5, column=1, columnspan=2, sticky="ew", pady=3)

        ttk.Label(root, text="AI Model Name").grid(row=6, column=0, sticky="w", pady=3)
        ttk.Entry(root, textvariable=self.vars["ai_model_name"]).grid(row=6, column=1, columnspan=2, sticky="ew", pady=3)

        ttk.Label(root, text="Heartbeat URL").grid(row=7, column=0, sticky="w", pady=3)
        ttk.Entry(root, textvariable=self.vars["heartbeat_url"]).grid(row=7, column=1, columnspan=2, sticky="ew", pady=3)

        ttk.Label(root, text="Remote Command URL").grid(row=8, column=0, sticky="w", pady=3)
        ttk.Entry(root, textvariable=self.vars["remote_command_url"]).grid(row=8, column=1, columnspan=2, sticky="ew", pady=3)

        ttk.Label(root, text="Image Folder").grid(row=9, column=0, sticky="w", pady=3)
        ttk.Entry(root, textvariable=self.vars["watch_dir"]).grid(row=9, column=1, sticky="ew", pady=3)
        ttk.Button(root, text="Browse", command=self._browse_folder).grid(row=9, column=2, padx=(8, 0), sticky="ew")

        ftp = ttk.LabelFrame(root, text="FTP")
        ftp.grid(row=10, column=0, columnspan=3, sticky="ew", pady=8)
        for index in range(10):
            ftp.columnconfigure(index, weight=1)
        labels = [("User", "ftp_user"), ("Password", "ftp_password"), ("Port", "ftp_port"), ("Passive From", "passive_start"), ("To", "passive_end")]
        for idx, (label, key) in enumerate(labels):
            ttk.Label(ftp, text=label).grid(row=0, column=idx * 2, sticky="w", padx=(6, 2), pady=5)
            show = "*" if key == "ftp_password" else ""
            ttk.Entry(ftp, textvariable=self.vars[key], show=show, width=14).grid(row=0, column=idx * 2 + 1, sticky="ew", padx=(0, 6), pady=5)

        advanced = ttk.LabelFrame(root, text="Advanced")
        advanced.grid(row=11, column=0, columnspan=3, sticky="ew", pady=4)
        for index in range(10):
            advanced.columnconfigure(index, weight=1)
        advanced_fields = [
            ("Poll", "poll_seconds"),
            ("Stable", "stable_seconds"),
            ("Timeout", "webhook_timeout"),
            ("Heartbeat min", "heartbeat_minutes"),
            ("Commands sec", "command_poll_seconds"),
        ]
        for idx, (label, key) in enumerate(advanced_fields):
            ttk.Label(advanced, text=label).grid(row=0, column=idx * 2, sticky="w", padx=(6, 2), pady=5)
            ttk.Entry(advanced, textvariable=self.vars[key], width=10).grid(row=0, column=idx * 2 + 1, sticky="ew", padx=(0, 6), pady=5)

        ttk.Label(root, text="YOLO Model").grid(row=12, column=0, sticky="w", pady=3)
        ttk.Combobox(
            root,
            textvariable=self.vars["yolo_model"],
            values=["yolo26n.pt", "yolov8n.pt"],
        ).grid(row=12, column=1, sticky="ew", pady=3)
        ttk.Button(root, text="Browse", command=self._browse_model).grid(row=12, column=2, padx=(8, 0), sticky="ew")

        alerts = ttk.LabelFrame(root, text="Alert Filter")
        alerts.grid(row=13, column=0, columnspan=3, sticky="ew", pady=4)
        for index in range(8):
            alerts.columnconfigure(index, weight=1)
        ttk.Label(alerts, text="Labels").grid(row=0, column=0, sticky="w", padx=(6, 2), pady=5)
        ttk.Entry(alerts, textvariable=self.vars["alert_labels"]).grid(row=0, column=1, sticky="ew", padx=(0, 6), pady=5)
        ttk.Label(alerts, text="Min Confidence").grid(row=0, column=2, sticky="w", padx=(6, 2), pady=5)
        ttk.Entry(alerts, textvariable=self.vars["alert_min_confidence"], width=10).grid(row=0, column=3, sticky="ew", padx=(0, 6), pady=5)
        ttk.Checkbutton(
            alerts,
            text="Send only matching alerts",
            variable=self.vars["send_only_alerts"],
            onvalue="1",
            offvalue="0",
        ).grid(row=0, column=4, columnspan=2, sticky="w", padx=6, pady=5)
        ttk.Label(alerts, text="Max CPU").grid(row=1, column=0, sticky="w", padx=(6, 2), pady=5)
        ttk.Entry(alerts, textvariable=self.vars["max_cpu_percent"], width=10).grid(row=1, column=1, sticky="ew", padx=(0, 6), pady=5)
        ttk.Label(alerts, text="YOLO Workers").grid(row=1, column=2, sticky="w", padx=(6, 2), pady=5)
        ttk.Entry(alerts, textvariable=self.vars["yolo_worker_count"], width=10).grid(row=1, column=3, sticky="ew", padx=(0, 6), pady=5)
        ttk.Checkbutton(
            alerts,
            text="Skip YOLO when PC is busy and send image directly",
            variable=self.vars["skip_yolo_when_busy"],
            onvalue="1",
            offvalue="0",
        ).grid(row=1, column=4, columnspan=4, sticky="w", padx=6, pady=5)
        ttk.Label(alerts, text="Max YOLO Queue").grid(row=2, column=0, sticky="w", padx=(6, 2), pady=5)
        ttk.Entry(alerts, textvariable=self.vars["max_yolo_queue_size"], width=10).grid(row=2, column=1, sticky="ew", padx=(0, 6), pady=5)
        ttk.Label(alerts, text="Max Image Age sec").grid(row=2, column=2, sticky="w", padx=(6, 2), pady=5)
        ttk.Entry(alerts, textvariable=self.vars["max_file_age_seconds"], width=10).grid(row=2, column=3, sticky="ew", padx=(0, 6), pady=5)
        ttk.Checkbutton(
            alerts,
            text="Newest first when backlogged",
            variable=self.vars["newest_first_when_backlogged"],
            onvalue="1",
            offvalue="0",
        ).grid(row=2, column=4, columnspan=3, sticky="w", padx=6, pady=5)

        upload = ttk.LabelFrame(root, text="Upload Size")
        upload.grid(row=14, column=0, columnspan=3, sticky="ew", pady=4)
        for index in range(8):
            upload.columnconfigure(index, weight=1)
        ttk.Checkbutton(
            upload,
            text="Compress image before webhook",
            variable=self.vars["compress_before_upload"],
            onvalue="1",
            offvalue="0",
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=6, pady=5)
        ttk.Label(upload, text="Max Width").grid(row=0, column=2, sticky="w", padx=(6, 2), pady=5)
        ttk.Entry(upload, textvariable=self.vars["upload_max_width"], width=10).grid(row=0, column=3, sticky="ew", padx=(0, 6), pady=5)
        ttk.Label(upload, text="JPEG Quality").grid(row=0, column=4, sticky="w", padx=(6, 2), pady=5)
        ttk.Entry(upload, textvariable=self.vars["upload_jpeg_quality"], width=10).grid(row=0, column=5, sticky="ew", padx=(0, 6), pady=5)
        ttk.Label(upload, text="Format").grid(row=0, column=6, sticky="w", padx=(6, 2), pady=5)
        ttk.Combobox(
            upload,
            textvariable=self.vars["webhook_format"],
            values=["json-base64", "multipart"],
            state="readonly",
            width=12,
        ).grid(row=0, column=7, sticky="ew", padx=(0, 6), pady=5)

        log_frame = ttk.Frame(root)
        log_frame.grid(row=15, column=0, columnspan=3, sticky="nsew", pady=(8, 0))
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self.log_text = tk.Text(log_frame, height=16, wrap="word", state="disabled")
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        buttons = ttk.Frame(root)
        buttons.grid(row=16, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        self.start_button = ttk.Button(buttons, text="Start All", command=self.start_all)
        self.stop_button = ttk.Button(buttons, text="Stop", command=self.stop_all, state="disabled")
        ttk.Button(buttons, text="Save", command=self.save_from_ui).pack(side="left", padx=(0, 8))
        self.start_button.pack(side="left", padx=(0, 8))
        self.stop_button.pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Send Heartbeat Now", command=self.heartbeat.send_once).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Open Folder", command=self._open_folder).pack(side="left")

        info = f"Local IPs: {', '.join(local_ipv4_addresses()) or 'not found'}"
        ttk.Label(root, text=info).grid(row=17, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Label(root, textvariable=self.mission_status_var).grid(row=18, column=0, columnspan=3, sticky="w", pady=(4, 0))

    def _load_vars(self):
        for key, value in self.config.items():
            if key in self.vars:
                self.vars[key].set(value)

    def save_from_ui(self):
        self.config = {key: var.get().strip() for key, var in self.vars.items()}
        save_config(self.config)
        self._log("[+] Settings saved.\n")

    def _browse_folder(self):
        folder = filedialog.askdirectory(initialdir=self.vars["watch_dir"].get() or str(RUNTIME_DIR))
        if folder:
            self.vars["watch_dir"].set(folder)

    def _browse_model(self):
        filename = filedialog.askopenfilename(filetypes=[("YOLO models", "*.pt *.onnx"), ("All files", "*.*")])
        if filename:
            self.vars["yolo_model"].set(filename)

    def _open_folder(self):
        folder = Path(self.vars["watch_dir"].get())
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)

    def agent_args(self):
        return SimpleNamespace(
            webhook_url=self.config["webhook_url"],
            webhook_token=self.config["webhook_token"],
            source_name=self.config["source_name"],
            watch_dir=Path(self.config["watch_dir"]),
            poll_seconds=float(self.config["poll_seconds"]),
            stable_seconds=float(self.config["stable_seconds"]),
            file_timeout=30.0,
            webhook_timeout=float(self.config["webhook_timeout"]),
            state_db=STATE_DB,
            enable_yolo=self.config["mode"] == "ftp-yolo-webhook",
            yolo_model=self.config["yolo_model"],
            ai_model_url=self.config["ai_model_url"] if self.config["mode"] == "ftp-ai-image-webhook" else "",
            ai_model_name=self.config["ai_model_name"],
            alert_labels=self.config["alert_labels"],
            alert_min_confidence=float(self.config["alert_min_confidence"]),
            send_only_alerts=self.config["send_only_alerts"] == "1",
            skip_yolo_when_busy=self.config["skip_yolo_when_busy"] == "1",
            max_cpu_percent=float(self.config["max_cpu_percent"]),
            yolo_worker_count=int(self.config["yolo_worker_count"]),
            max_yolo_queue_size=int(self.config["max_yolo_queue_size"]),
            max_file_age_seconds=float(self.config["max_file_age_seconds"]),
            ignore_existing_on_start=self.config["ignore_existing_on_start"] == "1",
            newest_first_when_backlogged=self.config["newest_first_when_backlogged"] == "1",
            compress_before_upload=self.config["compress_before_upload"] == "1",
            upload_max_width=int(self.config["upload_max_width"]),
            upload_jpeg_quality=int(self.config["upload_jpeg_quality"]),
            webhook_format=self.config["webhook_format"],
            health_file=HEALTH_FILE,
            should_process_images=lambda: self.image_processing_enabled,
            active_webhook_urls=self.active_webhook_urls,
            active_webhook_tokens=self.active_webhook_tokens,
            stop_event=self.agent_stop_event,
        )

    def start_all(self):
        self.save_from_ui()
        if self.config["mode"] == "ftp-ai-image-webhook" and not self.config["ai_model_url"]:
            messagebox.showerror(APP_NAME, "AI Image Model URL is required for ftp-ai-image-webhook mode.")
            return

        try:
            self.ftp_service = LocalFtpService(
                self.config,
                self.output_queue,
                should_accept_files=lambda: self.image_processing_enabled,
            )
            self.ftp_service.start()
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Could not start FTP: {exc}")
            return

        if self.config["webhook_url"]:
            self.agent_stop_event = threading.Event()
            args = self.agent_args()
            self.agent_thread = threading.Thread(target=self._agent_worker, args=(args,), daemon=True)
            self.agent_thread.start()
            heartbeat_targets = split_webhook_urls(self.config.get("heartbeat_url", "").strip())
            if not heartbeat_targets:
                heartbeat_targets = [
                    heartbeat_url_from_webhook_url(url)
                    for url in self.configured_webhook_urls()
                    if heartbeat_url_from_webhook_url(url)
                ]
            token_status = "set" if self.config.get("webhook_token", "").strip() else "empty"
            self._log(f"[*] Heartbeat targets: {len(heartbeat_targets)}; token={token_status}\n")
            self.heartbeat.start()
            self.remote_commands.start()
        else:
            self._log("[!] Webhook URL is empty. FTP server is running, but images will not be sent out.\n")

        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self._log("[+] Agent running.\n")

    def _agent_worker(self, args):
        writer = QueueWriter(self.output_queue)
        try:
            with redirect_stdout(writer), redirect_stderr(writer):
                run_agent(args)
        except Exception as exc:
            self.output_queue.put(f"[!] Agent crashed: {exc}\n")
        finally:
            self.output_queue.put("__AGENT_STOPPED__")

    def stop_all(self):
        if self.agent_stop_event:
            self.agent_stop_event.set()
        self.heartbeat.stop()
        self.remote_commands.stop()
        if self.ftp_service:
            self.ftp_service.stop()
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self._log("[*] Stop requested.\n")

    def restart_ftp(self):
        if self.ftp_service:
            self.ftp_service.stop()
        self.ftp_service = LocalFtpService(
            self.config,
            self.output_queue,
            should_accept_files=lambda: self.image_processing_enabled,
        )
        self.ftp_service.start()

    def configured_webhook_urls(self):
        with self.config_lock:
            return split_webhook_urls(self.config.get("webhook_url", ""))

    def configured_tokens(self, count=0):
        with self.config_lock:
            return split_webhook_tokens(self.config.get("webhook_token", ""), count)

    def active_webhook_urls(self):
        urls = self.configured_webhook_urls()
        if not urls:
            return []
        if not self.webhook_controls:
            return urls
        return [
            url for url in urls
            if self.webhook_controls.get(url, {}).get("should_process", True)
        ]

    def active_webhook_tokens(self):
        urls = self.configured_webhook_urls()
        tokens = self.configured_tokens(len(urls))
        active_urls = self.active_webhook_urls()
        token_by_url = {url: tokens[index] if index < len(tokens) else "" for index, url in enumerate(urls)}
        return join_config_list(token_by_url.get(url, "") for url in active_urls)

    def status_payload(self, webhook_url=None):
        usage = shutil.disk_usage(Path(self.config["watch_dir"]).anchor or str(RUNTIME_DIR))
        mission_id = mission_id_from_webhook_url(webhook_url or primary_webhook_url(self.config.get("webhook_url", "")))
        return {
            "agent_id": self.config["agent_id"],
            "source": self.config["source_name"],
            "mission_id": mission_id,
            "mode": self.config["mode"],
            "status": "running" if self.agent_thread and self.agent_thread.is_alive() else "stopped",
            "mission_status": self.mission_status,
            "agent_action": self.agent_action,
            "image_processing_enabled": self.image_processing_enabled,
            "time_utc": utc_now(),
            "hostname": socket.gethostname(),
            "local_ips": local_ipv4_addresses(),
            "ftp_port": int(self.config["ftp_port"]),
            "watch_dir": self.config["watch_dir"],
            "image_folder": folder_stats(self.config["watch_dir"]),
            "disk": {"total": usage.total, "used": usage.used, "free": usage.free},
        }

    def apply_heartbeat_control(self, response, webhook_url=None):
        try:
            data = response.json() if response.text else {}
        except ValueError:
            return

        mission_status = str(data.get("mission_status") or data.get("status") or "").upper()
        agent_action = str(data.get("agent_action") or "").upper()
        should_process = agent_action == "PROCESS_IMAGES" or mission_status == "RUNNING"
        if not mission_status and not agent_action:
            return

        webhook_url = webhook_url or primary_webhook_url(self.config.get("webhook_url", ""))
        previous = self.image_processing_enabled
        if webhook_url:
            self.webhook_controls[webhook_url] = {
                "should_process": should_process,
                "mission_status": mission_status or ("RUNNING" if should_process else "PAUSED"),
                "agent_action": agent_action or ("PROCESS_IMAGES" if should_process else "PAUSE_IMAGE_PROCESSING"),
                "updated_at_utc": utc_now(),
            }

        active_count = len(self.active_webhook_urls())
        total_count = len(self.configured_webhook_urls())
        self.image_processing_enabled = active_count > 0
        self.mission_status = "RUNNING" if self.image_processing_enabled else (mission_status or "PAUSED")
        self.agent_action = "PROCESS_IMAGES" if self.image_processing_enabled else (agent_action or "PAUSE_IMAGE_PROCESSING")
        self.mission_status_var.set(
            f"Active webhook missions: {active_count}/{total_count} | Action: {self.agent_action}"
        )

        if previous != self.image_processing_enabled:
            state = "enabled" if self.image_processing_enabled else "paused"
            self.output_queue.put(f"[*] Image processing {state} by mission status: {self.mission_status}\n")

    def apply_dynamic_webhooks(self, response):
        try:
            data = response.json() if response.text else {}
        except ValueError:
            return

        updates = self._extract_dynamic_webhooks(data)
        if not updates:
            return

        changed = False
        with self.config_lock:
            urls = split_webhook_urls(self.config.get("webhook_url", ""))
            tokens = split_webhook_tokens(self.config.get("webhook_token", ""), len(urls))
            heartbeat_urls = split_webhook_urls(self.config.get("heartbeat_url", ""))

            token_by_url = {url: tokens[index] if index < len(tokens) else "" for index, url in enumerate(urls)}
            heartbeat_by_url = {
                url: heartbeat_urls[index] if index < len(heartbeat_urls) else ""
                for index, url in enumerate(urls)
            }

            for item in updates:
                webhook_url = item.get("webhook_url", "").strip()
                if not webhook_url:
                    continue
                webhook_url = webhook_url.replace("/heartbeat", "/ingest") if webhook_url.endswith("/heartbeat") else webhook_url
                if webhook_url not in urls:
                    urls.append(webhook_url)
                    changed = True

                if item.get("token"):
                    if token_by_url.get(webhook_url) != item["token"]:
                        token_by_url[webhook_url] = item["token"]
                        changed = True

                heartbeat_url = item.get("heartbeat_url", "").strip()
                if heartbeat_url:
                    heartbeat_url = normalize_heartbeat_url(heartbeat_url)
                    if heartbeat_by_url.get(webhook_url) != heartbeat_url:
                        heartbeat_by_url[webhook_url] = heartbeat_url
                        changed = True

                mission_status = str(item.get("mission_status") or item.get("status") or "").upper()
                agent_action = str(item.get("agent_action") or "").upper()
                if mission_status or agent_action:
                    should_process = agent_action == "PROCESS_IMAGES" or mission_status == "RUNNING"
                    self.webhook_controls[webhook_url] = {
                        "should_process": should_process,
                        "mission_status": mission_status or ("RUNNING" if should_process else "PAUSED"),
                        "agent_action": agent_action or ("PROCESS_IMAGES" if should_process else "PAUSE_IMAGE_PROCESSING"),
                        "updated_at_utc": utc_now(),
                    }

            if changed:
                self.config["webhook_url"] = join_config_list(urls)
                self.config["webhook_token"] = join_config_list(token_by_url.get(url, "") for url in urls)
                self.config["heartbeat_url"] = join_config_list(
                    heartbeat_by_url.get(url, "") or heartbeat_url_from_webhook_url(url)
                    for url in urls
                )
                save_config(self.config)

        if changed:
            self.after(0, self._load_vars)
            self.output_queue.put(f"[*] Dynamic heartbeat updated webhook missions: {len(updates)} received, {len(urls)} configured.\n")

    def _extract_dynamic_webhooks(self, data):
        containers = []
        for key in ("webhooks", "missions", "mission_webhooks", "active_webhooks", "assignments"):
            value = data.get(key)
            if isinstance(value, list):
                containers.extend(value)

        single_url = data.get("webhook_url") or data.get("ingest_url") or data.get("new_webhook_url")
        if single_url:
            containers.append(data)

        updates = []
        for item in containers:
            if not isinstance(item, dict):
                continue
            webhook_url = (
                item.get("webhook_url")
                or item.get("ingest_url")
                or item.get("image_webhook_url")
                or item.get("url")
            )
            if not webhook_url:
                mission_id = item.get("mission_id") or item.get("id")
                base_url = item.get("base_url") or data.get("base_url")
                if base_url and mission_id:
                    webhook_url = f"{str(base_url).rstrip('/')}/api/mission-webhooks/{mission_id}/ingest"

            token = item.get("webhook_token") or item.get("token") or item.get("new_token")
            heartbeat_url = item.get("heartbeat_url")
            updates.append({
                "webhook_url": str(webhook_url or ""),
                "heartbeat_url": str(heartbeat_url or ""),
                "token": str(token or ""),
                "mission_status": item.get("mission_status") or item.get("status") or "",
                "agent_action": item.get("agent_action") or "",
            })

        return updates

    def _drain_output(self):
        try:
            while True:
                item = self.output_queue.get_nowait()
                if item == "__AGENT_STOPPED__":
                    self._log("[*] Image worker stopped.\n")
                else:
                    self._log(item)
        except queue.Empty:
            pass
        self.after(200, self._drain_output)

    def _tail_service_log(self):
        try:
            local_agent_running = bool(self.agent_thread and self.agent_thread.is_alive())
            if not local_agent_running:
                if self.service_log_path.exists():
                    if self.service_log_pos == 0:
                        file_size = self.service_log_path.stat().st_size
                        self.service_log_pos = max(0, file_size - 24000)
                        if not self.service_log_announced:
                            self._log(f"[*] Live service log: {self.service_log_path}\n")
                            self.service_log_announced = True

                    with self.service_log_path.open("r", encoding="utf-8", errors="replace") as handle:
                        handle.seek(self.service_log_pos)
                        text = handle.read()
                        self.service_log_pos = handle.tell()
                    if text:
                        self._log(text)
                elif not self.service_log_announced:
                    self._log(f"[*] Waiting for service log: {self.service_log_path}\n")
                    self.service_log_announced = True
        except OSError as exc:
            self._log(f"[!] Could not read service log: {exc}\n")
        finally:
            self.after(1000, self._tail_service_log)

    def _log(self, text):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _on_close(self):
        if self.agent_thread and self.agent_thread.is_alive():
            if not messagebox.askyesno(APP_NAME, "Agent is running. Stop and exit?"):
                return
            self.stop_all()
        self.destroy()


class HeadlessEdgeAgent:
    def __init__(self):
        self.config = load_config()
        self.output_queue = queue.Queue()
        self.agent_stop_event = threading.Event()
        self.agent_thread = None
        self.ftp_service = None
        self.heartbeat = HeartbeatWorker(self, self.output_queue)
        self.remote_commands = RemoteCommandWorker(self, self.output_queue)
        self.image_processing_enabled = True
        self.mission_status = "RUNNING"
        self.agent_action = "PROCESS_IMAGES"
        self.webhook_controls = {}
        self.config_lock = threading.Lock()
        self.log_dir = RUNTIME_DIR / "logs"
        self.log_path = self.log_dir / "edge-agent-service.log"
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _write_log(self, text):
        if not text:
            return
        try:
            with self.log_path.open("a", encoding="utf-8") as handle:
                for line in text.splitlines() or [text]:
                    handle.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {line}\n")
        except OSError:
            pass

    def drain_output_once(self):
        try:
            while True:
                item = self.output_queue.get_nowait()
                if item == "__AGENT_STOPPED__":
                    self._write_log("[*] Image worker stopped.\n")
                else:
                    self._write_log(item)
        except queue.Empty:
            pass

    def after(self, _delay_ms, callback=None):
        if callable(callback):
            callback()

    def _load_vars(self):
        return

    def agent_args(self):
        return SimpleNamespace(
            webhook_url=self.config["webhook_url"],
            webhook_token=self.config["webhook_token"],
            source_name=self.config["source_name"],
            watch_dir=Path(self.config["watch_dir"]),
            poll_seconds=float(self.config["poll_seconds"]),
            stable_seconds=float(self.config["stable_seconds"]),
            file_timeout=30.0,
            webhook_timeout=float(self.config["webhook_timeout"]),
            state_db=STATE_DB,
            enable_yolo=self.config["mode"] == "ftp-yolo-webhook",
            yolo_model=self.config["yolo_model"],
            ai_model_url=self.config["ai_model_url"] if self.config["mode"] == "ftp-ai-image-webhook" else "",
            ai_model_name=self.config["ai_model_name"],
            alert_labels=self.config["alert_labels"],
            alert_min_confidence=float(self.config["alert_min_confidence"]),
            send_only_alerts=self.config["send_only_alerts"] == "1",
            skip_yolo_when_busy=self.config["skip_yolo_when_busy"] == "1",
            max_cpu_percent=float(self.config["max_cpu_percent"]),
            yolo_worker_count=int(self.config["yolo_worker_count"]),
            max_yolo_queue_size=int(self.config["max_yolo_queue_size"]),
            max_file_age_seconds=float(self.config["max_file_age_seconds"]),
            ignore_existing_on_start=self.config["ignore_existing_on_start"] == "1",
            newest_first_when_backlogged=self.config["newest_first_when_backlogged"] == "1",
            compress_before_upload=self.config["compress_before_upload"] == "1",
            upload_max_width=int(self.config["upload_max_width"]),
            upload_jpeg_quality=int(self.config["upload_jpeg_quality"]),
            webhook_format=self.config["webhook_format"],
            health_file=HEALTH_FILE,
            should_process_images=lambda: self.image_processing_enabled,
            active_webhook_urls=self.active_webhook_urls,
            active_webhook_tokens=self.active_webhook_tokens,
            stop_event=self.agent_stop_event,
        )

    def start_all(self):
        self._write_log("[+] Starting MaiFocus Edge Agent headless service.\n")
        self.ftp_service = LocalFtpService(
            self.config,
            self.output_queue,
            should_accept_files=lambda: self.image_processing_enabled,
        )
        self.ftp_service.start()

        if self.config["webhook_url"]:
            args = self.agent_args()
            self.agent_thread = threading.Thread(target=self._agent_worker, args=(args,), daemon=True)
            self.agent_thread.start()
            self.heartbeat.start()
            self.remote_commands.start()
        else:
            self.output_queue.put("[!] Webhook URL is empty. FTP server is running, but images will not be sent out.\n")

    def _agent_worker(self, args):
        writer = QueueWriter(self.output_queue)
        try:
            with redirect_stdout(writer), redirect_stderr(writer):
                run_agent(args)
        except Exception as exc:
            self.output_queue.put(f"[!] Agent crashed: {exc}\n")
        finally:
            self.output_queue.put("__AGENT_STOPPED__")

    def stop_all(self):
        self.agent_stop_event.set()
        self.heartbeat.stop()
        self.remote_commands.stop()
        if self.ftp_service:
            self.ftp_service.stop()

    def restart_ftp(self):
        if self.ftp_service:
            self.ftp_service.stop()
        self.ftp_service = LocalFtpService(
            self.config,
            self.output_queue,
            should_accept_files=lambda: self.image_processing_enabled,
        )
        self.ftp_service.start()

    def configured_webhook_urls(self):
        with self.config_lock:
            return split_webhook_urls(self.config.get("webhook_url", ""))

    def configured_tokens(self, count=0):
        with self.config_lock:
            return split_webhook_tokens(self.config.get("webhook_token", ""), count)

    def active_webhook_urls(self):
        urls = self.configured_webhook_urls()
        if not urls:
            return []
        if not self.webhook_controls:
            return urls
        return [
            url for url in urls
            if self.webhook_controls.get(url, {}).get("should_process", True)
        ]

    def active_webhook_tokens(self):
        urls = self.configured_webhook_urls()
        tokens = self.configured_tokens(len(urls))
        active_urls = self.active_webhook_urls()
        token_by_url = {url: tokens[index] if index < len(tokens) else "" for index, url in enumerate(urls)}
        return join_config_list(token_by_url.get(url, "") for url in active_urls)

    def status_payload(self, webhook_url=None):
        usage = shutil.disk_usage(Path(self.config["watch_dir"]).anchor or str(RUNTIME_DIR))
        mission_id = mission_id_from_webhook_url(webhook_url or primary_webhook_url(self.config.get("webhook_url", "")))
        return {
            "agent_id": self.config["agent_id"],
            "source": self.config["source_name"],
            "mission_id": mission_id,
            "mode": self.config["mode"],
            "status": "running",
            "mission_status": self.mission_status,
            "agent_action": self.agent_action,
            "image_processing_enabled": self.image_processing_enabled,
            "time_utc": utc_now(),
            "hostname": socket.gethostname(),
            "local_ips": local_ipv4_addresses(),
            "ftp_port": int(self.config["ftp_port"]),
            "watch_dir": self.config["watch_dir"],
            "image_folder": folder_stats(self.config["watch_dir"]),
            "disk": {"total": usage.total, "used": usage.used, "free": usage.free},
        }

    def apply_heartbeat_control(self, response, webhook_url=None):
        try:
            data = response.json() if response.text else {}
        except ValueError:
            return

        mission_status = str(data.get("mission_status") or data.get("status") or "").upper()
        agent_action = str(data.get("agent_action") or "").upper()
        should_process = agent_action == "PROCESS_IMAGES" or mission_status == "RUNNING"
        if not mission_status and not agent_action:
            return

        webhook_url = webhook_url or primary_webhook_url(self.config.get("webhook_url", ""))
        previous = self.image_processing_enabled
        if webhook_url:
            self.webhook_controls[webhook_url] = {
                "should_process": should_process,
                "mission_status": mission_status or ("RUNNING" if should_process else "PAUSED"),
                "agent_action": agent_action or ("PROCESS_IMAGES" if should_process else "PAUSE_IMAGE_PROCESSING"),
                "updated_at_utc": utc_now(),
            }

        active_count = len(self.active_webhook_urls())
        self.image_processing_enabled = active_count > 0
        self.mission_status = "RUNNING" if self.image_processing_enabled else (mission_status or "PAUSED")
        self.agent_action = "PROCESS_IMAGES" if self.image_processing_enabled else (agent_action or "PAUSE_IMAGE_PROCESSING")

        if previous != self.image_processing_enabled:
            state = "enabled" if self.image_processing_enabled else "paused"
            self.output_queue.put(f"[*] Image processing {state} by mission status: {self.mission_status}\n")

    def apply_dynamic_webhooks(self, response):
        EdgeAgentGui.apply_dynamic_webhooks(self, response)

    def _extract_dynamic_webhooks(self, data):
        return EdgeAgentGui._extract_dynamic_webhooks(self, data)

    def run_forever(self):
        self.start_all()
        try:
            while True:
                self.drain_output_once()
                time.sleep(0.2)
        except KeyboardInterrupt:
            self._write_log("[*] Headless service stop requested.\n")
        finally:
            self.stop_all()
            self.drain_output_once()


def parse_args():
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--auto-start", action="store_true", help="Start FTP, image worker, heartbeat, and command polling immediately.")
    parser.add_argument("--headless-service", action="store_true", help="Run as a background service without the Tk GUI.")
    return parser.parse_args()


def main():
    args = parse_args()
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    DEFAULT_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    if args.headless_service:
        HeadlessEdgeAgent().run_forever()
        return 0
    app = EdgeAgentGui(auto_start=args.auto_start)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
