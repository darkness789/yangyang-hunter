"""Search a board allowing one Move Out and one revive.

This is an experimental planner for the classic Sheep Planet rule set. It
keeps tray order because Move Out takes the first three cards. Shuffle is not
planned in advance: its result is random and requires a fresh board reading.
"""

import argparse
import json
import random
import time
from dataclasses import dataclass
from pathlib import Path

from .board_model import Board, IllegalMove
from .solve import _available, _unlock_targets, _after_move


def insert_tray(tray, kind):
    """Reproduce crushArea.getNewPosit and consecutive triple elimination."""
    pos = len(tray)
    for index in range(len(tray) - 1, -1, -1):
        if tray[index] == kind:
            count = 1
            for earlier in range(index - 1, -1, -1):
                if tray[earlier] == kind:
                    count += 1
            if count % 3:
                pos = index + 1
            break
    next_tray = tray[:pos] + (kind,) + tray[pos:]
    for index in range(len(next_tray) - 2):
        if next_tray[index:index + 3] == (kind,) * 3:
            return next_tray[:index] + next_tray[index + 3:]
    return next_tray


@dataclass(frozen=True)
class ToolState:
    removed: int
    tray: tuple
    aux: tuple
    used_remove: bool = False
    used_revive: bool = False
    lost: bool = False


class ToolEngine:
    def __init__(self, board):
        self.board = board

    def initial(self):
        return ToolState(0, (), ((), (), ()))

    def apply(self, state, action):
        tray = state.tray
        aux = state.aux
        if action in ("MOVE_OUT", "REVIVE"):
            if action == "MOVE_OUT" and (state.used_remove or not 0 < len(tray) < 7):
                raise IllegalMove("移出道具此时不可用")
            if action == "REVIVE" and (state.used_revive or len(tray) != 7):
                raise IllegalMove("复活仅在槽位满 7 张后可用一次")
            count = min(3, len(tray))
            aux = tuple(aux[i] + ((tray[i],) if i < count else ()) for i in range(3))
            return ToolState(state.removed, tray[count:], aux,
                             state.used_remove or action == "MOVE_OUT",
                             state.used_revive or action == "REVIVE")
        if isinstance(action, tuple) and action[0] == "AUX":
            slot = action[1]
            if not 0 <= slot < 3 or not aux[slot] or len(tray) >= 7:
                raise IllegalMove("辅助区这列没有可点的牌")
            index = aux[slot][-1]
            aux = tuple(stack[:-1] if i == slot else stack
                        for i, stack in enumerate(aux))
            removed = state.removed
        else:
            if action not in self.board.index or len(tray) >= 7:
                raise IllegalMove("这张牌此时不可点")
            index = self.board.index[action]
            if index not in self.board.visible_indices(state):
                raise IllegalMove("这张牌被遮挡或已经消除")
            removed = state.removed | (1 << index)
        kind = self.board.tiles[index].type
        pos = len(tray)
        for i in range(len(tray)-1, -1, -1):
            if self.board.tiles[tray[i]].type == kind:
                pos = i + 1
                break
        tray = tray[:pos] + (index,) + tray[pos:]
        for i in range(len(tray)-2):
            if all(self.board.tiles[tray[j]].type == kind for j in range(i, i+3)):
                tray = tray[:i] + tray[i+3:]
                break
        return ToolState(removed, tray, aux, state.used_remove, state.used_revive)

    def won(self, state):
        return state.removed == self.board.all_mask and not state.tray and not any(state.aux)

    def search_start(self, state):
        return (state.removed,
                tuple(self.board.tiles[i].type for i in state.tray),
                tuple(tuple(self.board.tiles[i].type for i in stack) for stack in state.aux),
                state.used_remove, state.used_revive)


