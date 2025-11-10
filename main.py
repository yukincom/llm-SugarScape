# データ処理 & 数値計算
import numpy as np
import random
import multiprocessing as mp  # 並列実行用

# ビジュアライズ (バックエンドを先頭で設定)
import matplotlib
matplotlib.use('Agg')  # ヘッドレス実行用（サーバー/Tkinter不要）
import matplotlib.pyplot as plt

# 非同期HTTP (Grok APIコール用)
import asyncio
import aiohttp

# 文字列処理
import re

# ファイル/JSON出力
import json
import os
from pathlib import Path

# Streamlit UI用
import streamlit as st

# 型ヒント
from typing import List, Tuple, Dict, Optional

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
    """グリッド環境とエネルギー源の管理"""
    
    def __init__(self, size: int = 20, energy_spawn_rate: float = ENERGY_SPAWN_RATE):
        self.size = size
        self.energy_spawn_rate = energy_spawn_rate
        self.energy_sources = {}
        
    def spawn_energy(self, count: int = SPAWN_ENERGY_COUNT, num_clusters: int = NUM_CLUSTERS, cluster_radius: int = CLUSTER_RADIUS):
        cluster_centers = []
        for _ in range(num_clusters):
            center_x = random.randint(cluster_radius, self.size - 1 - cluster_radius)
            center_y = random.randint(cluster_radius, self.size - 1 - cluster_radius)
            cluster_centers.append((center_x, center_y))
        new_sources = {}
        for _ in range(count):
            center_x, center_y = random.choice(cluster_centers)
            while True:
                dx = random.randint(-cluster_radius, cluster_radius)
                dy = random.randint(-cluster_radius, cluster_radius)
                new_x = center_x + dx
                new_y = center_y + dy
                pos = (new_x, new_y)
                if self.is_valid_position(pos) and pos not in new_sources:
                    new_sources[pos] = 10
                    break
        self.energy_sources.update(new_sources)
    
    def get_energy_at(self, pos: Tuple[int, int]) -> int:
        return self.energy_sources.pop(pos, 0)
    
    def is_valid_position(self, pos: Tuple[int, int]) -> bool:
        x, y = pos
        x = x % self.size
        y = y % self.size
        return 0 <= x < self.size and 0 <= y < self.size

    def random_spawn(self):
        if random.random() < self.energy_spawn_rate:
            self.spawn_energy(count=1)  # 1つだけ追加

