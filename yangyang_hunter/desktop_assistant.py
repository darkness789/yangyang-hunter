"""Windows desktop overlay for assisted Sheep Planet play."""

from __future__ import annotations

import argparse
import ctypes
import json
import subprocess
import sys
import threading
import time
import tkinter as tk
from collections import Counter
from pathlib import Path
from tkinter import messagebox, ttk

from PIL import ImageChops, ImageGrab, ImageStat

from .board_model import Board, IllegalMove
from .map_templates import acquire_second_stage_template
from .special_rules import SpecialCards
from .special_planner import plan_next_crush
from .route_planner import plan_route
from .search_checkpoint import load_checkpoint, save_checkpoint
from .solve import depth_search, replay
from .solve_with_tools import ToolEngine


if getattr(sys, "frozen", False):
    # PyInstaller extracts Python modules to a temporary directory. Keep
    # captures and the external Node/PowerShell scripts beside the executable.
    ROOT = Path(sys.executable).resolve().parent
    PACKAGE_ROOT = ROOT / "yangyang_hunter"
else:
    PACKAGE_ROOT = Path(__file__).resolve().parent
    ROOT = PACKAGE_ROOT.parent
CAPTURES = ROOT / "captures"
SEARCH_CHECKPOINT = CAPTURES / "search_checkpoint.json"
AUTO_TRACE = CAPTURES / "auto_click_trace.jsonl"
SCRIPTS = ROOT / "scripts"
SEARCH_TIMEOUT_SECONDS = 30
SEARCH_BUDGET_SECONDS = 120
TITLE = "\u7f8a\u4e86\u4e2a\u7f8a\uff1a\u661f\u7403"
ICON_NAMES = {
    1: "青草", 2: "胡萝卜", 3: "玉米", 5: "叉子", 6: "白菜",
    7: "羊毛", 8: "蓝刷", 9: "剪刀", 10: "牛奶", 11: "红桶",
    12: "蓝手套", 13: "铃铛", 14: "火堆", 15: "毛线", 16: "干草",
}

user32 = ctypes.windll.user32
user32.FindWindowW.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p)
user32.FindWindowW.restype = ctypes.c_void_p
user32.GetForegroundWindow.restype = ctypes.c_void_p
user32.GetParent.argtypes = (ctypes.c_void_p,)
user32.GetParent.restype = ctypes.c_void_p
user32.GetWindowLongW.argtypes = (ctypes.c_void_p, ctypes.c_int)
user32.SetWindowLongW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_long)
user32.SetLayeredWindowAttributes.argtypes = (
    ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ubyte, ctypes.c_ulong)
user32.SetForegroundWindow.argtypes = (ctypes.c_void_p,)
user32.SetForegroundWindow.restype = ctypes.c_bool
user32.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
user32.SetCursorPos.restype = ctypes.c_bool
user32.mouse_event.argtypes = (ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong,
                               ctypes.c_ulong, ctypes.c_ulong)
try:
    user32.SetProcessDPIAware()
except OSError:
    pass


class Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class Rect(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def game_rect():
    hwnd = user32.FindWindowW(None, TITLE)
    if not hwnd or not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
        return None
    rect = Rect()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top


def cursor():
    point = Point()
    user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def tile_center(tile, rect):
    left, top, width, height = rect
    return (left + (110 + 6.3 * tile.x) * width / 573,
            top + (300 + 6.25 * tile.y) * height / 1067)


def crop_at(x, y, radius=20):
    return ImageGrab.grab(bbox=(int(x - radius), int(y - radius),
                                int(x + radius), int(y + radius))).convert("RGB")


def change_score(before, after):
    if before is None or after is None:
        return 0.0
    return sum(ImageStat.Stat(ImageChops.difference(before, after)).mean) / 3


def tray_count(image):
    """Read the seven slot bottoms; return None during an unclear animation."""
    if image is None or not hasattr(image, "size") or image.size[0] < 200:
        return None
    width, height = image.size
    if height < 30:
        return None
    occupied = []
    y = round(62 * height / 85)
    for slot in range(7):
        center = round((25 + 72 * slot) * width / 490)
        green = 0
        for offset in (-5, 0, 5):
            x = max(0, min(width - 1, center + round(offset * width / 490)))
            red, g, blue = image.getpixel((x, y))[:3]
            green += g > 1.3 * red and g > 1.6 * blue
        occupied.append(green < 2)
    if any(occupied[i] and not occupied[i - 1] for i in range(1, 7)):
        return None
    return sum(occupied)


def aux_area(rect):
    """The space between the board and the tray where moved cards appear."""
    left, top, width, height = rect
    return (int(left + 20*width/573), int(top + 690*height/1067),
            int(left + 553*width/573), int(top + 824*height/1067))


def find_aux_centers(before, after, rect):
    """Locate the three cards added by the move-out tool from image changes."""
    if before is None or after is None or before.size != after.size:
        return None
    diff = ImageChops.difference(before, after).convert("L")
    width, height = diff.size
    pixels = diff.load()
    activity = [sum(pixels[x, y] > 30 for y in range(height)) for x in range(width)]
    runs = []
    start = None
    for x, count in enumerate(activity + [0]):
        if count >= max(8, height//12) and start is None:
            start = x
        elif count < max(8, height//12) and start is not None:
            if x-start >= max(16, int(22*rect[2]/573)):
                runs.append((start, x))
            start = None
    if len(runs) != 3:
        return None
    box = aux_area(rect)
    centers = []
    for x0, x1 in runs:
        points = [(x, y) for x in range(x0, x1) for y in range(height)
                  if pixels[x, y] > 30]
        if not points:
            return None
        centers.append((box[0] + sum(x for x, _ in points)/len(points),
                        box[1] + sum(y for _, y in points)/len(points)))
    return centers


def second_stage_visible(image):
    """The second map has two stacks at row 0; the first map has none.

    ``image`` is a 573x1067 screenshot of the game window. Sampling the
    left and right stack backs avoids relying on tile pictures or text.
    """
    if image.size != (573, 1067):
        image = image.resize((573, 1067))
    samples = ((125, 285), (125, 300), (145, 285), (145, 300),
               (425, 285), (425, 300), (445, 285), (445, 300))
    dark = sum(1 for x, y in samples if max(image.getpixel((x, y))[:3]) < 185)
    return dark >= 6


def current_stage_is_second(rect):
    if not rect:
        return False
    left, top, width, height = rect
    image = ImageGrab.grab(bbox=(left, top, left+width, top+height)).convert("RGB")
    return second_stage_visible(image)


class Assistant:
    def __init__(self, root, args):
        self.root = root
        self.args = args
        self.board = None
        self.tool_engine = None
        self.special_cards = None
        self.special_history = []
        self.map_file = None
        self.state = None
        self.clicks = []
        self.plan = []
        self.pending = None
        self.aux_centers = None
        self.aux_rect = None
        self.capture_proc = None
        self.capture_stop_thread = None
        self.capture_stamp = None
        self.solving = False
        self.preparing = False
        self.work_epoch = 0
        self.cancel_event = threading.Event()
        self.capture_starting = False
        self.prepare_attempt = 0
        self.search_failed = False
        self.search_attempt = 0
        self.search_candidate = ()
        self.last_down = False
        self.rect = None
        self.focus_active = None
        self.stage2_active = False
        self.stage2_hits = 0
        self.last_stage_check = 0.0
        self.status = tk.StringVar(value="正在读取已保存关卡…")
        self.progress = tk.StringVar(value="")
        self.target = tk.StringVar(value="")
        self.tray = tk.StringVar(value="")
        self.overlay_enabled = tk.BooleanVar(value=True)
        self.auto_track = tk.BooleanVar(value=True)
        self.auto_click = tk.BooleanVar(value=False)
        self.special_mode = tk.BooleanVar(value=False)
        self.auto_next_at = 0.0
        self.auto_pending = False
        self.trace_enabled = True
        self._build_ui()
        self.root.after(150, self._initial_load)
        self.root.after(60, self._poll)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    def _build_ui(self):
        self.root.title("羊了个羊星球 · 通关辅助")
        game = game_rect()
        x = game[0] + game[2] + 16 if game else 620
        y = game[1] if game else 130
        self.root.geometry(f"410x330+{x}+{y}")
        self.root.attributes("-topmost", True)
        main = ttk.Frame(self.root, padding=14)
        main.pack(fill="both", expand=True)
        ttk.Label(main, text="下一张牌", font=("Microsoft YaHei UI", 11)).pack(anchor="w")
        ttk.Label(main, textvariable=self.target, font=("Microsoft YaHei UI", 22, "bold"),
                  foreground="#1268a3").pack(anchor="w", pady=(2, 8))
        ttk.Label(main, textvariable=self.progress).pack(anchor="w")
        ttk.Label(main, textvariable=self.tray).pack(anchor="w", pady=(4, 10))
        ttk.Label(main, textvariable=self.status, wraplength=380,
                  foreground="#555555").pack(anchor="w", pady=(0, 12))
        row = ttk.Frame(main)
        row.pack(fill="x", pady=2)
        ttk.Button(row, text="撤销识别", command=self.undo).pack(side="left")
        ttk.Button(row, text="重新规划", command=self.replan).pack(side="left", padx=5)
        ttk.Button(row, text="确认这步已完成", command=self.confirm_pending).pack(side="left")
        row2 = ttk.Frame(main)
        row2.pack(fill="x", pady=5)
        ttk.Button(row2, text="监听下一局", command=self.start_capture).pack(side="left")
        ttk.Button(row2, text="停止监听", command=self.stop_capture).pack(side="left", padx=5)
        ttk.Checkbutton(row2, text="显示标记", variable=self.overlay_enabled).pack(side="left")
        ttk.Checkbutton(main, text="自动识别我在游戏中的点击", variable=self.auto_track).pack(anchor="w")
        ttk.Checkbutton(main, text="自动点击棋盘和移出区牌（道具手动）", variable=self.auto_click,
                        command=self._auto_mode_changed).pack(anchor="w")
        ttk.Checkbutton(main, text="特殊关卡：三消后重新计算变色牌",
                        variable=self.special_mode,
                        command=self._special_mode_changed).pack(anchor="w")
        row3 = ttk.Frame(main)
        row3.pack(fill="x", pady=(6, 0))
        self.manual_choice = tk.StringVar()
        self.manual_choices = {}
        self.manual_picker = ttk.Combobox(row3, textvariable=self.manual_choice,
                                          state="readonly", width=13)
        self.manual_picker.pack(side="left")
        ttk.Button(row3, text="补记这张牌", command=self.manual_sync).pack(side="left", padx=5)
        ttk.Button(row3, text="重试", command=self.clear_pending).pack(side="left")
        self.root.geometry(f"410x450+{x}+{y}")
        self.overlay = tk.Toplevel(self.root)
        self.overlay.overrideredirect(True)
        self.overlay.attributes("-topmost", True)
        self.overlay.configure(bg="#ff00ff")
        self.overlay.wm_attributes("-transparentcolor", "#ff00ff")
        self.canvas = tk.Canvas(self.overlay, bg="#ff00ff", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.overlay.withdraw()
        self.root.after(300, self._make_clickthrough)

    def _make_clickthrough(self):
        # Tk's winfo_id() is its client HWND; Windows window styles belong to
        # the parent wrapper HWND. Apply the color key to that wrapper.
        hwnd = user32.GetParent(self.overlay.winfo_id())
        if not hwnd:
            hwnd = self.overlay.winfo_id()
        style = user32.GetWindowLongW(hwnd, -20)
        user32.SetWindowLongW(hwnd, -20, style | 0x20 | 0x80000 | 0x08000000)
        user32.SetLayeredWindowAttributes(hwnd, 0x00FF00FF, 0, 0x1)

    def _initial_load(self):
        if self.args.tool_solution:
            try:
                solution = json.loads(self.args.tool_solution.read_text(encoding="utf-8"))
                if solution.get("status") != "solved" or not solution.get("verified"):
                    raise ValueError("道具路线尚未验证")
                actions = [tuple(item) if isinstance(item, list) else item
                           for item in solution["actions"]]
                self.load_tool_board(self.args.map_file, actions,
                                     self.args.resume or 0)
            except Exception as exc:
                self.status.set(f"无法加载道具路线：{exc}")
            return
        if self.args.resume is None:
            if (CAPTURES / "recovered_seed.json").is_file():
                self.status.set("发现本机最近一次开局记录。点“重新规划”可恢复本局，或点“监听下一局”开始新局。")
            else:
                self.status.set("第一关自行完成。请先点“监听下一局”，进入第二关后会自动显示提示。")
            self.target.set("等待第二关")
            return
        try:
            solution = json.loads(self.args.solution.read_text(encoding="utf-8"))
            if solution.get("status") != "solved" or not solution.get("verified"):
                raise ValueError("已保存路线尚未完整验证")
            self.load_board(self.args.map_file, solution["clicks"], self.args.resume)
        except Exception as exc:
            self.status.set(f"没有可用的当前关卡：{exc}。请点“监听下一局”。")

    def load_board(self, path, ids, resume=0):
        board = Board.from_json(path)
        if any(tile.type <= 0 for tile in board.tiles):
            raise ValueError("地图尚未还原图案")
        state = board.initial()
        if resume < 0 or resume > len(ids):
            raise ValueError("续接步数超出路线长度")
        for tile_id in ids[:resume]:
            state = board.move(state, tile_id)
        if state.lost:
            raise ValueError("保存的续接状态已失败")
        self.board = board
        self.tool_engine = None
        self.special_cards = None
        self.search_candidate = ()
        self.map_file = path
        self.state = state
        self.clicks = ids[:resume]
        self.plan = ids[resume:]
        self.pending = None
        self.aux_centers = None
        self.aux_rect = None
        self.stage2_active = resume > 0
        self.search_failed = False
        self.stage2_hits = 0
        self.status.set("已连接。请在游戏中手动点击标记的牌。" if self.stage2_active
                        else "第一关自行完成；检测到第二关后自动开始辅助。")
        self.render()

    def load_tool_board(self, path, actions, resume=0):
        board = Board.from_json(path)
        engine = ToolEngine(board)
        if not 0 <= resume <= len(actions):
            raise ValueError("续接步数超出路线长度")
        state = engine.initial()
        for action in actions[:resume]:
            state = engine.apply(state, action)
        # Check the complete route before showing the first recommendation.
        verified = state
        for action in actions[resume:]:
            verified = engine.apply(verified, action)
        if not engine.won(verified):
            raise ValueError("道具路线无法完整通关")
        self.board = board
        self.tool_engine = engine
        self.special_cards = None
        self.search_candidate = ()
        self.map_file = path
        self.state = state
        self.clicks = list(actions[:resume])
        self.plan = list(actions[resume:])
        self.pending = None
        self.aux_centers = None
        self.aux_rect = None
        self.stage2_active = resume > 0
        self.search_failed = False
        self.stage2_hits = 0
        self.status.set("已载入含移出和复活的完整路线。" if self.stage2_active
                        else "第一关自行完成；检测到第二关后自动开始辅助。")
        self.render()

    def load_special_board(self, path):
        board = Board.from_json(path)
        special = SpecialCards.from_map(board, path)
        self.board = board
        self.tool_engine = ToolEngine(board)
        self.special_cards = special
        self.special_history = []
        self.map_file = path
        self.state = self.tool_engine.initial()
        self.clicks = []
        self.plan = []
        self.pending = None
        self.aux_centers = None
        self.aux_rect = None
        self.search_failed = False
        self.search_attempt = 0
        self.stage2_active = False
        self.stage2_hits = 0
        self.preparing = False
        self.status.set(f"已还原 {len(special.changing_ids)} 张变色牌，正在规划下一组三消…")
        self.render()
        self.replan()

    def render(self):
        if self.board is None:
            return
        done = bin(self.state.removed).count("1")
        self.progress.set(f"已点牌 {done} / {len(self.board.tiles)} · 剩余 {len(self.plan)} 个操作")
        counts = (Counter(self.board.tiles[index].type for index in self.state.tray)
                  if self.tool_engine else
                  {kind: count for kind, count in enumerate(self.state.tray) if count})
        tray_text = "、".join(f"{ICON_NAMES.get(kind, kind)}×{count}"
                              for kind, count in sorted(counts.items())) or "空"
        if self.tool_engine and any(self.state.aux):
            aux_text = "；移出区：" + "、".join(
                f"{i+1}列 {ICON_NAMES.get(self.board.tiles[stack[-1]].type, '')}"
                for i, stack in enumerate(self.state.aux) if stack)
        else:
            aux_text = ""
        self.tray.set("槽位：" + tray_text + aux_text)
        if not self.stage2_active:
            self.target.set("建议重新开一把" if self.search_failed else "等待第二关")
        elif ((self.tool_engine.won(self.state) if self.tool_engine
               else self.board.won(self.state))):
            self.target.set("已完成！")
        elif self.plan:
            action = self.plan[0]
            if action == "MOVE_OUT":
                self.target.set("使用“移出”道具")
            elif action == "REVIVE":
                self.target.set("点击“复活”")
            elif isinstance(action, tuple):
                slot = action[1]
                index = self.state.aux[slot][-1]
                kind = self.board.tiles[index].type
                self.target.set(f"点移出区第 {slot+1} 列 · {ICON_NAMES.get(kind, kind)}")
            else:
                tile = self.board.tiles[self.board.index[action]]
                self.target.set(f"{ICON_NAMES.get(tile.type, str(tile.type))}  ·  {tile.id}")
        else:
            self.target.set("建议重新开一把" if self.search_failed else "等待重新规划")
        visible = self.board.visible_indices(self.state)
        self.manual_choices = {
            f"{ICON_NAMES.get(self.board.tiles[index].type, self.board.tiles[index].type)} · {self.board.tiles[index].id}":
            self.board.tiles[index].id for index in visible}
        if self.tool_engine:
            for slot, stack in enumerate(self.state.aux):
                if stack:
                    tile = self.board.tiles[stack[-1]]
                    self.manual_choices[
                        f"移出区{slot+1}列 · {ICON_NAMES.get(tile.type, tile.type)}"] = ("AUX", slot)
        self.manual_picker["values"] = list(self.manual_choices)
        if self.manual_choice.get() not in self.manual_choices:
            self.manual_choice.set("")
        self._draw_overlay()

    def _draw_overlay(self):
        rect = game_rect()
        self.rect = rect
        foreground = user32.GetForegroundWindow()
        game_hwnd = user32.FindWindowW(None, TITLE)
        panel_hwnd = user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
        self.focus_active = foreground in (game_hwnd, panel_hwnd)
        if (not rect or not self.overlay_enabled.get() or not self.plan or
                self.board is None or not self.stage2_active or not self.focus_active):
            self.overlay.withdraw()
            return
        left, top, width, height = rect
        if width < 200 or height < 400:
            self.overlay.withdraw()
            return
        self.overlay.geometry(f"{width}x{height}+{left}+{top}")
        self.canvas.configure(width=width, height=height)
        self.canvas.delete("all")
        action = self.plan[0]
        if action == "REVIVE":
            self.overlay.withdraw()
            return
        if isinstance(action, tuple):
            centers = self._aux_points(rect)
            if not centers:
                self.overlay.withdraw()
                return
            sx, sy = centers[action[1]]
        elif action == "MOVE_OUT":
            sx, sy = left + 116*width/573, top + 1000*height/1067
        else:
            tile = self.board.tiles[self.board.index[action]]
            sx, sy = tile_center(tile, rect)
        x, y = sx - left, sy - top
        scale = width / 573
        radius = 28 * scale
        self.canvas.create_oval(x-radius, y-radius, x+radius, y+radius,
                                outline="#ff1717", width=max(4, int(5*scale)))
        self.canvas.create_oval(x-4, y-4, x+4, y+4, fill="#ff1717", outline="white")
        self.overlay.deiconify()
        self.overlay.lift()

    def _aux_points(self, rect):
        left, top, width, height = rect
        if self.aux_centers and self.aux_rect:
            old_left, old_top, old_width, old_height = self.aux_rect
            points = [(left + (x-old_left)*width/old_width,
                       top + (y-old_top)*height/old_height)
                      for x, y in self.aux_centers]
        else:
            # The client uses three fixed columns. This also covers a failed
            # tool-animation diff and a revive with no previous Move Out.
            points = [(left + (227 + 56*slot)*width/573,
                       top + 777*height/1067) for slot in range(3)]
        return [(x, y - max(0, len(self.state.aux[slot]) - 1)*4.5*height/1067)
                for slot, (x, y) in enumerate(points)]

    def _trace(self, event, **details):
        if not getattr(self, "trace_enabled", False):
            return
        try:
            CAPTURES.mkdir(parents=True, exist_ok=True)
            with AUTO_TRACE.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"time": time.time(), "event": event,
                                         **details}, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _pause_auto_for_tool(self, action):
        self.auto_click.set(False)
        if action == "MOVE_OUT":
            self.status.set("下一步需手动使用“移出”。自动点击已关闭；使用完后请自行重新开启。")
        else:
            self.status.set("下一步需手动使用“复活”并点“确认这步已完成”。自动点击已关闭；完成后请自行重新开启。")

    def _auto_mode_changed(self):
        self.auto_next_at = time.monotonic() + 0.35
        if not self.auto_click.get():
            self.status.set("自动点击已关闭。")
            return
        if self.plan and self.plan[0] in ("MOVE_OUT", "REVIVE"):
            self._pause_auto_for_tool(self.plan[0])
            return
        self.auto_track.set(True)
        hwnd = user32.FindWindowW(None, TITLE)
        if hwnd:
            user32.SetForegroundWindow(hwnd)
        if not self.plan:
            if self.board:
                self.status.set("自动点击已开启；等待下一组三消的路线。"
                                if self.special_cards else
                                "自动点击已开启，但当前没有完整路线。建议重新开一把或点“重新规划”。")
            else:
                self.status.set("自动点击已开启；等待完整路线。")
        else:
            self.status.set("自动点击已开启；道具操作仍需手动完成。")

    def _special_mode_changed(self):
        self.auto_click.set(False)
        if self.board is not None:
            self.status.set("模式将在“监听下一局”后生效；当前局面继续使用原模式。")
        else:
            self.status.set("特殊关卡模式已开启。进入下一局后按三消结果重新规划。"
                            if self.special_mode.get() else "已恢复普通关卡模式。")

    def _poll_auto(self):
        if (not self.auto_click.get() or not self.board or not self.plan or
                not self.stage2_active or self.pending or self.solving or
                self.preparing or time.monotonic() < self.auto_next_at):
            return
        action = self.plan[0]
        if action in ("MOVE_OUT", "REVIVE"):
            self._pause_auto_for_tool(action)
            return
        try:
            expected_state = (self.tool_engine.apply(self.state, action)
                              if self.tool_engine else self.board.move(self.state, action))
        except IllegalMove as exc:
            self.auto_click.set(False)
            self.status.set(f"自动点击已暂停：路线当前不可执行：{exc}")
            return
        if expected_state.lost:
            self.auto_click.set(False)
            self.status.set("自动点击已暂停：这步会填满槽位且复活已用过。")
            return
        rect = game_rect()
        hwnd = user32.FindWindowW(None, TITLE)
        if not rect or user32.GetForegroundWindow() != hwnd:
            hint = "自动点击已暂停：请激活游戏窗口。"
            if self.status.get() != hint:
                self.status.set(hint)
            return
        if user32.GetAsyncKeyState(0x01) & 0x8000:
            return
        if isinstance(action, tuple):
            centers = self._aux_points(rect)
            if not centers:
                hint = "无法定位移出区，请手动点击标记的牌；识别后自动继续。"
                if self.status.get() != hint:
                    self.status.set(hint)
                return
            x, y = centers[action[1]]
        else:
            x, y = tile_center(self.board.tiles[self.board.index[action]], rect)
        self._candidate_click(x, y, rect)
        if not self.pending or self.pending[0] != action:
            self.pending = None
            self.auto_click.set(False)
            self.status.set("自动点击位置与路线不一致，已暂停。请手动核对牌面。")
            return
        before_count = tray_count(self.pending[5])
        expected_count = (len(self.state.tray) if self.tool_engine else
                          sum(self.state.tray))
        if before_count != expected_count:
            self._trace("pre_click_mismatch", action=action,
                        observed=before_count, expected=expected_count)
            self.pending = None
            self.auto_click.set(False)
            self.status.set(f"自动点击已暂停：游戏槽位为 {before_count} 张，"
                            f"模型记录 {expected_count} 张，请先核对同步。")
            return
        self.verify_retry = 0
        self.auto_pending = True
        self._trace("attempt", action=action, removed=bin(self.state.removed).count("1"),
                    tray=expected_count, aux=[len(stack) for stack in self.state.aux]
                    if self.tool_engine else [])
        old_x, old_y = cursor()
        button_down = False
        try:
            if not user32.SetCursorPos(round(x), round(y)):
                raise OSError("无法移动鼠标到目标牌")
            user32.mouse_event(0x0002, 0, 0, 0, 0)
            button_down = True
            time.sleep(0.04)
            user32.mouse_event(0x0004, 0, 0, 0, 0)
            button_down = False
        except Exception as exc:
            self.pending = None
            self.auto_pending = False
            self.auto_click.set(False)
            self.status.set(f"自动点击已暂停：{exc}")
        finally:
            if button_down:
                user32.mouse_event(0x0004, 0, 0, 0, 0)
            user32.SetCursorPos(old_x, old_y)

    def _poll(self):
        try:
            self._poll_mouse()
            if self.capture_proc is not None:
                self._poll_capture()
            if self.board is not None and not self.stage2_active:
                self._poll_stage()
            self._poll_auto()
            if self.board is not None:
                rect = game_rect()
                foreground = user32.GetForegroundWindow()
                game_hwnd = user32.FindWindowW(None, TITLE)
                panel_hwnd = user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
                active = foreground in (game_hwnd, panel_hwnd)
                if rect != self.rect or active != self.focus_active:
                    self._draw_overlay()
        except Exception as exc:
            self.status.set(f"监控异常：{exc}")
        finally:
            self.root.after(20, self._poll)

    def _poll_mouse(self):
        # The low bit also reports a short click that started and ended between
        # polls. The high bit reports a button still held down.
        key_state = user32.GetAsyncKeyState(0x01)
        down = bool(key_state & 0x8000)
        pressed = bool(key_state & 0x0001)
        if ((down or pressed) and not self.last_down and
                (self.auto_track.get() or self.auto_click.get())
                and self.board and self.stage2_active and not self.pending
                and user32.GetForegroundWindow() == user32.FindWindowW(None, TITLE)):
            rect = game_rect()
            if rect:
                x, y = cursor()
                if rect[0] <= x < rect[0]+rect[2] and rect[1] <= y < rect[1]+rect[3]:
                    self._candidate_click(x, y, rect)
        self.last_down = down

    def _poll_stage(self):
        now = time.monotonic()
        if now - self.last_stage_check < 0.5:
            return
        panel_hwnd = user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
        if user32.GetForegroundWindow() not in (
                user32.FindWindowW(None, TITLE), panel_hwnd):
            return
        self.last_stage_check = now
        visible = current_stage_is_second(game_rect())
        self.stage2_hits = self.stage2_hits + 1 if visible else 0
        if self.stage2_hits >= 2:
            self.stage2_active = True
            if self.plan:
                self.status.set("检测到第二关，已开始显示通关提示。")
            self.render()

    def _candidate_click(self, x, y, rect):
        if self.tool_engine and self.plan:
            expected = self.plan[0]
            if expected == "MOVE_OUT":
                cx = rect[0] + 116*rect[2]/573
                cy = rect[1] + 1000*rect[3]/1067
                if abs(x-cx) > 60*rect[2]/573 or abs(y-cy) > 48*rect[3]/1067:
                    return
                try:
                    before = crop_at(cx, cy)
                    area_before = ImageGrab.grab(bbox=aux_area(rect)).convert("RGB")
                except Exception:
                    before = area_before = None
                self.pending = ("MOVE_OUT", cx, cy, rect, before, None, area_before)
                self.root.after(900, self._verify_click)
                return
            if expected == "REVIVE":
                return
            if isinstance(expected, tuple):
                area = aux_area(rect)
                if not (area[0] <= x < area[2] and area[1] <= y < area[3]):
                    return
                action = expected
                centers = self._aux_points(rect)
                if centers:
                    slot = min(range(3), key=lambda i: (
                        (x-centers[i][0])**2 +
                        (y-centers[i][1])**2))
                    cx, cy = centers[slot]
                    if (abs(x-cx) > 34*rect[2]/573 or
                            abs(y-cy) > 38*rect[3]/1067 or
                            not self.state.aux[slot]):
                        return
                    action = ("AUX", slot)
                else:
                    cx, cy = x, y
                try:
                    before = crop_at(cx, cy)
                    scale = rect[2]/573
                    tray_before = ImageGrab.grab(bbox=(
                        int(rect[0]+40*scale), int(rect[1]+835*rect[3]/1067),
                        int(rect[0]+530*scale), int(rect[1]+920*rect[3]/1067))).convert("RGB")
                except Exception:
                    before = tray_before = None
                self.pending = (action, cx, cy, rect, before, tray_before)
                self.root.after(650, self._verify_click)
                return
        visible = self.board.visible_indices(self.state)
        scale = rect[2] / 573
        candidates = []
        for index in visible:
            tile = self.board.tiles[index]
            cx, cy = tile_center(tile, rect)
            if abs(cx-x) <= 27*scale and abs(cy-y) <= 27*scale:
                candidates.append((tile.layer, -(cx-x)**2-(cy-y)**2, index))
        if not candidates:
            return
        index = max(candidates)[2]
        tile = self.board.tiles[index]
        cx, cy = tile_center(tile, rect)
        try:
            before = crop_at(cx, cy)
            tray_before = ImageGrab.grab(bbox=(
                int(rect[0]+40*scale), int(rect[1]+835*rect[3]/1067),
                int(rect[0]+530*scale), int(rect[1]+920*rect[3]/1067))).convert("RGB")
        except Exception:
            before = tray_before = None
        self.pending = (tile.id, cx, cy, rect, before, tray_before)
        self.root.after(650, self._verify_click)

    def _verify_click(self):
        if self.pending is None:
            self.auto_pending = False
            return
        tile_id, cx, cy, rect, before, tray_before, *extra = self.pending
        if game_rect() != rect:
            self.pending = None
            if self.auto_pending:
                self.auto_click.set(False)
                self.auto_pending = False
            self.status.set("游戏窗口位置发生变化，请重试这张牌。")
            return
        try:
            after = crop_at(cx, cy)
            scale = rect[2]/573
            tray_after = ImageGrab.grab(bbox=(
                int(rect[0]+40*scale), int(rect[1]+835*rect[3]/1067),
                int(rect[0]+530*scale), int(rect[1]+920*rect[3]/1067))).convert("RGB")
            target_score = change_score(before, after)
            score = max(target_score, change_score(tray_before, tray_after))
            if tile_id == "MOVE_OUT" and extra and extra[0] is not None:
                area_after = ImageGrab.grab(bbox=aux_area(rect)).convert("RGB")
                score = max(score, change_score(extra[0], area_after))
                centers = find_aux_centers(extra[0], area_after, rect)
                if centers:
                    self.aux_centers = centers
                    self.aux_rect = rect
        except Exception:
            target_score = 0
            tray_after = None
            score = 0
        threshold = 5 if isinstance(tile_id, tuple) else 3
        if self.auto_pending and tile_id != "MOVE_OUT":
            try:
                next_state = (self.tool_engine.apply(self.state, tile_id)
                              if self.tool_engine else self.board.move(self.state, tile_id))
                expected_count = (len(next_state.tray) if self.tool_engine else
                                  sum(next_state.tray))
            except IllegalMove:
                expected_count = None
            actual_count = tray_count(tray_after)
            if (actual_count is None or expected_count is None or
                    actual_count != expected_count or target_score < threshold):
                if (before is not None and tray_before is not None and
                        getattr(self, "verify_retry", 0) < 2):
                    self.verify_retry += 1
                    self.root.after(350, self._verify_click)
                    return
                self.auto_click.set(False)
                self.auto_pending = False
                self._trace("verify_mismatch", action=tile_id,
                            observed=actual_count, expected=expected_count,
                            target_score=round(target_score, 2))
                self.status.set("自动点击已暂停：目标牌或槽位张数与预期不符。"
                                f"游戏槽位 {actual_count} 张，预期 {expected_count} 张；"
                                "请核对游戏画面后再处理这步。")
                return
            self._trace("verified", action=tile_id, observed=actual_count,
                        expected=expected_count,
                        target_score=round(target_score, 2))
        if score >= threshold:
            self._accept(tile_id)
        else:
            if self.auto_pending:
                self.auto_click.set(False)
                self.auto_pending = False
                self.status.set("自动点击未检测到生效，已暂停。请核对游戏画面，再确认这步或重试。")
            else:
                self.status.set("没检测到画面变化。若操作已完成，点“确认这步已完成”；否则重试。")

    def confirm_pending(self):
        if self.pending:
            self._accept(self.pending[0])
        elif self.board and self.plan:
            # A click can be missed by mouse polling or the game can animate
            # before the screenshot check. Let the player explicitly confirm
            # the card currently highlighted on the board.
            self._accept(self.plan[0])
        elif self.board:
            self.status.set("当前没有待确认的路线，请先重新规划。")

    def clear_pending(self):
        self.pending = None
        self.auto_pending = False
        self.status.set("已清除待确认点击，可以在游戏里重试。")

    def manual_sync(self):
        tile_id = self.manual_choices.get(self.manual_choice.get())
        if tile_id:
            self._accept(tile_id)
        else:
            self.status.set("请先从下拉框选择刚才消除的牌。")

    def _accept(self, tile_id):
        self.pending = None
        self.auto_pending = False
        self.auto_next_at = time.monotonic() + 0.25
        try:
            next_state = (self.tool_engine.apply(self.state, tile_id) if self.tool_engine
                          else self.board.move(self.state, tile_id))
        except IllegalMove as exc:
            self.status.set(f"无法同步这次点击：{exc}")
            return
        if next_state.lost:
            self.status.set("模型显示这步会填满 7 格，请核对游戏状态。")
            return
        before_tray = len(self.state.tray) if self.tool_engine else 0
        if getattr(self, "special_cards", None):
            self.special_history.append((self.board, self.state,
                                         self.special_cards.rng.state))
        self.state = next_state
        self.clicks.append(tile_id)
        self._trace("accepted", action=tile_id,
                    removed=bin(next_state.removed).count("1"),
                    tray=len(next_state.tray) if self.tool_engine else sum(next_state.tray),
                    aux=[len(stack) for stack in next_state.aux]
                    if self.tool_engine else [],
                    used_remove=next_state.used_remove if self.tool_engine else False,
                    used_revive=next_state.used_revive if self.tool_engine else False)
        if (getattr(self, "special_cards", None) and tile_id not in ("MOVE_OUT", "REVIVE")
                and len(next_state.tray) < before_tray):
            self.board = self.special_cards.after_crush(self.board,
                                                        next_state.removed)
            self.tool_engine = ToolEngine(self.board)
            self.plan = []
            # Keep the user's auto-click choice across a changing-card replan.
            # The solver and this delay both block clicks during the animation.
            self.auto_next_at = max(self.auto_next_at, time.monotonic() + 1.2)
            if self.tool_engine.won(self.state):
                self.status.set("路线已完成，请确认游戏显示通关画面。")
                self.render()
            else:
                self.status.set("三消完成，变色牌已按本局种子更新，正在重新规划…")
                self.render()
                self.replan()
            return
        if self.plan and tile_id == self.plan[0]:
            self.plan.pop(0)
            if (getattr(self, "special_cards", None) and not self.plan
                    and tile_id in ("MOVE_OUT", "REVIVE")):
                self.status.set("道具操作已记录，正在规划下一组三消…")
                self.replan()
                self.render()
                return
            if (self.plan and self.plan[0] in ("MOVE_OUT", "REVIVE")
                    and self.auto_click.get()):
                self._pause_auto_for_tool(self.plan[0])
            elif self.plan and self.plan[0] == "REVIVE":
                self.status.set("完成屏幕提示的操作后，按“确认这步已完成”。")
            else:
                self.status.set("已识别操作，下一步已标出。")
        else:
            self.plan = []
            self.status.set("点击偏离路线，正在从当前局面重新规划…")
            self.replan()
        if (self.tool_engine.won(self.state) if self.tool_engine
                else self.board.won(self.state)):
            self.status.set("路线已完成，请确认游戏显示通关画面。")
        self.render()

    def undo(self):
        self.pending = None
        self.auto_pending = False
        if self.special_cards:
            if not self.special_history:
                self.status.set("没有可撤销的识别。")
                return
            self.board, self.state, self.special_cards.rng.state = self.special_history.pop()
            self.tool_engine = ToolEngine(self.board)
            self.clicks.pop()
            self.plan = []
            self.replan()
            return
        if not self.clicks or not self.board:
            return
        self.clicks.pop()
        state = self.tool_engine.initial() if self.tool_engine else self.board.initial()
        for tile_id in self.clicks:
            state = (self.tool_engine.apply(state, tile_id) if self.tool_engine
                     else self.board.move(state, tile_id))
        self.state = state
        self.plan = []
        self.status.set("已撤销最后一次识别，正在重新规划…")
        self.replan()
        self.render()

    def _next_work(self):
        self.cancel_event.set()
        self.cancel_event = threading.Event()
        self.work_epoch += 1
        return self.work_epoch, self.cancel_event

    def _current_work(self, epoch, cancel_event):
        return self.work_epoch == epoch and not cancel_event.is_set()

    def _search_status(self, epoch, cancel_event, message):
        self.root.after(0, lambda: self.status.set(message)
                        if self._current_work(epoch, cancel_event) else None)

    def replan(self):
        if not self.board:
            if self.capture_starting:
                self.status.set("正在启动监听，请先进入新关卡。")
                return
            if self.preparing:
                return
            seed_path = CAPTURES / "recovered_seed.json"
            if (self.capture_proc is not None and
                    (not seed_path.is_file() or
                     seed_path.stat().st_mtime_ns <= self.capture_stamp)):
                self.status.set("正在等待本局种子，请先进入关卡。")
                return
            if not seed_path.is_file():
                self.status.set("没有本局种子。请点“监听下一局”，再进入关卡。")
                return
            self.preparing = True
            epoch, cancel_event = self._next_work()
            self.status.set("正在从本机抓包记录恢复本局地图并求解…")
            threading.Thread(target=self._prepare_new_board,
                             args=(epoch, cancel_event, self.special_mode.get()),
                             daemon=True).start()
            return
        if self.solving:
            return
        if self.special_cards:
            self._replan_special()
            return
        if self.auto_click.get():
            self.auto_click.set(False)
        self.solving = True
        epoch, cancel_event = self._next_work()
        board, state = self.board, self.state
        engine = self.tool_engine
        self.search_attempt += 1
        attempt = self.search_attempt
        self.status.set("正在计算当前局面的路线…")
        self.root.after(SEARCH_TIMEOUT_SECONDS * 1000, lambda: self.status.set(
            "已搜索 30 秒，仍在继续找完整路线；结束后可考虑重新开局。")
            if (self.solving and self.search_attempt == attempt and
                self._current_work(epoch, cancel_event)) else None)

        def work():
            candidate = ()
            try:
                if engine:
                    search_state = engine.search_start(state)
                    result = plan_route(
                        board, seconds=SEARCH_BUDGET_SECONDS,
                        initial_state=search_state,
                        seed_offset=attempt,
                        candidate_path=self.search_candidate,
                        cancel_event=cancel_event,
                        on_progress=lambda message: self._search_status(
                            epoch, cancel_event, message))
                    if not self._current_work(epoch, cancel_event):
                        return
                    ids = [board.tiles[item].id if isinstance(item, int) else item
                           for item in result["path"]]
                    check = state
                    if result["status"] == "solved":
                        for action in ids:
                            check = engine.apply(check, action)
                    verified = engine.won(check)
                    if result["status"] != "solved":
                        candidate = result["path"]
                else:
                    result = depth_search(board, seconds=SEARCH_TIMEOUT_SECONDS,
                                          seed=attempt,
                                          initial_state=state, max_branches=6,
                                          max_states=3_000_000,
                                          cancel_event=cancel_event)
                    if not self._current_work(epoch, cancel_event):
                        return
                    ids = [board.tiles[index].id for index in result["path"]]
                    verified = (result["status"] == "solved" and
                                replay(board, result["path"], state))
                if result["status"] != "solved" or not verified:
                    raise ValueError("本次搜索未找到完整路线。可再试重新规划或重新开局；这不代表无解")
                self.root.after(0, lambda: self._finish_replan(
                    epoch, cancel_event, board, state, ids, None))
            except Exception as exc:
                if self._current_work(epoch, cancel_event):
                    self.root.after(0, lambda error=str(exc), path=candidate:
                                    self._finish_replan(epoch, cancel_event,
                                                        board, state, None, error, path))

        threading.Thread(target=work, daemon=True).start()

    def _replan_special(self):
        self.solving = True
        epoch, cancel_event = self._next_work()
        board, state = self.board, self.state
        self.search_attempt += 1
        attempt = self.search_attempt
        self.status.set("正在按变色后的牌面寻找下一组三消…")

        def work():
            try:
                segment = plan_next_crush(board, state, seed=attempt - 1,
                                          cancel_event=cancel_event)
                if self._current_work(epoch, cancel_event):
                    self.root.after(0, lambda: finish(segment, None))
            except Exception as exc:
                if self._current_work(epoch, cancel_event):
                    self.root.after(0, lambda error=str(exc): finish([], error))

        def finish(segment, error):
            if not self._current_work(epoch, cancel_event):
                return
            self.solving = False
            if self.board is not board or self.state != state:
                self.replan()
                return
            self.plan = segment
            self.search_failed = not bool(segment)
            if segment and segment[0] in ("MOVE_OUT", "REVIVE") and self.auto_click.get():
                self._pause_auto_for_tool(segment[0])
            else:
                self.status.set(f"特殊关卡规划失败：{error}" if error else
                                ("已根据当前变色牌规划到下一次三消；三消后自动重算。"
                                 if segment else "暂未找到安全的下一组三消。可使用移出道具或重新规划。"))
            self.render()

        threading.Thread(target=work, daemon=True).start()

    def _finish_replan(self, epoch, cancel_event, board, state, ids, error,
                       candidate=()):
        if not self._current_work(epoch, cancel_event):
            return
        self.solving = False
        if self.board is not board or self.state != state:
            self.replan()
            return
        if error:
            self.search_failed = True
            if (not state.removed and not state.tray and candidate and
                    sum(isinstance(action, int) for action in candidate) >
                    sum(isinstance(action, int) for action in self.search_candidate)):
                self.search_candidate = tuple(candidate)
            if self.tool_engine and not state.removed and not state.tray:
                save_checkpoint(SEARCH_CHECKPOINT, board,
                                self.search_attempt + 1, self.search_candidate)
            self.status.set(f"重新规划失败：{error}")
        else:
            self.search_failed = False
            self.search_candidate = ()
            self.plan = ids
            self.status.set("路线已重新计算并验证。")
            if self.tool_engine:
                (CAPTURES / "solution_current.json").write_text(
                    json.dumps({"status": "solved", "verified": True,
                                "actions": self.clicks + ids}, ensure_ascii=False, indent=2),
                    encoding="utf-8")
        self.render()

    def start_capture(self):
        if (self.capture_proc is not None and self.board is None and
                not self.preparing and not self.solving):
            self.status.set("已经在监听下一局。")
            return
        if self.capture_starting:
            self.status.set("正在启动监听，请稍候。")
            return
        if not (SCRIPTS / "start_capture.ps1").exists():
            self.status.set("找不到抓取脚本。")
            return
        self._next_work()
        self.preparing = False
        self.solving = False
        self.prepare_attempt += 1
        self.auto_click.set(False)
        seed_path = CAPTURES / "recovered_seed.json"
        self.capture_stamp = seed_path.stat().st_mtime_ns if seed_path.exists() else 0
        self.board = None
        self.tool_engine = None
        self.special_cards = None
        self.special_history = []
        self.map_file = None
        self.state = None
        self.plan = []
        self.clicks = []
        self.pending = None
        self.auto_pending = False
        self.aux_centers = None
        self.aux_rect = None
        self.stage2_active = False
        self.stage2_hits = 0
        self.search_failed = False
        self.search_candidate = ()
        self.overlay.withdraw()
        self.target.set("等待第二关")
        self.progress.set("")
        self.tray.set("")
        self.status.set("正在准备抓取。启动后请在微信小程序中重新进入关卡。")

        if self.capture_proc is not None and self.capture_proc.poll() is None:
            self.status.set("已中断旧关卡搜索，继续监听下一局。请重新进入关卡。")
            return
        self.capture_proc = None
        self.capture_starting = True
        epoch = self.work_epoch

        def work():
            try:
                stopping = self.capture_stop_thread
                if stopping is not None and stopping.is_alive():
                    stopping.join(timeout=35)
                subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                                "-File", str(SCRIPTS / "install_capture_cert.ps1")],
                               check=True, capture_output=True, text=True, timeout=45)
                flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                proc = subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy",
                                         "Bypass", "-File", str(SCRIPTS / "start_capture.ps1"),
                                         "-SeedProbe", "-DurationSeconds", "600"],
                                        cwd=ROOT, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.PIPE, creationflags=flags)
                self.root.after(0, lambda: self._capture_started(proc, epoch))
            except Exception as exc:
                self.root.after(0, lambda error=str(exc): self._capture_failed(
                    epoch, error))

        threading.Thread(target=work, daemon=True).start()

    def _capture_failed(self, epoch, error):
        if epoch == self.work_epoch:
            self.capture_starting = False
            self.status.set(f"抓取启动失败：{error}")

    def _capture_started(self, proc, epoch):
        if epoch != self.work_epoch:
            self.capture_starting = False
            proc.terminate()
            return
        self.capture_starting = False
        self.capture_proc = proc
        self.status.set("正在监听新开局。现在打开小程序并进入关卡；识别到地图后会自动求解。")

    def _poll_capture(self):
        seed_path = CAPTURES / "recovered_seed.json"
        if (not self.preparing and seed_path.exists() and
                seed_path.stat().st_mtime_ns > self.capture_stamp):
            self.capture_stamp = seed_path.stat().st_mtime_ns
            self.preparing = True
            epoch, cancel_event = self._next_work()
            self.status.set("已获取本局种子，正在查找或下载第二关地图…")
            threading.Thread(target=self._prepare_new_board,
                             args=(epoch, cancel_event, self.special_mode.get()),
                             daemon=True).start()
        elif self.capture_proc.poll() is not None and not self.preparing:
            self.capture_proc = None
            self.status.set("抓取已结束。如果尚未拿到种子，请检查代理和证书。")

    def stop_capture(self):
        proc = self.capture_proc
        self.capture_proc = None
        if proc is None:
            return
        pid_file = CAPTURES / "mitmdump.pid"

        def work():
            if pid_file.exists():
                try:
                    pid = int(pid_file.read_text().strip())
                    subprocess.run(["powershell", "-NoProfile", "-Command",
                                    f"Stop-Process -Id {pid} -ErrorAction SilentlyContinue"],
                                   capture_output=True, timeout=15)
                except (ValueError, OSError, subprocess.TimeoutExpired):
                    pass
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.terminate()
            subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                            "-File", str(SCRIPTS / "remove_capture_cert.ps1")],
                           capture_output=True, timeout=15)

        thread = threading.Thread(target=work, daemon=True)
        self.capture_stop_thread = thread
        thread.start()

    def _prepare_new_board(self, epoch, cancel_event, special_enabled=False):
        current = lambda: self._current_work(epoch, cancel_event)
        typed_temporary = CAPTURES / f"typed_current_{epoch}.tmp"
        try:
            seed = json.loads((CAPTURES / "recovered_seed.json").read_text(encoding="utf-8"))
            template = acquire_second_stage_template(
                seed, PACKAGE_ROOT / "templates", CAPTURES,
                wait_seconds=8 if self.capture_proc is not None else 0)
            if not current():
                return
            self.root.after(0, lambda: self.stop_capture() if current() else None)
            self._search_status(epoch, cancel_event,
                                "地图已准备好，正在还原牌面并求解…")
            typed = CAPTURES / "typed_current.json"
            subprocess.run(["node", str(SCRIPTS / "restore_types.js"),
                            str(template), str(CAPTURES / "recovered_seed.json"),
                            str(typed_temporary)],
                           check=True, capture_output=True, text=True, timeout=30)
            if not current():
                return
            typed_temporary.replace(typed)
            board = Board.from_json(typed)
            if special_enabled and any(tile.meta == 2 for tile in board.tiles):
                self.root.after(0, lambda: self.load_special_board(typed)
                                if current() else None)
                return
            engine = ToolEngine(board)
            previous_attempts, previous_path = load_checkpoint(
                SEARCH_CHECKPOINT, board)
            if not current():
                return
            self.search_attempt = previous_attempts
            self._search_status(epoch, cancel_event, "正在搜索完整路线…")
            self.root.after(SEARCH_TIMEOUT_SECONDS * 1000, lambda: self.status.set(
                "已搜索 30 秒，仍在继续找完整路线；结束后可考虑重新开局。")
                if self.preparing and current() else None)
            planned = plan_route(
                board, seconds=SEARCH_BUDGET_SECONDS,
                seed_offset=previous_attempts,
                candidate_path=previous_path,
                cancel_event=cancel_event,
                on_progress=lambda message: self._search_status(
                    epoch, cancel_event, message))
            if not current():
                return
            actions = None
            if planned["status"] == "solved":
                actions = [board.tiles[item].id if isinstance(item, int)
                           else item for item in planned["path"]]
            if actions is not None:
                check = engine.initial()
                for action in actions:
                    check = engine.apply(check, action)
                if not current():
                    return
                if engine.won(check):
                    (CAPTURES / "solution_current.json").write_text(json.dumps({
                        "status": "solved", "verified": True, "actions": actions,
                        "map_file": str(typed)}, ensure_ascii=False, indent=2), encoding="utf-8")
                    self.root.after(0, lambda route=actions: self.load_tool_board(
                        typed, route) if current() else None)
                    return
            self.root.after(0, lambda path=planned["path"],
                            attempts=previous_attempts:
                            self._load_unsolved(typed, path, attempts)
                            if current() else None)
        except Exception as exc:
            if current():
                self.root.after(0, lambda: self.stop_capture() if current() else None)
                self._search_status(epoch, cancel_event,
                    f"新关卡准备失败：{exc}。可点“重新规划”重试本局。")
        finally:
            if typed_temporary.exists():
                typed_temporary.unlink()
            if current():
                self.root.after(0, lambda: setattr(self, "preparing", False)
                                if current() else None)

    def _load_unsolved(self, path, candidate=(), attempts=0):
        self.board = Board.from_json(path)
        self.tool_engine = ToolEngine(self.board)
        self.map_file = path
        self.state = self.tool_engine.initial()
        self.clicks = []
        self.plan = []
        self.pending = None
        self.aux_centers = None
        self.aux_rect = None
        self.stage2_active = False
        self.stage2_hits = 0
        self.search_failed = True
        self.search_candidate = tuple(candidate)
        self.search_attempt = attempts
        save_checkpoint(SEARCH_CHECKPOINT, self.board,
                        attempts + 1, self.search_candidate)
        self.status.set("本次搜索未找到完整路线。这把可能较难；可重新规划或重新开局。这不代表无解。")
        self.render()

    def _close(self):
        self.cancel_event.set()
        self.work_epoch += 1
        self.stop_capture()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description="Sheep Planet manual-play desktop assistant")
    parser.add_argument("--map", dest="map_file", type=Path,
                        default=CAPTURES / "typed_map_2.json")
    parser.add_argument("--solution", type=Path, default=CAPTURES / "solution.json")
    parser.add_argument("--tool-solution", type=Path,
                        help="verified route including Move Out and revive actions")
    parser.add_argument("--resume", type=int, default=None,
                        help="number of already clicked cards in the saved solution")
    args = parser.parse_args()
    root = tk.Tk()
    Assistant(root, args)
    root.mainloop()


if __name__ == "__main__":
    main()
