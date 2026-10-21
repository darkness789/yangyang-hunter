"""Find or recover the second-stage map template for a captured game start."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.request import Request, urlopen

from .decode_map import decode_map


MAP_ID = re.compile(r"[0-9a-f]{32}\Z")
MAP_HOST = "https://cat-match-static.easygame2021.com"
MAX_MAP_BYTES = 4 * 1024 * 1024


def second_stage_map_id(seed):
    hashes = seed.get("map_md5")
    if not isinstance(hashes, list) or len(hashes) < 2:
        raise ValueError("开局信息中没有第二关地图编号")
    map_id = hashes[1]
    if not isinstance(map_id, str):
        raise ValueError("第二关地图编号格式无效")
    map_id = map_id.lower()
    if not MAP_ID.fullmatch(map_id):
        raise ValueError("第二关地图编号格式无效")
    return map_id


def _validate_template(data, map_id):
    if data.get("sourceMapMd5") != map_id:
        raise ValueError("地图编号与本局不匹配")
    layers = data.get("levelData")
    groups = data.get("blockTypeData")
    if not isinstance(layers, dict) or not isinstance(groups, dict):
        raise ValueError("地图结构不完整")
    cards = [card for layer in layers.values() for card in layer]
    if not cards or len(cards) != 3 * sum(groups.values()):
        raise ValueError("地图牌数与图案数量不匹配")
    ids = [card.get("id") for card in cards]
    if any(not isinstance(card_id, str) or not card_id for card_id in ids):
        raise ValueError("地图存在无效牌 ID")
    if len(ids) != len(set(ids)):
        raise ValueError("地图存在重复牌 ID")
    return len(cards)


def _existing_template(map_id, template_dir, capture_dir):
    candidates = [capture_dir / f"map_{map_id}.json"]
    candidates.extend(capture_dir.glob("map_*.json"))
    candidates.extend(template_dir.glob("map_*.json"))
    for path in candidates:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            _validate_template(data, map_id)
        except (OSError, ValueError, TypeError, KeyError):
            continue
        return path
    return None


def _captured_map_file(map_id, capture_dir):
    index = capture_dir / "index.jsonl"
    if not index.is_file():
        return None
    try:
        lines = index.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("path") != f"/maps/{map_id}.map" or record.get("status") != 200:
            continue
        name = record.get("saved_file")
        if not isinstance(name, str) or Path(name).name != name or not name.endswith(".bin"):
            continue
        path = capture_dir / name
        if path.is_file():
            return path
    return None


def _decode_and_save(raw_path, map_id, capture_dir):
    data = decode_map(raw_path)
    data["sourceMapMd5"] = map_id
    _validate_template(data, map_id)
    output = capture_dir / f"map_{map_id}.json"
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output)
    return output


def _download_map(map_id, capture_dir):
    url = f"{MAP_HOST}/maps/{map_id}.map"
    request = Request(url, headers={"User-Agent": "YangyangHunter/1.0"})
    with urlopen(request, timeout=15) as response:
        raw = response.read(MAX_MAP_BYTES + 1)
    if not raw.startswith(b".map") or len(raw) > MAX_MAP_BYTES:
        raise ValueError("下载的地图文件格式或大小无效")
    path = capture_dir / f"map_{map_id}.bin"
    path.write_bytes(raw)
    return path


def acquire_second_stage_template(seed, template_dir, capture_dir,
                                  wait_seconds=8, downloader=_download_map):
    """Use a known template, captured map, or the game's static map endpoint."""
    map_id = second_stage_map_id(seed)
    capture_dir.mkdir(parents=True, exist_ok=True)
    existing = _existing_template(map_id, template_dir, capture_dir)
    if existing:
        return existing

    deadline = time.monotonic() + wait_seconds
    capture_error = None
    while True:
        raw_path = _captured_map_file(map_id, capture_dir)
        if raw_path:
            try:
                return _decode_and_save(raw_path, map_id, capture_dir)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                capture_error = exc
        if time.monotonic() >= deadline:
            break
        time.sleep(0.25)

    try:
        return _decode_and_save(downloader(map_id, capture_dir), map_id, capture_dir)
    except Exception as exc:
        detail = f"；抓包文件也无法解码：{capture_error}" if capture_error else ""
        raise ValueError(f"无法取得本局第二关地图：{exc}{detail}") from exc