def search_with_tools(board, seconds=180, max_states=10_000_000,
                      max_branches=6, seed=0, allow_remove=True,
                      allow_revive=True, prefix=(), initial_state=None):
    if prefix and initial_state is not None:
        raise ValueError("Use either prefix or initial_state")
    start = time.monotonic()
    deadline = start + seconds
    randomizer = random.Random(seed)
    types = tuple(tile.type for tile in board.tiles)
    unlock_targets = _unlock_targets(board)
    seen = set()
    path = list(prefix)
    best = path.copy()
    nodes = 0
    start_removed = 0
    start_tray = ()
    for index in prefix:
        if index not in board.visible_indices(type("S", (), {
                "removed": start_removed, "lost": False})()):
            raise ValueError("Prefix contains an illegal tile")
        start_removed |= 1 << index
        start_tray = insert_tray(start_tray, types[index])
        if len(start_tray) >= 7:
            raise ValueError("Prefix fills the tray")

    def visit(removed, available, tray, moved, used_remove, used_revive):
        nonlocal nodes, best
        nodes += 1
        if nodes % 1024 == 0 and (nodes >= max_states or time.monotonic() >= deadline):
            return "limit"
        if removed == board.all_mask and not tray and not any(moved):
            return "solved"
        if len(path) > len(best):
            best = path.copy()
        key = (removed, tray, moved, used_remove, used_revive)
        if key in seen:
            return "dead"
        seen.add(key)

        if len(tray) >= 7:
            if not allow_revive or used_revive:
                return "dead"
            count = min(3, len(tray))
            path.append("REVIVE")
            result = visit(removed, available, tray[count:],
                           tuple(moved[i] + ((tray[i],) if i < count else ())
                                 for i in range(3)),
                           used_remove, True)
            if result in ("solved", "limit"):
                return result
            path.pop()
            return "dead"

        # Move Out is most useful when the tray is nearly full. It transfers
        # cards into the three auxiliary slots; those cards remain playable.
        if allow_remove and not used_remove and len(tray) >= 6:
            count = min(3, len(tray))
            path.append("MOVE_OUT")
            result = visit(removed, available, tray[count:],
                           tuple(moved[i] + ((tray[i],) if i < count else ())
                                 for i in range(3)),
                           True, used_revive)
            if result in ("solved", "limit"):
                return result
            path.pop()

        choices = list(_available(board, removed)) if available is None else [
            index for index in range(len(board.tiles)) if available & (1 << index)]
        if seed:
            randomizer.shuffle(choices)
        counts = {}
        for kind in tray:
            counts[kind] = counts.get(kind, 0) + 1

        def priority(index):
            tile = board.tiles[index]
            held = counts.get(tile.type, 0)
            return (100 if held == 2 else 50 if held else 0) + tile.layer * 2

        choices.sort(key=priority, reverse=True)
        choices = choices[:max_branches]
        # Auxiliary cards have no blockers and should be considered whenever
        # they complete a pair or there are few free tray slots.
        for slot in sorted(range(3), key=lambda slot: (
                counts.get(moved[slot][-1], 0) if moved[slot] else -1), reverse=True):
            if not moved[slot]:
                continue
            kind = moved[slot][-1]
            if counts.get(kind, 0) >= 1 or len(tray) <= 3:
                choices.append(("AUX", slot))
        for choice in choices:
            if isinstance(choice, tuple):
                slot = choice[1]
                kind = moved[slot][-1]
                next_moved = tuple(stack[:-1] if i == slot else stack
                                   for i, stack in enumerate(moved))
                next_removed, next_available = removed, available
            else:
                kind = types[choice]
                next_moved = moved
                next_removed, next_available = _after_move(
                    board, unlock_targets, removed, available, choice)
            next_tray = insert_tray(tray, kind)
            if len(next_tray) >= 7 and (not allow_revive or used_revive):
                continue
            path.append(choice)
            result = visit(next_removed, next_available, next_tray,
                           next_moved, used_remove, used_revive)
            if result in ("solved", "limit"):
                return result
            path.pop()
        return "dead"

    if initial_state is not None:
        start_removed, start_tray, start_aux, used_remove, used_revive = initial_state
    else:
        start_aux, used_remove, used_revive = ((), (), ()), False, False
    available = sum(1 << index for index in board.visible_indices(type("S", (), {
        "removed": start_removed, "lost": False})()))
    result = visit(start_removed, available, start_tray,
                   start_aux, used_remove, used_revive)
    return {"status": result if result == "solved" else "not_found",
            "path": tuple(path if result == "solved" else best),
            "depth": sum(isinstance(item, int) for item in
                         (path if result == "solved" else best)),
            "elapsed": time.monotonic() - start, "states": nodes,
            "limit": result if result != "solved" else None}


def replay_with_tools(board, path):
    removed = 0
    tray = ()
    moved = ((), (), ())
    remove_used = revive_used = False
    for action in path:
        if action in ("MOVE_OUT", "REVIVE"):
            if action == "MOVE_OUT":
                assert not remove_used and 0 < len(tray) < 7
                remove_used = True
            else:
                assert not revive_used and len(tray) == 7
                revive_used = True
            moved = tuple(moved[i] + ((tray[i],) if i < min(3, len(tray)) else ())
                          for i in range(3))
            tray = tray[3:]
        elif isinstance(action, tuple):
            assert action[0] == "AUX" and moved[action[1]]
            kind = moved[action[1]][-1]
            moved = tuple(stack[:-1] if i == action[1] else stack
                          for i, stack in enumerate(moved))
            tray = insert_tray(tray, kind)
        else:
            assert action in board.visible_indices(type("S", (), {
                "removed": removed, "lost": False})())
            removed |= 1 << action
            tray = insert_tray(tray, board.tiles[action].type)
        assert len(tray) < 8
    return removed == board.all_mask and not tray and not any(moved)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("map_file", type=Path)
    parser.add_argument("--seconds", type=int, default=180)
    parser.add_argument("--max-states", type=int, default=10_000_000)
    parser.add_argument("--branches", type=int, default=6)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output", type=Path, default=Path("captures/solution_with_tools.json"))
    parser.add_argument("--prefix-solution", type=Path)
    args = parser.parse_args()
    board = Board.from_json(args.map_file)
    prefix = ()
    if args.prefix_solution:
        partial = json.loads(args.prefix_solution.read_text(encoding="utf-8"))
        prefix = tuple(board.index[tile_id] for tile_id in partial["clicks"])
    result = search_with_tools(board, args.seconds, args.max_states,
                               args.branches, args.seed, prefix=prefix)
    path = result.pop("path")
    result["verified"] = replay_with_tools(board, path) if result["status"] == "solved" else False
    result["actions"] = [board.tiles[item].id if isinstance(item, int)
                         else item for item in path]
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "actions"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
