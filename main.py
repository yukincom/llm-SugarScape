"""Local-LLM Sugarscape: small experiments with an auditable data trail."""

import argparse
import asyncio
import json
import os
from pathlib import Path
import random
import re
import sys
import time

import aiohttp
import numpy as np

from run_data import RunRecorder, collect_runs, export_run

NUM_CLUSTERS = 3
CLUSTER_RADIUS = 5
VIEW_RANGE = 5
# 新しい定数（paramsでオーバーライド可能）
INITIAL_ENERGY = 150
SPAWN_ENERGY_COUNT = 20
REPRODUCE_COST = 70
CHILD_INITIAL_ENERGY = 150  # 子エージェントの初期エネルギー
ENERGY_SPAWN_RATE = 0.001  # ステップごとのランダム生成率（未使用だったのを有効化）
CUSTOM_WORLD_PROMPT = ""  # デフォルト空、世界観カスタム

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
                 custom_world_prompt=CUSTOM_WORLD_PROMPT, use_mbti=True, born_step=0):
        self.id, self.position, self.energy = agent_id, position, initial_energy
        self.age, self.born_step = 0, born_step
        self.memory, self.messages, self.next_messages = [], [], []
        self.parent, self.descendants = None, []
        self.alive, self.death_step, self.death_cause = True, None, None
        self.model = model
        self.thoughts, self.action, self.message = "", "", ""
        self.custom_world_prompt = custom_world_prompt
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
                view.append(f"{other.id}=(dx,dy)=({dx},{dy}){hint}")
        return view, list(self.messages)

    def build_prompt(self, local_view, local_messages, num_agents,
                     reproduce_cost=REPRODUCE_COST, population_cap=60):
        system_prompt = "\n\n".join(part for part in [
            self.custom_world_prompt, self.personality_prompt,
            "You are an independent Agent living on a toroidal Grid. Strive for survival and growth.\n"
            "You can move one cell: Move to (1,0), Move to (-1,0), Move to (0,1), Move to (0,-1) "
            "(costs 2 energy), or Stay (costs 1 energy). Diagonal or longer moves are invalid.\n"
            f"Reproduce costs {reproduce_cost} energy, requires at least that energy and fewer than "
            f"{population_cap} living agents.\n"
            "Moving onto an Energy Source (E) gives 50 energy and consumes that source.\n"
            "At zero or negative energy you die.\n"
            "Share: {id}-{amount} transfers a positive integer amount you can afford to another agent "
            "in your local view. Attack: {id} takes half (rounded down) of another visible agent's energy.\n"
            "Share and Attack have no additional energy cost. You cannot target yourself.\n"
            "Your Message will be delivered to nearby living agents for the next step.\n"
            "M=(x,y) is your absolute position; E=(dx,dy) and agent IDs use relative positions. "
            "x-1 is west, x+1 east, y-1 north, y+1 south; grid edges wrap."
        ] if part)
        user_prompt = (
            f"Global Info: Total Agents in the World: {num_agents}\n"
            f"Local View:\n{chr(10).join(local_view)}\n"
            f"LATEST Status: Agent{self.id}, Energy: {self.energy}, Position: {self.position}, Cycles: {self.age}\n"
            f"Memory:\n{chr(10).join(self.memory[-3:]) or 'No previous memory'}\n"
            f"Messages:\n{chr(10).join(local_messages) or 'No messages'}\n"
            "Output exactly these three fields (choose one action; give brief reasoning):\n"
            "Action: [Move to (dx,dy) | Stay | Share: {id}-{amount} | Attack: {id} | Reproduce]\n"
            "Message: [Your message to nearby agents, max 50 words]\n"
            "Thought: [Brief reasoning for your action]"
        )
        return system_prompt, user_prompt


