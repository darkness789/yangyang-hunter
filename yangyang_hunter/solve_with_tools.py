"""Search a board allowing one Move Out and one revive.

This is an experimental planner for the classic Sheep Planet rule set. It
keeps tray order because Move Out takes the first three cards. Shuffle is not
planned in advance: its result is random and requires a fresh board reading.
"""

import argparse
import heapq
import json
import random
import time
from dataclasses import dataclass
from pathlib import Path

from .board_model import Board, IllegalMove
from .solve import _available, _unlock_targets, _after_move, _bits, _available_mask


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
                      allow_revive=True, prefix=(), initial_state=None,
                      remove_min=6, priority_jitter=18,
                      allow_unmatched_aux=False, unlock_match_weight=0):
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
        # Once both order-sensitive tools are spent, only tray counts affect
        # future matches. Canonicalizing their order merges equivalent states.
        tray_key = tuple(sorted(tray)) if used_remove and used_revive else tray
        key = (removed, tray_key, moved, used_remove, used_revive)
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
        if allow_remove and not used_remove and len(tray) >= remove_min:
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
            remaining = board.all_mask & ~removed & ~(1 << index)
            unlocks = 0
            match_unlocks = 0
            for lower in _bits(unlock_targets[index] & remaining):
                if not (board.blockers[lower] & remaining):
                    unlocks += 1
                    match_unlocks += counts.get(types[lower], 0)
            score = (100 if held == 2 else 50 if held else 0)
            score += tile.layer * 2 + unlocks * 8 + unlock_match_weight * match_unlocks
            if seed:
                score += randomizer.uniform(-priority_jitter, priority_jitter)
            return score

        choices.sort(key=priority, reverse=True)
        choices = choices[:max_branches]
        # Auxiliary cards have no blockers and should be considered whenever
        # they complete a pair or there are few free tray slots.
        for slot in sorted(range(3), key=lambda slot: (
                counts.get(moved[slot][-1], 0) if moved[slot] else -1), reverse=True):
            if not moved[slot]:
                continue
            kind = moved[slot][-1]
            if allow_unmatched_aux or counts.get(kind, 0) >= 1 or len(tray) <= 3:
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


