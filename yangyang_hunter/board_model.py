"""Rule model for a captured Sheep Planet board.

The cover rule is based on the observed 8x8 map coordinates and the published
GameMap format. The tray rule matches the documented seven-slot match-three
gameplay. Tile types must be populated before moves can be simulated.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple


TILE_SIZE = 8
TRAY_CAPACITY = 7


@dataclass(frozen=True)
class Tile:
    id: str
    type: int
    x: int
    y: int
    layer: int
    mold: int


@dataclass(frozen=True)
class State:
    removed: int
    tray: Tuple[int, ...]
    lost: bool = False


class IllegalMove(ValueError):
    pass


class Board:
    def __init__(self, tiles):
        self.tiles = tuple(tiles)
        if len({tile.id for tile in self.tiles}) != len(self.tiles):
            raise ValueError("tile IDs must be unique")
        self.index = {tile.id: index for index, tile in enumerate(self.tiles)}
        self.all_mask = (1 << len(self.tiles)) - 1
        self.max_type = max((tile.type for tile in self.tiles), default=0)
        self.blockers = tuple(self._blockers_for(tile) for tile in self.tiles)

    @classmethod
    def from_json(cls, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        tiles = [
            Tile(node["id"], int(node["type"]), int(node.get("rolNum", 0)),
                 int(node.get("rowNum", 0)), int(node["layerNum"]),
                 int(node.get("moldType", 1)))
            for layer in data["levelData"].values() for node in layer
        ]
        return cls(tiles)

    def _blockers_for(self, tile):
        result = 0
        for index, other in enumerate(self.tiles):
            if (other.layer > tile.layer and
                    abs(other.x - tile.x) < TILE_SIZE and
                    abs(other.y - tile.y) < TILE_SIZE):
                result |= 1 << index
        return result

    def initial(self):
        return State(0, (0,) * (self.max_type + 1))

    def visible_indices(self, state):
        if state.lost:
            return ()
        remaining = self.all_mask & ~state.removed
        return tuple(
            index for index in range(len(self.tiles))
            if (remaining & (1 << index)) and not (self.blockers[index] & remaining)
        )

    def move(self, state, tile_id):
        if tile_id not in self.index:
            raise IllegalMove("unknown tile")
        index = self.index[tile_id]
        if index not in self.visible_indices(state):
            raise IllegalMove("tile is covered or already removed")
        tile = self.tiles[index]
        if tile.type <= 0:
            raise IllegalMove("tile type is not known yet")
        tray = list(state.tray)
        if tile.type >= len(tray):
            tray.extend([0] * (tile.type + 1 - len(tray)))
        tray[tile.type] = (tray[tile.type] + 1) % 3
        occupied = sum(tray)
        return State(state.removed | (1 << index), tuple(tray), occupied >= TRAY_CAPACITY)

    def won(self, state):
        return not state.lost and state.removed == self.all_mask and sum(state.tray) == 0


def main():
    import argparse
    from collections import Counter

    parser = argparse.ArgumentParser()
    parser.add_argument("map_file")
    args = parser.parse_args()
    board = Board.from_json(args.map_file)
    visible = board.visible_indices(board.initial())
    print(json.dumps({
        "tiles": len(board.tiles),
        "types_known": sum(tile.type > 0 for tile in board.tiles),
        "initial_visible": len(visible),
        "initial_visible_by_mold": dict(Counter(board.tiles[i].mold for i in visible)),
        "initial_visible_ids": [board.tiles[i].id for i in visible],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
