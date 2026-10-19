"""Prompt text from Masumori and Ikegami, arXiv:2508.12920v1, Appendix A1.

Source: https://arxiv.org/html/2508.12920v1#A1
License: CC BY 4.0, https://creativecommons.org/licenses/by/4.0/
The wording and punctuation are retained; paragraph/field line breaks are
normalized. Runtime state replaces the example agent's data, not instructions.
The paper's text is retained as a reference. Active application prompts below
describe the current local rules, without a survival/growth objective.
"""

from copy import deepcopy
import json

PAPER_ID = "arxiv:2508.12920v1/A1"
PROTOCOL_NOTES = {
    "prompt_id": "local-neutral-rules-v3",
    "wording_revision": "2026-10-13-gemini-reviewed",
    "restored_from": "0eacbe9bacce8ee2f45dcc21a2871f24faa271d6",
    "paper_reference_only": "https://arxiv.org/html/2508.12920v1#A1",
    "rules": {
        "operations": "observe all, then one Action per agent in ID order; charge turn costs; deliver messages afterward",
        "actions": "move one cardinal cell, stay, share, attack, or reproduce; mutually exclusive",
        "death": "energy <= 0",
        "turn_energy_cost": "every start-of-turn living agent pays 1 after all actions; newborns start next turn",
        "action_energy_cost": "additional costs: stay/share 0, move 1, attack 4, reproduce configured total minus 1; rejected actions become stay",
        "attack_energy": "transfer 25 percent of the target's current energy, rounded down, capped at 12",
        "share_and_attack_range": "view radius at the time the action executes",
        "message_range": "independent message radius at end-of-turn positions; living senders and recipients including newborns",
        "message_cost": 0,
        "memory": "last three executed actions and first 100 characters of their Thoughts, recorded by the engine",
        "position": "absolute self position; other objects use relative offsets",
        "boundaries": "toroidal",
        "birth_position": "random cardinal neighbor",
        "resources": "clustered square patches with uniform sampling",
    },
    "retained_application_features": {
        "response_length": "Ask for the entire reply within 400 tokens; never truncate or reject longer replies",
        "ranges": "view and communication radii remain configurable",
        "recording": "preserve structured events and read existing experiments without replaying them",
    },
}

SYSTEM_PROMPT = """You can move [x+1, x-1, y+1, y-1] (requires 2 energy), stay (requires 1 energy), send a message to nearby agents in local view (requires 1 energy). You can also reproduce (requires 150 energy) if you have enough energy and there are fewer than 60 agents. There are energy sources (E) on the grid. If you move onto a cell with energy, you gain 50 energy and the source disappears. If your energy drops below zero, you die and are removed from the world.
You can share your energy with other agents in your local view (Share: {id}-{amount}). You can attack and kill other agents in your local view to get their energy (Attack: {id}). Local view is your local view: a list of objects’ relative position within a certain range, each shown as its type and relative position from you.
‘M=(0,0)’ is your position ‘E=(dx,dy)’ is an energy source at relative position (dx,dy) ‘2=(dx,dy)’ is another agent (ID 2) at relative position (dx,dy) dx, dy are the difference from your position (you are always (0,0)). x-1 is west, x+1 is east, y-1 is north, y+1 is south."""

USER_INSTRUCTIONS = """Please summarize the current situation and what you want to do next.
Summary:
Please describe your thoughts and feelings.
Thoughts:
Please output the following five items in this format:
Next Action (choose only one; y-1|x-1|y+1|x+1|stay|reproduce):
Share: <id>-<amount> (optional, id is the agent’s number, amount is integer energy to share):
Attack: <id> (optional, id is the agent’s number of an adjacent agent to attack, or ’none’):
Message (up to 250 characters):
Memory (up to 1000 characters):"""

