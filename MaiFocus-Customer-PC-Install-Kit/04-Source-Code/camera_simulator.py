# -*- coding: utf-8 -*-
import json
import os
import queue
import socket
import sys
import tempfile
import threading
import time
from datetime import datetime
from ftplib import FTP
from io import BytesIO
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = None

try:
    import winreg
except ImportError:
    winreg = None


APP_NAME = "MaiFocus Camera Simulator"
RUNTIME_DIR = Path(os.environ.get("MAIFOCUS_CAMERA_SIM_HOME", Path.home() / "MaiFocusCameraSimulator"))
CONFIG_PATH = RUNTIME_DIR / "config.json"
REGISTRY_KEY = r"Software\MaiFocus\CameraSimulator"


DEFAULT_CONFIG = {
    "server": "",
    "port": "2121",
    "username": "hikvision",
    "password": "CHANGE_ME_FTP_PASSWORD",
    "remote_folder": "/",
    "interval_seconds": "10",
    "image_file": "",
    "camera_name": "sim-camera-1",
    "use_passive": "1",
}


def load_config():
    config = DEFAULT_CONFIG.copy()
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    if CONFIG_PATH.exists():
        try:
            config.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass

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

    return config


def save_config(config):
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
    if winreg is not None:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY) as key:
            for name, value in config.items():
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(value))


def local_ips():
    addresses = []
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = item[4][0]
            if ip != "127.0.0.1" and ip not in addresses:
                addresses.append(ip)
    except OSError:
        pass
    return addresses


def make_test_image(camera_name):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if Image is None:
        return BytesIO(f"{camera_name} test image {timestamp}\n".encode("utf-8")), "txt"

    image = Image.new("RGB", (1280, 720), color=(28, 34, 42))
    draw = ImageDraw.Draw(image)
    try:
        title_font = ImageFont.truetype("arial.ttf", 56)
        body_font = ImageFont.truetype("arial.ttf", 34)
    except OSError:
        title_font = None
        body_font = None

    draw.rectangle((40, 40, 1240, 680), outline=(82, 170, 255), width=6)
    draw.text((80, 100), "MaiFocus FTP Camera Simulator", fill=(255, 255, 255), font=title_font)
    draw.text((80, 210), f"Camera: {camera_name}", fill=(214, 231, 255), font=body_font)
    draw.text((80, 270), f"Time: {timestamp}", fill=(214, 231, 255), font=body_font)
    draw.text((80, 330), "This image was uploaded by FTP.", fill=(214, 231, 255), font=body_font)
    draw.ellipse((920, 210, 1120, 410), fill=(255, 190, 80), outline=(255, 255, 255), width=4)
    draw.rectangle((860, 430, 1180, 560), fill=(72, 110, 86), outline=(255, 255, 255), width=4)

    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    buffer.seek(0)
    return buffer, "jpg"


def ftp_upload(config, log):
    server = config["server"].strip()
    if not server:
        raise RuntimeError("Server address is required")

    port = int(config["port"])
    username = config["username"]
    password = config["password"]
    remote_folder = config["remote_folder"].strip() or "/"
    camera_name = config["camera_name"].strip() or "sim-camera"
    passive = config.get("use_passive", "1") == "1"

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    source_file = config.get("image_file", "").strip()

    if source_file:
        path = Path(source_file)
        payload = path.open("rb")
        filename = f"{camera_name}_{timestamp}{path.suffix}"
    else:
        payload, ext = make_test_image(camera_name)
        filename = f"{camera_name}_{timestamp}.{ext}"

    try:
        ftp = FTP()
        ftp.connect(server, port, timeout=20)
        ftp.login(username, password)
        ftp.set_pasv(passive)
        if remote_folder != "/":
            for part in remote_folder.strip("/").split("/"):
                try:
                    ftp.mkd(part)
                except Exception:
                    pass
                ftp.cwd(part)
        ftp.storbinary(f"STOR {filename}", payload)
        ftp.quit()
        log(f"[+] Uploaded {filename} to {server}:{port}\n")
    finally:
        payload.close()