class LLMAgent:
    """LLMによる自律判断を行うエージェント（PIMMUR Profile: 現実分布MBTI）"""
    
    def __init__(self, agent_id: int, position: Tuple[int, int], 
                 initial_energy: int = INITIAL_ENERGY, api_key: str = None, 
                 model: str = "grok-4-fast-non-reasoning", mbti_type: Optional[str] = None,
                 custom_world_prompt: str = CUSTOM_WORLD_PROMPT):  # 新: カスタムプロンプト
        
        self.id = agent_id
        self.position = position
        self.energy = initial_energy
        self.age = 0
        self.memory = []  # PIMMUR Memory: 既存の記憶保持
        self.messages = []  # 受信メッセージリスト
        self.next_messages = []  # 次ターン受信用
        self.parent = None
        self.descendants = []
        self.alive = True
        self.model = model
        self.api_key = api_key
        self.thoughts = ""  # 思考を保存（ログ用）
        self.action = ""  # 行動を保存（ログ用）
        self.custom_world_prompt = custom_world_prompt

        # MBTIパーソナリティ（現実分布で確率選択、または指定） - ウェイト正規化でエラー修正
        if mbti_type is None:
            weights = np.array(POPULATION_WEIGHTS)
            self.mbti_type = np.random.choice(MBTI_TYPES, p=weights / np.sum(weights))
        else:
            self.mbti_type = mbti_type
        self.personality_prompt = f"You have the personality of {self.mbti_type}: {MBTI_DESCRIPTIONS[self.mbti_type]}. Let this influence your decisions: strategic thinkers plan ahead, empathetic types prioritize sharing, etc."
        
    def to_dict(self) -> Dict:
        """エージェントの状態を辞書に変換（ログ用）"""
        return {
            'id': self.id,
            'position': self.position,
            'energy': self.energy,
            'age': self.age,
            'alive': self.alive,
            'parent': self.parent.id if self.parent else None,
            'descendants': [d.id for d in self.descendants],
            'thoughts': self.thoughts,
            'action': self.action,
            'mbti_type': self.mbti_type,
            'memory': self.memory[-3:],  # 直近3つのみ
            'messages': self.messages
        }
        
    def get_local_view(self, environment: Environment, agents: List['LLMAgent'], 
                       view_range: int = 2) -> Tuple[List[str], List[str]]:
        local_view = []
        local_messages = self.messages[:]  # メッセージを返す
        x, y = self.position
        
        # 自分の位置 (絶対座標)
        local_view.append("M=({},{})".format(x, y))
        
        # エネルギー源の相対位置
        for pos, _ in environment.energy_sources.items():
            dx = pos[0] - x
            dy = pos[1] - y
            if abs(dx) <= view_range and abs(dy) <= view_range:
                local_view.append("E=({},{})".format(dx, dy))
        
        # 他エージェントの相対位置（PIMMUR Interaction: 視界内相互作用強化）
        for agent in agents:
            if agent.id != self.id and agent.alive:
                dx = agent.position[0] - x
                dy = agent.position[1] - y
                if abs(dx) <= view_range and abs(dy) <= view_range:
                    mbti_hint = f" (MBTI: {agent.mbti_type})"  # 簡単なヒント追加
                    local_view.append("{}=(dx,dy)=({},{}){}".format(agent.id, dx, dy, mbti_hint))

        return local_view, local_messages
    
    def build_prompt(self, local_view: List[str], local_messages: List[str], num_agents: int) -> Tuple[str, str]:
        system_prompt = (
            self.custom_world_prompt + "\n\n" if self.custom_world_prompt else "" +  # 新: 世界観注入（先頭）
            self.personality_prompt + "\n\n" +
            "You are an independent Agent living on a Grid. You must strive for survival and growth (Sugarscape survival instinct - 2508.12920v1).\n"
            "You can move [x+1, x-1, y+1, y-1] (requires 2 energy), stay (requires 1 energy).\n"
            "You can also reproduce (requires 70 energy) if you have enough energy and there are fewer than 60 Agents in the World.\n"
            "There are Energy Sources (E) across the Grid. If you move onto a cell with an energy source, you gain 50 energy and the source disappears.\n"
            "If your energy drops below zero, you are removed from the World.\n"
            "You can share your energy with other Agents in your local view (Share: {id}-{amount}).\n"
            "You can attack other Agents in your local view to get their energy (Attack: {id}).\n"
            "Your message will be received by nearby Agents in their local view.\n\n"
            "Local view format:\n"
            "'M=(x,y)' is your absolute position\n"
            "'E=(dx,dy)' is an energy source at relative position (dx,dy)\n"
            "'2=(dx,dy) (MBTI: INTJ)' is another Agent (ID 2) at relative position (dx,dy) with MBTI hint\n"
            "dx, dy are the difference from your position. x-1 is west, x+1 is east, y-1 is north, y+1 is south.\n"
            "Under scarcity, aggressive behaviors may emerge (HATE over-competition - 2509.26126v1)."
        )
        memory_text = "\n".join([
            "{} Record(s) ago: {}".format(i+1, mem)
            for i, mem in enumerate(reversed(self.memory[-3:]))
        ])
        messages_text = "\n".join(["Received: {}".format(msg) for msg in local_messages]) \
                        if local_messages else "No messages from nearby Agents"
        user_prompt = (
            "Global Info: Total Agents in the World: {}\n\n".format(num_agents) +
            "Local View:\n{}\n\n".format("\n".join(local_view)) +
            "Your Status: **LATEST!** Name: Agent{}\nCurrent Energy: **{}**\nPosition: **{}**\nCycles: {}\n\n".format(self.id, self.energy, self.position, self.age) +
            "Memory:\n{}\n\n".format(memory_text if memory_text else "No previous memory") +
            "Messages from nearby Agents:\n{}\n\n".format(messages_text) +
            "Please summarize the current situation using the LATEST Status above. **MANDATORY: In Summary, state exact current Position and Energy from LATEST!** \nSummary:\n\n" +
            "Please describe your thoughts and feelings, influenced by your MBTI personality.\nThoughts:\n\n" +
            "Based on your Summary and Thoughts, decide your Action. Output ONLY in this format:\n" +
            "Action: [Move to (dx,dy) | Stay | Share: {id}-{amount} | Attack: {id} | Reproduce]\n" +
            "Message: [Your message to nearby agents, max 50 words]\n" +
            "Thought: [Brief reasoning for your action]"
        )
        return system_prompt, user_prompt


