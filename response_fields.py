"""Read response sections separately from deciding whether an action is valid."""

import re
import unicodedata
from native_geometry import absolute_move, cardinal_destinations

READING_LABELS = {"message": "message", "thought": "thoughts", "summary": "summary", "memory": "memory"}
ACTION_PATTERN = r"(?:[xy]\s*[+-]\s*1|stay|reproduce)"
MOVE_DIRECTIONS = {(1, 0): "x+1", (-1, 0): "x-1", (0, 1): "y+1", (0, -1): "y-1"}
ACTION_REPAIR_POLICY = {
    "version": 5,
    "scope": "Read each field independently; missing prose is empty; repeated fields use the last value",
    "actions": "Use the first supported command in the last action field; otherwise stay",
    "absolute_move": "Keep valid relative moves; otherwise convert an in-grid absolute destination only when it is one unambiguous cardinal step from the observed position, including wrapped edges",
    "optional_operations": "Share and Attack execute only when selected in Action; separate fields are retained for inspection only",
    "truncation": "Use available response text even when finish_reason is length",
    "retries": 1,
    "retry_scope": "Unusable diagonal Move to commands only; one same-turn replacement against the frozen observation",
    "retry_selection": "Choose which of the two axis steps toward the requested diagonal to take first, using computed absolute destinations; execute only that step; no listed selection means Stay without a Message",
    "retry_wording_revision": "2026-10-14-diagonal-two-destinations-v2",
}


def _action_text(text):
    # Normalize notation, never infer a direction from goals or world state.
    return unicodedata.normalize("NFKC", text).translate(str.maketrans({
        "−": "-", "–": "-", "’": "'",
    })).strip().casefold()


def _action_atom(text):
    text = _action_text(text).rstrip(".。;").strip()
    # Distinguish plain notation repairs from a command found in prose.
    # Repeat to allow e.g. **`x + 1`**.
    wrappers = (("**", "**"), ("`", "`"), ("[", "]"), ('"', '"'), ("'", "'"))
    while True:
        for start, end in wrappers:
            if len(text) > len(start) + len(end) and text.startswith(start) and text.endswith(end):
                text = text[len(start):-len(end)].strip()
                break
        else:
            break
    if re.fullmatch(ACTION_PATTERN, text):
        return re.sub(r"\s+", "", text)
    return None


def _absolute_move(target, position, grid_size):
    """Convert only a uniquely adjacent destination, never a route or a goal."""
    if position is None or type(grid_size) is not int or grid_size < 1:
        return None
    if len(position) != 2 or any(type(n) is not int or not 0 <= n < grid_size for n in (*position, *target)):
        return None
    # On a two-cell axis, east and west reach the same destination. Keep such
    # ambiguous absolute commands uncorrected; explicit relative moves work.
    return absolute_move(target, position, grid_size)


