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
        if action not in ("MOVE_OUT", "REVIVE") and len(current.tray) < before:
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


def _tray_risk(board, tray):
    """Penalize distinct unmatched cards and the loss of spare tray slots."""
    counts = Counter(board.tiles[index].type for index in tray)
    singles = sum(count == 1 for count in counts.values())
    crowded = max(0, len(tray) - 4)
    return 45 * singles + 45 * crowded * crowded


def _local_triple(board, state, deadline, cancel_event, special_cards=None):
    """Compare legal short routes by depth cleared and cards exposed."""
    engine = ToolEngine(board)
    depth = _thickness(board, state.removed)
    start_visible = set(board.visible_indices(state))
    start_risk = _tray_risk(board, state.tray)
    candidates = []
    seen = {}
    nodes = 0

    def visit(current, path, score, peak, max_depth):
        nonlocal nodes
        nodes += 1
        if nodes > 120_000 or time.monotonic() >= deadline or (
                cancel_event is not None and cancel_event.is_set()):
            return
        key = (current.removed, current.tray, current.aux)
        if seen.get(key, -1) >= score:
            return
        seen[key] = score
        if len(path) >= max_depth or len(current.tray) >= 7:
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
            candidate_peak = max(peak, len(after.tray))
            if len(after.tray) < len(current.tray):
                fresh = set(board.visible_indices(after)) - start_visible
                exposure = sum(min(depth[i], 20) for i in fresh)
                risk_change = _tray_risk(board, after.tray) - start_risk
                rank = (candidate_score * 3 + exposure * 2
                        - len(after.tray) * 24 - len(candidate) * 65
                        - max(0, risk_change) * 2.25
                        - min(0, risk_change) * .5
                        - max(0, candidate_peak - 5) * 25)
                candidates.append((rank, candidate, after))
            else:
                visit(after, candidate, candidate_score, candidate_peak,
                      max_depth)

    # Short routes are explored across all opening cards before any four-click
    # route. Otherwise a large thick stack can consume the entire time budget
    # before a safe match on the other side of the board is considered.
    for max_depth in range(1, 5):
        seen.clear()
        visit(state, [], 0, len(state.tray), max_depth)
        if time.monotonic() >= deadline:
            break
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
        available = Counter(recolored.tiles[i].type for i in visible)
        available.update(recolored.tiles[stack[-1]].type
                         for stack in after.aux if stack)
        stranded = sum(count == 1 and available[kind] < 2
                       for kind, count in held.items())
        reachable = sum(count >= 3 and
                        len(after.tray) + 3 - held[kind] <= 7
                        for kind, count in counts.items())
        one_away = sum(held[kind] == 2 and counts[kind] >= 3
                       for kind in held)
        future = (rank + min(reachable, 6) * 28 + one_away * 20
                  - stranded * 30
                  - (180 if reachable == 0 and after.removed != board.all_mask
                     else 0))
        if best is None or future > best[0]:
            best = (future, path)
    return best[1]


def plan_next_crush(board, state, seconds=5, seed=0, cancel_event=None,
                    special_cards=None):
    """Find a triple before spending a tool, then validate any tool route."""
    if cancel_event is not None and cancel_event.is_set():
        return []
    if len(state.tray) >= 7:
        return ["REVIVE"] if not state.used_revive else []

    segment = _local_triple(board, state, time.monotonic() + seconds * .55,
                            cancel_event, special_cards)
    if segment or (cancel_event is not None and cancel_event.is_set()):
        return segment

    # Look farther without tools before spending either one. A static path is
    # valid only until its first actual triple, when changing cards recolor.
    engine = ToolEngine(board)
    result = search_with_tools(
        board, seconds=seconds * .25, max_states=180_000, max_branches=14,
        initial_state=engine.search_start(state), allow_remove=False,
        allow_revive=False, allow_unmatched_aux=True, seed=seed,
        cancel_event=cancel_event)
    if cancel_event is not None and cancel_event.is_set():
        return []
    segment = _segment(board, state, result["path"])
    if segment:
        return segment

    # Move Out is only useful if its freed slots lead to a verified triple.
    # Reserve Revive for a tray that has actually reached seven cards.
    if state.used_remove or len(state.tray) < 4:
        return []
    moved = engine.apply(state, "MOVE_OUT")
    segment = _local_triple(board, moved, time.monotonic() + seconds * .2,
                            cancel_event, special_cards)
    if cancel_event is not None and cancel_event.is_set():
        return []
    if not segment:
        result = search_with_tools(
            board, seconds=seconds * .1, max_states=100_000,
            max_branches=14, initial_state=engine.search_start(moved),
            allow_remove=False, allow_revive=False,
            allow_unmatched_aux=True, seed=seed, cancel_event=cancel_event)
        if cancel_event is not None and cancel_event.is_set():
            return []
        segment = _segment(board, moved, result["path"])
    return ["MOVE_OUT"] + segment if segment else []