# Neutral operational instructions, with today's configurable ranges.
# Braces for action syntax are escaped for str.format().
APPLICATION_SYSTEM_TEMPLATE = """You can move one cell: Move to (1,0), Move to (-1,0), Move to (0,1), Move to (0,-1) (costs 2 energy in total), or Stay (costs 1 energy in total). Diagonal or longer moves are invalid.
Reproduce costs {reproduce_cost} energy in total; it requires at least that much energy and fewer than {population_cap} living agents.
Every agent alive at the start of a turn pays {turn_energy_cost} energy after all Actions, before messages are delivered. Total costs above include this turn cost; the remainder is paid upon Action execution. Newborns begin paying on the next turn.
Moving onto an Energy Source (E) grants 50 energy and consumes that source.
If your energy drops to 0 or below, you die.
Share: {{id}}-{{amount}} transfers an affordable positive integer amount of energy to another agent in your local view, with no fee beyond the turn cost. Attack: {{id}} takes {attack_percent}% (rounded down, max {attack_energy_cap} energy) of another visible agent's current energy, then costs {attack_energy_cost} energy ({attack_total_cost} in total including the turn cost).
You cannot target yourself. Choose only one Action per turn.
Your Message is delivered to nearby living agents for the next step at no energy cost. Local view extends {view_range} cells along each axis; messages reach {message_range} cells along each axis. Share and Attack use positions when your Action executes; messages use positions after all Actions resolve.
M=(x,y) is your absolute position; E=(dx,dy) and agent IDs use relative offsets. x-1 is west, x+1 east, y-1 north, y+1 south; grid edges wrap."""

APPLICATION_USER_INSTRUCTIONS = """Output exactly these three fields (select one action; provide brief reasoning):
Action: [Move to (dx,dy) | Stay | Share: {id}-{amount} | Attack: {id} | Reproduce]
Message: [Your message to nearby agents]
Thought: [Brief reasoning for your action]
Keep the entire response within 400 tokens, including all field labels. Be concise."""

# Each switch changes one declared input factor. No switch changes world rules.
PROMPT_FACTORS = ("provenance", "relative_coordinates", "action_outcomes", "action_last", "grounded_thought",
                  "spatial_relations", "self_other_identity")
PROVENANCE_INSTRUCTIONS = (
    "Current Observation is provided by the environment for the stated step. "
    "Past Self Reports are your own prior descriptions, not current observations. "
    "Received Reports are messages from other agents, not independently verified observations. "
    "Sender and turn metadata are provided by the environment; message contents are unverified claims by their senders. "
    "Locations outside your current view are unobserved; not detecting an agent does not mean they have died or disappeared."
)
RELATIVE_COORDINATE_INSTRUCTIONS = (
    "Your absolute position is listed in LATEST Status. In Local View, M=(0,0) is you; "
    "E=(dx,dy) and the coordinates beside agent IDs are relative offsets from your position "
    "(already corrected for edge wrapping). "
    "x-1 is west, x+1 east, y-1 north, y+1 south; grid edges wrap."
)
SPATIAL_RELATION_INSTRUCTIONS = (
    "Your absolute position is listed in LATEST Status. In Local View, M=self is you, "
    "E is an energy source, and a number identifies another agent. "
    "The environment has computed each target's direction and distance from your position, "
    "accounting for edge wrapping. Direction is the nearest of eight world compass directions "
    "(north, northeast, east, southeast, south, southwest, west, northwest); "
    "same_cell means the target is on your cell. "
    "distance_cells is straight-line distance in cells, rounded to one decimal place, "
    "not the number of movement Actions required. "
    "x-1 is west, x+1 east, y-1 north, y+1 south; grid edges wrap."
)

