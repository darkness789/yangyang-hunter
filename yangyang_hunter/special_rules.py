"""Seeded changing-card rule from the observed Sheep Planet client.

The client's map RNG is a 128-bit xor-shift generator. Every completed triple
shuffles the *remaining* ColorChangedWhenCrush types in board iteration order.
Cards already moved to the tray are fixed and excluded from the shuffle.
"""

import json
from pathlib import Path


MASK = 0xffffffff


class XorShift:
    def __init__(self, state):
        if len(state) != 4:
            raise ValueError("expected four RNG words")
        self.state = tuple(int(word) & MASK for word in state)

    def random(self):
        e, t, n, i = self.state
        total = i + t
        high = (n + e + (total >> 32)) & MASK
        low = total & MASK
        shifted = ((e << 23) | ((t & 0xfffffe00) >> 9)) & MASK
        e = (e ^ shifted) & MASK
        r = (e ^ n) & MASK
        t = (t ^ (t << 23)) & MASK
        c = (t ^ i) & MASK
        r ^= e >> 18
        c ^= (t >> 18) | ((e & 262143) << 14)
        r ^= n >> 5
        c ^= (i >> 5) | ((n & 31) << 27)
        self.state = (n, i, r & MASK, c & MASK)
        return high * 2.3283064365386963e-10 + (low >> 12) * 2.220446049250313e-16


def shuffle(values, rng):
    values = list(values)
    for index in range(len(values) - 1, -1, -1):
        other = int(rng.random() * (index + 1))
        values[index], values[other] = values[other], values[index]
    return values


class SpecialCards:
    def __init__(self, board, rng_state, changing_ids):
        self.board = board
        self.rng = XorShift(rng_state)
        self.changing_ids = tuple(changing_ids)
        self.changing_indices = tuple(board.index[tile_id] for tile_id in changing_ids)
        if any(board.tiles[index].meta != 2 for index in self.changing_indices):
            raise ValueError("changing card IDs and metadata disagree")

    @classmethod
    def from_map(cls, board, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        info = data.get("specialRng")
        if not info or not info.get("changingIds"):
            raise ValueError("map has no seeded changing-card state")
        return cls(board, info["state"], info["changingIds"])

    def after_crush(self, board, removed):
        """Return a new board with post-triple types, advancing the RNG."""
        from dataclasses import replace
        from .board_model import Board

        active = [index for index in self.changing_indices
                  if not removed & (1 << index)]
        if len(active) < 2:
            return board
        values = shuffle([board.tiles[index].type for index in active], self.rng)
        tiles = list(board.tiles)
        for index, kind in zip(active, values):
            tiles[index] = replace(tiles[index], type=kind)
        return Board(tiles)
