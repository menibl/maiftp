# -*- coding: utf-8 -*-
import json
import os
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel


BASE_DIR = Path(os.environ.get("MAIFOCUS_WEBHOOK_HOME", Path(__file__).resolve().parent / "data"))
UPLOAD_DIR = BASE_DIR / "uploads"
DB_PATH = BASE_DIR / "webhook.sqlite3"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def db():
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS images (
            id TEXT PRIMARY KEY,
            received_at TEXT NOT NULL,
            source TEXT,
            filename TEXT,
            stored_path TEXT NOT NULL,
            content_type TEXT,
            size INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            alert INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS heartbeats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            received_at TEXT NOT NULL,
            agent_id TEXT,
            source TEXT,
            payload_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS commands (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            action TEXT NOT NULL,
            args_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            picked_at TEXT,
            completed_at TEXT,
            result_json TEXT
        )
        """
    )
    conn.commit()
    return conn


def row_to_dict(row):
    return dict(row) if row is not None else None


def parse_payload(payload: str):
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid payload JSON: {exc}") from exc


app = FastAPI(title="MaiFocus Webhook Server")


@app.on_event("startup")
def startup():
    db().close()


@app.get("/", response_class=HTMLResponse)
def index():
    return """
    <html>
      <head><title>MaiFocus Webhook Server</title></head>
      <body style="font-family: Arial, sans-serif; margin: 32px;">
        <h1>MaiFocus Webhook Server</h1>
        <ul>
          <li><a href="/images">Recent images JSON</a></li>
          <li><a href="/heartbeats">Recent heartbeats JSON</a></li>
          <li>POST /webhook/image</li>
          <li>POST /webhook/heartbeat</li>
          <li>POST /webhook/commands</li>
        </ul>
      </body>
    </html>
    """


@app.post("/webhook/image")
async def receive_image(payload: str = Form(...), image: UploadFile = File(...)):
    data = parse_payload(payload)
    image_id = str(uuid.uuid4())
    received_at = utc_now()
    source = str(data.get("source") or "unknown")
    original_name = image.filename or data.get("filename") or "image.jpg"
    safe_name = Path(original_name).name
    source_dir = UPLOAD_DIR / source / received_at[:10]
    source_dir.mkdir(parents=True, exist_ok=True)
    stored_path = source_dir / f"{image_id}_{safe_name}"

    size = 0
    with stored_path.open("wb") as handle:
        while True:
            chunk = await image.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            handle.write(chunk)

    conn = db()
    conn.execute(
        """
        INSERT INTO images
        (id, received_at, source, filename, stored_path, content_type, size, payload_json, alert)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            image_id,
            received_at,
            source,
            safe_name,
            str(stored_path),
            image.content_type,
            size,
            json.dumps(data, ensure_ascii=False),
            1 if data.get("alert") else 0,
        ),
    )
    conn.commit()
    conn.close()

    return {
        "ok": True,
        "id": image_id,
        "received_at": received_at,
        "stored_path": str(stored_path),
        "size": size,
        "alert": bool(data.get("alert")),
    }


@app.post("/webhook/heartbeat")
async def receive_heartbeat(payload: dict[str, Any]):
    conn = db()
    conn.execute(
        """
        INSERT INTO heartbeats (received_at, agent_id, source, payload_json)
        VALUES (?, ?, ?, ?)
        """,
        (
            utc_now(),
            str(payload.get("agent_id") or ""),
            str(payload.get("source") or ""),
            json.dumps(payload, ensure_ascii=False),
        ),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/images")
def list_images(limit: int = 50, alert_only: bool = False):
    conn = db()
    where = "WHERE alert = 1" if alert_only else ""
    rows = conn.execute(
        f"""
        SELECT id, received_at, source, filename, stored_path, content_type, size, payload_json, alert
        FROM images
        {where}
        ORDER BY received_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()

    items = []
    for row in rows:
        item = row_to_dict(row)
        item["payload"] = json.loads(item.pop("payload_json"))
        item["alert"] = bool(item["alert"])
        item["download_url"] = f"/images/{item['id']}/file"
        items.append(item)
    return {"items": items}


@app.get("/images/{image_id}")
def get_image(image_id: str):
    conn = db()
    row = conn.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Image not found")
    item = row_to_dict(row)
    item["payload"] = json.loads(item.pop("payload_json"))
    item["alert"] = bool(item["alert"])
    item["download_url"] = f"/images/{item['id']}/file"
    return item


@app.get("/images/{image_id}/file")
def get_image_file(image_id: str):
    conn = db()
    row = conn.execute("SELECT stored_path, filename, content_type FROM images WHERE id = ?", (image_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Image not found")
    path = Path(row["stored_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Image file missing")
    return FileResponse(path, media_type=row["content_type"], filename=row["filename"])


@app.get("/heartbeats")
def list_heartbeats(limit: int = 50):
    conn = db()
    rows = conn.execute(
        """
        SELECT id, received_at, agent_id, source, payload_json
        FROM heartbeats
        ORDER BY received_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    items = []
    for row in rows:
        item = row_to_dict(row)
        item["payload"] = json.loads(item.pop("payload_json"))
        items.append(item)
    return {"items": items}


class CreateCommandRequest(BaseModel):
    agent_id: str
    action: str
    args: dict[str, Any] = {}


@app.post("/commands")
def create_command(request: CreateCommandRequest):
    command_id = str(uuid.uuid4())
    conn = db()
    conn.execute(
        """
        INSERT INTO commands (id, agent_id, action, args_json, status, created_at)
        VALUES (?, ?, ?, ?, 'pending', ?)
        """,
        (
            command_id,
            request.agent_id,
            request.action,
            json.dumps(request.args, ensure_ascii=False),
            utc_now(),
        ),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "id": command_id}


@app.get("/commands")
def list_commands(limit: int = 50):
    conn = db()
    rows = conn.execute(
        """
        SELECT * FROM commands
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    items = []
    for row in rows:
        item = row_to_dict(row)
        item["args"] = json.loads(item.pop("args_json"))
        item["result"] = json.loads(item["result_json"]) if item.get("result_json") else None
        items.append(item)
    return {"items": items}


@app.post("/webhook/commands")
async def agent_commands(payload: dict[str, Any]):
    agent = payload.get("agent") or {}
    agent_id = str(agent.get("agent_id") or "")
    result = payload.get("result")
    conn = db()

    if result and result.get("id"):
        conn.execute(
            """
            UPDATE commands
            SET status = ?, completed_at = ?, result_json = ?
            WHERE id = ?
            """,
            (
                "completed" if result.get("ok") else "failed",
                utc_now(),
                json.dumps(result, ensure_ascii=False),
                result["id"],
            ),
        )
        conn.commit()

    rows = conn.execute(
        """
        SELECT id, action, args_json
        FROM commands
        WHERE agent_id = ? AND status = 'pending'
        ORDER BY created_at ASC
        LIMIT 5
        """,
        (agent_id,),
    ).fetchall()

    command_ids = [row["id"] for row in rows]
    if command_ids:
        conn.executemany(
            "UPDATE commands SET status = 'picked', picked_at = ? WHERE id = ?",
            [(utc_now(), command_id) for command_id in command_ids],
        )
        conn.commit()

    conn.close()
    commands = []
    for row in rows:
        args = json.loads(row["args_json"])
        command = {"id": row["id"], "action": row["action"]}
        command.update(args)
        commands.append(command)
    return {"commands": commands}
