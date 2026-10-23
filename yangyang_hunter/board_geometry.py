"""Locate the card grid in the current game screenshot."""

from dataclasses import dataclass

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class BoardGeometry:
    origin_x: float
    step_x: float
    origin_y: float
    step_y: float
    confidence: float

    def center(self, tile):
        return (self.origin_x + self.step_x * tile.x,
                self.origin_y + self.step_y * tile.y)


def _rank(cream, tiles, x_pairs, y_pairs):
    """Count pale card corners at the projected centers."""
    x_origin, x_step = x_pairs
    y_origin, y_step = y_pairs
    scores = np.zeros((len(x_origin), len(y_origin)), dtype=np.int16)
    for tile in tiles:
        x = np.rint(x_origin + x_step * tile.x).astype(np.intp)[:, None]
        y = np.rint(y_origin + y_step * tile.y).astype(np.intp)[None, :]
        for sign_x in (-1, 1):
            for sign_y in (-1, 1):
                inner_x, inner_y = x + sign_x * 22, y + sign_y * 22
                outer_x, outer_y = x + sign_x * 28, y + sign_y * 28
                inner_valid = ((inner_x >= 0) & (inner_x < cream.shape[1]) &
                               (inner_y >= 0) & (inner_y < cream.shape[0]))
                outer_valid = ((outer_x >= 0) & (outer_x < cream.shape[1]) &
                               (outer_y >= 0) & (outer_y < cream.shape[0]))
                inner = cream[np.clip(inner_y, 0, cream.shape[0] - 1),
                              np.clip(inner_x, 0, cream.shape[1] - 1)]
                outer = cream[np.clip(outer_y, 0, cream.shape[0] - 1),
                              np.clip(outer_x, 0, cream.shape[1] - 1)]
                scores += inner & inner_valid
                scores += ~outer & outer_valid
    return np.unravel_index(scores.argmax(), scores.shape), int(scores.max())


def _pairs(origins, steps):
    origin, step = np.meshgrid(origins, steps, indexing="ij")
    return origin.ravel(), step.ravel()


def calibrate_board(image, board, state):
    """Fit a board grid from visible card corners; return None if uncertain.

    Game layout can move and zoom independently of the desktop window. The
    light card corners distinguish exposed cards from the green background
    and the darker covered cards without relying on changing tile pictures.
    Coordinates are normalized to a 573x1067 screenshot.
    """
    indices = board.visible_indices(state)
    if len(indices) < 6:
        return None
    tiles = [board.tiles[index] for index in indices]
    if max(tile.x for tile in tiles) - min(tile.x for tile in tiles) < 16 or (
            max(tile.y for tile in tiles) - min(tile.y for tile in tiles) < 16):
        return None
    if image.size != (573, 1067):
        image = image.resize((573, 1067), Image.NEAREST)
    pixels = np.asarray(image.convert("RGB"))
    cream = ((pixels[:, :, 0] > 220) & (pixels[:, :, 1] > 225) &
             (pixels[:, :, 2] > 160))

    # Use cards at the extremes for a fast broad search, then score every
    # exposed card near the best grid. The top and side piles give leverage
    # over both the origin and the spacing.
    anchors = []
    for key in (lambda tile: tile.x, lambda tile: tile.y,
                lambda tile: tile.x + tile.y,
                lambda tile: tile.x - tile.y):
        for tile in (min(tiles, key=key), max(tiles, key=key)):
            if tile not in anchors:
                anchors.append(tile)
    x_coarse = _pairs(np.arange(55, 131, 3), np.arange(5.5, 8.31, .12))
    y_coarse = _pairs(np.arange(170, 341, 5), np.arange(5.3, 8.71, .15))
    (ix, iy), _ = _rank(cream, anchors, x_coarse, y_coarse)
    ox, sx = (float(values[ix]) for values in x_coarse)
    oy, sy = (float(values[iy]) for values in y_coarse)

    x_fine = _pairs(np.arange(ox - 6, ox + 7, 1),
                    np.arange(sx - .25, sx + .251, .025))
    y_fine = _pairs(np.arange(oy - 8, oy + 9, 1),
                    np.arange(sy - .25, sy + .251, .025))
    (ix, iy), score = _rank(cream, tiles, x_fine, y_fine)
    confidence = score / (8 * len(tiles))
    if confidence < .65:
        return None
    return BoardGeometry(float(x_fine[0][ix]), float(x_fine[1][ix]),
                         float(y_fine[0][iy]), float(y_fine[1][iy]),
                         confidence)