def parse_response(response):
    """Accept bracketed or plain single-line fields; reject ambiguous actions."""
    fields = {}
    for label in ("Action", "Message", "Thought"):
        matches = re.findall(rf"^[ \t]*(?:\*\*)?{label}:[ \t]*(?:\*\*)?([^\n]*)", response, re.M | re.I)
        if label == "Action" and len(matches) != 1:
            raise ValueError("Expected exactly one Action field")
        text = matches[0].strip() if matches else ""
        if text.startswith("[") and text.endswith("]"):
            text = text[1:-1].strip()
        fields[label.lower()] = text
    action = fields["action"]
    parsed = {"requested_action": action, "message": fields["message"], "thought": fields["thought"]}
    if action.lower() in ("stay", "reproduce"):
        return {**parsed, "kind": action.lower()}
    move = re.fullmatch(r"Move\s+to\s*\(\s*([+-]?\d+)\s*,\s*([+-]?\d+)\s*\)", action, re.I)
    if move:
        return {**parsed, "kind": "move", "dx": int(move[1]), "dy": int(move[2])}
    share = re.fullmatch(r"Share:\s*(\d+)\s*-\s*([+-]?\d+)", action, re.I)
    if share:
        return {**parsed, "kind": "share", "target_id": int(share[1]), "amount": int(share[2])}
    attack = re.fullmatch(r"Attack:\s*(\d+)", action, re.I)
    if attack:
        return {**parsed, "kind": "attack", "target_id": int(attack[1])}
    raise ValueError("Unrecognized Action format")


