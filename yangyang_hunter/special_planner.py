"""Plan only until the next recolor; later types are simulated after it."""

import time

from .solve_with_tools import ToolEngine, search_with_tools


def _segment(board, state, path):
    engine = ToolEngine(board)
    current = state
    segment = []
    for action in path:
        before = len(current.tray)
        token = board.tiles[action].id if isinstance(action, int) else action
        current = engine.apply(current, token)
        segment.append(token)
        if len(current.tray) < before:
            return segment
    return []


def plan_next_crush(board, state, seconds=5, seed=0, cancel_event=None):
    """Find a legal short segment using the current (post-shuffle) types.

    The classic search is useful for ranking openings, but its route past a
    triple is invalid here. Only the prefix up to the first triple is used.
    """
    if cancel_event is not None and cancel_event.is_set():
        return []
    engine = ToolEngine(board)
    result = search_with_tools(
        board, seconds=seconds * .6, max_states=180_000, max_branches=14,
        initial_state=engine.search_start(state), allow_remove=False,
        seed=seed,
        allow_revive=False, cancel_event=cancel_event)
    if cancel_event is not None and cancel_event.is_set():
        return []
    segment = _segment(board, state, result["path"])
    if segment:
        return segment
    result = search_with_tools(
        board, seconds=seconds * .4, max_states=180_000, max_branches=14,
        initial_state=engine.search_start(state), remove_min=5,
        seed=seed,
        cancel_event=cancel_event)
    segment = _segment(board, state, result["path"])
    if segment:
        return segment

    # A bounded local search supplies a triple even when a full static route
    # is hard to find. Keep it separate from the normal, complete-route path.
    deadline = time.monotonic() + min(seconds, 2)
    seen = set()
    best = None

    def visit(current, path, depth):
        nonlocal best
        if (time.monotonic() >= deadline or
                (cancel_event is not None and cancel_event.is_set())):
            return
        key = (current.removed, current.tray, current.aux,
               current.used_remove, current.used_revive)
        if key in seen or depth >= 4:
            return
        seen.add(key)
        actions = [board.tiles[i].id for i in board.visible_indices(current)]
        actions += [("AUX", i) for i, stack in enumerate(current.aux) if stack]
        tray_types = [board.tiles[i].type for i in current.tray]
        actions.sort(key=lambda a: (tray_types.count(board.tiles[
            board.index[a] if isinstance(a, str) else current.aux[a[1]][-1]
        ].type), board.tiles[board.index[a]].layer if isinstance(a, str) else 0),
            reverse=True)
        for action in actions[:24]:
            try:
                after = engine.apply(current, action)
            except ValueError:
                continue
            if len(after.tray) >= 7:
                continue
            candidate = path + [action]
            if len(after.tray) < len(current.tray):
                newly_visible = len(board.visible_indices(after)) - len(board.visible_indices(current))
                score = (newly_visible * 3 +
                         (bin(after.removed).count("1") -
                          bin(state.removed).count("1")) * 2 -
                         len(after.tray) * 3)
                if best is None or score > best[0]:
                    best = (score, candidate)
            else:
                visit(after, candidate, depth + 1)

    visit(state, [], 0)
    return best[1] if best else []