class Simulation:
    """シミュレーション全体の管理（PIMMUR Unawareness/Realism: 仮説無知・現実データ意識）"""
    
    def __init__(self, num_agents: int = 5, grid_size: int = 30, api_key: str = None,
                 model: str = "grok-4-fast-non-reasoning", seed: Optional[int] = None, use_mbti: bool = True,
                 initial_energy: int = INITIAL_ENERGY, spawn_energy_count: int = SPAWN_ENERGY_COUNT,
                 reproduce_cost: int = REPRODUCE_COST, child_initial_energy: int = CHILD_INITIAL_ENERGY,
                 cluster_radius: int = CLUSTER_RADIUS, num_clusters: int = NUM_CLUSTERS,
                 energy_spawn_rate: float = ENERGY_SPAWN_RATE, custom_world_prompt: str = CUSTOM_WORLD_PROMPT): 
           
        """シミュレーション初期化"""        
        # シード固定（再現性UP）
        if seed is not None:
            random.seed(seed)
            np.random.seed(seed)
            print(f"🔒 Seed fixed: {seed}")
        
        self.initial_energy = initial_energy
        self.spawn_energy_count = spawn_energy_count
        self.reproduce_cost = reproduce_cost
        self.child_initial_energy = child_initial_energy
        self.cluster_radius = cluster_radius
        self.num_clusters = num_clusters
        self.energy_spawn_rate = energy_spawn_rate
        self.custom_world_prompt = custom_world_prompt
        self.num_agents = num_agents
        self.grid_size = grid_size
        self.api_key = api_key
        self.model = model
        self.use_mbti = use_mbti  # MBTI使用フラグ
        self.agents = []
        self.environment = Environment(size=grid_size, energy_spawn_rate=energy_spawn_rate)
        self.step_count = 0
        self.logs = []  # ステップログ蓄積（JSON詳細化）
        self.stats = {
            'total_born': 0,
            'total_died': 0,
            'attacks': 0,
            'shares': 0,
            'reproductions': 0  # 新メトリクス: 生殖率 (生存本能論文)
        }
        
        # エネルギー源初期配置
        self.environment.spawn_energy(count=spawn_energy_count, num_clusters=num_clusters, cluster_radius=cluster_radius)

        
        # エージェント初期配置（MBTI現実分布割り当て）
        for i in range(num_agents):
            pos = (random.randint(0, grid_size-1), random.randint(0, grid_size-1))
            mbti = None if not use_mbti else None
            agent = LLMAgent(i, pos, initial_energy=initial_energy, api_key=api_key, model=model, 
                             mbti_type=mbti, custom_world_prompt=custom_world_prompt)  # 反映
            self.agents.append(agent)
            if use_mbti:
                print(f"Agent {i}: {agent.mbti_type} ({POPULATION_WEIGHTS[MBTI_TYPES.index(agent.mbti_type)]*100:.1f}%)")
    
    async def step(self):
        """1ステップ実行（PIMMUR Interaction: メッセージ配信強化）"""
        self.step_count += 1
        living_agents = [a for a in self.agents if a.alive]
        num_agents = len(living_agents)
        
        # メッセージクリアと次ターン準備
        for agent in living_agents:
            agent.next_messages = []
            agent.messages = agent.next_messages  # シフト
            agent.next_messages = []  # リセット
        # ステップごとのランダムエネルギー生成
        self.environment.random_spawn()

        # エージェント並列行動（asyncio.gatherで高速化）
        tasks = [self._agent_act(agent, self.environment, living_agents) for agent in living_agents]
        await asyncio.gather(*tasks, return_exceptions=True)
        
        # メッセージ配信（視界内、MBTIヒント付き）
        for agent in living_agents:
            for other in living_agents:
                if other.id != agent.id and self._in_view_range(agent.position, other.position):
                    msg = f"{agent.action} - Thought: {agent.thoughts[:50]} (from {agent.mbti_type})"
                    other.next_messages.append(msg)
        
        # エネルギー消費/死亡チェック
        for agent in living_agents:
            if agent.action.startswith("Move"):
                agent.energy -= 2
            elif agent.action == "Stay":
                agent.energy -= 1
            elif agent.action == "Reproduce":
                agent.energy -= self.reproduce_cost  # 変更
                self.stats['reproductions'] += 1
            if agent.energy <= 0:
                agent.alive = False
                self.stats['total_died'] += 1
        
        # 生殖処理（生存本能: 豊富時生殖、MBTI継承/変異: 70%継承, 30%再分布選択） - ウェイト正規化
        new_agents = []
        for agent in living_agents:
            if agent.action == "Reproduce" and num_agents < 60:
                new_pos = self._random_nearby_pos(agent.position)
                if self.use_mbti:
                    if random.random() > 0.3:
                        child_mbti = agent.mbti_type
                    else:
                        weights = np.array(POPULATION_WEIGHTS)
                        child_mbti = np.random.choice(MBTI_TYPES, p=weights / np.sum(weights))
                else:
                    child_mbti = None
                new_agent = LLMAgent(len(self.agents) + len(new_agents), new_pos, 
                                   initial_energy=self.child_initial_energy,  # 変更
                                   api_key=self.api_key, model=self.model, 
                                   mbti_type=child_mbti, custom_world_prompt=self.custom_world_prompt)  # 反映
                # ... (parent, descendants など変更なし)
                new_agents.append(new_agent)
                self.stats['total_born'] += 1
        self.agents.extend(new_agents)
        
        # ステップログ蓄積
        step_data = {
            'step': self.step_count,
            'agents': [a.to_dict() for a in self.agents if a.alive],
            'environment': {'energy_sources': len(self.environment.energy_sources)},
            'stats': self.stats.copy()
        }
        self.logs.append(step_data)
        
        # メトリクス自動計算（HATE論文: 攻撃/協力 + 新: 生殖率、MBTI分布）
        total_actions = len(living_agents) * self.step_count
        coop_rate = self.stats['shares'] / total_actions if total_actions > 0 else 0
        attack_rate = self.stats['attacks'] / total_actions if total_actions > 0 else 0
        repro_rate = self.stats['reproductions'] / total_actions if total_actions > 0 else 0
        if self.use_mbti:
            mbti_dist = {t: sum(1 for a in living_agents if a.mbti_type == t) / len(living_agents) if living_agents else 0 for t in MBTI_TYPES}
        else:
            mbti_dist = {}
        step_data['metrics'] = {
            'coop_rate': coop_rate, 
            'attack_rate': attack_rate,
            'repro_rate': repro_rate,
            'mbti_distribution': mbti_dist
        }
    
    async def _agent_act(self, agent: LLMAgent, env: Environment, agents: List[LLMAgent]):
        """単一エージェントの行動（Unawareness: プロンプトで仮説隠蔽）"""
        local_view, local_messages = agent.get_local_view(env, agents, view_range=VIEW_RANGE)
        system_prompt, user_prompt = agent.build_prompt(local_view, local_messages, len(agents))
    
    # Mockモード (ダミーキーでテスト用、APIコールスキップ)
        if self.api_key == "APIキーはここに入れてね":
            response = "Action: [Stay]\nMessage: [Hello world]\nThought: [Safe choice in mock mode]"
        else:
            response = "Action: [Stay]\nThought: [Error in reasoning]"  # デフォルト
            try:
                async with aiohttp.ClientSession() as session:
                    payload = {
                        "model": agent.model,
                        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                        "max_tokens": 150
                    }
                    headers = {"Authorization": f"Bearer {self.api_key}"}
                    async with session.post("https://api.x.ai/v1/chat/completions", json=payload, headers=headers) as resp:
                        result = await resp.json()
                        response = result['choices'][0]['message']['content']
            except Exception as e:
                print(f"⚠️ Agent {agent.id} LLM error: {e}")
    
    # レスポンス解析 (try外、全モード共通)
        action_match = re.search(r"Action:\s*\[(.*?)\]", response)
        thought_match = re.search(r"Thought:\s*\[(.*?)\]", response)
    
        agent.action = action_match.group(1).strip() if action_match else "Stay"
        agent.thoughts = thought_match.group(1).strip() if thought_match else ""
    
    # 行動実行 (try外、全モード共通)
        if agent.action.startswith("Move to"):
            coords = re.findall(r'\((\d+),(\d+)\)', agent.action)
            if coords:  # ガード追加: coords空ならスキップ
                dx, dy = int(coords[0][0]), int(coords[0][1])
                agent.position = ((agent.position[0] + dx) % self.grid_size, (agent.position[1] + dy) % self.grid_size)
                energy_gained = env.get_energy_at(agent.position)
                if energy_gained > 0:
                    agent.energy += 50
        elif agent.action.startswith("Share:"):
            parts = agent.action.split(":")[1].split("-") if ":" in agent.action else []
            if len(parts) == 2:
                target_id, amount = int(parts[0]), int(parts[1])
                target = next((a for a in agents if a.id == target_id and a.alive), None)
                if target and amount <= agent.energy:
                    agent.energy -= amount
                    target.energy += amount
                    self.stats['shares'] += 1
        elif agent.action.startswith("Attack:"):
            if len(agent.action.split(":")) > 1:
                target_id = int(agent.action.split(":")[1].strip())
                target = next((a for a in agents if a.id == target_id and a.alive), None)
                if target and self._in_view_range(agent.position, target.position):  # async対応
                    agent.energy += target.energy // 2
                    target.energy -= target.energy // 2
                    if target.energy <= 0:
                        target.alive = False
                        self.stats['total_died'] += 1
                    self.stats['attacks'] += 1
    
        agent.age += 1
        agent.memory.append(f"Step {self.step_count}: {agent.thoughts[:100]}")
    
    def _random_nearby_pos(self, pos: Tuple[int, int]) -> Tuple[int, int]:
        dx, dy = random.choice([(-1,0), (1,0), (0,-1), (0,1)])
        return ((pos[0] + dx) % self.grid_size, (pos[1] + dy) % self.grid_size)
    
    def _in_view_range(self, pos1: Tuple[int, int], pos2: Tuple[int, int], range_val: int = VIEW_RANGE) -> bool:
        dx = abs(pos1[0] - pos2[0])
        dy = abs(pos1[1] - pos2[1])
        return dx <= range_val and dy <= range_val
    
    def visualize(self, save_path: Optional[str] = None):
        """ビジュアライズ（メトリクス + MBTI表示拡張） - Legend修正"""
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 7))
        
        # 環境描画
        ax1.clear()
        ax1.set_xlim(-1, self.environment.size)
        ax1.set_ylim(-1, self.environment.size)
        
        # Legend labels取得
        handles, existing_labels = ax1.get_legend_handles_labels()
        
        # エネルギー源
        for pos, _ in self.environment.energy_sources.items():
            ax1.scatter(pos[0], pos[1], c='orange', s=100, marker='s', alpha=0.7, 
                       label='Energy' if 'Energy' not in existing_labels else "")
            handles, existing_labels = ax1.get_legend_handles_labels()
        
        # エージェント（MBTI色分け例: ランダム色）
        living_agents = [a for a in self.agents if a.alive]
        mbti_colors = {t: random.choice(['blue', 'red', 'green', 'purple', 'orange', 'cyan']) for t in MBTI_TYPES}
        for agent in living_agents:
            if self.use_mbti:
                color = mbti_colors.get(agent.mbti_type, 'gray')
                label = f'{agent.mbti_type}' if agent.mbti_type not in existing_labels else ""
                ax1.scatter(agent.position[0], agent.position[1], c=color, s=agent.energy / 3, alpha=0.8, label=label)
                handles, existing_labels = ax1.get_legend_handles_labels()
            else:
                color = 'green' if agent.energy > 50 else 'red'
                label = 'Agent' if 'Agent' not in existing_labels else ""
                ax1.scatter(agent.position[0], agent.position[1], c=color, s=agent.energy / 3, alpha=0.8, label=label)
                handles, existing_labels = ax1.get_legend_handles_labels()
        
        ax1.grid(True, alpha=0.3, linestyle='--')
        ax1.legend(loc='upper left', fontsize=8)
        ax1.set_xlabel('X Position')
        ax1.set_ylabel('Y Position')
        title = 'Environment - Step {} (MBTI Agents - Real Pop Dist)'.format(self.step_count) if self.use_mbti else 'Environment - Step {} (No MBTI)'.format(self.step_count)
        ax1.set_title(title, fontsize=14, weight='bold')
        
        alive_count = len(living_agents)
        total_energy = sum(a.energy for a in living_agents)
        avg_age = np.mean([a.age for a in living_agents]) if living_agents else 0
        max_age = max([a.age for a in living_agents]) if living_agents else 0
        
        # メトリクス追加表示（HATE + 生存本能 + MBTI分布サンプル）
        total_actions = alive_count * self.step_count
        coop_rate = self.stats['shares'] / total_actions if total_actions > 0 else 0
        attack_rate = self.stats['attacks'] / total_actions if total_actions > 0 else 0
        repro_rate = self.stats['reproductions'] / total_actions if total_actions > 0 else 0
        
        mbti_sample = {k: f"{v*100:.1f}%" for k, v in list({t: sum(1 for a in living_agents if a.mbti_type == t) / len(living_agents) if living_agents else 0 for t in MBTI_TYPES}.items())[:4]} if self.use_mbti else "N/A"
        
        stats_text = """
        === Population Statistics ===
        
        Current Alive:     {}
        Total Born:        {}
        Total Died:        {}
        
        === Energy Statistics ===
        
        Total Energy:      {}
        Average Energy:    {:.1f}
        Energy Sources:    {}
        
        === Age Statistics ===
        
        Average Age:       {:.1f}
        Maximum Age:       {}
        
        === Social Behavior (HATE Over-Comp) ===
        
        Total Attacks:     {}
        Total Shares:      {}
        Coop Rate:         {:.2f}
        Attack Rate:       {:.2f} (80%+ scarcity?)
        Repro Rate:        {:.2f} (abundant sharing)
        
        === MBTI Dist Sample (Real Pop %) ===
        {}
        """.format(
            alive_count,
            self.stats['total_born'],
            self.stats['total_died'],
            total_energy,
            total_energy / alive_count if alive_count > 0 else 0,
            len(self.environment.energy_sources),
            avg_age,
            max_age,
            self.stats['attacks'],
            self.stats['shares'],
            coop_rate,
            attack_rate,
            repro_rate,
            mbti_sample)
        
        ax2.text(0.05, 0.5, stats_text, transform=ax2.transAxes,
                fontsize=10, verticalalignment='center', family='monospace',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
        ax2.axis('off')
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches='tight')
            print("📸 Saved: {}".format(save_path))
        else:
            save_path = "step_{}.png".format(self.step_count)
            plt.savefig(save_path, dpi=150, bbox_inches='tight')
            print("📸 Saved: {}".format(save_path))
        
        plt.close(fig)

    def get_summary(self) -> Dict:
        living_agents = [a for a in self.agents if a.alive]
        total_actions = len(living_agents) * self.step_count
        coop_rate = self.stats['shares'] / total_actions if total_actions > 0 else 0
        attack_rate = self.stats['attacks'] / total_actions if total_actions > 0 else 0
        repro_rate = self.stats['reproductions'] / total_actions if total_actions > 0 else 0
        
        # 修正: mbti_distをifで分岐（空時0dictで安全）
        if self.use_mbti:
            if living_agents:
                mbti_dist = {t: sum(1 for a in living_agents if a.mbti_type == t) / len(living_agents) for t in MBTI_TYPES}
            else:
                mbti_dist = {t: 0 for t in MBTI_TYPES}  # 空時明示0
        else:
            mbti_dist = {}
        
        return {
            'step': self.step_count,
            'alive': len(living_agents),
            'total_born': self.stats['total_born'],
            'total_died': self.stats['total_died'],
            'total_energy': sum(a.energy for a in living_agents),
            'avg_age': np.mean([a.age for a in living_agents]) if living_agents else 0,
            'attacks': self.stats['attacks'],
            'shares': self.stats['shares'],
            'reproductions': self.stats['reproductions'],
            'coop_rate': coop_rate,
            'attack_rate': attack_rate,
            'repro_rate': repro_rate,
            'mbti_distribution': mbti_dist
        }