class Simulation:
    """Observe a shared start-of-step state, then apply decisions in agent ID order."""

    def __init__(self, num_agents=5, grid_size=30, api_key=None, model="default_model", seed=0,
                 use_mbti=True, initial_energy=INITIAL_ENERGY, spawn_energy_count=SPAWN_ENERGY_COUNT,
                 reproduce_cost=REPRODUCE_COST, child_initial_energy=CHILD_INITIAL_ENERGY,
                 cluster_radius=CLUSTER_RADIUS, num_clusters=NUM_CLUSTERS,
                 energy_spawn_rate=ENERGY_SPAWN_RATE, custom_world_prompt=CUSTOM_WORLD_PROMPT,
                 base_url="http://127.0.0.1:8080/v1", mock_mode=False, temperature=0.0,
                 max_tokens=384, timeout=120.0, population_cap=60):
        if grid_size < 1 or not 1 <= num_agents <= population_cap:
            raise ValueError("grid_size must be positive and 1 <= num_agents <= population_cap")
        if min(initial_energy, reproduce_cost, child_initial_energy, num_clusters, max_tokens) <= 0:
            raise ValueError("Energy settings, num_clusters and max_tokens must be positive")
        if cluster_radius < 0 or not 0 <= spawn_energy_count <= grid_size ** 2:
            raise ValueError("Invalid cluster radius or source count")
        if not 0 <= energy_spawn_rate <= 1 or not 0 <= temperature <= 2 or timeout <= 0:
            raise ValueError("Invalid spawn rate, temperature or timeout")
        from urllib.parse import urlsplit
        url = urlsplit(base_url)
        if url.scheme not in ("http", "https") or not url.netloc or url.username or url.password or url.query or url.fragment:
            raise ValueError("base_url must be an HTTP(S) API base without credentials, query or fragment")
        self.rng = random.Random(seed)
        self.np_rng = np.random.default_rng(seed)
        self.seed, self.num_agents, self.grid_size = seed, num_agents, grid_size
        self.api_key, self.model = api_key, model
        self.base_url, self.mock_mode = base_url.rstrip("/"), mock_mode
        self.temperature, self.max_tokens, self.timeout = temperature, max_tokens, timeout
        self.use_mbti, self.custom_world_prompt = use_mbti, custom_world_prompt
        self.reproduce_cost, self.child_initial_energy = reproduce_cost, child_initial_energy
        self.population_cap = population_cap
        self.environment = Environment(grid_size, energy_spawn_rate, num_clusters, cluster_radius, self.rng)
        self.environment.spawn_energy(spawn_energy_count)
        self.step_count, self.logs = 0, []
        self.stats = dict.fromkeys(("total_born", "total_died", "attacks", "shares", "reproductions",
                                   "total_actions", "valid_decisions", "llm_errors", "parse_errors", "rejected_actions"), 0)
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
                         born_step=self.step_count)
        agent.parent = parent
        if parent:
            parent.descendants.append(agent)
        return agent

    def _in_view_range(self, pos1, pos2, range_val=VIEW_RANGE):
        return all(abs(d) <= range_val for d in self.environment.relative(pos1, pos2))

    async def _request_decision(self, session, agent, system_prompt, user_prompt):
        start = time.perf_counter()
        event = {"agent_id": agent.id, "decision_source": "mock" if self.mock_mode else "llm",
                 "decision_status": "ok", "error_kind": "", "reason": "", "http_status": None,
                 "response_model": None, "finish_reason": None, "prompt_tokens": None,
                 "completion_tokens": None, "raw_response": "", "requested_action": "",
                 "system_prompt": system_prompt, "user_prompt": user_prompt}
        if self.mock_mode:
            event["raw_response"] = "Action: [Stay]\nMessage: [Hello world]\nThought: [Mock decision]"
        else:
            payload = {"model": self.model,
                       "messages": [{"role": "system", "content": system_prompt},
                                    {"role": "user", "content": user_prompt}],
                       "max_tokens": self.max_tokens, "temperature": self.temperature, "stream": False}
            headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
            try:
                async with session.post(f"{self.base_url}/chat/completions", json=payload,
                                        headers=headers) as response:
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
                            raise ValueError("Invalid usage metadata")
                        event.update(raw_response=content, response_model=result.get("model"),
                                     finish_reason=choice.get("finish_reason"),
                                     prompt_tokens=usage.get("prompt_tokens"),
                                     completion_tokens=usage.get("completion_tokens"))
                        if choice.get("finish_reason") == "length":
                            event.update(decision_status="error", error_kind="truncated_response",
                                         reason="Model response reached max_tokens")
            except (aiohttp.ClientError, asyncio.TimeoutError) as error:
                event.update(decision_status="error", error_kind="transport_error", reason=type(error).__name__)
            except (ValueError, KeyError, IndexError, TypeError) as error:
                event.update(decision_status="error", error_kind="protocol_error", reason=type(error).__name__)
        event["latency_ms"] = round((time.perf_counter() - start) * 1000, 3)
        if event["decision_status"] == "ok":
            try:
                event.update(parse_response(event["raw_response"]))
            except ValueError as error:
                event.update(decision_status="error", error_kind="parse_error", reason=str(error))
        if event["decision_status"] != "ok":
            event.update(decision_source="fallback", kind="stay", message="", thought="")
        return event

    def _apply_decision(self, agent, event):
        self.stats["total_actions"] += 1
        if event["decision_status"] == "ok":
            self.stats["valid_decisions"] += 1
        elif event["error_kind"] == "parse_error":
            self.stats["parse_errors"] += 1
        else:
            self.stats["llm_errors"] += 1
        event.update(energy_before=agent.energy, position_before=agent.position,
                     energy_collected=0, energy_transferred=0, energy_cost=0,
                     action_status="executed", child_id=None)
        kind = event["kind"]
        target = next((other for other in self.agents if other.id == event.get("target_id") and other.alive), None)
        reject = ""
        if not agent.alive:
            event.update(executed_action="", action_status="skipped_dead", reason="Actor already dead",
                         energy_after=agent.energy, position_after=agent.position)
            return
        if kind == "move" and abs(event["dx"]) + abs(event["dy"]) != 1:
            reject = "Move must be one cardinal cell"
        elif kind in ("share", "attack"):
            if not target or target is agent or not self._in_view_range(agent.position, target.position):
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
            event.update(action_status="rejected", reason=reject)
            kind = "stay"
        elif event["decision_source"] == "fallback":
            event["action_status"] = "fallback"

        if kind == "move":
            agent.position = ((agent.position[0] + event["dx"]) % self.grid_size,
                              (agent.position[1] + event["dy"]) % self.grid_size)
            event["energy_collected"] = self.environment.get_energy_at(agent.position)
            agent.energy += event["energy_collected"]
            event["energy_cost"] = 2
            executed = f"Move to ({event['dx']},{event['dy']})"
        elif kind == "share":
            event["energy_transferred"] = event["amount"]
            agent.energy -= event["amount"]
            target.energy += event["amount"]
            self.stats["shares"] += 1
            executed = f"Share: {target.id}-{event['amount']}"
        elif kind == "attack":
            amount = target.energy // 2
            event["energy_transferred"] = amount
            agent.energy += amount
            target.energy -= amount
            self.stats["attacks"] += 1
            executed = f"Attack: {target.id}"
        elif kind == "reproduce":
            dx, dy = self.rng.choice([(-1, 0), (1, 0), (0, -1), (0, 1)])
            pos = ((agent.position[0] + dx) % self.grid_size, (agent.position[1] + dy) % self.grid_size)
            child = self._new_agent(len(self.agents), pos, self.child_initial_energy, parent=agent)
            self.agents.append(child)
            self.stats["total_born"] += 1
            self.stats["reproductions"] += 1
            event.update(energy_cost=self.reproduce_cost, child_id=child.id)
            executed = "Reproduce"
        else:
            event["energy_cost"] = 1
            executed = "Stay"
        agent.energy -= event["energy_cost"]
        agent.action, agent.thoughts, agent.message = executed, event["thought"], event["message"]
        agent.age += 1
        agent.memory.append(f"Step {self.step_count}: {executed}; {agent.thoughts[:100]}")
        if agent.energy <= 0:
            agent.alive = False
            agent.death_step, agent.death_cause = self.step_count, "energy_depleted"
            self.stats["total_died"] += 1
        event.update(executed_action=executed, energy_after=agent.energy, position_after=agent.position)

    async def step(self, session=None):
        if session is None:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as client:
                return await self.step(client)
        self.step_count += 1
        living = [agent for agent in self.agents if agent.alive]
        before = self.stats.copy()
        for agent in living:
            agent.messages, agent.next_messages = agent.next_messages, []
        self.environment.random_spawn()
        decisions = []
        # Collect all decisions from the same world state. One HTTP request at a time.
        for agent in living:
            view, messages = agent.get_local_view(self.environment, living)
            prompts = agent.build_prompt(view, messages, len(living), self.reproduce_cost, self.population_cap)
            decisions.append(await self._request_decision(session, agent, *prompts))
        for agent, event in zip(living, decisions):
            self._apply_decision(agent, event)
        for sender in living:
            if not sender.alive or not sender.message:
                continue
            for recipient in self.agents:
                if recipient.alive and recipient is not sender and self._in_view_range(sender.position, recipient.position):
                    recipient.next_messages.append(f"Agent{sender.id}: {sender.message}")
        snapshot = self.snapshot(decisions)
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

    def visualize(self, save_path):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(7, 7))
        if self.environment.energy_sources:
            xs, ys = zip(*self.environment.energy_sources)
            ax.scatter(xs, ys, c="orange", marker="s", s=60, label="Energy")
        living = [agent for agent in self.agents if agent.alive]
        for agent in living:
            index = MBTI_TYPES.index(agent.mbti_type) if agent.mbti_type else 0
            ax.scatter(*agent.position, c=[plt.get_cmap("tab20")(index)], s=max(10, agent.energy / 2))
            ax.annotate(str(agent.id), agent.position, fontsize=8)
        ax.set(xlim=(-1, self.grid_size), ylim=(-1, self.grid_size), xlabel="X", ylabel="Y",
               title=f"Step {self.step_count} | Alive {len(living)} | Decisions {self.stats['total_actions']}")
        ax.grid(alpha=0.2)
        fig.tight_layout()
        fig.savefig(save_path, dpi=120)
        plt.close(fig)


