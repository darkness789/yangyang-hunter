import unittest

from yangyang_hunter.board_model import Board, IllegalMove, State, Tile


def tile(number, kind, x=0, y=0, layer=1):
    return Tile(str(number), kind, x, y, layer, 1)


class BoardModelTests(unittest.TestCase):
    def test_upper_tile_must_be_removed_first(self):
        board = Board([tile(1, 1), tile(2, 1, layer=2)])
        state = board.initial()
        self.assertEqual([board.tiles[i].id for i in board.visible_indices(state)], ["2"])
        with self.assertRaises(IllegalMove):
            board.move(state, "1")
        self.assertEqual([board.tiles[i].id for i in board.visible_indices(board.move(state, "2"))], ["1"])

    def test_three_of_a_kind_clears_tray(self):
        board = Board([tile(1, 1, 0), tile(2, 1, 8), tile(3, 1, 16)])
        state = board.initial()
        for tile_id in ("1", "2", "3"):
            state = board.move(state, tile_id)
        self.assertEqual(sum(state.tray), 0)
        self.assertTrue(board.won(state))

    def test_seventh_unmatched_tile_loses_but_triplet_can_save_full_tray(self):
        board = Board([tile(i, i, i * 8) for i in range(1, 8)])
        state = board.initial()
        for tile_id in map(str, range(1, 8)):
            state = board.move(state, tile_id)
        self.assertTrue(state.lost)

        rescue = Board([tile(1, 1)])
        near_full = State(0, (0, 2, 1, 1, 1, 1))
        saved = rescue.move(near_full, "1")
        self.assertEqual(sum(saved.tray), 4)
        self.assertFalse(saved.lost)


if __name__ == "__main__":
    unittest.main()