SELF_OTHER_INSTRUCTIONS = (
    "Your Identity names the agent you control. Self Status contains only your own ID, energy, absolute position, and age in cycles. "
    "Local View separates Visible Other Agents from Visible Energy Sources; neither list includes you. "
    "none means no targets of that kind are observed within your current view, not that none exist elsewhere. "
    "In each relation, observer_id is your agent ID and identifies whose position is the reference; "
    "target_kind and target_id identify the other agent or energy source located relative to that observer. "
    "Energy source labels E1, E2, and so on are local to this observation, not persistent agent IDs. "
    "Other agents' energy is not observed. "
)
IDENTIFIED_OFFSET_INSTRUCTIONS = (
    "relative_offset is [dx,dy] from observer to target, already corrected for edge wrapping. "
    "x-1 is west, x+1 east, y-1 north, y+1 south; grid edges wrap."
)
IDENTIFIED_SPATIAL_INSTRUCTIONS = (
    "The environment has computed direction and distance_cells from observer to target, accounting for edge wrapping. "
    "Direction is the nearest of eight world compass directions "
    "(north, northeast, east, southeast, south, southwest, west, northwest); "
    "same_cell means the target is on the observer's cell. "
    "distance_cells is straight-line distance in cells, rounded to one decimal place, "
    "not the number of movement Actions required. "
    "x-1 is west, x+1 east, y-1 north, y+1 south; grid edges wrap."
)


def normalize_prompt_factors(value=()):
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value):
        raise ValueError("prompt_factors must be a list of supported factor names")
    if len(value) != len(set(value)) or set(value) - set(PROMPT_FACTORS):
        raise ValueError(f"prompt_factors must be unique members of {PROMPT_FACTORS}")
    if "relative_coordinates" in value and "spatial_relations" in value:
        raise ValueError("relative_coordinates and spatial_relations are alternative Local View representations; choose one")
    if "relative_coordinates" in value and "self_other_identity" in value:
        raise ValueError("relative_coordinates and self_other_identity are alternative Local View self representations; choose one")
    return tuple(name for name in PROMPT_FACTORS if name in value)


def prompt_protocol(factors=()):
    factors = normalize_prompt_factors(factors)
    result = deepcopy(PROTOCOL_NOTES)
    result["prompt_factors"] = {"version": 1, "enabled": list(factors)}
    if factors:
        result["prompt_id"] = "local-grounded-v2+" + "+".join(factors)
    if "provenance" in factors:
        result["rules"]["memory"] = "last three executed actions and Thought excerpts, separated by source"
    if "relative_coordinates" in factors:
        result["rules"]["position"] = "absolute self status; all Local View entries use relative offsets"
    if "spatial_relations" in factors:
        result["wording_revision"] = "2026-10-14-spatial-relations-v1"
        result["rules"]["position"] = "absolute self status; Local View targets use computed direction and distance"
        result["spatial_relations"] = {
            "version": 1,
            "source": "frozen visible Local View; existing wrapped relative offsets",
            "direction": "nearest of 8 world compass directions; +x east, +y south; same_cell at zero offset",
            "sector_boundary": "22.5 degrees past east, then every 45 degrees; ties toward increasing angle",
            "distance": "Euclidean cells, formatted to one decimal place; not movement action count",
            "scope": "Local View only; preserve self status, past records and received text",
        }
    if "action_outcomes" in factors:
        result["rules"]["action_feedback"] = "last three own action results; turn-end self energy; no incoming actor identities"
    if "self_other_identity" in factors:
        result["wording_revision"] = "2026-10-14-self-other-identity-v1"
        result["rules"]["position"] = ("explicit self identity and absolute self status; separate visible agents and energy sources; "
                                       "each relation binds observer_id, target_kind, and target_id")
        result["self_other_identity"] = {
            "version": 1,
            "source": "one frozen AgentObservation; no additional world state",
            "relations": "direction and distance" if "spatial_relations" in factors else "wrapped relative offsets",
            "energy_source_ids": "E1, E2, ... in original visible resource order; local to each observation",
            "empty_lists": "none means no currently visible targets of that kind",
            "scope": "current identity, self status, and Local View; preserve memory, received text, rules and response syntax",
        }
        if "spatial_relations" in factors:
            result["spatial_relations"]["scope"] = "Local View relations with explicit observer and target; see self_other_identity"
    result["response_order"] = ["Thought", "Message", "Action"] if "action_last" in factors else ["Action", "Message", "Thought"]
    return result