DEFAULT_PARAMS = {
    "num_agents": 5, "grid_size": 30, "num_steps": 15, "seed": 0, "use_mbti": True,
    "initial_energy": INITIAL_ENERGY, "spawn_energy_count": SPAWN_ENERGY_COUNT,
    "reproduce_cost": REPRODUCE_COST, "child_initial_energy": CHILD_INITIAL_ENERGY,
    "cluster_radius": CLUSTER_RADIUS, "num_clusters": NUM_CLUSTERS,
    "energy_spawn_rate": ENERGY_SPAWN_RATE, "custom_world_prompt": "",
    "model": "default_model", "base_url": "http://127.0.0.1:8080/v1", "api_key": "",
    "mock_mode": False, "temperature": 0.0, "max_tokens": 384, "timeout": 120.0,
    "population_cap": 60, "output_dir": "outputs", "save_images": False,
    "action_order": "observe_then_apply_by_agent_id", "request_concurrency": 1,
}


async def main(run_id=0, params=None):
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
    sim_params = {key: value for key, value in config.items()
                  if key not in ("num_steps", "output_dir", "save_images", "action_order", "request_concurrency")}
    sim = Simulation(**sim_params)
    recorder = RunRecorder(config["output_dir"], config, run_id)
    recorder.record(sim.snapshot())
    print(f"Run: {recorder.directory}", flush=True)
    image_dir = recorder.directory / "img"
    try:
        if config["save_images"]:
            image_dir.mkdir()
            sim.visualize(image_dir / "step_000.png")
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=config["timeout"])) as session:
            for _ in range(config["num_steps"]):
                snapshot = await sim.step(session)
                recorder.record(snapshot)
                summary = snapshot["summary"]
                print(f"Step {sim.step_count}: alive={summary['alive']}, decisions={summary['total_actions']}, "
                      f"llm_errors={summary['llm_errors']}, parse_errors={summary['parse_errors']}", flush=True)
                if config["save_images"] and sim.step_count % 5 == 0:
                    sim.visualize(image_dir / f"step_{sim.step_count:03d}.png")
                if not summary["alive"]:
                    break
        if config["save_images"]:
            sim.visualize(image_dir / "final.png")
        errors = sim.stats["llm_errors"] + sim.stats["parse_errors"]
        status = "completed_with_errors" if errors else "completed"
        reason = "extinction" if not sim.get_summary()["alive"] else "step_limit"
        return recorder.finish(status, reason)
    except (KeyboardInterrupt, asyncio.CancelledError):
        recorder.finish("interrupted", "cancelled")
        raise
    except Exception as error:
        # Store a safe type, not arbitrary exception text that could contain a credential.
        return recorder.finish("failed", "exception", type(error).__name__)


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


