import unittest
from unittest.mock import patch
from dataclasses import replace
from PIL import Image

from yangyang_hunter.board_model import Board, Tile
from yangyang_hunter.board_geometry import BoardGeometry
from yangyang_hunter.solve_with_tools import ToolEngine
from yangyang_hunter.special_rules import SpecialCards
from yangyang_hunter import desktop_assistant as ui


class Value:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeUser32:
    def __init__(self):
        self.events = []

    def FindWindowW(self, *_):
        return 1

    def GetForegroundWindow(self):
        return 1

    def GetAsyncKeyState(self, *_):
        return 0

    def SetCursorPos(self, x, y):
        self.events.append(("move", x, y))
        return True

    def mouse_event(self, flag, *_):
        self.events.append(("button", flag))

    def GetParent(self, *_):
        return 2

    def SetForegroundWindow(self, *_):
        return True


class AutoClickTests(unittest.TestCase):
    @staticmethod
    def tray_image(count):
        image = Image.new("RGB", (490, 85), (99, 167, 31))
        for slot in range(count):
            center = 25 + 72 * slot
            for x in range(center - 12, center + 13):
                for y in range(56, 70):
                    image.putpixel((x, y), (246, 255, 205))
        return image

    def assistant(self, action="0"):
        assistant = ui.Assistant.__new__(ui.Assistant)
        assistant.board = Board([Tile("0", 1, 0, 0, 1, 1)])
        assistant.board_geometry = BoardGeometry(110, 6.3, 300, 6.25, 1)
        assistant.tool_engine = ToolEngine(assistant.board)
        assistant.state = assistant.tool_engine.initial()
        assistant.plan = [action]
        assistant.auto_click = Value(True)
        assistant.status = Value("")
        assistant.stage2_active = True
        assistant.pending = None
        assistant.solving = False
        assistant.preparing = False
        assistant.auto_next_at = 0
        assistant.auto_pending = False
        assistant._candidate_click = lambda x, y, rect: setattr(
            assistant, "pending", (action, x, y, rect, None, self.tray_image(0)))
        return assistant

    def test_tray_reader_counts_cards_and_rejects_gaps(self):
        for count in (0, 1, 4, 7):
            with self.subTest(count=count):
                self.assertEqual(ui.tray_count(self.tray_image(count)), count)
        gap = self.tray_image(0)
        for x in range(92, 113):
            gap.putpixel((x, 62), (246, 255, 205))
        self.assertIsNone(ui.tray_count(gap))

    def test_clicks_a_normal_card_once_and_waits_for_confirmation(self):
        assistant = self.assistant()
        fake = FakeUser32()
        with patch.object(ui, "user32", fake), \
                patch.object(ui, "game_rect", return_value=(0, 0, 573, 1067)), \
                patch.object(ui, "cursor", return_value=(5, 6)):
            assistant._poll_auto()
            assistant._poll_auto()
        self.assertTrue(assistant.auto_pending)
        self.assertEqual([event for event in fake.events if event[0] == "button"],
                         [("button", 0x0002), ("button", 0x0004)])

    def test_auto_clicks_an_aux_card_without_animation_detection(self):
        assistant = self.assistant(("AUX", 0))
        assistant.board = Board([Tile(str(i), 1, i * 8, 0, 1, 1)
                                 for i in range(3)])
        assistant.tool_engine = ToolEngine(assistant.board)
        assistant.state = assistant.tool_engine.apply(
            assistant.tool_engine.apply(assistant.tool_engine.initial(), "0"),
            "MOVE_OUT")
        assistant.aux_centers = None
        assistant.aux_rect = None
        fake = FakeUser32()
        with patch.object(ui, "user32", fake), \
                patch.object(ui, "game_rect", return_value=(0, 0, 573, 1067)), \
                patch.object(ui, "cursor", return_value=(5, 6)):
            assistant._poll_auto()
        self.assertTrue(assistant.auto_pending)
        self.assertIn(("move", 227, 777), fake.events)

    def test_auto_stops_before_clicking_if_tray_is_out_of_sync(self):
        assistant = self.assistant(("AUX", 1))
        assistant.board = Board([Tile(str(i), 1, i * 8, 0, 1, 1)
                                 for i in range(3)])
        assistant.tool_engine = ToolEngine(assistant.board)
        state = assistant.tool_engine.initial()
        for action in ("0", "1", "MOVE_OUT", ("AUX", 0)):
            state = assistant.tool_engine.apply(state, action)
        assistant.state = state
        # The pending screenshot says zero cards while the model says one.
        assistant._candidate_click = lambda x, y, rect: setattr(
            assistant, "pending", (("AUX", 1), x, y, rect, None,
                                  self.tray_image(0)))
        assistant.aux_centers = None
        assistant.aux_rect = None
        fake = FakeUser32()
        with patch.object(ui, "user32", fake), \
                patch.object(ui, "game_rect", return_value=(0, 0, 573, 1067)):
            assistant._poll_auto()
        self.assertFalse(assistant.auto_click.get())
        self.assertFalse(any(event[0] == "button" for event in fake.events))

    def test_tool_action_waits_for_player(self):
        for action in ("MOVE_OUT", "REVIVE"):
            with self.subTest(action=action):
                assistant = self.assistant(action)
                fake = FakeUser32()
                with patch.object(ui, "user32", fake):
                    assistant._poll_auto()
                self.assertEqual(fake.events, [])
                self.assertFalse(assistant.auto_click.get())
                self.assertIn("自行重新开启", assistant.status.get())

    def test_auto_stays_off_after_manually_using_tool(self):
        assistant = self.assistant()
        assistant.board = Board([Tile(str(i), 1, i * 8, 0, 1, 1)
                                 for i in range(3)])
        assistant.tool_engine = ToolEngine(assistant.board)
        assistant.state = assistant.tool_engine.initial()
        assistant.plan = ["0", "MOVE_OUT", "1"]
        assistant.clicks = []
        assistant.render = lambda: None
        assistant.auto_track = Value(True)

        assistant._accept("0")
        self.assertFalse(assistant.auto_click.get())
        self.assertEqual(assistant.plan[0], "MOVE_OUT")
        assistant._accept("MOVE_OUT")
        self.assertFalse(assistant.auto_click.get())
        self.assertEqual(assistant.plan[0], "1")

        assistant.auto_click.set(True)
        with patch.object(ui, "user32", FakeUser32()):
            assistant._auto_mode_changed()
        self.assertTrue(assistant.auto_click.get())

    def test_special_triple_keeps_auto_enabled_during_replan(self):
        assistant = self.assistant()
        assistant.board = Board([
            Tile(str(i), 1 if i < 3 else i, i * 8, 0, 1, 1, 2)
            for i in range(5)
        ])
        assistant.tool_engine = ToolEngine(assistant.board)
        assistant.special_cards = SpecialCards(
            assistant.board, [1, 2, 3, 4], [str(i) for i in range(5)])
        assistant.special_history = []
        assistant.state = assistant.tool_engine.initial()
        assistant.plan = ["0", "1", "2"]
        assistant.clicks = []
        assistant.render = lambda: None
        replans = []
        assistant.replan = lambda: replans.append(True)

        for tile_id in ("0", "1", "2"):
            assistant._accept(tile_id)

        self.assertTrue(assistant.auto_click.get())
        self.assertEqual(replans, [True])
        self.assertEqual(assistant.plan, [])
        self.assertEqual(len(assistant.state.tray), 0)
        self.assertGreater(assistant.auto_next_at, 0)

    def test_cannot_enable_auto_while_tool_is_next(self):
        assistant = self.assistant("MOVE_OUT")
        assistant.auto_track = Value(True)
        assistant._auto_mode_changed()
        self.assertFalse(assistant.auto_click.get())
        self.assertIn("移出", assistant.status.get())

    def test_auto_click_stops_when_game_does_not_change(self):
        assistant = self.assistant()
        assistant.auto_pending = True
        assistant.pending = ("0", 100, 100, (0, 0, 573, 1067), None, None)
        fake_image = type("Image", (), {"convert": lambda self, _: self})()
        with patch.object(ui, "game_rect", return_value=(0, 0, 573, 1067)), \
                patch.object(ui, "crop_at", return_value=fake_image), \
                patch.object(ui.ImageGrab, "grab", return_value=fake_image), \
                patch.object(ui, "change_score", return_value=0):
            assistant._verify_click()
        self.assertFalse(assistant.auto_click.get())
        self.assertIn("已暂停", assistant.status.get())

    def test_tray_animation_alone_does_not_confirm_auto_click(self):
        assistant = self.assistant()
        assistant.auto_pending = True
        assistant.verify_retry = 2
        before = Image.new("RGB", (40, 40), (246, 255, 205))
        assistant.pending = ("0", 100, 100, (0, 0, 573, 1067), before,
                             self.tray_image(0))
        assistant.clicks = []
        with patch.object(ui, "game_rect", return_value=(0, 0, 573, 1067)), \
                patch.object(ui, "crop_at", return_value=before), \
                patch.object(ui.ImageGrab, "grab", return_value=self.tray_image(1)):
            assistant._verify_click()
        self.assertFalse(assistant.auto_click.get())
        self.assertEqual(assistant.state.removed, 0)

    def test_auto_never_takes_a_seventh_card_after_revive(self):
        assistant = self.assistant("6")
        assistant.board = Board([Tile(str(i), i + 1, i * 8, 0, 1, 1)
                                 for i in range(7)])
        assistant.tool_engine = ToolEngine(assistant.board)
        state = replace(assistant.tool_engine.initial(), used_revive=True)
        for i in range(6):
            state = assistant.tool_engine.apply(state, str(i))
        assistant.state = state
        fake = FakeUser32()
        with patch.object(ui, "user32", fake):
            assistant._poll_auto()
        self.assertFalse(assistant.auto_click.get())
        self.assertFalse(any(event[0] == "button" for event in fake.events))

    def test_stage_detection_keeps_failed_search_hint(self):
        assistant = self.assistant()
        assistant.plan = []
        assistant.stage2_active = False
        assistant.stage2_hits = 1
        assistant.last_stage_check = 0
        assistant.status.set("30 秒内未找到完整路线，建议重新开一把")
        assistant.root = type("Root", (), {"winfo_id": lambda self: 3})()
        assistant.render = lambda: None
        fake = FakeUser32()
        with patch.object(ui, "user32", fake), \
                patch.object(ui, "game_rect", return_value=(0, 0, 573, 1067)), \
                patch.object(ui, "current_stage_is_second", return_value=True):
            assistant._poll_stage()
        self.assertTrue(assistant.stage2_active)
        self.assertIn("重新开一把", assistant.status.get())


if __name__ == "__main__":
    unittest.main()
