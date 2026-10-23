import unittest

from yangyang_hunter.board_model import Board, Tile
from yangyang_hunter.solve_with_tools import ToolEngine, ToolState
from yangyang_hunter.special_planner import (_reserve_mask, _segment,
                                            plan_next_crush)


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

    def test_move_out_is_not_mistaken_for_a_triple(self):
        board = Board([Tile(str(i), i + 1 if i < 5 else 6,
                            i * 16, 0, 1, 1) for i in range(8)])
        path = tuple(range(5)) + ("MOVE_OUT", 5, 6, 7)
        self.assertEqual(_segment(board, ToolEngine(board).initial(), path),
                         [str(i) for i in range(5)] +
                         ["MOVE_OUT", "5", "6", "7"])

    def test_does_not_spend_move_out_before_a_verified_triple(self):
        board = Board([Tile(str(i), i + 1, i * 16, 0, 1, 1)
                       for i in range(5)])
        self.assertEqual(plan_next_crush(board, ToolEngine(board).initial(),
                                         seconds=.1), [])

    def test_revive_requires_a_verified_followup_triple(self):
        board = Board([Tile(str(i), i + 1, i * 16, 0, 1, 1)
                       for i in range(8)])
        state = ToolState((1 << 6) - 1, tuple(range(6)),
                          ((), (), ()), used_remove=True)
        self.assertEqual(plan_next_crush(board, state, seconds=.1), [])
        full = ToolState((1 << 7) - 1, tuple(range(7)),
                         ((), (), ()), used_remove=True)
        self.assertEqual(plan_next_crush(board, full, seconds=.1), ["REVIVE"])

    def test_plans_into_revive_when_it_unlocks_a_triple(self):
        tiles = [Tile(str(i), i + 1, i * 16, 0, 1, 1)
                 for i in range(6)]
        tiles += [Tile(f"match-{i}", 7, 100 + i * 16, 0, 1, 1)
                  for i in range(3)]
        board = Board(tiles)
        state = ToolState((1 << 6) - 1, tuple(range(6)),
                          ((), (), ()), used_remove=True)
        path = plan_next_crush(board, state, seconds=.5)
        self.assertIn("REVIVE", path)
        self.assertNotIn("MOVE_OUT", path)
        for action in path:
            state = ToolEngine(board).apply(state, action)
        self.assertTrue(state.used_revive)
        self.assertEqual(len(state.tray), 3)

    def test_move_out_must_enable_a_triple_without_revive(self):
        tiles = [Tile(str(i), i + 1, i * 16, 0, 1, 1)
                 for i in range(6)]
        tiles += [Tile("match-a", 1, 100, 0, 1, 1),
                  Tile("match-b", 1, 116, 0, 1, 1)]
        board = Board(tiles)
        state = ToolState((1 << 6) - 1, tuple(range(6)),
                          ((), (), ()))
        path = plan_next_crush(board, state, seconds=.2)
        self.assertEqual(path[0], "MOVE_OUT")
        self.assertNotIn("REVIVE", path)
        for action in path:
            state = ToolEngine(board).apply(state, action)
        self.assertEqual(len(state.tray), 3)

    def test_keeps_shallow_side_pile_as_reserve(self):
        tiles = [Tile(f"thin-{i}", 2, 100 + i * 16, 0, 4, 1)
                 for i in range(9)]
        tiles += [Tile(f"center-{i}", 1 if i < 3 else 10 + i,
                       i * 16, 100, 20, 1) for i in range(11)]
        board = Board(tiles)
        self.assertEqual(bin(_reserve_mask(board)).count("1"), 9)
        path = plan_next_crush(board, ToolEngine(board).initial(),
                               seconds=.5)
        self.assertEqual(set(path),
                         {"center-0", "center-1", "center-2"})


if __name__ == "__main__":
    unittest.main()