def diverse_beam_search(board, seconds=90, width=1200, seed=0,
                        initial_state=None, allow_remove=True, allow_revive=True):
    """Search complete tool routes while keeping alternatives at each click depth.

    The frontier is grouped by board clicks. Tool and auxiliary actions have
    zero click cost, so they are expanded within the current depth. Exact
    states are deduplicated, while a quota for each tray shape prevents one
    promising-looking opening from taking the entire beam.
    """
    if any(tile.type <= 0 for tile in board.tiles):
        raise ValueError("Every tile needs a recovered nonzero type")
    if width < 1 or seconds <= 0:
        raise ValueError("width and seconds must be positive")
    start = time.monotonic()
    deadline = start + seconds
    rng = random.Random(seed)
    types = tuple(tile.type for tile in board.tiles)
    unlock_targets = _unlock_targets(board)
    if initial_state is None:
        initial_state = (0, (), ((), (), ()), False, False)
    removed, tray, aux, used_remove, used_revive = initial_state
    available = _available_mask(board, removed)
    # A node is (removed, available, tray, aux, used_remove, used_revive, path).
    frontier = [(removed, available, tray, aux, used_remove, used_revive, ())]
    target_depth = len(board.tiles) - bin(removed).count("1")
    expanded = 0
    best = ()
    reached = 0

    def rank(node):
        removed, available, tray, aux, used_remove, used_revive, path = node
        held = {}
        for kind in tray:
            held[kind] = held.get(kind, 0) + 1
        free = {}
        for index in _bits(available):
            kind = types[index]
            free[kind] = free.get(kind, 0) + 1
        # Empty slots and immediately finishable pairs matter more than a
        # small difference in the number of visible cards.
        matches = sum(min(n, 3 - held[k]) for k, n in free.items() if k in held)
        exposed_triples = sum((n + held.get(k, 0)) // 3 for k, n in free.items())
        aux_count = sum(map(len, aux))
        return (-31 * len(tray) - 13 * aux_count + 11 * matches +
                8 * exposed_triples + 0.7 * bin(available).count("1") +
                (65 if not used_remove else 0) +
                (45 if not used_revive else 0) + rng.random() * 18)

    def key(node):
        return (node[0], node[2], node[3], node[4], node[5])

    for depth in range(target_depth + 1):
        if not frontier or time.monotonic() >= deadline:
            break
        reached = depth
        next_states = {}
        pending = frontier
        seen_here = set()
        # Zero-click actions are expanded before advancing to the next board
        # depth. A state can use each tool once and auxiliary cards are finite.
        while pending and time.monotonic() < deadline:
            node = pending.pop()
            removed, available, tray, aux, used_remove, used_revive, path = node
            state_key = key(node)
            if state_key in seen_here:
                continue
            seen_here.add(state_key)
            expanded += 1
            if len(path) > len(best):
                best = path
            if removed == board.all_mask and not tray and not any(aux):
                return {"status": "solved", "path": path, "depth": depth,
                        "elapsed": time.monotonic() - start, "states": expanded}
            if len(tray) == 7:
                if allow_revive and not used_revive:
                    shifted = tuple(aux[i] + (tray[i],) for i in range(3))
                    pending.append((removed, available, tray[3:], shifted,
                                    used_remove, True, path + ("REVIVE",)))
                continue
            if allow_remove and not used_remove and len(tray) >= 4:
                count = min(3, len(tray))
                shifted = tuple(aux[i] + ((tray[i],) if i < count else ())
                                for i in range(3))
                pending.append((removed, available, tray[count:], shifted,
                                True, used_revive, path + ("MOVE_OUT",)))
            for slot, stack in enumerate(aux):
                if not stack:
                    continue
                if stack[-1] not in tray and len(tray) > 2 and removed != board.all_mask:
                    continue
                next_tray = insert_tray(tray, stack[-1])
                if len(next_tray) == 7 and (used_revive or not allow_revive):
                    continue
                shifted = tuple(s[:-1] if i == slot else s
                                for i, s in enumerate(aux))
                pending.append((removed, available, next_tray, shifted,
                                used_remove, used_revive, path + (("AUX", slot),)))
            for index in _bits(available):
                next_tray = insert_tray(tray, types[index])
                if len(next_tray) == 7 and (used_revive or not allow_revive):
                    continue
                next_removed, next_available = _after_move(
                    board, unlock_targets, removed, available, index)
                child = (next_removed, next_available, next_tray, aux,
                         used_remove, used_revive, path + (index,))
                child_key = key(child)
                if child_key not in next_states:
                    next_states[child_key] = child
            if expanded % 512 == 0 and time.monotonic() >= deadline:
                break
        if not next_states:
            break
        # The tray signature quota preserves different ways of handling the
        # next layers even when their heuristic scores are close.
        cohorts = {(False, False): [], (True, False): [],
                   (False, True): [], (True, True): []}
        for node in next_states.values():
            cohorts[(node[4], node[5])].append(node)
        frontier = []
        leftovers = []
        quota = max(4, width // 45)
        shares = {(False, False): 0.45, (True, False): 0.25,
                  (False, True): 0.10, (True, True): 0.20}
        for status, group in cohorts.items():
            if not group:
                continue
            ranked = heapq.nlargest(min(width * 4, len(group)), group, key=rank)
            shape_counts = {}
            reserved = max(1, int(width * shares[status]))
            taken = 0
            for node in ranked:
                shape = tuple(sorted(node[2]))
                if shape_counts.get(shape, 0) >= quota:
                    leftovers.append(node)
                    continue
                shape_counts[shape] = shape_counts.get(shape, 0) + 1
                if taken < reserved:
                    frontier.append(node)
                    taken += 1
                else:
                    leftovers.append(node)
                if len(frontier) >= width:
                    break
        if len(frontier) < width:
            frontier.extend(heapq.nlargest(width - len(frontier), leftovers,
                                          key=rank))
    return {"status": "not_found", "path": best,
            "depth": reached,
            "elapsed": time.monotonic() - start, "states": expanded,
            "limit": "timeout" if time.monotonic() >= deadline else "search_exhausted"}


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