def resolve_next_action(values, *, position=None, grid_size=None, destination_choices=None):
    """Read a usable command without grading the surrounding explanation."""
    value = values[-1] if values else ""
    text = _action_text(value)
    if destination_choices is not None:
        # This explicit retry mode resolves coordinate pairs as destinations,
        # even when the pair is also valid relative notation, e.g. (1,0).
        selected = re.fullmatch(r"(?:move\s+to\s*)?\(\s*([+-]?\d+)\s*,\s*([+-]?\d+)\s*\)",
                                text.strip(" []`*"))
        try:
            target = [int(selected[1]), int(selected[2])] if selected else None
        except ValueError:
            target = None
        choice = next((choice for choice in destination_choices if choice["position"] == target), None)
        if choice is not None:
            action = MOVE_DIRECTIONS[tuple(choice["delta"])]
            return action, [{"field": "Next Action", "rule": "selected_destination_to_delta",
                             "original": values.copy(), "normalized": action,
                             "observed_position": list(position), "target_position": target,
                             "delta": choice["delta"].copy(), "grid_size": grid_size}]
        return "stay", [{"field": "Next Action", "rule": "invalid_destination_selection",
                         "original": values.copy(), "normalized": "stay"}]
    atom = _action_atom(text)
    # A command can have an explanation, Markdown, or other choices after it.
    # Pick one deterministically; never execute two moves in one turn.
    found = re.search(rf"(?<![\w])({ACTION_PATTERN})(?!\w|\.\d)", text)
    candidates = [(found.start(), re.sub(r"\s+", "", found[1]), None)] if found else []
    diagonal_moves = []
    for move in re.finditer(r"move\s+to\s*\(\s*([+-]?\d+)\s*,\s*([+-]?\d+)\s*\)", text):
        try:
            coordinates = (int(move[1]), int(move[2]))
        except ValueError:
            continue
        direction = MOVE_DIRECTIONS.get(coordinates)
        if direction:
            candidates.append((move.start(), direction, None))
        elif (delta := _absolute_move(coordinates, position, grid_size)) is not None:
            candidates.append((move.start(), MOVE_DIRECTIONS[delta], {
                "observed_position": list(position), "target_position": list(coordinates),
                "delta": list(delta), "grid_size": grid_size}))
        elif all(coordinates):
            diagonal_moves.append({"text": move[0], "delta": list(coordinates)})
    for share in re.finditer(r"\bshare\s*:\s*(?:agent\s*)?(\d+)\s*[-:,]\s*([+-]?\d+)(?!\w|\.\d)", text):
        candidates.append((share.start(), f"share: {share[1]}-{share[2]}", None))
    for attack in re.finditer(r"\battack\s*:\s*(?:agent\s*)?(\d+)(?!\w|\.\d)", text):
        candidates.append((attack.start(), f"attack: {attack[1]}", None))
    selected = min(candidates, key=lambda item: item[0]) if candidates else None
    action = atom or (selected[1] if selected else None)
    absolute_repair = selected[2] if selected and not atom else None
    rule = "notation" if atom else "command_in_text"
    if action is None:
        action, rule = "stay", "default_stay"
    elif len(values) > 1:
        rule = "last_field"
    repairs = []
    # The restored three-field interface uses Move to (dx,dy) as its ordinary
    # spelling. Mapping this supported notation is not a response repair.
    normal_move = re.fullmatch(r"move to \(([+-]?[01]),([+-]?[01])\)", text)
    normal = value.strip().casefold() == action or (
        normal_move is not None and abs(int(normal_move[1])) + abs(int(normal_move[2])) == 1)
    if len(values) != 1 or (not normal and absolute_repair is None):
        repairs.append({"field": "Next Action", "rule": rule, "original": values.copy(), "normalized": action})
    if absolute_repair is not None:
        repairs.append({"field": "Next Action", "rule": "absolute_target_to_delta",
                        "original": [value], "normalized": action, **absolute_repair})
    if rule == "default_stay" and diagonal_moves:
        repairs.append({"field": "Next Action", "rule": "diagonal_move_rejected",
                        "original": [move["text"] for move in diagonal_moves], "normalized": "stay",
                        "requested_delta": diagonal_moves[0]["delta"]})
    return action, repairs


def response_sections(response):
    """Read labels tolerantly while retaining their occurrences and original values."""
    response = response.strip()
    if response.startswith("```") and response.endswith("```"):
        response = "\n".join(response.splitlines()[1:-1])
    labels = "Summary|Thoughts?|Next Action|Action|Share|Attack|Message|Memory"
    headers = list(re.finditer(
        rf"^[ \t]*(?:[-*#>] |\d+[.)] )?[ \t]*[*_`]*({labels})[*_`]*(?:[ \t]*\([^\n:：]*\))?[ \t]*[:：][*_`]*[ \t]*",
        response, re.M | re.I))
    sections = []
    for index, match in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(response)
        text = response[match.end():end].strip()
        if text.startswith("[") and text.endswith("]"):
            text = text[1:-1].strip()
        label = {"action": "Next Action", "thought": "Thoughts"}.get(match[1].lower(), match[1])
        sections.append((label, text))
    return sections


def reading_fields(event):
    """Recover unambiguous prose for display only; never modify execution data."""
    fields = {key: event[key] for key in READING_LABELS if isinstance(event.get(key), str)}
    if (event.get("decision_source") == "fallback" and event.get("error_kind") == "parse_error"
            and isinstance(event.get("raw_response"), str)):
        sections = response_sections(event["raw_response"])
        for key, label in READING_LABELS.items():
            values = [text for name, text in sections if name.lower() == label]
            # A repeated action must not hide a unique thought/message. A
            # repeated prose field is ambiguous: retain only the raw response.
            if not fields.get(key, "").strip() and len(values) == 1:
                fields[key] = values[0]
    return fields


def decision_notice(event):
    if event.get("decision_source") != "fallback":
        return ""
    cause = {"parse_error": "応答の形式エラー", "invalid_action": "移動先の選び直しが不成立"}.get(
        event.get("error_kind"), "応答エラー")
    action = "死亡で未実行" if event.get("action_status") == "skipped_dead" else "行動は待機に置換"
    return f"⚠️ {cause}（{action}・メッセージ未送信）"