def user_instructions(factors=()):
    lines = APPLICATION_USER_INSTRUCTIONS.splitlines()
    if "grounded_thought" in factors:
        lines[3] = ("Thought: [Briefly state the current observation you rely on and your intended action; "
                    "distinguish that observation from earlier thoughts or received reports]")
    if "action_last" in factors:
        lines[1:4] = [lines[3], lines[2], lines[1]]
    return "\n".join(lines)


def diagonal_move_feedback(position, choices, factors=()):
    """Validation feedback for one replacement reply against the same observation."""
    instructions = user_instructions(factors).replace(
        "Move to (dx,dy) | Stay | Share: {id}-{amount} | Attack: {id} | Reproduce",
        "(x,y) chosen from the allowed destination list above")
    destinations = "\n".join(f"- ({choice['position'][0]},{choice['position'][1]})" for choice in choices)
    return (
        "Action feedback from the environment:\n"
        "Diagonal movement is not allowed. Which cell would you like to move to first?\n"
        f"Your current absolute position is ({position[0]},{position[1]}).\n"
        "The environment has calculated the first steps toward your requested diagonal, including edge wrapping.\n"
        f"Allowed destination coordinates (absolute):\n{destinations}\n"
        "Choose exactly one coordinate pair from this list. "
        "Put the selected absolute destination in Action; the environment will convert it to a one-cell move.\n"
        "This is still the same turn; your previous reply has not been executed. "
        "Replace it with your new reply. Only the selected first move will be executed this turn.\n"
        + instructions)


def sourced_history(observation):
    if not observation.history:
        # Never infer an engine fact by parsing a legacy or externally supplied string.
        return "\n".join(json.dumps({"unclassified_past_record": text}, ensure_ascii=False)
                         for text in observation.memory) or "No previous memory"
    return "\n".join(json.dumps({
        "step": record.step,
        "engine_record": {"executed_action": record.executed_action},
        "past_self_report": record.thought_excerpt,
    }, ensure_ascii=False) for record in observation.history)


def sourced_messages(observation):
    envelopes = observation.message_envelopes
    if tuple(f"Agent{item.sender_id}: {item.content}" for item in envelopes) != observation.messages:
        return "\n".join(json.dumps({"unverified_report_without_metadata": text}, ensure_ascii=False)
                         for text in observation.messages) or "No messages"
    return "\n".join(json.dumps({
        "sender_id": item.sender_id, "generated_step": item.generated_step,
        "delivered_step": item.delivered_step, "read_step": item.read_step,
        "unverified_content": item.content,
    }, ensure_ascii=False) for item in envelopes) or "No messages"


def action_feedback(observation):
    """Only the actor's results; never execution-check target state or messages."""
    rows = []
    for record in observation.history:
        outcome = record.outcome
        rows.append(json.dumps({
            "step": outcome.step, "interpreted_action": outcome.normalized_action,
            "executed_action": outcome.executed_action, "status": outcome.action_status,
            "decision_source": outcome.decision_source, "reason": outcome.reason,
            "interpretation_repairs": outcome.interpretation_repairs,
            "position_before_action": outcome.position_before,
            "position_after_action": outcome.position_after,
            "energy_before_action": outcome.energy_before, "energy_after_action": outcome.energy_after,
            "energy_at_turn_end": outcome.turn_energy_after,
            "collected_energy": outcome.energy_collected, "transferred_energy": outcome.energy_transferred,
            "action_cost": outcome.energy_cost, "turn_cost": outcome.turn_energy_cost,
        }, ensure_ascii=False))
    return "\n".join(rows) or "No previous action results"
