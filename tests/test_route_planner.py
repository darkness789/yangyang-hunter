import unittest
from pathlib import Path
from unittest.mock import patch

from yangyang_hunter.board_model import Board, Tile
from yangyang_hunter import route_planner
from yangyang_hunter.route_planner import plan_route
from yangyang_hunter.solve_with_tools import ToolEngine, replay_with_tools


class RoutePlannerTests(unittest.TestCase):
    def test_retry_changes_search_order(self):
        board = Board([Tile(str(i), 1, i * 8, 0, 1, 1)
                       for i in range(3)])
        seeds = []

        def fake_depth(_board, **kwargs):
            seeds.append(kwargs["seed"])
            return {"status": "solved", "path": (0, 1, 2), "depth": 3}

        with patch.object(route_planner, "depth_search", side_effect=fake_depth):
            plan_route(board, seconds=2, seed_offset=0)
            plan_route(board, seconds=2, seed_offset=1)
        self.assertEqual(seeds, [0, 1])

    def test_captured_difficult_board_has_verified_full_route(self):
        board = Board.from_json(Path(__file__).parent / "fixtures" /
                                "difficult_216.json")
        result = plan_route(board, seconds=45)
        self.assertEqual(result["status"], "solved")
        self.assertEqual(result["depth"], 216)
        self.assertIn("MOVE_OUT", result["path"])
        self.assertIn("REVIVE", result["path"])
        self.assertTrue(replay_with_tools(board, result["path"]))

    def test_complete_route_with_both_tools_from_opening(self):
        board = Board([Tile(str(i), i % 4 + 1, 0, 0, 12 - i, 1)
                       for i in range(12)])
        result = plan_route(board, seconds=3)
        self.assertEqual(result["status"], "solved")
        self.assertIn("MOVE_OUT", result["path"])
        self.assertIn("REVIVE", result["path"])
        self.assertTrue(replay_with_tools(board, result["path"]))

    def test_retry_repairs_previous_partial_route(self):
        board = Board([Tile(str(i), i % 4 + 1, 0, 0, 12 - i, 1)
                       for i in range(12)])
        partial = tuple(range(6))
        with patch.object(route_planner, "depth_search", return_value={
                "status": "not_found", "path": (), "depth": 0}):
            result = plan_route(board, seconds=3, seed_offset=1,
                                candidate_path=partial)
        self.assertEqual(result["status"], "solved")
        self.assertEqual(result["path"][:6], partial)
        self.assertTrue(replay_with_tools(board, result["path"]))

    def test_route_from_current_tool_state(self):
        board = Board([Tile(str(i), i % 4 + 1, 0, 0, 12 - i, 1)
                       for i in range(12)])
        engine = ToolEngine(board)
        state = engine.initial()
        for action in ("0", "1", "2", "3", "4", "MOVE_OUT"):
            state = engine.apply(state, action)
        result = plan_route(board, seconds=3,
                            initial_state=engine.search_start(state))
        self.assertEqual(result["status"], "solved")
        for action in result["path"]:
            state = engine.apply(state, board.tiles[action].id
                                 if isinstance(action, int) else action)
        self.assertTrue(engine.won(state))


if __name__ == "__main__":
    unittest.main()
