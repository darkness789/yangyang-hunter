import unittest

from yangyang_hunter.board_model import Board, Tile
from yangyang_hunter.solve_with_tools import (
    ToolEngine, diverse_beam_search, replay_with_tools,
)


class DiverseSearchTests(unittest.TestCase):
    def test_route_is_legal_and_clears_board(self):
        tiles = [Tile(str(i), 1 + i // 3, i * 8, 0, 1, 1)
                 for i in range(9)]
        board = Board(tiles)
        result = diverse_beam_search(board, seconds=3, width=40)
        self.assertEqual(result["status"], "solved")
        self.assertTrue(replay_with_tools(board, result["path"]))

    def test_replans_from_a_partial_tool_state(self):
        tiles = [Tile(str(i), 1 + i // 3, i * 8, 0, 1, 1)
                 for i in range(9)]
        board = Board(tiles)
        engine = ToolEngine(board)
        state = engine.apply(engine.initial(), "0")
        result = diverse_beam_search(board, seconds=3, width=40,
                                     initial_state=engine.search_start(state))
        self.assertEqual(result["status"], "solved")
        for action in result["path"]:
            state = engine.apply(state, board.tiles[action].id
                                 if isinstance(action, int) else action)
        self.assertTrue(engine.won(state))

    def test_forced_order_needs_both_tools_and_aux_cards(self):
        # One visible card at a time: the seventh click would fill the tray.
        board = Board([Tile(str(i), i % 4 + 1, 0, 0, 12 - i, 1)
                       for i in range(12)])
        result = diverse_beam_search(board, seconds=3, width=200)
        self.assertEqual(result["status"], "solved")
        self.assertIn("MOVE_OUT", result["path"])
        self.assertIn("REVIVE", result["path"])
        self.assertTrue(any(isinstance(action, tuple) for action in result["path"]))
        self.assertTrue(replay_with_tools(board, result["path"]))

        engine = ToolEngine(board)
        state = engine.initial()
        for action in ("0", "1", "2", "3", "4", "MOVE_OUT"):
            state = engine.apply(state, action)
        remaining = diverse_beam_search(
            board, seconds=3, width=200,
            initial_state=engine.search_start(state), allow_remove=False)
        self.assertEqual(remaining["status"], "solved")
        for action in remaining["path"]:
            state = engine.apply(state, board.tiles[action].id
                                 if isinstance(action, int) else action)
        self.assertTrue(engine.won(state))


if __name__ == "__main__":
    unittest.main()
