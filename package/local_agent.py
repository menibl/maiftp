# -*- coding: utf-8 -*-
import base64
import hashlib
import json
import mimetypes
import os
import sqlite3
import sys
import time
import argparse
import copy
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

try:
    import requests
except ImportError:
    print("[!] Missing dependency: requests")
    print("[*] Install with: python -m pip install -r requirements.txt")
    sys.exit(1)

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None
    ImageDraw = None


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
ANNOTATED_DIR_NAME = "_annotated"
ANNOTATED_SUFFIX = "_annotated"
KNOWN_YOLO_MODELS = {
    "yolov8n.pt": "https://github.com/ultralytics/assets/releases/download/v8.4.0/yolov8n.pt",
    "yolov8s.pt": "https://github.com/ultralytics/assets/releases/download/v8.4.0/yolov8s.pt",
    "yolov8m.pt": "https://github.com/ultralytics/assets/releases/download/v8.4.0/yolov8m.pt",
    "yolo26n.pt": "https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26n.pt",
}
HEALTH_LOCK = threading.Lock()


def env(name, default=None):
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def write_health(args, **updates):
    health_file = getattr(args, "health_file", None)
    if not health_file:
        return

    with HEALTH_LOCK:
        health_path = Path(health_file)
        health_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "updated_at_utc": utc_now(),
            "status": "running",
        }
        if health_path.exists():
            try:
                with health_path.open("r", encoding="utf-8-sig") as handle:
                    existing = json.load(handle)
                if isinstance(existing, dict):
                    data.update(existing)
            except (OSError, json.JSONDecodeError):
                pass

        data.update(updates)
        data["updated_at_utc"] = utc_now()
        temp_path = health_path.with_suffix(health_path.suffix + ".tmp")
        try:
            with temp_path.open("w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, sort_keys=True)
            temp_path.replace(health_path)
        except OSError:
            pass


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def default_model_dir():
    return Path(os.environ.get("MAIFOCUS_AGENT_HOME", Path.home() / "MaiFocusEdgeAgent")) / "models"


def download_file(url, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_target = target.with_suffix(target.suffix + ".download")
    print(f"[*] Downloading model to: {target}", flush=True)
    with requests.get(url, stream=True, timeout=120) as response:
        response.raise_for_status()
        with temp_target.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
    temp_target.replace(target)


def resolve_yolo_model(model_name):
    model_name = model_name.strip() or "yolov8n.pt"
    parsed = urlparse(model_name)
    if parsed.scheme in {"http", "https"}:
        target = default_model_dir() / Path(parsed.path).name
        if not target.exists():
            download_file(model_name, target)
        return str(target)

    model_path = Path(model_name)
    if model_path.is_absolute() or model_path.parent != Path("."):
        return str(model_path)

    target = default_model_dir() / model_name
    if not target.exists() and model_name in KNOWN_YOLO_MODELS:
        download_file(KNOWN_YOLO_MODELS[model_name], target)
    return str(target if target.exists() else model_path)


def wait_until_file_is_stable(path, stable_seconds, timeout_seconds):
    deadline = time.time() + timeout_seconds
    last_size = -1
    last_changed = time.time()

    while time.time() < deadline:
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            return False

        if size != last_size:
            last_size = size
            last_changed = time.time()
        elif size > 0 and time.time() - last_changed >= stable_seconds:
            return True

        time.sleep(0.5)

    return False


class StateStore:
    def __init__(self, db_path):
        self.lock = threading.Lock()
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sent_files (
                path TEXT PRIMARY KEY,
                sha256 TEXT NOT NULL,
                size INTEGER NOT NULL,
                sent_at TEXT NOT NULL,
                status_code INTEGER,
                response_text TEXT
            )
            """
        )
        self.conn.commit()

    def is_sent(self, path):
        with self.lock:
            cursor = self.conn.execute("SELECT 1 FROM sent_files WHERE path = ?", (str(path),))
            return cursor.fetchone() is not None

    def mark_sent(self, path, file_hash, size, status_code, response_text):
        with self.lock:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO sent_files
                (path, sha256, size, sent_at, status_code, response_text)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (str(path), file_hash, size, utc_now(), status_code, response_text[:1000]),
            )
            self.conn.commit()


def load_yolo(model_name):
    try:
        from ultralytics import YOLO
    except ImportError:
        raise RuntimeError("YOLO requested but ultralytics is not installed")
    return YOLO(resolve_yolo_model(model_name))


def current_cpu_percent():
    try:
        import psutil
    except ImportError:
        return None
    return psutil.cpu_percent(interval=0.2)


def should_skip_yolo_for_load(args):
    if not getattr(args, "skip_yolo_when_busy", False):
        return False, None

    max_cpu = float(getattr(args, "max_cpu_percent", 85))
    cpu_percent = current_cpu_percent()
    if cpu_percent is None:
        return False, None
    if cpu_percent >= max_cpu:
        return True, f"cpu_percent={cpu_percent:.1f} >= {max_cpu:.1f}"
    return False, f"cpu_percent={cpu_percent:.1f}"


def should_skip_yolo_for_queue(args):
    max_queue = int(getattr(args, "max_yolo_queue_size", 0) or 0)
    if max_queue <= 0:
        return False, None

    queue_backlog = int(getattr(args, "queue_backlog", 0) or 0)
    if queue_backlog > max_queue:
        return True, f"queue_backlog={queue_backlog} > {max_queue}"
    return False, f"queue_backlog={queue_backlog}"


def run_yolo(model, image_path):
    results = model(str(image_path), verbose=False)
    detections = []

    for result in results:
        names = result.names or {}
        boxes = result.boxes
        if boxes is None:
            continue

        for box in boxes:
            class_id = int(box.cls[0])
            confidence = float(box.conf[0])
            xyxy = [float(value) for value in box.xyxy[0].tolist()]
            detections.append(
                {
                    "class_id": class_id,
                    "label": names.get(class_id, str(class_id)),
                    "confidence": confidence,
                    "xyxy": xyxy,
                }
            )

    return detections


def parse_label_filter(value):
    labels = []
    for item in (value or "").split(","):
        label = item.strip().lower()
        if label:
            labels.append(label)
    return set(labels)


def matching_alerts(detections, labels, min_confidence):
    if not labels:
        return detections

    matches = []
    for detection in detections:
        label = str(detection.get("label", "")).lower()
        confidence = float(detection.get("confidence", 0))
        if label in labels and confidence >= min_confidence:
            matches.append(detection)
    return matches


def summarize_detections(detections, max_items=5):
    if not detections:
        return "none"

    items = []
    for detection in sorted(detections, key=lambda item: float(item.get("confidence", 0)), reverse=True)[:max_items]:
        label = str(detection.get("label", "unknown"))
        confidence = float(detection.get("confidence", 0))
        items.append(f"{label}:{confidence:.2f}")
    if len(detections) > max_items:
        items.append(f"+{len(detections) - max_items} more")
    return ", ".join(items)


def save_annotated_image(original_path, relative_path, watch_dir, detections):
    if not detections or Image is None or ImageDraw is None:
        return None, "no_detections" if not detections else "Pillow is not installed"

    output_dir = Path(watch_dir) / ANNOTATED_DIR_NAME / Path(relative_path).parent
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{original_path.stem}{ANNOTATED_SUFFIX}.jpg"

    try:
        with Image.open(original_path) as image:
            image = image.convert("RGB")
            draw = ImageDraw.Draw(image)
            width, height = image.size
            line_width = max(3, int(min(width, height) / 250))

            for detection in detections:
                xyxy = detection.get("xyxy") or []
                if len(xyxy) != 4:
                    continue
                x1, y1, x2, y2 = xyxy
                x1 = max(0, min(width - 1, int(round(x1))))
                y1 = max(0, min(height - 1, int(round(y1))))
                x2 = max(0, min(width - 1, int(round(x2))))
                y2 = max(0, min(height - 1, int(round(y2))))
                if x2 <= x1 or y2 <= y1:
                    continue

                draw.rectangle((x1, y1, x2, y2), outline="red", width=line_width)
                label = str(detection.get("label", "object"))
                confidence = float(detection.get("confidence", 0))
                text = f"{label} {confidence:.2f}"
                text_bbox = draw.textbbox((x1, y1), text)
                text_width = text_bbox[2] - text_bbox[0]
                text_height = text_bbox[3] - text_bbox[1]
                label_y = max(0, y1 - text_height - (line_width * 2))
                draw.rectangle(
                    (x1, label_y, min(width - 1, x1 + text_width + 8), label_y + text_height + 6),
                    fill="red",
                )
                draw.text((x1 + 4, label_y + 3), text, fill="white")

            image.save(output_path, format="JPEG", quality=92, optimize=True)
            return output_path, None
    except Exception as exc:
        return None, str(exc)


def auth_headers(token):
    if not token:
        return {}
    return {
        "X-Webhook-Token": token,
        "Authorization": f"Bearer {token}",
    }


def split_webhook_urls(value):
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]

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


def prepare_upload_image(image_path, payload, compress, max_width, jpeg_quality, temp_dir):
    if not compress:
        return image_path, image_path.name, mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    if Image is None:
        payload["upload_image_compressed"] = False
        payload["upload_image_compression_error"] = "Pillow is not installed"
        return image_path, image_path.name, mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"

    try:
        with Image.open(image_path) as image:
            image = image.convert("RGB")
            original_width, original_height = image.size
            if max_width > 0 and original_width > max_width:
                new_height = int(original_height * (max_width / original_width))
                image = image.resize((max_width, new_height), Image.Resampling.LANCZOS)

            output_path = Path(temp_dir) / f"{image_path.stem}_upload.jpg"
            image.save(output_path, format="JPEG", quality=jpeg_quality, optimize=True)

        payload["upload_image_compressed"] = True
        payload["upload_original_filename"] = image_path.name
        payload["upload_original_size"] = image_path.stat().st_size
        payload["upload_sent_filename"] = output_path.name
        payload["upload_sent_size"] = output_path.stat().st_size
        payload["upload_max_width"] = max_width
        payload["upload_jpeg_quality"] = jpeg_quality
        return output_path, output_path.name, "image/jpeg"
    except Exception as exc:
        payload["upload_image_compressed"] = False
        payload["upload_image_compression_error"] = str(exc)
        return image_path, image_path.name, mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"


def post_image(
    webhook_url,
    image_path,
    payload,
    timeout_seconds,
    token="",
    compress=False,
    max_width=1280,
    jpeg_quality=80,
    webhook_format="json-base64",
):
    mime_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    with TemporaryDirectory() as temp_dir:
        upload_path, upload_name, mime_type = prepare_upload_image(
            image_path,
            payload,
            compress,
            int(max_width),
            int(jpeg_quality),
            temp_dir,
        )
        headers = auth_headers(token)
        if webhook_format == "multipart":
            with upload_path.open("rb") as image_file:
                response = requests.post(
                    webhook_url,
                    data={"payload": json.dumps(payload, ensure_ascii=False)},
                    files={"image": (upload_name, image_file, mime_type)},
                    headers=headers,
                    timeout=timeout_seconds,
                )
        else:
            image_bytes = upload_path.read_bytes()
            body = {
                **payload,
                "camera_name": payload.get("camera_name") or payload.get("source"),
                "message": "image alert" if payload.get("alert") else "image received",
                "image": {
                    "filename": upload_name,
                    "content_type": mime_type,
                    "size": len(image_bytes),
                    "base64": base64.b64encode(image_bytes).decode("ascii"),
                },
            }
            response = requests.post(
                webhook_url,
                json=body,
                headers=headers,
                timeout=timeout_seconds,
            )
    return response


def post_image_to_webhooks(
    webhook_urls,
    image_path,
    payload,
    timeout_seconds,
    token="",
    compress=False,
    max_width=1280,
    jpeg_quality=80,
    webhook_format="json-base64",
):
    urls = split_webhook_urls(webhook_urls)
    if not urls:
        raise RuntimeError("No webhook URLs configured")

    with TemporaryDirectory() as temp_dir:
        upload_path, upload_name, mime_type = prepare_upload_image(
            image_path,
            payload,
            compress,
            int(max_width),
            int(jpeg_quality),
            temp_dir,
        )
        tokens = split_webhook_tokens(token, len(urls))
        image_bytes = None
        json_body = None
        if webhook_format != "multipart":
            image_bytes = upload_path.read_bytes()
            json_body = {
                **payload,
                "camera_name": payload.get("camera_name") or payload.get("source"),
                "message": "image alert" if payload.get("alert") else "image received",
                "image": {
                    "filename": upload_name,
                    "content_type": mime_type,
                    "size": len(image_bytes),
                    "base64": base64.b64encode(image_bytes).decode("ascii"),
                },
            }

        def send_one(index, url):
            headers = auth_headers(tokens[index] if index < len(tokens) else "")
            if webhook_format == "multipart":
                with upload_path.open("rb") as image_file:
                    return url, requests.post(
                        url,
                        data={"payload": json.dumps(payload, ensure_ascii=False)},
                        files={"image": (upload_name, image_file, mime_type)},
                        headers=headers,
                        timeout=timeout_seconds,
                    )
            return url, requests.post(
                url,
                json=json_body,
                headers=headers,
                timeout=timeout_seconds,
            )

        if len(urls) == 1:
            return [send_one(0, urls[0])]

        workers = min(len(urls), 8)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(send_one, index, url) for index, url in enumerate(urls)]
            return [future.result() for future in as_completed(futures)]


def call_ai_image_model(ai_model_url, image_path, payload, timeout_seconds, model_name=None, token=""):
    mime_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    data = {"payload": json.dumps(payload, ensure_ascii=False)}
    if model_name:
        data["model"] = model_name

    with image_path.open("rb") as image_file:
        response = requests.post(
            ai_model_url,
            data=data,
            files={"image": (image_path.name, image_file, mime_type)},
            headers=auth_headers(token),
            timeout=timeout_seconds,
        )

    response.raise_for_status()
    if not response.text:
        return {}

    try:
        return response.json()
    except ValueError:
        return {"raw_text": response.text}


def iter_images(root):
    for path in root.rglob("*"):
        if ANNOTATED_DIR_NAME in path.parts or path.stem.endswith(ANNOTATED_SUFFIX):
            continue
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            yield path


def camera_name_from_relative_path(relative_path, fallback):
    parts = Path(relative_path).parts
    if len(parts) > 1 and parts[0]:
        return parts[0]
    return fallback


def clear_pending_images_for_paused_mission(args, state):
    deleted = 0
    failed = 0
    for image_path in list(iter_images(args.watch_dir)):
        if state.is_sent(image_path):
            continue
        try:
            image_path.unlink()
            deleted += 1
        except OSError as exc:
            failed += 1
            print(f"[!] Could not delete pending paused image {image_path}: {exc}", flush=True)

    if deleted or failed:
        print(
            f"[*] Cleared pending image buffer while mission is not RUNNING: "
            f"deleted={deleted}, failed={failed}",
            flush=True,
        )


def drop_stale_image(args, state, image_path, reason, file_age_seconds=None):
    try:
        stat = image_path.stat()
    except OSError:
        return True

    if file_age_seconds is None:
        file_age_seconds = max(0.0, time.time() - stat.st_mtime)

    relative_path = str(image_path.relative_to(args.watch_dir))
    state.mark_sent(
        image_path,
        f"dropped-{int(stat.st_mtime_ns)}-{stat.st_size}",
        stat.st_size,
        0,
        reason,
    )
    try:
        image_path.unlink()
        print(
            f"[*] Dropped stale image {relative_path}: {reason}, "
            f"age={file_age_seconds:.1f}s",
            flush=True,
        )
        return True
    except OSError as exc:
        print(f"[!] Could not delete stale image {relative_path}: {exc}", flush=True)
        return False


def process_image(args, state, yolo_model, image_path):
    started_at = time.perf_counter()
    timings = {}

    if state.is_sent(image_path):
        return

    should_process_images = getattr(args, "should_process_images", None)
    if callable(should_process_images) and not should_process_images():
        try:
            image_path.unlink()
            print(f"[*] Deleted {image_path.name}: mission is not RUNNING", flush=True)
        except OSError as exc:
            print(f"[!] Could not delete {image_path.name} while mission is paused: {exc}", flush=True)
        return

    stable_started_at = time.perf_counter()
    if not wait_until_file_is_stable(image_path, args.stable_seconds, args.file_timeout):
        print(f"[!] Skipping unstable file: {image_path}", flush=True)
        return
    timings["stable"] = time.perf_counter() - stable_started_at

    stat = image_path.stat()
    relative_path = str(image_path.relative_to(args.watch_dir))
    file_age_seconds = max(0.0, time.time() - stat.st_mtime)
    max_file_age_seconds = float(getattr(args, "max_file_age_seconds", 0) or 0)
    if max_file_age_seconds > 0 and file_age_seconds > max_file_age_seconds:
        drop_stale_image(
            args,
            state,
            image_path,
            f"dropped_old_file age={file_age_seconds:.1f}s > max={max_file_age_seconds:.1f}s",
            file_age_seconds,
        )
        return

    hash_started_at = time.perf_counter()
    file_hash = sha256_file(image_path)
    timings["hash"] = time.perf_counter() - hash_started_at
    camera_name = camera_name_from_relative_path(relative_path, args.source_name)
    write_health(
        args,
        status="processing_image",
        last_image_seen_utc=utc_now(),
        last_image_path=relative_path,
    )

    detections = []
    yolo_skipped = False
    yolo_skip_reason = None
    if yolo_model is not None:
        yolo_skipped, yolo_skip_reason = should_skip_yolo_for_queue(args)
    if yolo_model is not None and not yolo_skipped:
        yolo_skipped, yolo_skip_reason = should_skip_yolo_for_load(args)
    if yolo_model is not None and not yolo_skipped:
        yolo_started_at = time.perf_counter()
        write_health(
            args,
            status="running_yolo",
            last_yolo_started_utc=utc_now(),
            last_image_path=relative_path,
        )
        detections = run_yolo(yolo_model, image_path)
        timings["yolo"] = time.perf_counter() - yolo_started_at
        write_health(
            args,
            status="yolo_completed",
            last_yolo_finished_utc=utc_now(),
            last_yolo_seconds=round(timings["yolo"], 3),
            last_image_path=relative_path,
            last_yolo_detections=len(detections),
        )
    elif yolo_skipped:
        timings["yolo"] = 0.0
        print(f"[*] Skipping YOLO for {relative_path}: {yolo_skip_reason}", flush=True)
        write_health(
            args,
            status="yolo_skipped",
            last_yolo_skipped_utc=utc_now(),
            last_yolo_skip_reason=yolo_skip_reason,
            last_image_path=relative_path,
        )

    alert_labels = parse_label_filter(getattr(args, "alert_labels", ""))
    min_confidence = float(getattr(args, "alert_min_confidence", 0))
    alert_matches = matching_alerts(detections, alert_labels, min_confidence)
    alert = bool(alert_matches)
    requires_server_ai = bool(yolo_skipped)
    if requires_server_ai:
        alert = True
        yolo_skipped = True

    if yolo_model is not None and not yolo_skipped:
        print(
            f"[*] YOLO result for {relative_path}: "
            f"detections={len(detections)}, matches={len(alert_matches)}, "
            f"alert={alert}, filter={','.join(sorted(alert_labels)) or 'all'}, "
            f"min_confidence={min_confidence:.2f}, found={summarize_detections(detections)}",
            flush=True,
        )

    upload_source_path = image_path
    annotated_path = None
    annotation_error = None
    if alert_matches:
        annotation_started_at = time.perf_counter()
        annotated_path, annotation_error = save_annotated_image(
            image_path,
            relative_path,
            args.watch_dir,
            alert_matches,
        )
        timings["annotation"] = time.perf_counter() - annotation_started_at
        if annotated_path is not None:
            upload_source_path = annotated_path
    else:
        timings["annotation"] = 0.0

    payload = {
        "source": args.source_name,
        "camera_name": camera_name,
        "filename": image_path.name,
        "relative_path": relative_path,
        "size": stat.st_size,
        "sha256": file_hash,
        "created_at_utc": datetime.fromtimestamp(stat.st_ctime, timezone.utc).isoformat(),
        "modified_at_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "sent_at_utc": utc_now(),
        "detections": detections,
        "alert": alert,
        "alert_labels": sorted({item["label"] for item in alert_matches}),
        "alert_detections": alert_matches,
        "yolo_model": getattr(args, "yolo_model", "") if yolo_model is not None else None,
        "yolo_skipped": yolo_skipped,
        "yolo_skip_reason": yolo_skip_reason,
        "requires_server_ai": requires_server_ai,
        "queue_backlog": int(getattr(args, "queue_backlog", 0) or 0),
        "fast_lane": bool(yolo_skipped),
        "image_annotated": annotated_path is not None,
        "annotation_error": annotation_error,
        "annotated_filename": annotated_path.name if annotated_path is not None else None,
        "processing_file_age_seconds": round(file_age_seconds, 3),
    }

    ai_model_url = getattr(args, "ai_model_url", "") or ""
    if ai_model_url:
        print(f"[*] Running AI image model for {relative_path}", flush=True)
        ai_started_at = time.perf_counter()
        payload["ai_image_model"] = {
            "url": ai_model_url,
            "model": getattr(args, "ai_model_name", "") or None,
            "result": call_ai_image_model(
                ai_model_url,
                image_path,
                payload,
                args.webhook_timeout,
                getattr(args, "ai_model_name", "") or None,
                getattr(args, "webhook_token", "") or "",
            ),
        }
        timings["ai_model"] = time.perf_counter() - ai_started_at
    else:
        timings["ai_model"] = 0.0

    if getattr(args, "send_only_alerts", False) and not alert and not yolo_skipped:
        state.mark_sent(image_path, file_hash, stat.st_size, 0, "skipped_no_alert")
        timings["total"] = time.perf_counter() - started_at
        write_health(
            args,
            status="processed_no_alert",
            last_image_processed_utc=utc_now(),
            last_image_path=relative_path,
            last_processing_result="skipped_no_alert",
            last_total_seconds=round(timings["total"], 3),
        )
        print(
            f"[*] Skipped {relative_path}: alert=False, no matching alert "
            f"(detections={len(detections)}, matches=0, "
            f"filter={','.join(sorted(alert_labels)) or 'all'}, "
            f"min_confidence={min_confidence:.2f})",
            flush=True,
        )
        print(
            f"[*] PERF {relative_path}: skipped_no_alert, "
            f"age={file_age_seconds:.1f}s, queue={int(getattr(args, 'queue_backlog', 0) or 0)}, "
            f"stable={timings.get('stable', 0):.2f}s, hash={timings.get('hash', 0):.2f}s, "
            f"yolo={timings.get('yolo', 0):.2f}s, total={timings['total']:.2f}s",
            flush=True,
        )
        return

    print(f"[*] Sending {relative_path} ({stat.st_size} bytes, alert={alert})", flush=True)
    write_health(
        args,
        status="sending_webhook",
        last_webhook_attempt_utc=utc_now(),
        last_image_path=relative_path,
        last_webhook_alert=bool(alert),
        last_requires_server_ai=bool(requires_server_ai),
    )
    webhook_started_at = time.perf_counter()
    active_webhook_urls = getattr(args, "active_webhook_urls", None)
    active_webhook_tokens = getattr(args, "active_webhook_tokens", None)
    target_webhook_urls = active_webhook_urls() if callable(active_webhook_urls) else args.webhook_url
    target_webhook_tokens = active_webhook_tokens() if callable(active_webhook_tokens) else getattr(args, "webhook_token", "")
    if not split_webhook_urls(target_webhook_urls):
        try:
            image_path.unlink()
            print(f"[*] Deleted {relative_path}: no RUNNING webhook missions", flush=True)
        except OSError as exc:
            print(f"[!] Could not delete {relative_path} with no RUNNING webhook missions: {exc}", flush=True)
        write_health(
            args,
            status="processed_no_running_webhook",
            last_image_processed_utc=utc_now(),
            last_image_path=relative_path,
            last_processing_result="no_running_webhook",
        )
        return

    responses = post_image_to_webhooks(
        target_webhook_urls,
        upload_source_path,
        payload,
        args.webhook_timeout,
        target_webhook_tokens or "",
        bool(getattr(args, "compress_before_upload", False)),
        int(getattr(args, "upload_max_width", 1280)),
        int(getattr(args, "upload_jpeg_quality", 80)),
        getattr(args, "webhook_format", "json-base64") or "json-base64",
    )
    timings["webhook"] = time.perf_counter() - webhook_started_at
    timings["total"] = time.perf_counter() - started_at
    failures = [
        (url, response)
        for url, response in responses
        if not (200 <= response.status_code < 300)
    ]
    response_text = "; ".join(
        f"{url}: HTTP {response.status_code} {(response.text or '')[:160]}"
        for url, response in responses
    )

    if not failures:
        state.mark_sent(image_path, file_hash, stat.st_size, responses[0][1].status_code, response_text)
        write_health(
            args,
            status="webhook_sent",
            last_webhook_success_utc=utc_now(),
            last_image_processed_utc=utc_now(),
            last_image_path=relative_path,
            last_processing_result="sent",
            last_webhook_status="ok",
            last_webhook_count=len(responses),
            last_yolo_skipped=bool(yolo_skipped),
            last_requires_server_ai=bool(requires_server_ai),
            last_total_seconds=round(timings["total"], 3),
        )
        status_summary = ", ".join(f"HTTP {response.status_code}" for _, response in responses)
        print(f"[+] Sent {relative_path}: {len(responses)} webhook(s) OK ({status_summary})", flush=True)
        print(
            f"[*] PERF {relative_path}: sent, "
            f"age={file_age_seconds:.1f}s, queue={int(getattr(args, 'queue_backlog', 0) or 0)}, "
            f"yolo_skipped={yolo_skipped}, stable={timings.get('stable', 0):.2f}s, "
            f"hash={timings.get('hash', 0):.2f}s, yolo={timings.get('yolo', 0):.2f}s, "
            f"annotation={timings.get('annotation', 0):.2f}s, ai={timings.get('ai_model', 0):.2f}s, "
            f"webhook={timings.get('webhook', 0):.2f}s, total={timings['total']:.2f}s",
            flush=True,
        )
        return

    failure_text = "; ".join(
        f"{url}: HTTP {response.status_code} {(response.text or '')[:220]}"
        for url, response in failures
    )
    write_health(
        args,
        status="webhook_failed",
        last_webhook_failed_utc=utc_now(),
        last_image_path=relative_path,
        last_webhook_status=failure_text[:500],
    )
    raise RuntimeError(f"Webhook failed for {relative_path}: {failure_text[:500]}")


def parse_args():
    default_watch_dir = Path(__file__).resolve().parent / "hikvision_images"
    parser = argparse.ArgumentParser(description="Local FTP image receiver agent")
    parser.add_argument("--watch-dir", type=Path, default=Path(env("WATCH_DIR", default_watch_dir)))
    parser.add_argument("--webhook-url", default=env("WEBHOOK_URL"))
    parser.add_argument("--source-name", default=env("SOURCE_NAME", "local-hikvision-agent"))
    parser.add_argument("--poll-seconds", type=float, default=float(env("POLL_SECONDS", "2")))
    parser.add_argument("--stable-seconds", type=float, default=float(env("STABLE_SECONDS", "2")))
    parser.add_argument("--file-timeout", type=float, default=float(env("FILE_TIMEOUT", "30")))
    parser.add_argument("--webhook-timeout", type=float, default=float(env("WEBHOOK_TIMEOUT", "30")))
    parser.add_argument("--state-db", type=Path, default=Path(env("STATE_DB", Path(__file__).resolve().parent / "agent_state.sqlite3")))
    parser.add_argument("--enable-yolo", action="store_true", default=env("ENABLE_YOLO", "0") == "1")
    parser.add_argument("--yolo-model", default=env("YOLO_MODEL", "yolov8n.pt"))
    parser.add_argument("--ai-model-url", default=env("AI_MODEL_URL", ""))
    parser.add_argument("--ai-model-name", default=env("AI_MODEL_NAME", ""))
    parser.add_argument("--webhook-token", default=env("WEBHOOK_TOKEN", ""))
    parser.add_argument("--alert-labels", default=env("ALERT_LABELS", "person,car"))
    parser.add_argument("--alert-min-confidence", type=float, default=float(env("ALERT_MIN_CONFIDENCE", "0.6")))
    parser.add_argument("--send-only-alerts", action="store_true", default=env("SEND_ONLY_ALERTS", "0") == "1")
    parser.add_argument("--skip-yolo-when-busy", action="store_true", default=env("SKIP_YOLO_WHEN_BUSY", "0") == "1")
    parser.add_argument("--max-cpu-percent", type=float, default=float(env("MAX_CPU_PERCENT", "85")))
    parser.add_argument("--yolo-worker-count", type=int, default=int(env("YOLO_WORKER_COUNT", "2")))
    parser.add_argument("--max-yolo-queue-size", type=int, default=int(env("MAX_YOLO_QUEUE_SIZE", "10")))
    parser.add_argument("--max-file-age-seconds", type=float, default=float(env("MAX_FILE_AGE_SECONDS", "120")))
    parser.add_argument("--ignore-existing-on-start", action="store_true", default=env("IGNORE_EXISTING_ON_START", "1") == "1")
    parser.add_argument("--newest-first-when-backlogged", action="store_true", default=env("NEWEST_FIRST_WHEN_BACKLOGGED", "1") == "1")
    parser.add_argument("--compress-before-upload", action="store_true", default=env("COMPRESS_BEFORE_UPLOAD", "1") == "1")
    parser.add_argument("--upload-max-width", type=int, default=int(env("UPLOAD_MAX_WIDTH", "1280")))
    parser.add_argument("--upload-jpeg-quality", type=int, default=int(env("UPLOAD_JPEG_QUALITY", "80")))
    parser.add_argument("--webhook-format", choices=["json-base64", "multipart"], default=env("WEBHOOK_FORMAT", "json-base64"))
    parser.add_argument("--health-file", type=Path, default=Path(env("HEALTH_FILE", Path(env("MAIFOCUS_AGENT_HOME", Path(__file__).resolve().parent)) / "agent_health.json")))
    return parser.parse_args()


def run_agent(args):
    if not args.webhook_url:
        print("[!] WEBHOOK_URL is required.")
        print("[*] Example: $env:WEBHOOK_URL='https://your-server.example/webhook'")
        return 1

    args.watch_dir.mkdir(parents=True, exist_ok=True)
    state = StateStore(args.state_db)
    write_health(
        args,
        status="starting",
        started_at_utc=utc_now(),
        watch_dir=str(args.watch_dir),
        webhook_url=args.webhook_url,
        yolo_enabled=bool(args.enable_yolo),
        yolo_model=args.yolo_model if args.enable_yolo else None,
        pending_count=0,
        oldest_pending_age_seconds=0,
    )

    yolo_models = []
    if args.enable_yolo:
        worker_count = max(1, int(getattr(args, "yolo_worker_count", 1) or 1))
        print(f"[*] Loading YOLO model: {args.yolo_model} (workers={worker_count})", flush=True)
        write_health(
            args,
            status="loading_yolo",
            yolo_model=args.yolo_model,
            yolo_worker_count=worker_count,
            yolo_workers_loaded=0,
        )
        for index in range(worker_count):
            if worker_count > 1:
                print(f"[*] Loading YOLO worker {index + 1}/{worker_count}", flush=True)
            yolo_models.append(load_yolo(args.yolo_model))
            write_health(
                args,
                status="loading_yolo",
                yolo_model=args.yolo_model,
                yolo_worker_count=worker_count,
                yolo_workers_loaded=index + 1,
            )

    print(f"[+] Watching: {args.watch_dir}", flush=True)
    print(f"[+] Webhook: {args.webhook_url}", flush=True)
    write_health(
        args,
        status="started",
        started_at_utc=utc_now(),
        watch_dir=str(args.watch_dir),
        webhook_url=args.webhook_url,
        yolo_enabled=bool(args.enable_yolo),
        yolo_model=args.yolo_model if args.enable_yolo else None,
        yolo_worker_count=len(yolo_models) if yolo_models else 0,
        yolo_workers_loaded=len(yolo_models),
    )

    stop_event = getattr(args, "stop_event", None)
    started_wall_time = time.time()
    startup_ignore_cutoff = started_wall_time - max(float(getattr(args, "stable_seconds", 2) or 2), 5.0)
    ignored_existing_count = 0

    while stop_event is None or not stop_event.is_set():
        should_process_images = getattr(args, "should_process_images", None)
        if callable(should_process_images) and not should_process_images():
            write_health(
                args,
                status="paused_by_mission",
                pending_count=0,
                oldest_pending_age_seconds=0,
                image_processing_enabled=False,
            )
            clear_pending_images_for_paused_mission(args, state)
            if stop_event is not None:
                stop_event.wait(args.poll_seconds)
            else:
                time.sleep(args.poll_seconds)
            continue

        image_paths = []
        for image_path in sorted(iter_images(args.watch_dir), key=lambda p: p.stat().st_mtime):
            if not state.is_sent(image_path):
                try:
                    stat = image_path.stat()
                except OSError:
                    continue

                if (
                    getattr(args, "ignore_existing_on_start", True)
                    and stat.st_mtime < startup_ignore_cutoff
                ):
                    if drop_stale_image(args, state, image_path, "dropped_existing_before_agent_start"):
                        ignored_existing_count += 1
                    continue

                max_file_age_seconds = float(getattr(args, "max_file_age_seconds", 0) or 0)
                file_age_seconds = max(0.0, time.time() - stat.st_mtime)
                if max_file_age_seconds > 0 and file_age_seconds > max_file_age_seconds:
                    drop_stale_image(
                        args,
                        state,
                        image_path,
                        f"dropped_old_file age={file_age_seconds:.1f}s > max={max_file_age_seconds:.1f}s",
                        file_age_seconds,
                    )
                    continue

                image_paths.append(image_path)

        if ignored_existing_count:
            print(
                f"[*] Startup backlog guard active: dropped {ignored_existing_count} "
                f"pre-existing image(s); processing only new FTP arrivals",
                flush=True,
            )
            ignored_existing_count = 0

        args.queue_backlog = len(image_paths)
        oldest_pending_age = 0.0
        if image_paths:
            pending_mtimes = []
            for pending_path in image_paths:
                try:
                    pending_mtimes.append(pending_path.stat().st_mtime)
                except OSError:
                    pass
            if pending_mtimes:
                oldest_pending_age = max(0.0, time.time() - min(pending_mtimes))
        write_health(
            args,
            status="running",
            pending_count=len(image_paths),
            oldest_pending_age_seconds=round(oldest_pending_age, 3),
            image_processing_enabled=True,
            last_poll_utc=utc_now(),
        )
        max_queue = int(getattr(args, "max_yolo_queue_size", 0) or 0)
        if (
            max_queue > 0
            and args.queue_backlog > max_queue
            and getattr(args, "newest_first_when_backlogged", False)
        ):
            image_paths.reverse()
            print(
                f"[*] Fast lane active: backlog={args.queue_backlog}, "
                f"processing newest images first and skipping YOLO",
                flush=True,
            )

        worker_count = max(1, len(yolo_models) if yolo_models else 1)
        if worker_count > 1 and image_paths:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = []
                for index, image_path in enumerate(image_paths):
                    if stop_event is not None and stop_event.is_set():
                        break
                    task_args = copy.copy(args)
                    task_args.queue_backlog = len(image_paths) - index
                    yolo_model = yolo_models[index % len(yolo_models)] if yolo_models else None
                    futures.append(executor.submit(process_image, task_args, state, yolo_model, image_path))

                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as exc:
                        print(f"[!] {exc}", flush=True)
        else:
            yolo_model = yolo_models[0] if yolo_models else None
            for index, image_path in enumerate(image_paths):
                if stop_event is not None and stop_event.is_set():
                    break
                args.queue_backlog = len(image_paths) - index
                try:
                    process_image(args, state, yolo_model, image_path)
                except Exception as exc:
                    print(f"[!] {exc}", flush=True)

        if stop_event is not None:
            stop_event.wait(args.poll_seconds)
        else:
            time.sleep(args.poll_seconds)

    print("[*] Agent stopped.", flush=True)
    write_health(args, status="stopped", stopped_at_utc=utc_now())
    return 0


def main():
    return run_agent(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
