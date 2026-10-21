"""Click a verified solution in the PC WeChat game, one checked batch at a time.

Coordinates are calibrated for the current Sheep Planet window. Pass explicit
start/end step numbers, inspect the screenshot, then continue the next batch.
"""

import argparse
import ctypes
import json
import sys
import time
from ctypes import wintypes
from pathlib import Path

from board_model import Board
from solve import replay


WINDOW_TITLE = "羊了个羊：星球"
BASE_WIDTH = 573
BASE_HEIGHT = 1067


def window():
    user32 = ctypes.windll.user32
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    handle = user32.FindWindowW(None, WINDOW_TITLE)
    if not handle:
        raise RuntimeError("Sheep Planet game window is not open")
    rect = wintypes.RECT()
    if not user32.GetWindowRect(handle, ctypes.byref(rect)):
        raise RuntimeError("Could not read game window position")
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width < 400 or height < 700:
        raise RuntimeError("Game window is too small for calibrated clicks")
    return user32, handle, rect, width, height


def click(user32, x, y):
    user32.SetCursorPos(x, y)
    user32.mouse_event(2, 0, 0, 0, 0)
    user32.mouse_event(4, 0, 0, 0, 0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("map_file", type=Path)
    parser.add_argument("solution_file", type=Path)
    parser.add_argument("--start", type=int, required=True,
                        help="first 1-based step to click")
    parser.add_argument("--end", type=int, required=True,
                        help="last 1-based step to click, inclusive")
    parser.add_argument("--delay", type=float, default=0.65)
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    board = Board.from_json(args.map_file)
    solution = json.loads(args.solution_file.read_text(encoding="utf-8"))
    if solution.get("status") != "solved" or not solution.get("verified"):
        parser.error("solution file is not marked solved and verified")
    ids = solution["clicks"]
    if len(ids) != len(board.tiles) or len(set(ids)) != len(ids):
        parser.error("solution length or tile IDs do not match this board")
    path = tuple(board.index[tile_id] for tile_id in ids)
    if not replay(board, path):
        parser.error("independent replay rejected this solution")
    if not 1 <= args.start <= args.end <= len(ids):
        parser.error("start/end must lie within the solution")
    if args.delay < 0:
        parser.error("delay must be nonnegative")

    user32, handle, rect, width, height = window()
    if not args.dry_run:
        user32.SetForegroundWindow(handle)
        time.sleep(0.2)
    for step in range(args.start, args.end + 1):
        tile = board.tiles[board.index[ids[step - 1]]]
        relative_x = (110 + 6.3 * tile.x) * width / BASE_WIDTH
        relative_y = (300 + 6.25 * tile.y) * height / BASE_HEIGHT
        x, y = rect.left + round(relative_x), rect.top + round(relative_y)
        if not args.dry_run:
            click(user32, x, y)
            time.sleep(args.delay)
        print("step {}: {} type={} pixel=({}, {}){}".format(
            step, tile.id, tile.type, x, y,
            " [dry run]" if args.dry_run else ""), flush=True)
    if args.screenshot:
        from PIL import ImageGrab
        args.screenshot.parent.mkdir(parents=True, exist_ok=True)
        ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom)).save(
            str(args.screenshot))
        print("screenshot:", args.screenshot)


if __name__ == "__main__":
    if sys.platform != "win32":
        raise SystemExit("This click helper requires Windows")
    main()
