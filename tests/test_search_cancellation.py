import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from yangyang_hunter.board_model import Board, Tile
from yangyang_hunter import desktop_assistant as ui
from yangyang_hunter.route_planner import plan_route


class Value:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class SearchCancellationTests(unittest.TestCase):
    def test_cancelled_plan_stops_without_searching(self):
        board = Board([Tile(str(i), 1, i * 8, 0, 1, 1)
                       for i in range(3)])
        stop = threading.Event()
        stop.set()
        with patch("yangyang_hunter.route_planner.depth_search") as search:
            result = plan_route(board, seconds=120, cancel_event=stop)
        self.assertEqual(result["status"], "cancelled")
        search.assert_not_called()

    def test_listen_cancels_old_search_and_ignores_late_result(self):
        assistant = ui.Assistant.__new__(ui.Assistant)
        assistant.cancel_event = threading.Event()
        old_cancel = assistant.cancel_event
        assistant.work_epoch = 0
        assistant.prepare_attempt = 1
        assistant.preparing = True
        assistant.solving = True
        assistant.capture_starting = False
        assistant.capture_proc = None
        assistant.board = object()
        assistant.tool_engine = object()
        assistant.search_failed = True
        assistant.search_candidate = (1,)
        assistant.status = Value()
        assistant.target = Value()
        assistant.progress = Value()
        assistant.tray = Value()
        assistant.auto_click = Value(True)
        assistant.overlay = type("Overlay", (), {"withdraw": lambda self: None})()

        class FakeThread:
            def __init__(self, target, daemon):
                self.target = target

            def start(self):
                pass

        with tempfile.TemporaryDirectory() as folder, \
                patch.object(ui, "CAPTURES", Path(folder)), \
                patch.object(ui.threading, "Thread", FakeThread):
            assistant.start_capture()

        self.assertTrue(old_cancel.is_set())
        self.assertEqual(assistant.work_epoch, 1)
        self.assertFalse(assistant.preparing)
        self.assertFalse(assistant.solving)
        self.assertFalse(assistant.auto_click.get())
        self.assertIsNone(assistant.board)
        self.assertEqual(assistant.target.get(), "等待第二关")
        status = assistant.status.get()
        assistant._finish_replan(0, old_cancel, object(), None, ["old"], None)
        self.assertEqual(assistant.status.get(), status)
        self.assertIsNone(assistant.board)


if __name__ == "__main__":
    unittest.main()