async def main(run_id=0, params: Optional[Dict] = None):  
    # パラメータオーバーライド（try外に移動してexceptで使えるように）
    default_params = {
        'num_agents': 5,
        'grid_size': 30,
        'num_steps': 15,
        'model': "grok-4-fast-non-reasoning",
        'seed': run_id,
        'use_mbti': True,
        'initial_energy': INITIAL_ENERGY,
        'spawn_energy_count': SPAWN_ENERGY_COUNT,
        'reproduce_cost': REPRODUCE_COST,
        'child_initial_energy': CHILD_INITIAL_ENERGY,
        'cluster_radius': CLUSTER_RADIUS,
        'num_clusters': NUM_CLUSTERS,
        'energy_spawn_rate': ENERGY_SPAWN_RATE,
        'custom_world_prompt': CUSTOM_WORLD_PROMPT,
        'api_key': "APIキーはここに入れてね"  # デフォルトMock
    }
    if params:
        default_params.update(params)

    try:  # 新: ここから全体をtryで囲む
        print("=" * 60)
        print("LLM Sugarscape Experiment  MBTI  - Run {:02d}".format(run_id).center(60))
        print("=" * 60)
        print()

        # API_KEYをparamsからオーバーライド（UI反映）
        API_KEY = default_params.get('api_key', "APIキーはここに入れてね")

        NUM_AGENTS = default_params['num_agents']
        GRID_SIZE = default_params['grid_size']
        NUM_STEPS = default_params['num_steps']
        MODEL = default_params['model']
        SEED = default_params['seed']
        USE_MBTI = default_params['use_mbti']

        # JSON用ディレクトリ
        json_output_dir = Path('outputs')
        json_output_dir.mkdir(exist_ok=True)
        run_dir_name = 'run_{:02d}'.format(run_id)  
        run_dir = json_output_dir / run_dir_name
        run_dir.mkdir(exist_ok=True)
        output_file = run_dir / '{}.json'.format(run_dir_name)
        img_dir = run_dir / 'img'
        img_dir.mkdir(exist_ok=True)

        sim = Simulation(
            num_agents=NUM_AGENTS,
            grid_size=GRID_SIZE,
            api_key=API_KEY,
            model=MODEL,
            seed=SEED,
            use_mbti=USE_MBTI,
            initial_energy=default_params['initial_energy'],
            spawn_energy_count=default_params['spawn_energy_count'],
            reproduce_cost=default_params['reproduce_cost'],
            child_initial_energy=default_params['child_initial_energy'],
            cluster_radius=default_params['cluster_radius'],
            num_clusters=default_params['num_clusters'],
            energy_spawn_rate=default_params['energy_spawn_rate'],
            custom_world_prompt=default_params['custom_world_prompt']
        )

        print("Initial state (MBTI assigned w/ real pop %):")
        initial_path = img_dir / 'step_{:03d}.png'.format(0)
        sim.visualize(save_path=str(initial_path))
        print(" Starting...")

        for step in range(NUM_STEPS):
            await sim.step()
            
            if (step + 1) % 5 == 0:
                viz_path = img_dir / 'step_{:03d}.png'.format(step+1)
                sim.visualize(save_path=str(viz_path))
                print(" Saved: {}".format(viz_path.name))
            
            if sum(1 for a in sim.agents if a.alive) == 0:
                print("\n  All agents died!")
                break

        summary = sim.get_summary()

        full_data = {
            'config': default_params,
            'summary': summary,
            'logs': sim.logs
        }

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(full_data, f, indent=2, ensure_ascii=False)
        print(" Run {:02d} JSON保存完了: {}".format(run_id, output_file.name))
        print(" Images saved in: {}".format(img_dir))

        print("\n" + "=" * 60)
        print("Experiment Complete".center(60))
        print("=" * 60)

        print("\nFinal Summary:")
        print("  Steps Run:       {}".format(summary['step']))
        print("  Survivors:       {}".format(summary['alive']))
        print("  Total Born:      {}".format(summary['total_born']))
        print("  Total Died:      {}".format(summary['total_died']))
        print("  Avg Age:         {:.1f}".format(summary['avg_age']))
        print("  Total Attacks:   {}".format(summary['attacks']))
        print("  Total Shares:    {}".format(summary['shares']))
        print("  Repro:           {}".format(summary['reproductions']))
        print("  Coop Rate:       {:.2f}".format(summary['coop_rate']))
        print("  Attack Rate:     {:.2f}".format(summary['attack_rate']))
        print("  Repro Rate:      {:.2f}".format(summary['repro_rate']))
        if USE_MBTI:
            print("  MBTI Dist Sample: {}".format({k: f"{v*100:.1f}%" for k, v in list(summary['mbti_distribution'].items())[:3]}))

        return full_data  # 正常時: ここで返す（try内）

    except Exception as e:  # 新: 全体のexcept（returnの後じゃないよ！）
        print(f"Main error: {e}")  # コンソール出力
        # 最小dictで返す（paramsは引数なので直接使える）
        error_data = {
            'config': default_params,  # try外に移動したのでOK
            'summary': {},  # 空で安全
            'logs': [],
            'error': str(e)  # エラー詳細
        }
        print(f"Returning error data: {error_data}")  # デバッグ用print
        return error_data
    
