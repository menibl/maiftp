#!/usr/bin/env python3
import base64
import json
import os
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


EDGE_BASE_URL = os.environ.get("EDGE_BASE_URL", "http://127.0.0.1:8088").rstrip("/")
EDGE_TOKEN = os.environ.get("EDGE_TOKEN", "")
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8090"))
SNAPSHOT_DIR = Path(os.environ.get("SNAPSHOT_DIR", "snapshots"))


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def safe_name(value: str) -> str:
    keep = []
    for ch in value:
        keep.append(ch if ch.isalnum() or ch in ("-", "_") else "_")
    return "".join(keep).strip("_") or "camera"


def read_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length <= 0:
        return {}
    return json.loads(handler.rfile.read(length).decode("utf-8"))


def call_edge(camera_name: str, count: int, interval_ms: int, camera_id: str = "", local_ip: str = "") -> dict:
    payload = {
        "camera_name": camera_name,
        "count": count,
        "interval_ms": interval_ms,
    }
    if camera_id:
        payload["camera_id"] = camera_id
    if local_ip:
        payload["local_ip"] = local_ip
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if EDGE_TOKEN:
        headers["Authorization"] = f"Bearer {EDGE_TOKEN}"
    request = Request(f"{EDGE_BASE_URL}/api/snapshot", data=body, headers=headers, method="POST")
    with urlopen(request, timeout=90) as response:
        return json.loads(response.read().decode("utf-8"))


def save_images(edge_response: dict) -> list[dict]:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    saved = []
    camera_name = edge_response.get("camera_name", "camera")
    for image in edge_response.get("images", []):
        if not image.get("ok") or not image.get("base64"):
            continue
        filename = f"{utc_stamp()}_{safe_name(camera_name)}_{image.get('index', 1)}.jpg"
        path = SNAPSHOT_DIR / filename
        path.write_bytes(base64.b64decode(image["base64"]))
        saved.append({
            "index": image.get("index"),
            "path": str(path),
            "size": path.stat().st_size,
        })
    return saved


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_json(200, {
                "ok": True,
                "edge_base_url": EDGE_BASE_URL,
                "snapshot_dir": str(SNAPSHOT_DIR),
            })
            return
        self.send_json(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:
        if self.path != "/snapshot":
            self.send_json(404, {"ok": False, "error": "not_found"})
            return
        try:
            data = read_json(self)
            camera_name = str(data.get("camera_name") or "")
            if not camera_name:
                self.send_json(400, {"ok": False, "error": "camera_name_required"})
                return
            camera_id = str(data.get("camera_id") or "")
            local_ip = str(data.get("local_ip") or "")
            count = max(1, min(int(data.get("count") or 1), 10))
            interval_ms = max(0, min(int(data.get("interval_ms") or 0), 10000))
            edge_response = call_edge(camera_name, count, interval_ms, camera_id, local_ip)
            saved = save_images(edge_response)
            self.send_json(200, {
                "ok": bool(edge_response.get("ok")) and len(saved) == count,
                "camera_name": edge_response.get("camera_name", camera_name),
                "saved": saved,
                "edge_response": edge_response,
            })
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            self.send_json(exc.code, {"ok": False, "error": "edge_http_error", "detail": detail})
        except URLError as exc:
            self.send_json(502, {"ok": False, "error": "edge_unreachable", "detail": str(exc)})
        except Exception as exc:
            self.send_json(500, {"ok": False, "error": "server_error", "detail": str(exc)})


def main() -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"GCP webhook test server listening on http://{HOST}:{PORT}")
    print(f"Forwarding snapshot requests to {EDGE_BASE_URL}")
    server.serve_forever()


if __name__ == "__main__":
    main()
