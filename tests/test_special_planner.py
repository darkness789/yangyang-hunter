import unittest

from yangyang_hunter.board_model import Board, Tile
from yangyang_hunter.solve_with_tools import ToolEngine
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


if __name__ == "__main__":
    unittest.main()
