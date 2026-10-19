"""Shared display states for the board, live dialogue and saved timeline."""

from pathlib import Path
from response_fields import decision_notice, reading_fields

ICONS = {
    "dead": ("😇", "死んだ", "1f607"),
    "hungry": ("😱", "空腹", "1f631"),
    "normal": ("🙂", "普通", "1f642"),
    "comfortable": ("😊", "余裕", "1f60a"),
    "attack": ("😡", "攻撃", "1f621"),
    "hurt": ("😭", "被ダメージ", "1f62d"),
    "share": ("😘", "分配", "1f618"),
    "reproduce": ("🥰", "繁殖", "1f970"),
    "panic": ("😵‍💫", "パニック", "1f635-200d-1f4ab"),
    "resource": ("🍬", "砂糖", "candy-pink"),
}
HUNGRY_BELOW = 50
COMFORTABLE_FROM = 150
ICON_DIRECTORY = Path(__file__).resolve().parent / "assets" / "emoji"
SILENT_MESSAGES = {"", "none", "no message", "null", "n/a"}


def icon_path(state):
    return ICON_DIRECTORY / f"{ICONS[state][2]}.png"


def is_executed_attack(event):
    if "attack_status" in event:
        return event["attack_status"] == "executed"
    return event.get("kind") == "attack" and event.get("action_status") == "executed"


def is_executed_share(event):
    if "share_status" in event:
        return event["share_status"] == "executed"
    return event.get("kind") == "share" and event.get("action_status") == "executed"


def attack_victims(events):
    """Only executed attacks cause damage; ordinary energy costs do not."""
    victims = set()
    for event in events:
        if not is_executed_attack(event):
            continue
        target = event.get("executed_attack") if "attack_status" in event else event.get("target_id")
        try:
            victims.add(int(target))
        except (TypeError, ValueError):
            pass
    return victims


def is_panicked(event):
    """An exhausted reply with no usable action gets a display-only state."""
    return event.get("finish_reason") == "length" and any(
        repair.get("field") == "Next Action" and repair.get("rule") == "default_stay"
        for repair in event.get("response_repairs", []))


def agent_states(agent, event=None, victims=()):
    """Death wins; an attacked death also carries the damage icon this turn."""
    event = event or {}
    if not agent.get("alive", True):
        return ("dead", "hurt") if agent["id"] in victims else ("dead",)
    if is_executed_share(event):
        return ("share",)
    if agent["id"] in victims:
        return ("hurt",)
    if is_panicked(event):
        return ("panic",)
    if is_executed_attack(event):
        return ("attack",)
    if event.get("executed_action", "").casefold() == "reproduce":
        return ("reproduce",)
    if agent.get("energy", 100) < HUNGRY_BELOW:
        return ("hungry",)
    if agent.get("energy", 100) >= COMFORTABLE_FROM:
        return ("comfortable",)
    return ("normal",)


def agent_heading(agent, event=None, victims=()):
    states = agent_states(agent, event, victims)
    faces = "".join(ICONS[state][0] for state in states)
    label = "　パニック" if "panic" in states else ""
    return f"{faces} エージェント {agent['id']:02d}{label}"


def display_message(text):
    return "(無言)" if (text or "").strip().casefold() in SILENT_MESSAGES else text


def format_live_decision(event, agent, victims=()):
    """Show the agent's current face alongside each received response."""
    fields = reading_fields(event)
    notice = decision_notice(event)
    heading = agent_heading(agent, event, victims) + (f"　{notice}" if notice else "")
    return (f"{heading}\n"
            f"💬 {display_message(fields.get('message'))}\n"
            f"💭 {fields.get('thought') or '（記録なし）'}")


def step_pages(logs, page_size=10):
    steps = sorted((snap for snap in logs if snap["step"] > 0), key=lambda snap: snap["step"])
    return [steps[start:start + page_size] for start in range(0, len(steps), page_size)]


def event_steps(logs):
    """Index occurrences, not persistent faces or unexecuted requests."""
    found = {state: [] for state in ("dead", "attack", "hurt", "share", "reproduce")}
    previous = {}
    for snapshot in sorted(logs, key=lambda item: item["step"]):
        step = snapshot["step"]
        agents = snapshot["agents"]
        if step > 0:
            if any(not agent["alive"] and (agent.get("death_step") == step or
                   previous.get(agent["id"], {}).get("alive", False)) for agent in agents):
                found["dead"].append(step)
            if any(is_executed_attack(event) for event in snapshot["events"]):
                found["attack"].append(step)
            if attack_victims(snapshot["events"]):
                found["hurt"].append(step)
            if any(is_executed_share(event) for event in snapshot["events"]):
                found["share"].append(step)
            if any(event.get("executed_action", "").casefold() == "reproduce"
                   for event in snapshot["events"]):
                found["reproduce"].append(step)
        previous = {agent["id"]: agent for agent in agents}
    return found


def page_numbers(total, current, width=5):
    start = max(1, min(current - width // 2, total - width + 1))
    return list(range(start, min(total + 1, start + width)))
