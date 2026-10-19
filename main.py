"""Local-LLM Sugarscape: small experiments with an auditable data trail."""

import argparse
import asyncio
from copy import deepcopy
import json
import os
import random
import re
import sys
import time
import unicodedata
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

import aiohttp
import numpy as np

from run_data import RunRecorder, collect_runs, export_run, provenance
from model_identity import ModelIdentity
from grid_view import draw_grid, PLOT_LOCK
from paper_prompts import (APPLICATION_SYSTEM_TEMPLATE, PROMPT_FACTORS, PROVENANCE_INSTRUCTIONS,
                          RELATIVE_COORDINATE_INSTRUCTIONS, SPATIAL_RELATION_INSTRUCTIONS,
                          SELF_OTHER_INSTRUCTIONS, IDENTIFIED_OFFSET_INSTRUCTIONS, IDENTIFIED_SPATIAL_INSTRUCTIONS,
                          action_feedback, diagonal_move_feedback, normalize_prompt_factors,
                          prompt_protocol, sourced_history, sourced_messages, user_instructions)
from llm_api import (REASONING_EFFORTS, REASONING_FORMATS, REASONING_MODES, REQUEST_OPTION_DEFAULTS, TOKEN_LIMIT_PARAMETERS,
                     chat_completion_request, ensure_server_reachable, request_options, validate_base_url)
from response_fields import cardinal_destinations, response_sections, resolve_next_action
from observations import (AgentObservation, ActionOutcome, MessageEnvelope, PastDecision,
                          identified_observation, prompt_hashes, spatial_local_view)

NUM_CLUSTERS = 3
CLUSTER_RADIUS = 5
VIEW_RANGE = 5
MESSAGE_RANGE = 5
# 新しい定数（paramsでオーバーライド可能）
INITIAL_ENERGY = 100
SPAWN_ENERGY_COUNT = 20
REPRODUCE_COST = 70
CHILD_INITIAL_ENERGY = 100  # 出生時のエージェントの体力
ENERGY_SPAWN_RATE = 0.2  # 1ターン20%で1か所追加（平均10ターンに2か所）。
CUSTOM_WORLD_PROMPT = ""  # デフォルト空、世界観カスタム
TURN_ENERGY_COST = 1
ATTACK_ENERGY_COST = 4  # Plus the common turn cost: 5 in total.
ATTACK_ENERGY_DIVISOR = 4
ATTACK_ENERGY_CAP = 12

# MBTIパーソナリティ（PIMMUR Profile強化: 現実人口分布反映）
MBTI_TYPES = [
    "INTJ", "INTP", "ENTJ", "ENTP", "INFJ", "INFP", "ENFJ", "ENFP",
    "ISTJ", "ISFJ", "ESTJ", "ESFJ", "ISTP", "ISFP", "ESTP", "ESFP"
]

# 世界人口割合（%）: Myers-Briggs/16Personalities統計から
POPULATION_WEIGHTS = [
    0.021,  # INTJ: 2.1%
    0.033,  # INTP: 3.3%
    0.018,  # ENTJ: 1.8%
    0.032,  # ENTP: 3.2%
    0.015,  # INFJ: 1.5%
    0.044,  # INFP: 4.4%
    0.025,  # ENFJ: 2.5%
    0.081,  # ENFP: 8.1%
    0.116,  # ISTJ: 11.6%
    0.138,  # ISFJ: 13.8%
    0.087,  # ESTJ: 8.7%
    0.123,  # ESFJ: 12.3%
    0.054,  # ISTP: 5.4%
    0.088,  # ISFP: 8.8%
    0.043,  # ESTP: 4.3%
    0.085   # ESFP: 8.5%
]

# 記述追加用辞書（プロンプト用）
MBTI_DESCRIPTIONS = {
    "INTJ": "Architect - Strategic, independent, high standards.",
    "INTP": "Logician - Innovative, analytical, curious.",
    "ENTJ": "Commander - Bold, strong-willed, charismatic.",
    "ENTP": "Debater - Quick-witted, clever, resourceful.",
    "INFJ": "Advocate - Insightful, principled, passionate.",
    "INFP": "Mediator - Empathetic, creative, idealistic.",
    "ENFJ": "Protagonist - Charismatic, inspiring, empathetic.",
    "ENFP": "Campaigner - Enthusiastic, creative, sociable.",
    "ISTJ": "Logistician - Honest, dutiful, practical.",
    "ISFJ": "Defender - Warm, responsible, harmonious.",
    "ESTJ": "Executive - Efficient, strong-willed, organized.",
    "ESFJ": "Consul - Sociable, caring, loyal.",
    "ISTP": "Virtuoso - Practical, adaptable, analytical.",
    "ISFP": "Adventurer - Gentle, sensitive, artistic.",
    "ESTP": "Entrepreneur - Energetic, perceptive, bold.",
    "ESFP": "Entertainer - Spontaneous, energetic, sociable."
}



