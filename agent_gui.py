# -*- coding: utf-8 -*-
import json
import queue
import socket
import sys
import threading
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from local_agent import run_agent

try:
    import winreg
except ImportError:
    winreg = None


APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "agent_gui_config.json"
REGISTRY_KEY = r"Software\MaiFocus\HikvisionLocalAgent"


DEFAULT_CONFIG = {
    "webhook_url": "",
    "source_name": "customer-site-1",
    "watch_dir": str(APP_DIR / "hikvision_images"),
    "poll_seconds": "2",
    "stable_seconds": "2",
    "webhook_timeout": "30",
    "enable_yolo": False,
    "yolo_model": "yolov8n.pt",
}


class QueueWriter:
    def __init__(self, output_queue):
        self.output_queue = output_queue

    def write(self, text):
        if text:
            self.output_queue.put(text)

    def flush(self):
        pass


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


def load_saved_config():
    config = DEFAULT_CONFIG.copy()

    if winreg is not None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY) as key:
                for name in DEFAULT_CONFIG:
                    try:
                        value, _ = winreg.QueryValueEx(key, name)
                    except FileNotFoundError:
                        continue
                    if isinstance(DEFAULT_CONFIG[name], bool):
                        config[name] = str(value) == "1"
                    else:
                        config[name] = value
            return config
        except FileNotFoundError:
            pass
        except OSError:
            pass

    if CONFIG_PATH.exists():
        try:
            config.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass

    return config


def save_config(config):
    if winreg is not None:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY) as key:
            for name, value in config.items():
                stored_value = "1" if isinstance(value, bool) and value else "0" if isinstance(value, bool) else str(value)
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, stored_value)
        return "registry"

    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return "file"


