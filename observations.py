"""Immutable per-agent evidence; no world updates, planning, or model calls."""

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import re


OBSERVATION_PROTOCOL = {
    "version": 1,
    "phase": "after_resource_spawn_before_all_decisions",
    "execution": "existing ID order and legality; context changes are audit-only",
    "history": "three completed turns; self Thought excerpt limited to 100 characters",
    "messages": "generated from start observation; delivered at turn end; read next turn",
    "world_state": "audit only; never included in the agent prompt",
}


_SELF_VIEW_ROW = re.compile(r"M=\(-?[0-9]+,-?[0-9]+\)")
_TARGET_VIEW_ROW = re.compile(
    r"(E|[0-9]+)=\((-?[0-9]+),(-?[0-9]+)\)( \(MBTI: [EI][NS][TF][JP]\))?"
)
_COMPASS_DIRECTIONS = ("east", "southeast", "south", "southwest",
                       "west", "northwest", "north", "northeast")


def _visible_targets(local_view):
    """Parse only engine-generated rows, already filtered and edge-wrapped."""
    if not local_view or not _SELF_VIEW_ROW.fullmatch(local_view[0]):
        raise ValueError("An engine Local View starting with M=(x,y) is required")
    targets = []
    for row in local_view[1:]:
        match = _TARGET_VIEW_ROW.fullmatch(row)
        if match is None:
            raise ValueError(f"Unsupported engine Local View row: {row!r}")
        tag, dx, dy, hint = match.groups()
        targets.append((tag, int(dx), int(dy), hint or ""))
    return targets


def _spatial_fields(dx, dy):
    if dx == dy == 0:
        direction = "same_cell"
    else:
        # +y is south; select the nearest 45-degree compass direction.
        sector = math.floor((math.degrees(math.atan2(dy, dx)) + 22.5) / 45) % 8
        direction = _COMPASS_DIRECTIONS[sector]
    return {"direction": direction, "distance_cells": float(f"{math.hypot(dx, dy):.1f}")}


def spatial_local_view(local_view):
    """Preserve the original direction/distance condition byte for byte."""
    rows = ["M=self"]
    for tag, dx, dy, hint in _visible_targets(local_view):
        relation = _spatial_fields(dx, dy)
        rows.append(f"{tag}: direction={relation['direction']}; distance_cells={relation['distance_cells']:.1f}{hint}")
    return tuple(rows)


def identified_observation(observation, *, spatial=False):
    """Bind self and targets using one frozen observation, never live world state."""
    others, resources = [], []
    for tag, dx, dy, hint in _visible_targets(observation.local_view):
        is_agent = tag != "E"
        target_id = int(tag) if is_agent else f"E{len(resources) + 1}"
        if is_agent and target_id == observation.agent_id:
            raise ValueError("Local View must not include self as another agent")
        relation = {"observer_id": observation.agent_id,
                    "target_kind": "agent" if is_agent else "energy_source", "target_id": target_id}
        relation.update(_spatial_fields(dx, dy) if spatial else {"relative_offset": [dx, dy]})
        if hint:
            relation["mbti"] = hint.removeprefix(" (MBTI: ").removesuffix(")")
        (others if is_agent else resources).append(json.dumps(relation, ensure_ascii=False))
    status = json.dumps({"agent_id": observation.agent_id, "energy": observation.energy,
                         "position": observation.position, "cycles": observation.age})
    return (f"Your Identity: You are Agent{observation.agent_id}. Your agent ID is {observation.agent_id}.\n"
            f"Self Status (you):\n{status}\nLocal View:\nVisible Other Agents:\n"
            + ("\n".join(others) or "none") + "\nVisible Energy Sources:\n"
            + ("\n".join(resources) or "none") + "\n")


@dataclass(frozen=True)
class MessageEnvelope:
    sender_id: int
    observation_id: str
    generated_step: int
    delivered_step: int
    read_step: int
    content: str


@dataclass(frozen=True)
class ActionOutcome:
    step: int
    observation_id: str
    normalized_action: str
    executed_action: str
    action_status: str
    decision_source: str
    reason: str
    position_before: tuple
    position_after: tuple
    energy_before: int
    energy_after: int
    turn_energy_after: int
    energy_collected: int
    energy_transferred: int
    energy_cost: int
    turn_energy_cost: int
    interpretation_repairs: tuple

    @classmethod
    def from_event(cls, step, event):
        return cls(step=step, observation_id=event["observation_id"],
                   normalized_action=event.get("normalized_action", ""),
                   executed_action=event["executed_action"], action_status=event["action_status"],
                   decision_source=event["decision_source"], reason=event.get("reason", ""),
                   position_before=tuple(event["position_before"]),
                   position_after=tuple(event["position_after"]),
                   energy_before=event["energy_before"], energy_after=event["energy_after"],
                   turn_energy_after=event["turn_energy_after"],
                   energy_collected=event["energy_collected"],
                   energy_transferred=event["energy_transferred"],
                   energy_cost=event["energy_cost"], turn_energy_cost=event["turn_energy_cost"],
                   interpretation_repairs=tuple(item["rule"] for item in event.get("response_repairs", ())))


@dataclass(frozen=True)
class PastDecision:
    step: int
    executed_action: str
    thought_excerpt: str
    outcome: ActionOutcome


@dataclass(frozen=True)
class AgentObservation:
    run_id: str
    observation_id: str
    world_state_id: str
    step: int
    agent_id: int
    position: tuple
    energy: int
    age: int
    num_agents: int
    grid_size: int
    view_range: int
    message_range: int
    local_view: tuple
    memory: tuple
    messages: tuple
    history: tuple
    message_envelopes: tuple

    def to_dict(self):
        return asdict(self)


def prompt_hashes(system, user):
    return {name: hashlib.sha256(text.encode("utf-8")).hexdigest()
            for name, text in (("system", system), ("user", user))}
