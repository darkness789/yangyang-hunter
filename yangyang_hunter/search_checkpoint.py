"""Keep a timed-out search's best legal route across assistant restarts."""

import hashlib
import json
from pathlib import Path


def board_signature(board):
    records = sorted((tile.id, tile.type, tile.x, tile.y, tile.layer, tile.mold)
                     for tile in board.tiles)
    payload = json.dumps(records, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_checkpoint(path, board):
    try:
        saved = json.loads(Path(path).read_text(encoding="utf-8"))
        if saved["board"] == board_signature(board):
            return max(0, int(saved["attempts"])), tuple(saved["path"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return 0, ()


def save_checkpoint(path, board, attempts, route):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps({
        "board": board_signature(board), "attempts": attempts,
        "path": route}, ensure_ascii=False), encoding="utf-8")
    temporary.replace(destination)