class Environment:
    """Toroidal grid with finite, clustered resource placement."""

    def __init__(self, size=30, energy_spawn_rate=ENERGY_SPAWN_RATE,
                 num_clusters=NUM_CLUSTERS, cluster_radius=CLUSTER_RADIUS, rng=None):
        self.size = size
        self.energy_spawn_rate = energy_spawn_rate
        self.num_clusters = num_clusters
        self.cluster_radius = min(cluster_radius, (size - 1) // 2)
        self.rng = rng or random.Random()
        self.energy_sources = {}

    def spawn_energy(self, count=SPAWN_ENERGY_COUNT, num_clusters=None, cluster_radius=None):
        radius = self.cluster_radius if cluster_radius is None else min(cluster_radius, (self.size - 1) // 2)
        clusters = self.num_clusters if num_clusters is None else num_clusters
        centers = [(self.rng.randrange(radius, self.size - radius),
                    self.rng.randrange(radius, self.size - radius)) for _ in range(clusters)]
        candidates = sorted({((x + dx) % self.size, (y + dy) % self.size)
                             for x, y in centers for dx in range(-radius, radius + 1)
                             for dy in range(-radius, radius + 1)} - self.energy_sources.keys())
        selected = self.rng.sample(candidates, min(count, len(candidates)))
        if len(selected) < count:
            remaining = sorted({(x, y) for x in range(self.size) for y in range(self.size)}
                               - self.energy_sources.keys() - set(selected))
            selected.extend(self.rng.sample(remaining, min(count - len(selected), len(remaining))))
        self.energy_sources.update({pos: 50 for pos in selected})

    def get_energy_at(self, pos):
        return self.energy_sources.pop(pos, 0)

    def is_valid_position(self, pos):
        return all(0 <= coordinate < self.size for coordinate in pos)

    def relative(self, origin, target):
        return tuple((b - a + self.size // 2) % self.size - self.size // 2
                     for a, b in zip(origin, target))

    def random_spawn(self):
        if self.rng.random() < self.energy_spawn_rate:
            self.spawn_energy(count=1)


class LLMAgent:
    def __init__(self, agent_id, position, initial_energy=INITIAL_ENERGY,
                 api_key=None, model="default_model", mbti_type=None,
                 custom_world_prompt=CUSTOM_WORLD_PROMPT, use_mbti=False, born_step=0, prompt_factors=()):
        self.id, self.position, self.energy = agent_id, position, initial_energy
        self.age, self.born_step = 0, born_step
        self.memory, self.messages, self.next_messages = [], [], []
        # Structured evidence stays separate from legacy UI-facing strings.
        self.history, self.message_envelopes, self.next_message_envelopes = [], [], []
        self.parent, self.descendants = None, []
        self.alive, self.death_step, self.death_cause = True, None, None
        self.model = model
        self.thoughts, self.action, self.message = "", "", ""
        self.summary = ""
        self.shared_energy, self.attacked_by = {}, []
        self.custom_world_prompt = custom_world_prompt
        self.prompt_factors = normalize_prompt_factors(prompt_factors)
        self.mbti_type = (mbti_type or "INTJ") if use_mbti else None
        self.personality_prompt = (
            f"You have the personality of {self.mbti_type}: {MBTI_DESCRIPTIONS[self.mbti_type]}. "
            "Let this influence your decisions." if use_mbti else "")

    def to_dict(self):
        return {"id": self.id, "position": self.position, "energy": self.energy,
                "age": self.age, "alive": self.alive,
                "parent": self.parent.id if self.parent else None,
                "descendants": [child.id for child in self.descendants],
                "born_step": self.born_step, "death_step": self.death_step,
                "death_cause": self.death_cause, "thoughts": self.thoughts,
                "action": self.action, "message": self.message, "mbti_type": self.mbti_type,
                "summary": self.summary, "shared_energy": dict(self.shared_energy),
                "attacked_by": list(self.attacked_by),
                "memory": self.memory[-3:], "messages": list(self.messages)}

    def get_local_view(self, environment, agents, view_range=VIEW_RANGE):
        view = [f"M=({self.position[0]},{self.position[1]})"]
        for pos in sorted(environment.energy_sources):
            dx, dy = environment.relative(self.position, pos)
            if abs(dx) <= view_range and abs(dy) <= view_range:
                view.append(f"E=({dx},{dy})")
        for other in agents:
            if other.id == self.id or not other.alive:
                continue
            dx, dy = environment.relative(self.position, other.position)
            if abs(dx) <= view_range and abs(dy) <= view_range:
                hint = f" (MBTI: {other.mbti_type})" if other.mbti_type else ""
                view.append(f"{other.id}=({dx},{dy}){hint}")
        return view, list(self.messages)

    def build_prompt(self, local_view, local_messages, num_agents,
                     reproduce_cost=REPRODUCE_COST, population_cap=60,
                     view_range=VIEW_RANGE, message_range=MESSAGE_RANGE, *, observation=None):
        factors = self.prompt_factors
        if factors and observation is None:
            raise ValueError("Prompt factors require a frozen observation")
        position, energy, age, agent_id = self.position, self.energy, self.age, self.id
        memory = self.memory[-3:]
        if observation is not None:
            position, energy, age, agent_id = (observation.position, observation.energy,
                                               observation.age, observation.agent_id)
            local_view, local_messages = observation.local_view, observation.messages
            memory, num_agents = observation.memory, observation.num_agents
        rules = APPLICATION_SYSTEM_TEMPLATE.format(
            reproduce_cost=reproduce_cost, population_cap=population_cap,
            view_range=view_range, message_range=message_range,
            turn_energy_cost=TURN_ENERGY_COST,
            attack_energy_cost=ATTACK_ENERGY_COST,
            attack_total_cost=ATTACK_ENERGY_COST + TURN_ENERGY_COST,
            attack_percent=100 // ATTACK_ENERGY_DIVISOR,
            attack_energy_cap=ATTACK_ENERGY_CAP)
        if "self_other_identity" in factors:
            relation_rules = (IDENTIFIED_SPATIAL_INSTRUCTIONS if "spatial_relations" in factors
                              else IDENTIFIED_OFFSET_INSTRUCTIONS)
            rules = rules.rsplit("\n", 1)[0] + "\n" + SELF_OTHER_INSTRUCTIONS + relation_rules
        elif "relative_coordinates" in factors:
            # Replace the existing coordinate paragraph, not the action rules.
            rules = rules.rsplit("\n", 1)[0] + "\n" + RELATIVE_COORDINATE_INSTRUCTIONS
            local_view = ("M=(0,0)", *local_view[1:])
        elif "spatial_relations" in factors:
            rules = rules.rsplit("\n", 1)[0] + "\n" + SPATIAL_RELATION_INSTRUCTIONS
            local_view = spatial_local_view(local_view)
        if "provenance" in factors:
            rules += "\n\n" + PROVENANCE_INSTRUCTIONS
        system_prompt = "\n\n".join(part for part in (
            self.custom_world_prompt, self.personality_prompt, rules) if part)
        step_header = f"Current Step: {observation.step}\n" if observation is not None else ""
        current_header = (f"Current Observation (Step {observation.step}; source: environment):\n"
                          if "provenance" in factors else "")
        memory_header = "Past Records (engine actions and Past Self Reports)" if "provenance" in factors else "Memory"
        memory_text = sourced_history(observation) if "provenance" in factors else "\n".join(memory) or "No previous memory"
        message_header = "Received Reports (unverified content)" if "provenance" in factors else "Messages"
        message_text = sourced_messages(observation) if "provenance" in factors else "\n".join(local_messages) or "No messages"
        feedback = ("Self Action Results (source: environment; completed turns):\n"
                    + action_feedback(observation) + "\n" if "action_outcomes" in factors else "")
        current_state = (identified_observation(observation, spatial="spatial_relations" in factors)
                         if "self_other_identity" in factors else
                         f"Local View:\n{chr(10).join(local_view)}\n"
                         f"LATEST Status: Agent{agent_id}, Energy: {energy}, Position: {position}, Cycles: {age}\n")
        user_prompt = (
            f"Global Info: Total Agents in the World: {num_agents}\n"
            f"{step_header}"
            f"{current_header}"
            f"{current_state}"
            f"{memory_header}:\n{memory_text}\n"
            f"{feedback}"
            f"{message_header}:\n{message_text}\n"
            f"{user_instructions(factors)}"
        )
        return system_prompt, user_prompt


def parse_response(response, *, position=None, grid_size=None, destination_choices=None):
    """Read useful fields independently; formatting mistakes do not reject a reply."""
    fields = {}
    occurrences = {}
    for name, text in response_sections(response):
        label = name.lower()
        occurrences.setdefault(label, []).append(text)
        fields[label] = text
    action_fields = occurrences.get("next action", [])
    if not fields:
        # Also accept a bare command without any headings.
        action_fields = [response]
    elif not action_fields and len(fields) == 1 and next(iter(fields)) in ("share", "attack"):
        label, value = next(iter(fields.items()))
        action_fields = [f"{label.title()}: {value}"]
    action, repairs = resolve_next_action(action_fields, position=position, grid_size=grid_size,
                                         destination_choices=destination_choices)
    for label, values in occurrences.items():
        if label != "next action" and len(values) > 1:
            repairs.append({"field": label.title(), "rule": "last_field",
                            "original": values, "normalized": values[-1]})
    directions = {"x-1": (-1, 0), "x+1": (1, 0), "y-1": (0, -1), "y+1": (0, 1)}
    parsed = {"requested_action": "\nNext Action: ".join(action_fields), "normalized_action": action,
              "response_repairs": repairs, "summary": fields.get("summary", ""),
              "thought": fields.get("thoughts", ""), "memory": fields.get("memory", ""),
              "message": fields.get("message", ""), "requested_share": fields.get("share", ""),
              "requested_attack": fields.get("attack", ""), "share": None, "attack": None,
              "kind": "move" if action in directions else action}
    if action in directions:
        parsed.update(zip(("dx", "dy"), directions[action]))
    interaction = re.fullmatch(r"(share|attack): (\d+)(?:-([+-]?\d+))?", action)
    if interaction:
        try:
            parsed.update(kind=interaction[1], target_id=int(interaction[2]))
            if interaction[1] == "share":
                parsed["amount"] = int(interaction[3])
        except (ValueError, TypeError):
            parsed.update(kind="stay", normalized_action="stay")
            repairs.append({"field": "Next Action", "rule": "default_stay",
                            "original": action_fields, "normalized": "stay"})
    silent = {"", "none", "no message", "null", "n/a"}
    if parsed["message"].casefold() in silent:
        parsed["message"] = ""
    for label in ("share", "attack"):
        value = fields.get(label, "")
        if value.casefold() in silent:
            continue
        value = unicodedata.normalize("NFKC", value).replace("−", "-").replace("–", "-").strip(" *`[]")
        pattern = r"(?:Agent\s*)?(\d+)\s*[-:,]\s*([+-]?\d+)" if label == "share" else r"(?:Agent\s*)?(\d+)"
        found = re.match(pattern, value, re.I)
        try:
            target = int(found[1]) if found else None
            amount = int(found[2]) if found and label == "share" else None
        except ValueError:
            target = None
        if target is None:
            repairs.append({"field": label.title(), "rule": "ignored_unreadable",
                            "original": [fields[label]], "normalized": "none"})
            continue
        parsed[label] = {"target_id": target}
        if label == "share":
            parsed[label]["amount"] = amount
        normalized = f"{target}-{amount}" if label == "share" else str(target)
        if fields[label] != normalized:
            repairs.append({"field": label.title(), "rule": "target_notation",
                            "original": [fields[label]], "normalized": normalized})
    # Share/Attack are main Actions again, not independent extra operations.
    # Preserve separately returned fields for the audit trail; only the selected
    # Action below determines execution.
    if parsed["kind"] in ("share", "attack"):
        label = parsed["kind"]
        parsed[label] = {"target_id": parsed["target_id"]}
        normalized = str(parsed["target_id"])
        if label == "share":
            parsed[label]["amount"] = parsed["amount"]
            normalized += f"-{parsed['amount']}"
        parsed[f"requested_{label}"] = normalized
    return parsed


class Simulation:
    """Observe a shared start-of-step state, then apply decisions in agent ID order."""

    def __init__(self, num_agents=5, grid_size=30, api_key=None, model="default_model", seed=0,
                 use_mbti=False, initial_energy=INITIAL_ENERGY, spawn_energy_count=SPAWN_ENERGY_COUNT,
                 reproduce_cost=REPRODUCE_COST, child_initial_energy=CHILD_INITIAL_ENERGY,
                 cluster_radius=CLUSTER_RADIUS, num_clusters=NUM_CLUSTERS,
                 energy_spawn_rate=ENERGY_SPAWN_RATE, custom_world_prompt=CUSTOM_WORLD_PROMPT,
                 base_url="http://127.0.0.1:8080/v1", mock_mode=False, temperature=0.0,
                 max_tokens=5000, top_p=1.0, timeout=120.0, population_cap=60,
                 view_range=VIEW_RANGE, message_range=MESSAGE_RANGE,
                 send_temperature=True, send_top_p=True, reasoning_mode="default",
                 reasoning_effort="medium", reasoning_format="openai", max_tokens_parameter="max_tokens",
                 prompt_factors=()):
        if grid_size < 1 or not 1 <= num_agents <= population_cap:
            raise ValueError("grid_size must be positive and 1 <= num_agents <= population_cap")
        if min(initial_energy, reproduce_cost, child_initial_energy, num_clusters, max_tokens) <= 0:
            raise ValueError("Energy settings, num_clusters and max_tokens must be positive")
        if cluster_radius < 0 or not 0 <= spawn_energy_count <= grid_size ** 2:
            raise ValueError("Invalid cluster radius or source count")
        if not 0 <= energy_spawn_rate <= 1 or not 0 <= temperature <= 2 or not 0 < top_p <= 1 or timeout <= 0:
            raise ValueError("Invalid spawn rate, temperature, top_p or timeout")
        if any(type(value) is not int or value < 0 for value in (view_range, message_range)):
            raise ValueError("Observation and communication radii must be nonnegative integers")
        validate_base_url(base_url)
        self.prompt_factors = normalize_prompt_factors(prompt_factors)
        self.request_options = request_options({
            "send_temperature": send_temperature, "send_top_p": send_top_p,
            "reasoning_mode": reasoning_mode, "reasoning_effort": reasoning_effort,
            "reasoning_format": reasoning_format,
            "max_tokens_parameter": max_tokens_parameter,
        })
        self.rng = random.Random(seed)
        self.np_rng = np.random.default_rng(seed)
        self.seed, self.num_agents, self.grid_size = seed, num_agents, grid_size
        self.api_key, self.model = api_key, model
        self.base_url, self.mock_mode = base_url.rstrip("/"), mock_mode
        self.temperature, self.max_tokens, self.timeout = temperature, max_tokens, timeout
        self.top_p, self.view_range, self.message_range = top_p, view_range, message_range
        self.use_mbti, self.custom_world_prompt = use_mbti, custom_world_prompt
        self.reproduce_cost, self.child_initial_energy = reproduce_cost, child_initial_energy
        self.population_cap = population_cap
        self.environment = Environment(grid_size, energy_spawn_rate, num_clusters, cluster_radius, self.rng)
        self.environment.spawn_energy(spawn_energy_count)
        self.step_count, self.logs = 0, []
        self.run_id = f"unsaved-{uuid4().hex}"
        self._observations = {}
        self.stats = dict.fromkeys(("total_born", "total_died", "attacks", "shares", "reproductions",
                                   "total_actions", "valid_decisions", "repaired_decisions",
                                   "llm_errors", "parse_errors", "rejected_actions"), 0)
        self.agents = [self._new_agent(i, (self.rng.randrange(grid_size), self.rng.randrange(grid_size)),
                                       initial_energy) for i in range(num_agents)]

    def _new_agent(self, agent_id, position, energy, parent=None):
        mbti = None
        if self.use_mbti:
            if parent and self.rng.random() > 0.3:
                mbti = parent.mbti_type
            else:
                weights = np.array(POPULATION_WEIGHTS)
                mbti = str(self.np_rng.choice(MBTI_TYPES, p=weights / weights.sum()))
        agent = LLMAgent(agent_id, position, energy, model=self.model, mbti_type=mbti,
                         use_mbti=self.use_mbti, custom_world_prompt=self.custom_world_prompt,
                         born_step=self.step_count, prompt_factors=self.prompt_factors)
        agent.parent = parent
        if parent:
            parent.descendants.append(agent)
        return agent

    def _in_view_range(self, pos1, pos2, range_val=None):
        radius = self.view_range if range_val is None else range_val
        return all(abs(d) <= radius for d in self.environment.relative(pos1, pos2))

    async def _request_decision(self, session, agent, system_prompt, user_prompt):
        # Resolve permissive absolute-move notation against the request's pose,
        # never a potentially newer pose after awaiting the response.
        observation = self._observations.get(agent.id)
        observed_position = observation.position if observation is not None else tuple(agent.position)
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
        start = time.perf_counter()
        attempts = []
        choices = None
        feedback = ""
        for attempt_index in range(2):
            event = await self._request_decision_once(
                session, agent, system_prompt, user_prompt, observed_position, messages, choices)
            rules = {repair["rule"] for repair in event["response_repairs"]}
            diagonal = next((repair for repair in event["response_repairs"]
                             if repair["rule"] == "diagonal_move_rejected"), None)
            if "invalid_destination_selection" in rules:
                event.update(decision_status="error", error_kind="invalid_action",
                             reason="Selected destination is not one of the offered cells",
                             decision_source="fallback", kind="stay", message="", thought="",
                             summary="", memory="", share=None, attack=None)
            attempt = {key: deepcopy(value) for key, value in event.items()
                       if key not in ("system_prompt", "user_prompt")}
            attempt.update(attempt=attempt_index + 1, feedback_prompt=feedback,
                           validation_status="rejected" if diagonal or event["decision_status"] != "ok" else "accepted")
            attempts.append(attempt)
            if attempt_index or self.mock_mode or not diagonal or event["decision_status"] != "ok":
                break
            choices = cardinal_destinations(observed_position, self.grid_size, toward_delta=diagonal["requested_delta"])
            feedback = diagonal_move_feedback(observed_position, choices, self.prompt_factors)
            messages = [*messages, {"role": "assistant", "content": event["raw_response"]},
                        {"role": "user", "content": feedback}]
        event.update(decision_attempts=attempts, retry_count=len(attempts) - 1,
                     llm_request_count=0 if self.mock_mode else len(attempts),
                     retry_status=("corrected" if event["decision_status"] == "ok" else "failed") if choices else "not_needed",
                     retry_destinations=choices or [],
                     latency_ms=round((time.perf_counter() - start) * 1000, 3))
        # Missing usage stays unknown; do not present a partial sum as the total.
        for key in ("prompt_tokens", "completion_tokens"):
            values = [attempt[key] for attempt in attempts]
            event[key] = sum(values) if all(type(value) is int for value in values) else None
        return event

    async def _request_decision_once(self, session, agent, system_prompt, user_prompt,
                                     observed_position, messages, destination_choices=None):
        """Use the existing HTTP and parser path for each bounded attempt."""
        start = time.perf_counter()
        event = {"agent_id": agent.id, "decision_source": "mock" if self.mock_mode else "llm",
                 "decision_status": "ok", "error_kind": "", "reason": "", "http_status": None,
                 "finish_reason": None, "prompt_tokens": None,
                 "completion_tokens": None, "raw_response": "", "requested_action": "",
                 "normalized_action": "", "response_repairs": [],
                 "system_prompt": system_prompt, "user_prompt": user_prompt}
        if self.mock_mode:
            event["raw_response"] = "Action: [Stay]\nMessage: [Hello world]\nThought: [Mock decision]"
        else:
            try:
                async with chat_completion_request(
                    session, base_url=self.base_url, model=self.model, api_key=self.api_key,
                    messages=messages,
                    max_tokens=self.max_tokens, temperature=self.temperature, top_p=self.top_p,
                    **self.request_options,
                ) as response:
                    event["http_status"] = response.status
                    body = await response.text()
                    # A service may echo a credential in an error body; never persist it.
                    if self.api_key:
                        body = body.replace(self.api_key, "[REDACTED]")
                    event["raw_response"] = body
                    if response.status != 200:
                        event.update(decision_status="error", error_kind="http_error",
                                     reason=f"HTTP {response.status}", raw_response=body)
                    else:
                        result = json.loads(body)
                        choice = result["choices"][0]
                        content = choice["message"]["content"]
                        if not isinstance(content, str) or not content.strip():
                            raise ValueError("Empty or non-text model response")
                        usage = result.get("usage") or {}
                        if not isinstance(usage, dict):
                            usage = {}
                        # Optional counters must not prevent a usable reply from being saved.
                        usage = {key: value for key, value in usage.items()
                                 if type(value) is int and value >= 0}
                        event.update(raw_response=content,
                                     finish_reason=choice.get("finish_reason"),
                                     prompt_tokens=usage.get("prompt_tokens"),
                                     completion_tokens=usage.get("completion_tokens"))
            except (aiohttp.ClientError, asyncio.TimeoutError) as error:
                event.update(decision_status="error", error_kind="transport_error", reason=type(error).__name__)
            except (ValueError, KeyError, IndexError, TypeError) as error:
                event.update(decision_status="error", error_kind="protocol_error", reason=type(error).__name__)
        event["latency_ms"] = round((time.perf_counter() - start) * 1000, 3)
        if event["decision_status"] == "ok":
            try:
                event.update(parse_response(event["raw_response"], position=observed_position,
                                            grid_size=self.grid_size, destination_choices=destination_choices))
                if event["finish_reason"] == "length":
                    event["response_repairs"].append({"field": "Response", "rule": "partial_response",
                                                      "original": ["length"], "normalized": "use_available_fields"})
            except ValueError as error:
                event.update(decision_status="error", error_kind="parse_error", reason=str(error))
        if event["decision_status"] != "ok":
            event.update(decision_source="fallback", kind="stay", message="", thought="",
                         summary="", memory="", share=None, attack=None)
        return event

    def _mark_dead(self, agent, cause):
        if agent.alive:
            agent.alive = False
            agent.death_step, agent.death_cause = self.step_count, cause
            self.stats["total_died"] += 1

    def _apply_decision(self, agent, event, observed_positions):
        self.stats["total_actions"] += 1
        if event["decision_status"] == "ok":
            self.stats["valid_decisions"] += 1
            if event.get("response_repairs"):
                self.stats["repaired_decisions"] += 1
        elif event["error_kind"] == "parse_error":
            self.stats["parse_errors"] += 1
        elif event["error_kind"] == "invalid_action":
            self.stats["rejected_actions"] += 1
        else:
            self.stats["llm_errors"] += 1
        event.update(energy_before=agent.energy, position_before=agent.position,
                     energy_collected=0, energy_transferred=0, energy_cost=0,
                     action_status="executed", next_action_status="executed", child_id=None,
                     share_status="not_requested", attack_status="not_requested",
                     message_status="not_requested", message_cost=0,
                     shared_amount=0, stolen_amount=0, executed_share="", executed_attack="",
                     observed_position=observed_positions[agent.id])
        if not agent.alive:
            event.update(executed_action="", action_status="skipped_dead", next_action_status="skipped_dead",
                         reason="Actor already dead", energy_after=agent.energy, position_after=agent.position)
            for label in ("share", "attack", "message"):
                if event.get(label):
                    event[f"{label}_status"] = "skipped_dead"
            return

        kind = event["kind"]
        target = next((other for other in self.agents
                       if other.id == event.get("target_id") and other.alive), None)
        reject = ""
        if kind == "move" and abs(event["dx"]) + abs(event["dy"]) != 1:
            reject = "Move must be one cardinal cell"
        elif kind in ("share", "attack"):
            if target is None or target is agent or not self._in_view_range(agent.position, target.position):
                reject = "Target must be another living agent in view"
            elif kind == "share" and not 0 < event["amount"] <= agent.energy:
                reject = "Share amount must be positive and affordable"
        elif kind == "reproduce":
            if agent.energy < self.reproduce_cost:
                reject = "Insufficient energy for reproduction"
            elif sum(a.alive for a in self.agents) >= self.population_cap:
                reject = "Population cap reached"
        if reject:
            self.stats["rejected_actions"] += 1
            event.update(action_status="rejected", next_action_status="rejected", reason=reject)
            if kind in ("share", "attack"):
                event[f"{kind}_status"] = "rejected"
            kind = "stay"
        elif event["decision_source"] == "fallback":
            event["action_status"] = event["next_action_status"] = "fallback"

        if kind == "move":
            agent.position = ((agent.position[0] + event["dx"]) % self.grid_size,
                              (agent.position[1] + event["dy"]) % self.grid_size)
            event["energy_collected"] = self.environment.get_energy_at(agent.position)
            agent.energy += event["energy_collected"]
            event["energy_cost"] = 2 - TURN_ENERGY_COST
            executed = f"Move to ({event['dx']},{event['dy']})"
        elif kind == "share":
            amount = event["amount"]
            agent.energy -= amount
            target.energy += amount
            agent.shared_energy[target.id] = agent.shared_energy.get(target.id, 0) + amount
            event.update(share_status="executed", shared_amount=amount,
                         executed_share=f"{target.id}-{amount}", energy_transferred=amount)
            self.stats["shares"] += 1
            executed = f"Share: {target.id}-{amount}"
        elif kind == "attack":
            amount = min(ATTACK_ENERGY_CAP, target.energy // ATTACK_ENERGY_DIVISOR)
            agent.energy += amount
            target.energy -= amount
            target.attacked_by.append(agent.id)
            event.update(attack_status="executed", stolen_amount=amount,
                         executed_attack=str(target.id), energy_transferred=amount,
                         energy_cost=ATTACK_ENERGY_COST)
            self.stats["attacks"] += 1
            executed = f"Attack: {target.id}"
        elif kind == "reproduce":
            dx, dy = self.rng.choice([(-1, 0), (1, 0), (0, -1), (0, 1)])
            pos = ((agent.position[0] + dx) % self.grid_size,
                   (agent.position[1] + dy) % self.grid_size)
            child = self._new_agent(len(self.agents), pos, self.child_initial_energy, parent=agent)
            self.agents.append(child)
            self.stats["total_born"] += 1
            self.stats["reproductions"] += 1
            event.update(energy_cost=self.reproduce_cost - TURN_ENERGY_COST, child_id=child.id)
            executed = "Reproduce"
        else:
            executed = "Stay"
        agent.energy -= event["energy_cost"]
        agent.action, agent.thoughts, agent.message = executed, event["thought"], event["message"]
        agent.summary = event["summary"]
        agent.age += 1
        # Restore the previous factual action history, even when the model
        # omits Memory or the request fails and the engine executes Stay.
        memory = f"Step {self.step_count}: {executed}; {agent.thoughts[:100]}"
        agent.memory.append(memory)
        agent.memory = agent.memory[-3:]
        event.update(response_memory=event["memory"], memory=memory, memory_source="engine")
        if agent.energy <= 0:
            self._mark_dead(agent, "energy_depleted")
        if event["message"]:
            event["message_status"] = "sent" if agent.alive else "skipped_dead"
        event.update(executed_action=executed, energy_after=agent.energy, position_after=agent.position)

    def _prepare_observations(self):
        """Advance the existing turn boundary once, then freeze all inputs."""
        self.step_count += 1
        living = [agent for agent in self.agents if agent.alive]
        for agent in living:
            agent.messages, agent.next_messages = agent.next_messages, []
            agent.message_envelopes, agent.next_message_envelopes = agent.next_message_envelopes, []
        self.environment.random_spawn()
        state = self.snapshot()
        state.update(world_state_id=f"{self.run_id}:{self.step_count}:world",
                     phase="after_resource_spawn_before_all_decisions")
        observations = []
        for agent in living:
            observations.append(self._capture_observation(agent, living, state["world_state_id"]))
        self._observations = {observation.agent_id: observation for observation in observations}
        return living, tuple(observations), state

    def _capture_observation(self, agent, living, world_state_id):
        view, messages = agent.get_local_view(self.environment, living, self.view_range)
        return AgentObservation(
            run_id=self.run_id, observation_id=f"{self.run_id}:{self.step_count}:{agent.id}",
            world_state_id=world_state_id, step=self.step_count, agent_id=agent.id,
            position=tuple(agent.position), energy=agent.energy, age=agent.age, num_agents=len(living),
            grid_size=self.grid_size, view_range=self.view_range, message_range=self.message_range,
            local_view=tuple(view), memory=tuple(agent.memory[-3:]), messages=tuple(messages),
            history=tuple(agent.history[-3:]), message_envelopes=tuple(agent.message_envelopes))

    def _build_prompts(self, agent, observation):
        return agent.build_prompt(observation.local_view, observation.messages, observation.num_agents,
                                  self.reproduce_cost, self.population_cap, self.view_range, self.message_range,
                                  observation=observation)

    def preview_next_prompts(self):
        """Render the next inputs without HTTP or advancing this simulation/RNG."""
        preview = deepcopy(self)
        living, observations, state = preview._prepare_observations()
        agents = []
        for agent, observation in zip(living, observations):
            system, user = preview._build_prompts(agent, observation)
            agents.append({"agent_id": agent.id, "observation": observation.to_dict(),
                           "system_prompt": system, "user_prompt": user,
                           "prompt_sha256": prompt_hashes(system, user)})
        return {"step": preview.step_count, "phase": state["phase"], "agents": agents}

    def _action_context(self, agent_id, event, state):
        """Audit declared action inputs, including hidden truth only in the log.

        This does not decide legality or gate execution. _apply_decision remains
        the sole owner of execution rules.
        """
        agents = {agent["id"]: agent for agent in state["agents"]}
        actor = agents[agent_id]
        context = {f"actor_{key}": actor[key] for key in ("position", "energy", "alive")}
        if event["kind"] in ("attack", "share"):
            target = agents.get(event.get("target_id"))
            context["target"] = ({key: target[key] for key in ("id", "position", "energy", "alive")}
                                 if target else None)
        elif event["kind"] == "move":
            destination = ((actor["position"][0] + event["dx"]) % self.grid_size,
                           (actor["position"][1] + event["dy"]) % self.grid_size)
            context["destination"] = destination
            context["destination_energy"] = next((resource["energy"]
                for resource in state["environment"]["resources"]
                if (resource["x"], resource["y"]) == destination), 0)
        elif event["kind"] == "reproduce":
            context["population"] = sum(agent["alive"] for agent in state["agents"])
        return context

    async def step(self, session=None, on_decision=None):
        if session is None:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as client:
                return await self.step(client, on_decision=on_decision)
        before = self.stats.copy()
        living, observations, observed_state = self._prepare_observations()
        decisions = []
        observed_positions = {observation.agent_id: observation.position for observation in observations}
        # Collect all decisions from the same world state. One HTTP request at a time.
        for agent, observation in zip(living, observations):
            prompts = self._build_prompts(agent, observation)
            event = await self._request_decision(session, agent, *prompts)
            event.update(observation_id=observation.observation_id, observation=observation.to_dict(),
                         prompt_sha256=prompt_hashes(*prompts))
            decisions.append(event)
            if on_decision is not None:
                on_decision(self.step_count, deepcopy(event))
        for agent, event in zip(living, decisions):
            observed = self._action_context(agent.id, event, observed_state)
            current = self._action_context(agent.id, event, self.snapshot())
            event["execution_check"] = {"observed": observed, "before_execution": current,
                                        "changed": [key for key in observed if observed[key] != current[key]]}
            self._apply_decision(agent, event, observed_positions)
        # Charge each participant once, after every action. Newborns first
        # participate next turn. Even an actor depleted during its action owes
        # this turn's cost; rejected actions and API fallback cannot avoid it.
        for agent, event in zip(living, decisions):
            event.update(turn_energy_before=agent.energy, turn_energy_cost=TURN_ENERGY_COST,
                         total_energy_cost=event["energy_cost"] + TURN_ENERGY_COST)
            agent.energy -= TURN_ENERGY_COST
            event["turn_energy_after"] = agent.energy
            if agent.energy <= 0:
                self._mark_dead(agent, "energy_depleted")
        for sender, event in zip(living, decisions):
            if not sender.alive or not event["message"]:
                if event["message"]:
                    event["message_status"] = "skipped_dead"
                continue
            recipients = []
            for recipient in self.agents:
                if (recipient.alive and recipient is not sender and self._in_view_range(
                        sender.position, recipient.position, self.message_range)):
                    recipient.next_messages.append(f"Agent{sender.id}: {event['message']}")
                    recipient.next_message_envelopes.append(MessageEnvelope(
                        sender_id=sender.id, observation_id=event["observation_id"],
                        generated_step=self.step_count, delivered_step=self.step_count,
                        read_step=self.step_count + 1, content=event["message"]))
                    recipients.append(recipient.id)
            event["message_recipient_ids"] = recipients
        for agent, event in zip(living, decisions):
            outcome = ActionOutcome.from_event(self.step_count, event)
            event["outcome"] = asdict(outcome)
            agent.history.append(PastDecision(self.step_count, event["executed_action"],
                                              event["thought"][:100], outcome))
            agent.history = agent.history[-3:]
        snapshot = self.snapshot(decisions)
        snapshot["observation_state"] = observed_state
        snapshot["step_stats"] = {key: self.stats[key] - before[key] for key in self.stats}
        snapshot["alive_start"] = len(living)
        self.logs.append(snapshot)
        return snapshot

    def get_summary(self):
        living = [agent for agent in self.agents if agent.alive]
        count, total = len(living), self.stats["total_actions"]
        energy = sum(agent.energy for agent in living)
        return {"step": self.step_count, "alive": count, **self.stats,
                "total_energy": energy, "avg_energy": energy / count if count else 0,
                "avg_age": sum(agent.age for agent in living) / count if count else 0,
                "energy_sources": len(self.environment.energy_sources),
                "coop_rate": self.stats["shares"] / total if total else 0,
                "attack_rate": self.stats["attacks"] / total if total else 0,
                "repro_rate": self.stats["reproductions"] / total if total else 0,
                "mbti_distribution": {mbti: sum(a.mbti_type == mbti for a in living) / count if count else 0
                                      for mbti in MBTI_TYPES} if self.use_mbti else {}}

    def snapshot(self, events=None):
        return {"step": self.step_count, "agents": [agent.to_dict() for agent in self.agents],
                "environment": {"energy_sources": len(self.environment.energy_sources),
                                "resources": [{"x": x, "y": y, "energy": energy}
                                              for (x, y), energy in sorted(self.environment.energy_sources.items())]},
                "stats": self.stats.copy(), "summary": self.get_summary(), "events": events or []}

    def visualize(self, save_path, snapshot=None):
        with PLOT_LOCK:
            fig = draw_grid(self.snapshot() if snapshot is None else snapshot,
                            self.grid_size, self.reproduce_cost)
            fig.savefig(save_path, dpi=120)
            fig.clear()


DEFAULT_PARAMS = {
    "num_agents": 5, "grid_size": 30, "num_steps": 15, "seed": 0, "use_mbti": False,
    "initial_energy": INITIAL_ENERGY, "spawn_energy_count": SPAWN_ENERGY_COUNT,
    "reproduce_cost": REPRODUCE_COST, "child_initial_energy": CHILD_INITIAL_ENERGY,
    "cluster_radius": CLUSTER_RADIUS, "num_clusters": NUM_CLUSTERS,
    "energy_spawn_rate": ENERGY_SPAWN_RATE, "custom_world_prompt": "",
    "model": "default_model", "base_url": "http://127.0.0.1:8080/v1", "api_key": "",
    "mock_mode": False, "temperature": 0.0, "max_tokens": 5000, "top_p": 1.0, "timeout": 120.0,
    **REQUEST_OPTION_DEFAULTS,
    "view_range": VIEW_RANGE, "message_range": MESSAGE_RANGE,
    "population_cap": 60, "output_dir": "outputs", "save_images": True,
    "action_order": "observe_then_apply_by_agent_id", "request_concurrency": 1,
    "prompt_factors": (),
}


def format_agent_decision(step, event):
    lines = [f"Step {step} / Agent {event['agent_id']}"]
    if event["decision_status"] != "ok":
        lines.append(f"  応答エラー: {event.get('error_kind', 'unknown')}（待機に置換）")
    else:
        lines.append(f"  選択: {event.get('requested_action', '')}")
        lines.append(f"  共有: {event.get('requested_share') or 'なし'} / 攻撃: {event.get('requested_attack') or 'なし'}")
    lines.append(f"  発言: {event.get('message') or '（発言なし）'}")
    if event.get("summary"):
        lines.append(f"  状況の要約: {event['summary']}")
    if event.get("thought"):
        lines.append(f"  思考・感情: {event['thought']}")
    if event.get("memory"):
        lines.append(f"  次回へ残す記憶: {event['memory']}")
    return "\n".join(lines)


def _configured_simulation(params=None, run_id=0):
    """Shared configuration and world initialization; no model access."""
    config = {**DEFAULT_PARAMS, "seed": run_id, **(params or {})}
    unknown = set(config) - set(DEFAULT_PARAMS)
    if unknown:
        raise ValueError(f"Unknown parameters: {sorted(unknown)}")
    if config["num_steps"] < 0 or config["action_order"] != DEFAULT_PARAMS["action_order"] or config["request_concurrency"] != 1:
        raise ValueError("Invalid step count or unsupported execution order/concurrency")
    if config["seed"] is None:
        config["seed"] = random.SystemRandom().randrange(2 ** 32)
    if not isinstance(config["seed"], int) or not 0 <= config["seed"] < 2 ** 32:
        raise ValueError("seed must be an integer in [0, 2**32)")
    config["base_url"] = config["base_url"].rstrip("/")
    config["prompt_factors"] = list(normalize_prompt_factors(config["prompt_factors"]))
    sim_params = {key: value for key, value in config.items()
                  if key not in ("num_steps", "output_dir", "save_images", "action_order", "request_concurrency")}
    sim = Simulation(**sim_params)
    return config, sim


def preview_prompts(params=None):
    """Return reviewable first-turn inputs through the normal prompt builder."""
    config, sim = _configured_simulation(params)
    sim.run_id = "preview"
    return {"kind": "prompt_preview", "llm_calls": 0,
            "config": {key: value for key, value in config.items() if key != "api_key"},
            "protocol": prompt_protocol(config["prompt_factors"]), "provenance": provenance(),
            **sim.preview_next_prompts()}


async def main(run_id=0, params=None, on_decision=None, on_snapshot=None, stop_requested=None):
    config, sim = _configured_simulation(params, run_id)
    async with aiohttp.ClientSession() as session:
        if not config["mock_mode"]:
            await ensure_server_reachable(session, base_url=config["base_url"], timeout=config["timeout"])
        identity = await ModelIdentity.capture(config, session)
    recorder = RunRecorder(config["output_dir"], config, run_id, model_info=identity.info)
    sim.run_id = recorder.run_id
    initial_snapshot = sim.snapshot()
    recorder.record(initial_snapshot)
    print(f"Run: {recorder.directory}", flush=True)
    def report_decision(step, event):
        print(format_agent_decision(step, event), flush=True)
        if on_decision is not None:
            on_decision(step, event)

    image_dir = recorder.directory / "img"
    try:
        if config["save_images"]:
            image_dir.mkdir()
            sim.visualize(image_dir / "step000.png", initial_snapshot)
        # Deliver a UI cancellation even when Mock or preparation did not await.
        await asyncio.sleep(0)
        if stop_requested and stop_requested():
            raise asyncio.CancelledError
        if on_snapshot is not None:
            on_snapshot(deepcopy(initial_snapshot))
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=config["timeout"])) as session:
            for _ in range(config["num_steps"]):
                await asyncio.sleep(0)
                if stop_requested and stop_requested():
                    raise asyncio.CancelledError
                snapshot = await sim.step(session, on_decision=report_decision)
                recorder.record(snapshot)
                if config["save_images"]:
                    sim.visualize(image_dir / f"step{sim.step_count:03d}.png", snapshot)
                if on_snapshot is not None:
                    on_snapshot(deepcopy(snapshot))
                summary = snapshot["summary"]
                print(f"Step {sim.step_count}: alive={summary['alive']}, "
                      f"decisions_this_step={snapshot['step_stats']['total_actions']}, decisions_total={summary['total_actions']}, "
                      f"llm_errors={summary['llm_errors']}, parse_errors={summary['parse_errors']}", flush=True)
                if not summary["alive"]:
                    break
            model_info = await identity.finish(session)
        errors = sim.stats["llm_errors"] + sim.stats["parse_errors"]
        status = "completed_with_errors" if errors else "completed"
        reason = "extinction" if not sim.get_summary()["alive"] else "step_limit"
        if model_info["status"] in ("changed_during_run", "unverified_after_run"):
            status, reason = "completed_with_errors", "model_identity_changed_or_unverified"
        return recorder.finish(status, reason, model_info=model_info)
    except (KeyboardInterrupt, asyncio.CancelledError):
        requested = bool(stop_requested and stop_requested())
        model_info = (identity.info if config["mock_mode"] else
                      {**identity.info, "status": "unverified_after_run", "reason": "run_interrupted"})
        result = recorder.finish("interrupted", "user_stop" if requested else "cancelled", model_info=model_info)
        if requested:
            return result
        raise
    except Exception as error:
        # Store a safe type, not arbitrary exception text that could contain a credential.
        model_info = {**identity.info, "status": "unverified_after_run", "reason": "run_failed"}
        return recorder.finish("failed", "exception", type(error).__name__, model_info=model_info)


async def batch_experiment(num_runs_per_set=3, params_sets=None):
    """Small sequential repetitions; distinct seeds are recorded for every run."""
    if params_sets is None:
        params_sets = [{"use_mbti": True}, {"use_mbti": False}]
    results = []
    for params in params_sets:
        for repetition in range(num_runs_per_set):
            config = {**params, "seed": params.get("seed", 0) + repetition}
            results.append(await main(len(results), config))
            if results[-1]["status"] != "completed":
                return results
    return results


async def batch_experiment_parallel(num_runs=5, params_list=None):
    """Compatibility entry point; local-server runs now deliberately execute serially."""
    results = []
    for index, params in enumerate(params_list or [{"seed": i} for i in range(num_runs)]):
        results.append(await main(index, params))
        if results[-1]["status"] != "completed":
            break
    return results


async def check_connection(params, session=None):
    """One explicit probe through the same request/parser path; no saved run."""
    config = {**DEFAULT_PARAMS, **params, "num_agents": 1, "spawn_energy_count": 0,
              "use_mbti": False, "custom_world_prompt": ""}
    sim = Simulation(**{key: value for key, value in config.items()
                        if key not in ("num_steps", "output_dir", "save_images", "action_order", "request_concurrency")})
    agent = sim.agents[0]
    observation = sim._capture_observation(agent, sim.agents, f"{sim.run_id}:connection-check")
    sim._observations = {agent.id: observation}
    prompts = sim._build_prompts(agent, observation)
    if session is None:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=sim.timeout)) as client:
            return await sim._request_decision(client, agent, *prompts)
    return await sim._request_decision(session, agent, *prompts)


