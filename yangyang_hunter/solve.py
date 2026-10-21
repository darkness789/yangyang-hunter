"""Find a legal click sequence for a fully typed Sheep Planet map.

Beam search is intentionally bounded: failure to find a route is reported as
"not found", never as proof that a level is impossible.
"""

import argparse
import json
import random
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .board_model import Board


@dataclass(frozen=True)
class SearchState:
    removed: int
    tray: tuple
    available: int
    path: tuple
    score: float = 0.0


def _bits(mask):
    while mask:
        bit = mask & -mask
        yield bit.bit_length() - 1
        mask ^= bit


def _available(board, removed):
    remaining = board.all_mask & ~removed
    return [index for index in _bits(remaining)
            if board.blockers[index] & remaining == 0]


def _available_mask(board, removed):
    return sum(1 << index for index in _available(board, removed))


def _score(board, removed, tray, available, jitter):
    occupied = sum(tray)
    type_counts = Counter(board.tiles[index].type for index in available)
    pair_matches = sum(min(count, 3 - tray[kind]) for kind, count in type_counts.items()
                       if kind < len(tray) and tray[kind])
    triples = sum((count + tray[kind]) // 3 for kind, count in type_counts.items())
    # All candidates in a beam have taken the same number of clicks. Prefer
    # states with room in the tray and several ways to finish a triple.
    return (-24 * occupied + 9 * triples + 3 * pair_matches
            + 0.3 * len(available) + jitter)


def _unlock_targets(board):
    targets = [0] * len(board.tiles)
    for lower, blockers in enumerate(board.blockers):
        for upper in _bits(blockers):
            targets[upper] |= 1 << lower
    return targets


def _after_move(board, unlock_targets, removed, available, index):
    removed |= 1 << index
    available &= ~(1 << index)
    remaining = board.all_mask & ~removed
    for lower in _bits(unlock_targets[index] & remaining):
        if board.blockers[lower] & remaining == 0:
            available |= 1 << lower
    return removed, available


def depth_search(board, seconds=60, seed=0, initial_state=None,
                 max_branches=5, max_states=2000000, coarse=False):
    """Bounded exact-state DFS, ordered toward matches and upper layers."""
    if any(tile.type <= 0 for tile in board.tiles):
        raise ValueError("Every tile needs a recovered nonzero type")
    start_state = initial_state or board.initial()
    if start_state.lost:
        raise ValueError("Cannot solve a lost position")
    start = time.monotonic()
    deadline = start + seconds
    randomizer = random.Random(seed)
    unlock_targets = _unlock_targets(board)
    seen = set()
    path = []
    best = []
    nodes = 0
    remaining_counts = [0] * (board.max_type + 1)
    for index, tile in enumerate(board.tiles):
        if not start_state.removed & (1 << index):
            remaining_counts[tile.type] += 1

    def visit(removed, tray, available, counts):
        nonlocal nodes, best
        nodes += 1
        if nodes % 1024 == 0 and (time.monotonic() >= deadline or
                                  nodes >= max_states):
            return "timeout"
        if len(path) > len(best):
            best = path.copy()
        if removed == board.all_mask:
            return "solved" if not any(tray) else "dead"
        if coarse:
            available_counts = [0] * len(tray)
            for index in _bits(available):
                available_counts[board.tiles[index].type] += 1
            key = (tray, tuple(available_counts), counts)
        else:
            # With no tools, each type's tray count is fixed by the set of
            # clicked tiles (and the fixed initial state). Keeping the tray
            # in the transposition key only duplicates memory and hashing.
            key = removed
        if key in seen:
            return "dead"
        seen.add(key)
        choices = list(_bits(available))
        if seed:
            randomizer.shuffle(choices)

        def priority(index):
            tile = board.tiles[index]
            held = tray[tile.type]
            count = counts[tile.type]
            score = 100 if held == 2 else 50 if held else 0
            score += 30 if count >= 3 else 20 if count == 2 else 0
            score += tile.layer * 2
            if sum(tray) >= 5 and held:
                score += 40
            # Reward cards that reveal new choices. With a nonzero seed,
            # perturb nearby scores so retries visit genuinely different
            # branches instead of merely changing the order of exact ties.
            remaining = board.all_mask & ~removed & ~(1 << index)
            score += 8 * sum(1 for lower in _bits(unlock_targets[index] & remaining)
                             if not (board.blockers[lower] & remaining))
            if seed:
                score += randomizer.uniform(-18, 18)
            return score

        choices.sort(key=priority, reverse=True)
        for index in choices[:max_branches]:
            kind = board.tiles[index].type
            next_tray = list(tray)
            next_tray[kind] = (next_tray[kind] + 1) % 3
            if sum(next_tray) >= 7:
                continue
            next_removed, next_available = _after_move(
                board, unlock_targets, removed, available, index)
            next_counts = list(counts)
            next_counts[kind] -= 1
            path.append(index)
            result = visit(next_removed, tuple(next_tray), next_available,
                           tuple(next_counts))
            if result in ("solved", "timeout"):
                return result
            path.pop()
        return "dead"

    result = visit(start_state.removed, start_state.tray,
                   _available_mask(board, start_state.removed),
                   tuple(remaining_counts))
    elapsed = time.monotonic() - start
    if result == "solved":
        return {"status": "solved", "path": tuple(path),
                "depth": len(path), "elapsed": elapsed, "states": nodes}
    return {"status": "not_found", "path": tuple(best),
            "depth": len(best), "elapsed": elapsed, "states": nodes,
            "limit": result if result == "timeout" else "search_exhausted"}


def beam_search(board, width=2000, seconds=60, seed=0, initial_state=None):
    if any(tile.type <= 0 for tile in board.tiles):
        raise ValueError("Every tile needs a recovered nonzero type")
    if len(board.tiles) % 3 or any(count % 3 for count in Counter(
            tile.type for tile in board.tiles).values()):
        raise ValueError("The typed map has counts incompatible with triples")
    if width < 1 or seconds <= 0:
        raise ValueError("width and seconds must be positive")

    randomizer = random.Random(seed)
    start = time.monotonic()
    start_state = initial_state or board.initial()
    if start_state.lost:
        raise ValueError("Cannot solve a lost position")
    initial = SearchState(start_state.removed, start_state.tray,
                          _available_mask(board, start_state.removed), ())
    unlock_targets = _unlock_targets(board)
    beam = [initial]
    reached = 0
    for depth in range(len(board.tiles) - bin(start_state.removed).count("1")):
        if time.monotonic() - start >= seconds:
            break
        candidates = {}
        for state in beam:
            if time.monotonic() - start >= seconds:
                break
            for index in _bits(state.available):
                kind = board.tiles[index].type
                tray = list(state.tray)
                tray[kind] = (tray[kind] + 1) % 3
                if sum(tray) >= 7:
                    continue
                removed = state.removed | (1 << index)
                path = state.path + (index,)
                if removed == board.all_mask and not any(tray):
                    return {"status": "solved", "path": path,
                            "depth": len(path), "elapsed": time.monotonic() - start}
                tray = tuple(tray)
                key = (removed, tray)
                if key in candidates:
                    continue
                _, available_mask = _after_move(
                    board, unlock_targets, state.removed, state.available, index)
                available = list(_bits(available_mask))
                score = _score(board, removed, tray, available,
                               randomizer.random() * 0.15)
                candidates[key] = SearchState(removed, tray, available_mask,
                                              path, score)
        if not candidates:
            break
        beam = sorted(candidates.values(), key=lambda state: state.score,
                      reverse=True)[:width]
        reached = depth + 1
    return {"status": "not_found", "depth": reached,
            "elapsed": time.monotonic() - start,
            "path": beam[0].path if beam else ()}


def replay(board, path, initial_state=None):
    """Independently check each click with the board's rule model."""
    state = initial_state or board.initial()
    for index in path:
        state = board.move(state, board.tiles[index].id)
        if state.lost:
            raise ValueError("Search returned a losing route")
    return board.won(state)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("map_file", type=Path)
    parser.add_argument("--width", type=int, default=2000)
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--method", choices=("depth", "beam"), default="depth")
    parser.add_argument("--branches", type=int, default=5)
    parser.add_argument("--max-states", type=int, default=2000000)
    parser.add_argument("--output", type=Path, default=Path("captures/solution.json"))
    args = parser.parse_args()
    board = Board.from_json(args.map_file)
    if args.method == "depth":
        result = depth_search(board, args.seconds, args.seed,
                              max_branches=args.branches,
                              max_states=args.max_states)
    else:
        result = beam_search(board, args.width, args.seconds, args.seed)
    path = result.pop("path")
    result["verified"] = replay(board, path) if result["status"] == "solved" else False
    result["clicks"] = [board.tiles[index].id for index in path]
    result["map_file"] = str(args.map_file)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "clicks"},
                     ensure_ascii=False, indent=2))
    print("output:", args.output)


if __name__ == "__main__":
    main()
