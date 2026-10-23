"""Plan one triple at a time for maps whose card types change after a crush."""

import time
from collections import Counter

from .solve_with_tools import ToolEngine, search_with_tools
from .special_rules import SpecialCards


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


def _thickness(board, removed):
    """Measure how much of the remaining stack each card covers."""
    remaining = board.all_mask & ~removed
    result = []
    for index, tile in enumerate(board.tiles):
        cover = 0
        deepest = 0
        bit = 1 << index
        for lower, blockers in enumerate(board.blockers):
            if remaining & (1 << lower) and blockers & bit:
                cover += 1
                deepest = max(deepest, tile.layer - board.tiles[lower].layer)
        result.append(cover * 2 + deepest)
    return tuple(result)


def _local_triple(board, state, deadline, cancel_event, special_cards=None):
    """Compare legal short routes by depth cleared and cards exposed."""
    engine = ToolEngine(board)
    depth = _thickness(board, state.removed)
    start_visible = set(board.visible_indices(state))
    candidates = []
    seen = {}
    nodes = 0

    def visit(current, path, score):
        nonlocal nodes
        nodes += 1
        if nodes > 120_000 or time.monotonic() >= deadline or (
                cancel_event is not None and cancel_event.is_set()):
            return
        key = (current.removed, current.tray, current.aux)
        if seen.get(key, -1) >= score:
            return
        seen[key] = score
        if len(path) >= 4 or len(current.tray) >= 7:
            return
        actions = [board.tiles[i].id for i in board.visible_indices(current)]
        actions += [("AUX", i) for i, stack in enumerate(current.aux) if stack]
        held = [board.tiles[i].type for i in current.tray]
        actions.sort(key=lambda action: (
            held.count(board.tiles[board.index[action] if isinstance(action, str)
                                   else current.aux[action[1]][-1]].type),
            depth[board.index[action]] if isinstance(action, str) else 0),
            reverse=True)
        for action in actions[:24]:
            try:
                after = engine.apply(current, action)
            except ValueError:
                continue
            if len(after.tray) >= 7:
                continue
            index = board.index[action] if isinstance(action, str) else None
            candidate_score = score + (depth[index] if index is not None else 0)
            candidate = path + [action]
            if len(after.tray) < len(current.tray):
                fresh = set(board.visible_indices(after)) - start_visible
                exposure = sum(min(depth[i], 20) for i in fresh)
                rank = (candidate_score * 3 + exposure * 2
                        - len(after.tray) * 24 - len(candidate) * 65)
                candidates.append((rank, candidate, after))
            else:
                visit(after, candidate, candidate_score)

    visit(state, [], 0)
    if not candidates:
        return []
    candidates.sort(key=lambda item: item[0], reverse=True)
    if special_cards is None:
        return candidates[0][1]

    # The next recolor is deterministic once the map RNG has been recovered.
    # Reject an attractive thick-stack move when it strands the tray with no
    # immediately playable triple after that recolor.
    best = None
    for rank, path, after in candidates[:24]:
        if cancel_event is not None and cancel_event.is_set():
            return []
        forecast = SpecialCards(board, special_cards.rng.state,
                                special_cards.changing_ids)
        recolored = forecast.after_crush(board, after.removed)
        visible = recolored.visible_indices(after)
        counts = Counter(recolored.tiles[i].type for i in visible)
        counts.update(recolored.tiles[i].type for i in after.tray)
        counts.update(recolored.tiles[stack[-1]].type
                      for stack in after.aux if stack)
        held = Counter(recolored.tiles[i].type for i in after.tray)
        reachable = sum(count >= 3 and
                        len(after.tray) + 3 - held[kind] <= 7
                        for kind, count in counts.items())
        one_away = sum(held[kind] == 2 and counts[kind] >= 3
                       for kind in held)
        future = (rank + min(reachable, 6) * 28 + one_away * 20
                  - (180 if reachable == 0 and after.removed != board.all_mask
                     else 0))
        if best is None or future > best[0]:
            best = (future, path)
    return best[1]


def plan_next_crush(board, state, seconds=5, seed=0, cancel_event=None,
                    special_cards=None):
    """Find a thick-first segment ending at the next triple."""
    if cancel_event is not None and cancel_event.is_set():
        return []
    segment = _local_triple(board, state, time.monotonic() + seconds * .7,
                            cancel_event, special_cards)
    if segment or (cancel_event is not None and cancel_event.is_set()):
        return segment

    # If no triple is nearby, use a longer route only up to the next recolor.
    engine = ToolEngine(board)
    result = search_with_tools(
        board, seconds=seconds * .3, max_states=180_000, max_branches=14,
        initial_state=engine.search_start(state), remove_min=5,
        seed=seed, cancel_event=cancel_event)
    if cancel_event is not None and cancel_event.is_set():
        return []
    return _segment(board, state, result["path"])