class CameraSimulatorGui(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("760x520")
        self.minsize(680, 460)
        self.config_data = load_config()
        self.vars = {}
        self.output_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker = None

        self._build_ui()
        self._load_vars()
        self._drain_output()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(9, weight=1)

        for key in DEFAULT_CONFIG:
            self.vars[key] = tk.StringVar()

        fields = [
            ("FTP Server IP", "server"),
            ("Port", "port"),
            ("Username", "username"),
            ("Password", "password"),
            ("Remote Folder", "remote_folder"),
            ("Camera Name", "camera_name"),
            ("Interval Seconds", "interval_seconds"),
        ]
        for row, (label, key) in enumerate(fields):
            ttk.Label(root, text=label).grid(row=row, column=0, sticky="w", pady=4)
            show = "*" if key == "password" else ""
            ttk.Entry(root, textvariable=self.vars[key], show=show).grid(row=row, column=1, columnspan=2, sticky="ew", pady=4)

        ttk.Checkbutton(root, text="Passive FTP", variable=self.vars["use_passive"], onvalue="1", offvalue="0").grid(row=7, column=1, sticky="w", pady=4)

        ttk.Label(root, text="Image File").grid(row=8, column=0, sticky="w", pady=4)
        ttk.Entry(root, textvariable=self.vars["image_file"]).grid(row=8, column=1, sticky="ew", pady=4)
        ttk.Button(root, text="Browse", command=self._browse_image).grid(row=8, column=2, sticky="ew", padx=(8, 0), pady=4)

        log_frame = ttk.Frame(root)
        log_frame.grid(row=9, column=0, columnspan=3, sticky="nsew", pady=(8, 0))
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self.log_text = tk.Text(log_frame, height=12, state="disabled", wrap="word")
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        buttons = ttk.Frame(root)
        buttons.grid(row=10, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        ttk.Button(buttons, text="Save", command=self._save_from_ui).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Upload Once", command=self._upload_once).pack(side="left", padx=(0, 8))
        self.loop_button = ttk.Button(buttons, text="Start Loop", command=self._start_loop)
        self.stop_button = ttk.Button(buttons, text="Stop", command=self._stop_loop, state="disabled")
        self.loop_button.pack(side="left", padx=(0, 8))
        self.stop_button.pack(side="left", padx=(0, 8))

        ttk.Label(root, text=f"This PC IPs: {', '.join(local_ips()) or 'not found'}").grid(row=11, column=0, columnspan=3, sticky="w", pady=(8, 0))

    def _load_vars(self):
        for key, value in self.config_data.items():
            self.vars[key].set(value)

    def _save_from_ui(self):
        self.config_data = {key: var.get().strip() for key, var in self.vars.items()}
        save_config(self.config_data)
        self._log("[+] Settings saved.\n")

    def _browse_image(self):
        filename = filedialog.askopenfilename(filetypes=[("Images", "*.jpg *.jpeg *.png *.bmp *.webp"), ("All files", "*.*")])
        if filename:
            self.vars["image_file"].set(filename)

    def _upload_once(self):
        self._save_from_ui()
        threading.Thread(target=self._upload_worker, daemon=True).start()

    def _upload_worker(self):
        try:
            ftp_upload(self.config_data, self.output_queue.put)
        except Exception as exc:
            self.output_queue.put(f"[!] Upload failed: {exc}\n")

    def _start_loop(self):
        self._save_from_ui()
        if self.worker and self.worker.is_alive():
            return
        self.stop_event.clear()
        self.worker = threading.Thread(target=self._loop_worker, daemon=True)
        self.worker.start()
        self.loop_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self._log("[+] Loop started.\n")

    def _loop_worker(self):
        while not self.stop_event.is_set():
            try:
                ftp_upload(self.config_data, self.output_queue.put)
            except Exception as exc:
                self.output_queue.put(f"[!] Upload failed: {exc}\n")
            self.stop_event.wait(max(1, int(float(self.config_data["interval_seconds"]))))
        self.output_queue.put("__STOPPED__")

    def _stop_loop(self):
        self.stop_event.set()

    def _drain_output(self):
        try:
            while True:
                item = self.output_queue.get_nowait()
                if item == "__STOPPED__":
                    self.loop_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    self._log("[*] Loop stopped.\n")
                else:
                    self._log(item)
        except queue.Empty:
            pass
        self.after(200, self._drain_output)

    def _log(self, text):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _on_close(self):
        self.stop_event.set()
        self.destroy()


def main():
    CameraSimulatorGui().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
