import tempfile
import unittest
from pathlib import Path

from yangyang_hunter.board_model import Board, Tile
from yangyang_hunter.search_checkpoint import load_checkpoint, save_checkpoint


class SearchCheckpointTests(unittest.TestCase):
    def test_retry_state_survives_restart_but_not_a_new_deal(self):
        board = Board([Tile(str(i), 1, i * 8, 0, 1, 1)
                       for i in range(3)])
        changed = Board([Tile(str(i), 2, i * 8, 0, 1, 1)
                         for i in range(3)])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "checkpoint.json"
            save_checkpoint(path, board, 2, (0, 1))
            self.assertEqual(load_checkpoint(path, board), (2, (0, 1)))
            self.assertEqual(load_checkpoint(path, changed), (0, ()))


if __name__ == "__main__":
    unittest.main()
