import unittest

from PIL import Image, ImageDraw

from yangyang_hunter.board_geometry import calibrate_board
from yangyang_hunter.board_model import Board, Tile


class BoardGeometryTests(unittest.TestCase):
    def setUp(self):
        self.board = Board([
            Tile(str(i), 1, x, y, 1, 1)
            for i, (x, y) in enumerate([
                (0, 0), (48, 0), (8, 8), (24, 8), (40, 8),
                (0, 24), (16, 24), (32, 24), (48, 24),
                (8, 40), (24, 40), (40, 40), (0, 56), (48, 56),
            ])
        ])

    def test_finds_shifted_board_and_tile_center(self):
        image = Image.new("RGB", (573, 1067), (199, 252, 147))
        draw = ImageDraw.Draw(image)
        for tile in self.board.tiles:
            x = 82 + 7.35 * tile.x
            y = 225 + 7.4 * tile.y
            draw.rectangle((x-25, y-25, x+25, y+25), fill=(246, 255, 205))
        geometry = calibrate_board(image.resize((578, 1069)),
                                   self.board, self.board.initial())
        self.assertIsNotNone(geometry)
        self.assertGreater(geometry.confidence, .8)
        for tile in self.board.tiles:
            x, y = geometry.center(tile)
            self.assertAlmostEqual(x, 82 + 7.35 * tile.x, delta=4)
            self.assertAlmostEqual(y, 225 + 7.4 * tile.y, delta=4)

    def test_refuses_blank_image(self):
        image = Image.new("RGB", (573, 1067), (199, 252, 147))
        self.assertIsNone(calibrate_board(image, self.board,
                                          self.board.initial()))


if __name__ == "__main__":
    unittest.main()
