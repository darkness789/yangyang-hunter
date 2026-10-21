import unittest
from unittest.mock import patch

from yangyang_hunter.board_model import Board, Tile
from yangyang_hunter.solve_with_tools import ToolEngine
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
    def assistant(self, action="0"):
        assistant = ui.Assistant.__new__(ui.Assistant)
        assistant.board = Board([Tile("0", 1, 0, 0, 1, 1)])
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
            assistant, "pending", (action, x, y, rect, None, None))
        return assistant

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