class AgentGui(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Hikvision Local Agent")
        self.geometry("860x620")
        self.minsize(760, 520)

        self.output_queue = queue.Queue()
        self.agent_thread = None
        self.stop_event = None
        self.vars = {}

        self._build_ui()
        self._load_config()
        self._drain_output()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(7, weight=1)

        self.vars["webhook_url"] = tk.StringVar()
        self.vars["source_name"] = tk.StringVar()
        self.vars["watch_dir"] = tk.StringVar()
        self.vars["poll_seconds"] = tk.StringVar()
        self.vars["stable_seconds"] = tk.StringVar()
        self.vars["webhook_timeout"] = tk.StringVar()
        self.vars["enable_yolo"] = tk.BooleanVar()
        self.vars["yolo_model"] = tk.StringVar()

        ttk.Label(root, text="Webhook URL").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(root, textvariable=self.vars["webhook_url"]).grid(row=0, column=1, columnspan=2, sticky="ew", pady=4)

        ttk.Label(root, text="Site / Source Name").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(root, textvariable=self.vars["source_name"]).grid(row=1, column=1, columnspan=2, sticky="ew", pady=4)

        ttk.Label(root, text="Image Folder").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(root, textvariable=self.vars["watch_dir"]).grid(row=2, column=1, sticky="ew", pady=4)
        ttk.Button(root, text="Browse", command=self._browse_watch_dir).grid(row=2, column=2, sticky="ew", padx=(8, 0), pady=4)

        timings = ttk.Frame(root)
        timings.grid(row=3, column=1, columnspan=2, sticky="ew", pady=4)
        for index in range(6):
            timings.columnconfigure(index, weight=1)

        ttk.Label(root, text="Timing").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Label(timings, text="Poll").grid(row=0, column=0, sticky="w")
        ttk.Entry(timings, textvariable=self.vars["poll_seconds"], width=8).grid(row=0, column=1, sticky="w")
        ttk.Label(timings, text="Stable").grid(row=0, column=2, sticky="w")
        ttk.Entry(timings, textvariable=self.vars["stable_seconds"], width=8).grid(row=0, column=3, sticky="w")
        ttk.Label(timings, text="HTTP Timeout").grid(row=0, column=4, sticky="w")
        ttk.Entry(timings, textvariable=self.vars["webhook_timeout"], width=8).grid(row=0, column=5, sticky="w")

        ttk.Checkbutton(root, text="Run YOLO locally", variable=self.vars["enable_yolo"]).grid(row=4, column=1, sticky="w", pady=4)

        ttk.Label(root, text="YOLO Model").grid(row=5, column=0, sticky="w", pady=4)
        ttk.Entry(root, textvariable=self.vars["yolo_model"]).grid(row=5, column=1, sticky="ew", pady=4)
        ttk.Button(root, text="Browse", command=self._browse_yolo_model).grid(row=5, column=2, sticky="ew", padx=(8, 0), pady=4)

        info = "Local IPs: " + (", ".join(local_ipv4_addresses()) or "not found") + " | Camera FTP port: 2121"
        ttk.Label(root, text=info).grid(row=6, column=0, columnspan=3, sticky="w", pady=(8, 6))

        log_frame = ttk.Frame(root)
        log_frame.grid(row=7, column=0, columnspan=3, sticky="nsew")
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        self.log_text = tk.Text(log_frame, height=16, wrap="word", state="disabled")
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        buttons = ttk.Frame(root)
        buttons.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        buttons.columnconfigure(4, weight=1)

        self.start_button = ttk.Button(buttons, text="Start Agent", command=self._start_agent)
        self.stop_button = ttk.Button(buttons, text="Stop", command=self._stop_agent, state="disabled")
        self.save_button = ttk.Button(buttons, text="Save Settings", command=self._save_config)
        self.open_folder_button = ttk.Button(buttons, text="Open Image Folder", command=self._open_image_folder)

        self.start_button.grid(row=0, column=0, padx=(0, 8))
        self.stop_button.grid(row=0, column=1, padx=(0, 8))
        self.save_button.grid(row=0, column=2, padx=(0, 8))
        self.open_folder_button.grid(row=0, column=3)

    def _load_config(self):
        config = load_saved_config()

        for key, value in config.items():
            if key in self.vars:
                self.vars[key].set(value)

    def _save_config(self):
        config = {key: var.get() for key, var in self.vars.items()}
        target = save_config(config)
        self._log(f"[+] Settings saved to {target}.\n")

    def _browse_watch_dir(self):
        folder = filedialog.askdirectory(initialdir=self.vars["watch_dir"].get() or str(APP_DIR))
        if folder:
            self.vars["watch_dir"].set(folder)

    def _browse_yolo_model(self):
        filename = filedialog.askopenfilename(filetypes=[("Model files", "*.pt *.onnx"), ("All files", "*.*")])
        if filename:
            self.vars["yolo_model"].set(filename)

    def _open_image_folder(self):
        folder = Path(self.vars["watch_dir"].get())
        folder.mkdir(parents=True, exist_ok=True)
        try:
            import os
            os.startfile(folder)
        except OSError as exc:
            messagebox.showerror("Open Folder", str(exc))

    def _args_from_ui(self):
        return SimpleNamespace(
            webhook_url=self.vars["webhook_url"].get().strip(),
            source_name=self.vars["source_name"].get().strip() or "local-hikvision-agent",
            watch_dir=Path(self.vars["watch_dir"].get().strip()),
            poll_seconds=float(self.vars["poll_seconds"].get()),
            stable_seconds=float(self.vars["stable_seconds"].get()),
            file_timeout=30.0,
            webhook_timeout=float(self.vars["webhook_timeout"].get()),
            state_db=APP_DIR / "agent_state.sqlite3",
            enable_yolo=self.vars["enable_yolo"].get(),
            yolo_model=self.vars["yolo_model"].get().strip() or "yolov8n.pt",
            stop_event=self.stop_event,
        )

    def _start_agent(self):
        if self.agent_thread and self.agent_thread.is_alive():
            return

        try:
            args = self._args_from_ui()
        except ValueError as exc:
            messagebox.showerror("Invalid Settings", str(exc))
            return

        if not args.webhook_url:
            messagebox.showerror("Missing Webhook", "Webhook URL is required.")
            return

        self._save_config()
        self.stop_event = threading.Event()
        args.stop_event = self.stop_event

        self.agent_thread = threading.Thread(target=self._agent_worker, args=(args,), daemon=True)
        self.agent_thread.start()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self._log("[+] Agent started.\n")

    def _agent_worker(self, args):
        writer = QueueWriter(self.output_queue)
        try:
            with redirect_stdout(writer), redirect_stderr(writer):
                run_agent(args)
        except Exception as exc:
            self.output_queue.put(f"[!] Agent crashed: {exc}\n")
        finally:
            self.output_queue.put("__AGENT_STOPPED__")

    def _stop_agent(self):
        if self.stop_event:
            self.stop_event.set()
        self._log("[*] Stop requested.\n")

    def _on_agent_stopped(self):
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self._log("[*] Agent stopped.\n")

    def _drain_output(self):
        try:
            while True:
                item = self.output_queue.get_nowait()
                if item == "__AGENT_STOPPED__":
                    self._on_agent_stopped()
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
        if self.agent_thread and self.agent_thread.is_alive():
            if not messagebox.askyesno("Quit", "Agent is running. Stop and exit?"):
                return
            self._stop_agent()
        self.destroy()


def main():
    app = AgentGui()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
