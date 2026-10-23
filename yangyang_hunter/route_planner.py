"""An anytime portfolio for complete routes on a known, typed board.

The first attempts start from the actual position. Later attempts may repair
different prefixes of the deepest partial route; none is a mandatory opening.
"""

import time

from .solve import depth_search
from .solve_with_tools import ToolEngine, search_with_tools


def plan_route(board, seconds=120, initial_state=None, on_progress=None,
               seed_offset=0, candidate_path=()):
    """Search with several genuinely different move and tool orderings.

    ``initial_state`` is ToolEngine.search_start's type-level tuple. All
    results use indices for board clicks and action tokens for tools.
    A time limit means *not found*, never a proof of no solution.
    """
    if seconds <= 0:
        raise ValueError("seconds must be positive")
    started = time.monotonic()
    deadline = started + seconds
    best = {"status": "not_found", "path": (), "depth": 0}
    attempts = 0
    engine = ToolEngine(board)
    fresh = initial_state is None or initial_state == (
        0, (), ((), (), ()), False, False)
    if fresh and candidate_path:
        # A candidate from an earlier timed-out search is only useful when it
        # still replays legally on this exact board. A new map may reuse IDs.
        try:
            state = engine.initial()
            path = tuple(tuple(action) if isinstance(action, list) else action
                         for action in candidate_path)
            for action in path:
                state = engine.apply(state, board.tiles[action].id
                                     if isinstance(action, int) else action)
                if len(state.tray) > 7:
                    raise ValueError("candidate fills the tray")
            best = {"status": "not_found", "path": path,
                    "depth": sum(isinstance(action, int) for action in path)}
        except (IndexError, KeyError, ValueError):
            pass

    def record(result):
        nonlocal best, attempts
        attempts += 1
        if result["status"] == "solved" or result["depth"] > best["depth"]:
            best = result
        return result["status"] == "solved"

    if fresh and deadline - time.monotonic() > 1:
        if on_progress:
            on_progress("正在搜索不使用道具的路线…")
        normal = depth_search(board, seconds=min(10, deadline - time.monotonic()),
                              seed=seed_offset, max_branches=12,
                              max_states=1_500_000,
                              priority_jitter=min(180, 18 + 30 * seed_offset),
                              unlock_match_weight=20 if seed_offset else 0)
        if record(normal):
            return dict(normal, attempts=attempts,
                        elapsed=time.monotonic() - started)

        # The deepest ordinary route is a valuable *reachable* position. In
        # practice the remaining puzzle can be easy once Move Out is offered
        # there. Try several cut points before spending time at the opening.
        source = best["path"]
        fractions = (((3, 4), (1, 2), (7, 8), (1, 4))
                     if any(not isinstance(action, int) for action in source)
                     else ((1, 1), (7, 8), (3, 4), (1, 2)))
        for turn, (numerator, denominator) in enumerate(fractions):
            if deadline - time.monotonic() < 0.2 or not source:
                break
            cut = len(source) * numerator // denominator
            prefix_path = source[:cut]
            state = engine.initial()
            for action in prefix_path:
                state = engine.apply(state, board.tiles[action].id
                                     if isinstance(action, int) else action)
            if on_progress:
                on_progress("正在从已找到的深路线尝试道具…")
            suffix = search_with_tools(
                board, seconds=min(8, deadline - time.monotonic()),
                max_states=1_500_000, max_branches=32,
                seed=29 + 997 * seed_offset + 37 * turn,
                initial_state=engine.search_start(state),
                remove_min=(3, 2, 1, 3)[turn],
                priority_jitter=100 + 20 * turn,
                allow_unmatched_aux=turn >= 2,
                unlock_match_weight=20 * turn)
            combined = prefix_path + suffix["path"]
            result = dict(suffix, path=combined,
                          depth=sum(isinstance(action, int)
                                    for action in combined))
            if record(result):
                return dict(result, attempts=attempts,
                            elapsed=time.monotonic() - started)

    # Start with independent full-board searches that vary both click ordering
    # and the earliest point at which Move Out can be used.
    settings = ((0, 8, 6, 18), (11, 12, 5, 65),
                (29, 16, 4, 110), (47, 24, 3, 160))
    turn = 0
    while deadline - time.monotonic() > 0.1:
        seed, branches, remove_min, jitter = settings[turn % len(settings)]
        seed += 101 * (turn // len(settings)) + 997 * seed_offset
        remaining = deadline - time.monotonic()
        # Small, bounded slices stop one DFS ordering from consuming the
        # entire budget. The final slice may be shorter.
        slice_seconds = min(14 if turn < len(settings) else 12, remaining)
        if on_progress:
            elapsed = time.monotonic() - started
            prefix = "已超过 30 秒，仍在搜索。" if elapsed >= 30 else ""
            on_progress(prefix + "正在尝试不同开局和道具时机…")
        # Later slices repair several points along the deepest *current*
        # route, including routes that already used a tool. Full-root slices
        # above preserve the possibility of changing the opening entirely.
        prefix_path = ()
        attempt_state = initial_state
        if fresh and best["path"] and turn >= len(settings):
            cut_fraction = ((1, 4), (1, 2), (3, 4), (7, 8))[
                (turn - len(settings)) % 4]
            cut = len(best["path"]) * cut_fraction[0] // cut_fraction[1]
            prefix_path = best["path"][:cut]
            state = engine.initial()
            for action in prefix_path:
                state = engine.apply(state, board.tiles[action].id
                                     if isinstance(action, int) else action)
            attempt_state = engine.search_start(state)
        result = search_with_tools(
            board, seconds=slice_seconds, max_states=1_500_000,
            max_branches=branches, seed=seed,
            initial_state=attempt_state,
            remove_min=(1 if turn >= len(settings) and turn % 2 else remove_min),
            priority_jitter=jitter,
            allow_unmatched_aux=turn >= len(settings),
            unlock_match_weight=15 * (turn % len(settings)))
        if prefix_path:
            result = dict(result, path=prefix_path + result["path"],
                          depth=sum(isinstance(action, int)
                                    for action in prefix_path + result["path"]))
        if record(result):
            return dict(result, attempts=attempts,
                        elapsed=time.monotonic() - started)
        turn += 1
    return dict(best, status="not_found", attempts=attempts,
                elapsed=time.monotonic() - started, limit="timeout")
