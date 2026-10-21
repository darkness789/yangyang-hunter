"""mitmproxy addon for locating Sheep Planet level data.

It keeps a URL inventory without query strings or headers, and saves only
responses that look like level data. Never records request bodies or cookies.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

from mitmproxy import http


OUTPUT = Path(os.environ.get("YLGY_CAPTURE_DIR", "captures"))
BODY_LIMIT = 4 * 1024 * 1024
MAP_PATH = re.compile(r"map|level|stage|board|config|game_start|game/start", re.I)
MAP_KEYS = re.compile(r'"(?:map_seed|map_md5|levelData|blockTypeData|layerNum|rowNum|rolNum|chessIndex|tileMap|boardData)"', re.I)
PRIVATE_KEY = re.compile(r"token|cookie|secret|session|openid|unionid|authorization|password|phone|email|avatar|nickname|user.?id|access.?key", re.I)
SKIP_PATH = re.compile(r"login|auth|payment|pay/|profile|analytics|report|telemetry|track|log/upload", re.I)
TEXT_TYPES = ("json", "text/", "javascript", "xml")


def scrub(value):
    if isinstance(value, dict):
        return {key: ("[REDACTED]" if PRIVATE_KEY.search(str(key)) else scrub(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [scrub(item) for item in value]
    return value


def safe_path(path):
    # Omit query parameters, then mask long IDs embedded in path components.
    if re.fullmatch(r"/maps/[a-fA-F0-9]{32}\.map", path):
        return path
    return re.sub(r"[A-Za-z0-9_-]{32,}", "[ID]", path.split("?", 1)[0])


class LevelCapture:
    def __init__(self):
        self.counter = 0

    def response(self, flow: http.HTTPFlow):
        if flow.response is None:
            return
        request = flow.request
        response = flow.response
        host = request.pretty_host.lower()
        if host != "easygame2021.com" and not host.endswith(".easygame2021.com"):
            return
        path = request.path.split("?", 1)[0]
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        body = response.get_content(strict=False) or b""
        path_hint = bool(MAP_PATH.search(path)) and not SKIP_PATH.search(path)
        text_hint = any(kind in content_type for kind in TEXT_TYPES)
        key_hint = bool(MAP_KEYS.search(body.decode("utf-8", errors="ignore"))) if text_hint and len(body) <= BODY_LIMIT else False
        candidate = path_hint or key_hint

        OUTPUT.mkdir(parents=True, exist_ok=True)
        record = {
            "time": int(time.time()),
            "host": host,
            "path": safe_path(path),
            "status": response.status_code,
            "content_type": content_type,
            "body_bytes": len(body),
            "candidate": candidate,
        }

        if candidate and len(body) <= BODY_LIMIT:
            self.counter += 1
            digest = hashlib.sha256((host + path).encode()).hexdigest()[:12]
            stem = f"{int(time.time() * 1000)}_{self.counter:04d}_{digest}"
            try:
                parsed = json.loads(body)
            except (UnicodeDecodeError, json.JSONDecodeError):
                # Preserve binary map resources only when their path suggests a map.
                if path_hint and not text_hint:
                    filename = stem + ".bin"
                    (OUTPUT / filename).write_bytes(body)
                    record["saved_file"] = filename
            else:
                filename = stem + ".json"
                (OUTPUT / filename).write_text(
                    json.dumps(scrub(parsed), ensure_ascii=False, indent=2), encoding="utf-8"
                )
                record["saved_file"] = filename

        with (OUTPUT / "index.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        if candidate:
            print(f"[candidate] {host}{safe_path(path)} -> {record.get('saved_file', 'metadata only')}")


addons = [LevelCapture()]