def run_streamlit_ui():
    import streamlit as st
    import pandas as pd
    st.set_page_config(page_title="LLM SugarScape", layout="wide")
    st.title("LLM SugarScape")
    st.caption("小規模実験・行動記録・CSV集計")
    mode = st.sidebar.selectbox("Connection", ["Local LLM (8080)", "Mock (no API)", "Custom API"])
    mock_mode = mode == "Mock (no API)"
    local_mode = mode == "Local LLM (8080)"
    base_url = st.sidebar.text_input("API base URL", DEFAULT_PARAMS["base_url"], disabled=mode != "Custom API")
    model = st.sidebar.text_input("Model", "default_model", disabled=mode != "Custom API",
                                  help="8080では起動済みモデルを使う default_model を指定します。")
    api_key = st.sidebar.text_input("API key (optional)", type="password")
    params = {"base_url": DEFAULT_PARAMS["base_url"] if local_mode else base_url,
              "model": "default_model" if local_mode else model,
              "mock_mode": mock_mode, "api_key": api_key or os.getenv("SUGARSCAPE_API_KEY", "")}
    params["num_agents"] = st.sidebar.slider("Num Agents", 1, 20, 5)
    params["num_steps"] = st.sidebar.number_input("Num Steps", min_value=1, max_value=1000, value=15)
    params["seed"] = st.sidebar.number_input("Seed", min_value=0, max_value=2 ** 32 - 1, value=42)
    params["use_mbti"] = st.sidebar.checkbox("Use MBTI", True)
    with st.sidebar.expander("World and energy"):
        params["grid_size"] = st.number_input("Grid Size", min_value=11, max_value=100, value=30)
        params["initial_energy"] = st.number_input("Initial Energy", min_value=1, value=150)
        params["spawn_energy_count"] = st.number_input("Initial Energy Sources", min_value=0, max_value=100, value=20)
        params["energy_spawn_rate"] = st.number_input("Resource spawn probability per step", 0.0, 1.0, 0.001, format="%.3f")
        params["cluster_radius"] = st.number_input("Cluster Radius", min_value=0, max_value=10, value=5)
        params["num_clusters"] = st.number_input("Num Clusters", min_value=1, max_value=10, value=3)
        params["reproduce_cost"] = st.number_input("Reproduce Cost", min_value=1, value=70)
        params["child_initial_energy"] = st.number_input("Child Energy", min_value=1, value=150)
        params["custom_world_prompt"] = st.text_area("World Lore")
    with st.sidebar.expander("Generation and output"):
        params["temperature"] = st.number_input("Temperature", 0.0, 2.0, 0.0, step=0.1)
        params["max_tokens"] = st.number_input("Max tokens", min_value=64, max_value=8192, value=384)
        params["timeout"] = st.number_input("Request timeout (seconds)", min_value=1.0, value=120.0)
        params["save_images"] = st.checkbox("Save grid images", False)
        params["output_dir"] = st.text_input("Output directory", "outputs")
    if st.sidebar.button("Run Simulation", type="primary"):
        st.session_state.pop("result", None)
        with st.spinner("Running sequentially and saving each completed step..."):
            try:
                st.session_state.result = asyncio.run(main(params=params))
            except Exception as error:
                st.error(f"Simulation could not start: {type(error).__name__}")
    if st.sidebar.button("Clear Results"):
        st.session_state.pop("result", None)
        st.rerun()
    result = st.session_state.get("result")
    if result:
        status = result["status"]
        if status == "completed":
            st.success("Simulation complete")
        else:
            st.warning(f"Run status: {status}. Inspect events.csv / run.json before analysis.")
        summary = result["summary"]
        columns = st.columns(4)
        for column, key in zip(columns, ("alive", "total_born", "total_died", "total_actions")):
            column.metric(key, summary.get(key, 0))
        st.write(f"Saved: {result['output_dir']}")
        frame = pd.DataFrame([snap["summary"] for snap in result["logs"]]).set_index("step")
        st.line_chart(frame[["alive", "total_born", "total_died"]])
        st.dataframe(frame, width="stretch")
        for filename in ("steps.csv", "agents.csv", "events.csv", "run.json"):
            path = Path(result["output_dir"]) / filename
            st.download_button(f"Download {filename}", data=path.read_bytes(), file_name=filename,
                               mime="application/json" if filename.endswith("json") else "text/csv")
        with st.expander("Experiment config"):
            st.json(result["config"])
        final = Path(result["output_dir"]) / "img" / "final.png"
        if final.exists():
            st.image(str(final))
    st.info("Each run has its own folder. To compare saved runs: python main.py aggregate --input outputs")


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
    run.add_argument("--no-mbti", action="store_true")
    run.add_argument("--grid-size", type=int, default=30)
    run.add_argument("--initial-energy", type=int, default=INITIAL_ENERGY)
    run.add_argument("--spawn-energy-count", type=int, default=SPAWN_ENERGY_COUNT)
    run.add_argument("--reproduce-cost", type=int, default=REPRODUCE_COST)
    run.add_argument("--child-initial-energy", type=int, default=CHILD_INITIAL_ENERGY)
    run.add_argument("--energy-spawn-rate", type=float, default=ENERGY_SPAWN_RATE)
    run.add_argument("--cluster-radius", type=int, default=CLUSTER_RADIUS)
    run.add_argument("--num-clusters", type=int, default=NUM_CLUSTERS)
    run.add_argument("--population-cap", type=int, default=60)
    run.add_argument("--world-prompt", default="")
    run.add_argument("--temperature", type=float, default=0.0)
    run.add_argument("--max-tokens", type=int, default=384)
    run.add_argument("--timeout", type=float, default=120.0)
    run.add_argument("--output", default="outputs")
    run.add_argument("--images", action="store_true")
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
              "api_key": os.getenv("SUGARSCAPE_API_KEY", ""), "use_mbti": not args.no_mbti,
              "temperature": args.temperature, "max_tokens": args.max_tokens, "timeout": args.timeout,
              "output_dir": args.output, "save_images": args.images, "custom_world_prompt": args.world_prompt}
    for key in ("initial_energy", "spawn_energy_count", "reproduce_cost", "child_initial_energy",
                "energy_spawn_rate", "cluster_radius", "num_clusters", "population_cap"):
        config[key] = getattr(args, key)
    for index in range(args.runs):
        try:
            result = asyncio.run(main(index, {**config, "seed": args.seed + index}))
        except ValueError as error:
            parser.error(str(error))
        print(json.dumps({"status": result["status"], "output_dir": result["output_dir"],
                          "summary": result["summary"]}, ensure_ascii=False, indent=2))
        if result["status"] != "completed":
            return 2
    return 0


if __name__ == "__main__":
    # Preserve the existing Streamlit entry; CLI and UI call the same main()/Simulation.
    if len(sys.argv) > 1:
        raise SystemExit(cli())
    run_streamlit_ui()
