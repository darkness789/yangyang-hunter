import unittest

from yangyang_hunter.board_model import Board, Tile
from yangyang_hunter.special_rules import SpecialCards, XorShift


class SpecialRuleTests(unittest.TestCase):
    def test_rng_matches_observed_client_words(self):
        rng = XorShift([340642632, 2226265659, 1901112208, 4007297080])
        self.assertAlmostEqual(rng.random(), 0.52194922264929944)
        self.assertEqual(rng.state,
                         (1901112208, 4007297080, 3268776072, 336571470))

    def test_only_remaining_changing_cards_are_permuted(self):
        tiles = [Tile(str(i), i + 1, i * 8, 0, 1, 1, 2) for i in range(3)]
        tiles.append(Tile("fixed", 9, 40, 0, 1, 1))
        board = Board(tiles)
        special = SpecialCards(board, [1, 2, 3, 4], ["0", "1", "2"])
        updated = special.after_crush(board, 1 << board.index["0"])
        self.assertEqual(updated.tiles[0].type, board.tiles[0].type)
        self.assertEqual(updated.tiles[3].type, 9)
        self.assertCountEqual([updated.tiles[1].type, updated.tiles[2].type],
                              [2, 3])
        state = special.rng.state
        special.after_crush(updated, 0b11)
        self.assertEqual(special.rng.state, state)


if __name__ == "__main__":
    unittest.main()