def run_streamlit_ui():
    from app_ui import run_streamlit_ui as show_app
    show_app(main, DEFAULT_PARAMS, format_agent_decision, check_connection)


def cli():
    parser = argparse.ArgumentParser(description="Small local-LLM Sugarscape experiments and CSV export")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Run one or more sequential experiments")
    run.add_argument("--mock", action="store_true", help="Use deterministic Stay decisions, without HTTP")
    run.add_argument("--base-url", default=os.getenv("SUGARSCAPE_BASE_URL", DEFAULT_PARAMS["base_url"]))
    run.add_argument("--model", default=os.getenv("SUGARSCAPE_MODEL", "default_model"))
    run.add_argument("--agents", type=int, default=5)
    run.add_argument("--steps", type=int, default=15)
    run.add_argument("--seed", type=int, default=42)
    run.add_argument("--runs", type=int, default=1, help="Sequential repetitions with seed + index")
    personality = run.add_mutually_exclusive_group()
    personality.add_argument("--mbti", dest="use_mbti", action="store_true", help="Enable MBTI personality prompts")
    personality.add_argument("--no-mbti", dest="use_mbti", action="store_false", help="Disable MBTI personality prompts (default)")
    run.set_defaults(use_mbti=DEFAULT_PARAMS["use_mbti"])
    run.add_argument("--grid-size", type=int, default=30)
    run.add_argument("--initial-energy", type=int, default=INITIAL_ENERGY)
    run.add_argument("--spawn-energy-count", type=int, default=SPAWN_ENERGY_COUNT)
    run.add_argument("--reproduce-cost", type=int, default=REPRODUCE_COST)
    run.add_argument("--child-initial-energy", type=int, default=CHILD_INITIAL_ENERGY)
    run.add_argument("--energy-spawn-rate", type=float, default=ENERGY_SPAWN_RATE)
    run.add_argument("--cluster-radius", type=int, default=CLUSTER_RADIUS)
    run.add_argument("--num-clusters", type=int, default=NUM_CLUSTERS)
    run.add_argument("--population-cap", type=int, default=60)
    run.add_argument("--view-range", type=int, default=VIEW_RANGE)
    run.add_argument("--message-range", type=int, default=MESSAGE_RANGE)
    run.add_argument("--world-prompt", default="")
    run.add_argument("--prompt-factor", action="append", choices=PROMPT_FACTORS, default=[],
                     help="Enable one independent input factor; repeat to combine (default: none)")
    run.add_argument("--preview-prompts", metavar="PATH",
                     help="Save first-turn prompt JSON without connecting to a model or starting a run")
    run.add_argument("--temperature", type=float, default=DEFAULT_PARAMS["temperature"])
    run.add_argument("--max-tokens", type=int, default=DEFAULT_PARAMS["max_tokens"])
    run.add_argument("--top-p", type=float, default=DEFAULT_PARAMS["top_p"])
    run.add_argument("--send-temperature", action=argparse.BooleanOptionalAction,
                     default=DEFAULT_PARAMS["send_temperature"])
    run.add_argument("--send-top-p", action=argparse.BooleanOptionalAction,
                     default=DEFAULT_PARAMS["send_top_p"])
    run.add_argument("--reasoning-mode", choices=REASONING_MODES, default=DEFAULT_PARAMS["reasoning_mode"])
    run.add_argument("--reasoning-effort", choices=REASONING_EFFORTS, default=DEFAULT_PARAMS["reasoning_effort"])
    run.add_argument("--reasoning-format", choices=REASONING_FORMATS, default=DEFAULT_PARAMS["reasoning_format"])
    run.add_argument("--max-tokens-parameter", choices=TOKEN_LIMIT_PARAMETERS,
                     default=DEFAULT_PARAMS["max_tokens_parameter"])
    run.add_argument("--timeout", type=float, default=120.0)
    run.add_argument("--output", default="outputs")
    run.add_argument("--images", action=argparse.BooleanOptionalAction,
                     default=DEFAULT_PARAMS["save_images"],
                     help="Save the initial board and every completed step (default: on)")
    aggregate = commands.add_parser("aggregate", help="Rebuild tables and export one row per run")
    aggregate.add_argument("--input", default="outputs")
    aggregate.add_argument("--output")
    export = commands.add_parser("export", help="Rebuild one run's CSV files from its journal")
    export.add_argument("run_directory")
    args = parser.parse_args()
    if args.command == "aggregate":
        destination, count = collect_runs(args.input, args.output)
        print(f"{count} runs -> {destination}")
        return 0
    if args.command == "export":
        result = export_run(args.run_directory)
        print(f"Exported: {result['output_dir']} (status={result['status']})")
        return 0
    if args.runs < 1:
        parser.error("--runs must be positive")
    config = {"num_agents": args.agents, "num_steps": args.steps, "grid_size": args.grid_size,
              "mock_mode": args.mock, "base_url": args.base_url, "model": args.model,
              "api_key": os.getenv("SUGARSCAPE_API_KEY", ""), "use_mbti": args.use_mbti,
              "temperature": args.temperature, "max_tokens": args.max_tokens, "top_p": args.top_p, "timeout": args.timeout,
              "output_dir": args.output, "save_images": args.images, "custom_world_prompt": args.world_prompt,
              "prompt_factors": args.prompt_factor}
    for key in ("initial_energy", "spawn_energy_count", "reproduce_cost", "child_initial_energy",
                "energy_spawn_rate", "cluster_radius", "num_clusters", "population_cap",
                "view_range", "message_range", *REQUEST_OPTION_DEFAULTS):
        config[key] = getattr(args, key)
    if args.preview_prompts:
        if args.runs != 1:
            parser.error("--preview-prompts requires --runs 1")
        try:
            preview = preview_prompts({**config, "seed": args.seed})
            destination = Path(args.preview_prompts).expanduser()
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("x", encoding="utf-8") as handle:
                json.dump(preview, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
        except (ValueError, OSError) as error:
            parser.error(str(error))
        print(f"Prompt preview (no model calls): {destination}")
        return 0
    for index in range(args.runs):
        try:
            result = asyncio.run(main(index, {**config, "seed": args.seed + index}))
        except ValueError as error:
            parser.error(str(error))
        print(json.dumps({"status": result["status"], "output_dir": result["output_dir"],
                          "execution_date": result["execution_date"], "model": result["model"],
                          "summary": result["summary"]}, ensure_ascii=False, indent=2))
        if result["status"] != "completed":
            return 2
    return 0


if __name__ == "__main__":
    # Preserve the existing Streamlit entry; CLI and UI call the same main()/Simulation.
    if len(sys.argv) > 1:
        raise SystemExit(cli())
    run_streamlit_ui()
