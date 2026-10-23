import unittest

from yangyang_hunter.board_model import Board, Tile
from yangyang_hunter.solve_with_tools import ToolEngine, ToolState
from yangyang_hunter.special_planner import plan_next_crush


class SpecialPlannerTests(unittest.TestCase):
    def test_clears_deep_stack_before_matching_thin_reserve(self):
        tiles = []
        for number, x in enumerate((0, 16, 32)):
            tiles.append(Tile(f"deep-{number}", 1, x, 0, 3, 1))
            tiles.append(Tile(f"buried-{number}", 3, x, 0, 1, 1))
            tiles.append(Tile(f"thin-{number}", 2, x + 100, 0, 1, 1))
        board = Board(tiles)
        path = plan_next_crush(board, ToolEngine(board).initial(), seconds=.1)
        self.assertEqual(set(path), {"deep-0", "deep-1", "deep-2"})

    def test_does_not_add_singleton_to_crowded_tray_for_deeper_route(self):
        tiles = [Tile(f"held-{i}", i + 1, 200 + i * 16, 0, 1, 1)
                 for i in range(3)]
        tiles.append(Tile("filler", 9, 0, 0, 20, 1))
        tiles.extend(Tile(f"covered-{i}", 8, 0, 0, 1, 1)
                     for i in range(25))
        tiles.extend(Tile(f"safe-{i}", 7, 100 + i * 16, 0, 1, 1)
                     for i in range(3))
        board = Board(tiles)
        state = ToolState(0b111, (0, 1, 2), ((), (), ()))
        path = plan_next_crush(board, state, seconds=.1)
        self.assertEqual(set(path), {"safe-0", "safe-1", "safe-2"})


if __name__ == "__main__":
    unittest.main()