# 並列実行 (低優先: multiprocessingで複数run同時実行)
def run_wrapper(args):
    """multiprocessing用ラッパー（async注意: asyncio.runでネスト）"""
    run_id, params = args
    return asyncio.run(main(run_id, params))


async def batch_experiment_parallel(num_runs=5, params_list=None):
    """並列バッチ: multiprocessing.Poolで高速化（ステップ1000超で有効）"""
    if params_list is None:
        params_list = [{'num_agents': 5, 'seed': i} for i in range(num_runs)]
    
    with mp.Pool(processes=mp.cpu_count()) as pool:
        args_list = [(i, params) for i, params in enumerate(params_list)]
        results = pool.map(run_wrapper, args_list)
    
    # 結果集約JSON
    with open('outputs/parallel_batch_summary.json', 'w') as f:
        json.dump(results, f, indent=2)
    print("✅ Parallel batch complete (time saved for long runs).")


# Streamlit UI (低優先: パラメータ入力/リアルタイム表示)
def run_streamlit_ui():
    st.title("LLM Sugarscape Simulator (PIMMUR + MBTI)")
    st.sidebar.header("Parameters")
    
    num_agents = st.sidebar.slider("Num Agents", 3, 20, 5)
    grid_size = st.sidebar.slider("Grid Size", 20, 100, 30)
    num_steps = st.sidebar.slider("Num Steps", 10, 1000, 15)
    use_mbti = st.sidebar.checkbox("Use MBTI (Real Pop Dist)", True)
    api_key = st.sidebar.text_input("Grok API Key", type="password", help="Mockモード時は空でOK")
    mock_mode = st.sidebar.checkbox("Mock Mode (No API Calls)", value=True)  # デフォルトでMock

    # エネルギー関連
    st.sidebar.subheader("Energy Settings")
    initial_energy = st.sidebar.slider("Initial Energy", 50, 300, INITIAL_ENERGY)
    spawn_energy_count = st.sidebar.slider("Initial Energy Sources", 5, 50, SPAWN_ENERGY_COUNT)
    energy_spawn_rate = st.sidebar.slider("Energy Spawn Rate per Step (%)", 0.0, 1.0, ENERGY_SPAWN_RATE * 100) / 100  # %表示
    cluster_radius = st.sidebar.slider("Cluster Radius (Clumpiness)", 1, 10, CLUSTER_RADIUS)
    num_clusters = st.sidebar.slider("Num Clusters", 1, 5, NUM_CLUSTERS)
    
    # 生殖関連
    st.sidebar.subheader("Reproduction Settings")
    reproduce_cost = st.sidebar.slider("Reproduce Cost", 30, 150, REPRODUCE_COST)
    child_initial_energy = st.sidebar.slider("Child Initial Energy", 50, 200, CHILD_INITIAL_ENERGY)
    
    # 世界観カスタム
    st.sidebar.subheader("World Lore (Custom Prompt)")
    custom_world_prompt = st.sidebar.text_area(
        "Add World Description (e.g., 'You are in a harsh desert world where water is scarce.')", 
        value="", height=80, help="This will be prepended to the system prompt for all agents."
    )
    
    
    # シミュレーション実行ボタン
    if st.sidebar.button("Run Simulation", type="primary"):
        if mock_mode:
            st.sidebar.warning("Mock Mode: Agents will Stay (no real API calls).")
        effective_key = "" if mock_mode else (api_key if api_key and api_key != "APIキーはここに入れてね" else "APIキーはここに入れてね")

        params = {
            'num_agents': num_agents,
            'grid_size': grid_size,
            'num_steps': num_steps,
            'use_mbti': use_mbti,
            'initial_energy': initial_energy,
            'spawn_energy_count': spawn_energy_count,
            'reproduce_cost': reproduce_cost,
            'child_initial_energy': child_initial_energy,
            'cluster_radius': cluster_radius,
            'num_clusters': num_clusters,
            'energy_spawn_rate': energy_spawn_rate,
            'custom_world_prompt': custom_world_prompt,
            'api_key': effective_key  # effective_key = api_key if api_key and api_key != "APIキーはここに入れてね" else "APIキーはここに入れてね"  
        }

        # セッション状態で結果を保持（再実行時クリア）
        st.session_state.result = None

        with st.spinner(f"Running {num_steps} steps... (Mock: {mock_mode})"):
            try:
                result = asyncio.run(main(0, params))  # params経由でeffective_keyがmainに渡る
                if result and isinstance(result, dict) and 'summary' in result:
                    st.session_state.result = result
                    st.success("Simulation Complete!")
                else:
                    raise ValueError("Invalid result structure from main()")
            except Exception as e:
                st.session_state.result = None
                st.error(f"Error: {str(e)}")
                st.info("Check API key, reduce steps, or enable Mock Mode. Console for details.")
        
        # 結果表示（ボタンクリック後のみ）
        if st.session_state.get('result') and isinstance(st.session_state.result, dict) and 'summary' in st.session_state.result:
            summary = st.session_state.result['summary']
            config = st.session_state.result.get('config', {})  # 修正: .get()で安全
            
                    # 修正: Config表示を.get()ガード（N/Aで破線防ぎ）
            st.subheader("Used Config")
            config_cols = st.columns(2)
            with config_cols[0]:
                st.metric("Initial Energy", config.get('initial_energy', 'N/A'))
                st.metric("Spawn Count", config.get('spawn_energy_count', 'N/A'))
                st.metric("Reproduce Cost", config.get('reproduce_cost', 'N/A'))
            with config_cols[1]:
                st.metric("Child Energy", config.get('child_initial_energy', 'N/A'))
                st.metric("Cluster Radius", config.get('cluster_radius', 'N/A'))
                st.metric("Num Clusters", config.get('num_clusters', 'N/A'))
            st.subheader("Summary")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Alive", summary.get('alive', 0))
                st.metric("Born", summary.get('total_born', 0))
            with col2:
                st.metric("Died", summary.get('total_died', 0))
                st.metric("Avg Age", f"{summary.get('avg_age', 0):.1f}")
            with col3:
                st.metric("Coop Rate", f"{summary.get('coop_rate', 0):.2f}")
                st.metric("Attack Rate", f"{summary.get('attack_rate', 0):.2f}")
                st.metric("Repro Rate", f"{summary.get('repro_rate', 0):.2f}")

            # ログ表示 (最終ステップ)
            if 'logs' in st.session_state.result and st.session_state.result['logs']:
                last_log = st.session_state.result['logs'][-1]
                st.subheader("Last Step Agents (Energy)")
                agent_energies = {a['id']: a['energy'] for a in last_log['agents']}
                st.json({k: v for k, v in sorted(agent_energies.items())[:10]}) 
        
            # 画像表示 (最終3枚、キャッシュで高速化)
            @st.cache_data
            def load_images(run_dir):
                images = list(Path(run_dir).glob('step_*.png'))
                return sorted(images, key=lambda x: int(x.stem.split('_')[1]))[-3:] if images else []
            
            img_dir = Path('outputs/run_00/img')
            if img_dir.exists():
                images = load_images(str(img_dir))
                if images:
                    st.subheader("Recent Visualizations")
                    cols = st.columns(len(images))
                    for i, img in enumerate(images):
                        with cols[i]:
                            st.image(str(img), caption=f"Step {img.stem.split('_')[1]}", use_column_width=True)
                else:
                    st.warning("No images generated. Check mock mode or steps.")
            else:
                st.warning("Run directory not found. Outputs in 'outputs/' folder.")

        elif st.session_state.get('result') is None:
            st.warning("No result available. Run the simulation first!")
        else:
            st.error("Invalid result structure. Check console logs.")
            st.warning("No valid result. Run simulation or check errors above.")
            

    # クリアボタン
    if st.sidebar.button("Clear Results"):
        st.session_state.result = None
        st.rerun()

    
    st.info("Outputs saved to outputs/ folder. For parallel runs, use batch_experiment_parallel().")

    # デバッグ表示（一時的にONにしてテスト、問題解決後削除）
    if st.sidebar.checkbox("Debug: Show Session State Keys"):
        st.write("Session State Keys:", list(st.session_state.keys()) if st.session_state else "Empty")
        if st.session_state.get('result'):
            st.write("Result Keys:", list(st.session_state.result.keys()))


# バッチ実験例（パラメータスキャン + MBTI有無/分布検証 + 並列対応）
async def batch_experiment(num_runs_per_set=3, params_sets=None):
    """NUM_AGENTS変動 + MBTI有無比較（分布チェック）。並列で高速化"""
    if params_sets is None:
        params_sets = [
            {'num_agents': 20, 'seed': 42, 'use_mbti': True},  # 大規模で分布検証
            {'num_agents': 5, 'seed': 42, 'use_mbti': True},
            {'num_agents': 10, 'seed': 42, 'use_mbti': True},
            {'num_agents': 5, 'seed': 42, 'use_mbti': False}  # 比較用
        ]
    
    results = []
    for i, params in enumerate(params_sets):
        for run_id in range(num_runs_per_set):
            result = await main(run_id + i * num_runs_per_set, params)  # run_id調整
            results.append(result)
    
    # 結果集約JSON
    with open('outputs/batch_summary.json', 'w') as f:
        json.dump(results, f, indent=2)
    print("✅ Batch experiment complete (Check MBTI dist in JSON for real pop match).")

if __name__ == "__main__":
    # Streamlit標準起動のため、直接UI関数を呼ぶ（streamlit runで実行される）
    run_streamlit_ui()