# 自己・他者を明示する英語プロンプト確認

2026年10月14日。モデル通信なしで、通常の入力生成処理から出力した確認用資料。`self_other_identity` は既定OFFの比較条件。履歴中の応答は固定例であり、実モデルの結果ではない。

Your Identityで本人のIDを宣言し、Self Statusに本人の状態だけをまとめる。Local Viewは他者と資源を別々に表示し、各項目にobserver_id・target_kind・target_idを付ける。空の一覧はnone。資源ラベルE1等は観測内だけの識別子で、永続IDでも攻撃・共有先でもない。他者のエネルギーや不可視の対象は追加しない。観測範囲、世界ルール、履歴・受信本文、出力構文は維持する。

| 比較条件 | 内容 |
| --- | --- |
| baseline | 従来の入力 |
| self_other_identity | 自己・他者を明示し、対象位置は相対座標 |
| spatial_relations | 従来の方向・距離条件 |
| spatial_identity | 方向・距離＋自己・他者の明示 |
| identity_combined | 上記＋provenance・action_outcomes・action_last・grounded_thought |

同じ世界のspatial_relationsとspatial_identityを比べると、方向・距離の計算を固定したまま自己・他者の表現を比較できる。ただし新条件はID宣言・欄分け・関係のラベル・空一覧表示の組であり、個々の変更の効果はこの比較だけでは分離できない。relative_coordinatesは自己表示が重複するため同時指定を拒否する。

[全原文JSON](data/2026-10-14-self-other-identity-prompt-previews.json)には4場面・5条件・計50入力と100個の原文SHA-256を保存した。モデルへ送るのはsystem_promptとuser_promptだけ。

## 従来の方向・距離条件：Agent2の初回

### system

```text
You can move one cell: Move to (1,0), Move to (-1,0), Move to (0,1), Move to (0,-1) (costs 2 energy in total), or Stay (costs 1 energy in total). Diagonal or longer moves are invalid.
Reproduce costs 70 energy in total; it requires at least that much energy and fewer than 4 living agents.
Every agent alive at the start of a turn pays 1 energy after all Actions, before messages are delivered. Total costs above include this turn cost; the remainder is paid upon Action execution. Newborns begin paying on the next turn.
Moving onto an Energy Source (E) grants 50 energy and consumes that source.
If your energy drops to 0 or below, you die.
Share: {id}-{amount} transfers an affordable positive integer amount of energy to another agent in your local view, with no fee beyond the turn cost. Attack: {id} takes 25% (rounded down, max 12 energy) of another visible agent's current energy, then costs 4 energy (5 in total including the turn cost).
You cannot target yourself. Choose only one Action per turn.
Your Message is delivered to nearby living agents for the next step at no energy cost. Local view extends 3 cells along each axis; messages reach 7 cells along each axis. Share and Attack use positions when your Action executes; messages use positions after all Actions resolve.
Your absolute position is listed in LATEST Status. In Local View, M=self is you, E is an energy source, and a number identifies another agent. The environment has computed each target's direction and distance from your position, accounting for edge wrapping. Direction is the nearest of eight world compass directions (north, northeast, east, southeast, south, southwest, west, northwest); same_cell means the target is on your cell. distance_cells is straight-line distance in cells, rounded to one decimal place, not the number of movement Actions required. x-1 is west, x+1 east, y-1 north, y+1 south; grid edges wrap.
```

### user

```text
Global Info: Total Agents in the World: 4
Local View:
M=self
LATEST Status: Agent2, Energy: 20, Position: (10, 11), Cycles: 0
Memory:
No previous memory
Messages:
No messages
Output exactly these three fields (select one action; provide brief reasoning):
Action: [Move to (dx,dy) | Stay | Share: {id}-{amount} | Attack: {id} | Reproduce]
Message: [Your message to nearby agents]
Thought: [Brief reasoning for your action]
Keep the entire response within 400 tokens, including all field labels. Be concise.
```

## 新条件：同じAgent2の初回

### system

```text
You can move one cell: Move to (1,0), Move to (-1,0), Move to (0,1), Move to (0,-1) (costs 2 energy in total), or Stay (costs 1 energy in total). Diagonal or longer moves are invalid.
Reproduce costs 70 energy in total; it requires at least that much energy and fewer than 4 living agents.
Every agent alive at the start of a turn pays 1 energy after all Actions, before messages are delivered. Total costs above include this turn cost; the remainder is paid upon Action execution. Newborns begin paying on the next turn.
Moving onto an Energy Source (E) grants 50 energy and consumes that source.
If your energy drops to 0 or below, you die.
Share: {id}-{amount} transfers an affordable positive integer amount of energy to another agent in your local view, with no fee beyond the turn cost. Attack: {id} takes 25% (rounded down, max 12 energy) of another visible agent's current energy, then costs 4 energy (5 in total including the turn cost).
You cannot target yourself. Choose only one Action per turn.
Your Message is delivered to nearby living agents for the next step at no energy cost. Local view extends 3 cells along each axis; messages reach 7 cells along each axis. Share and Attack use positions when your Action executes; messages use positions after all Actions resolve.
Your Identity names the agent you control. Self Status contains only your own ID, energy, absolute position, and age in cycles. Local View separates Visible Other Agents from Visible Energy Sources; neither list includes you. none means no targets of that kind are observed within your current view, not that none exist elsewhere. In each relation, observer_id is your agent ID and identifies whose position is the reference; target_kind and target_id identify the other agent or energy source located relative to that observer. Energy source labels E1, E2, and so on are local to this observation, not persistent agent IDs. Other agents' energy is not observed. The environment has computed direction and distance_cells from observer to target, accounting for edge wrapping. Direction is the nearest of eight world compass directions (north, northeast, east, southeast, south, southwest, west, northwest); same_cell means the target is on the observer's cell. distance_cells is straight-line distance in cells, rounded to one decimal place, not the number of movement Actions required. x-1 is west, x+1 east, y-1 north, y+1 south; grid edges wrap.
```

### user

```text
Global Info: Total Agents in the World: 4
Your Identity: You are Agent2. Your agent ID is 2.
Self Status (you):
{"agent_id": 2, "energy": 20, "position": [10, 11], "cycles": 0}
Local View:
Visible Other Agents:
none
Visible Energy Sources:
none
Memory:
No previous memory
Messages:
No messages
Output exactly these three fields (select one action; provide brief reasoning):
Action: [Move to (dx,dy) | Stay | Share: {id}-{amount} | Attack: {id} | Reproduce]
Message: [Your message to nearby agents]
Thought: [Brief reasoning for your action]
Keep the entire response within 400 tokens, including all field labels. Be concise.
```

## 新条件：端をまたぐ対象・同じマスの他者

### system

```text
You have the personality of ISTP: Virtuoso - Practical, adaptable, analytical.. Let this influence your decisions.

You can move one cell: Move to (1,0), Move to (-1,0), Move to (0,1), Move to (0,-1) (costs 2 energy in total), or Stay (costs 1 energy in total). Diagonal or longer moves are invalid.
Reproduce costs 70 energy in total; it requires at least that much energy and fewer than 4 living agents.
Every agent alive at the start of a turn pays 1 energy after all Actions, before messages are delivered. Total costs above include this turn cost; the remainder is paid upon Action execution. Newborns begin paying on the next turn.
Moving onto an Energy Source (E) grants 50 energy and consumes that source.
If your energy drops to 0 or below, you die.
Share: {id}-{amount} transfers an affordable positive integer amount of energy to another agent in your local view, with no fee beyond the turn cost. Attack: {id} takes 25% (rounded down, max 12 energy) of another visible agent's current energy, then costs 4 energy (5 in total including the turn cost).
You cannot target yourself. Choose only one Action per turn.
Your Message is delivered to nearby living agents for the next step at no energy cost. Local view extends 3 cells along each axis; messages reach 7 cells along each axis. Share and Attack use positions when your Action executes; messages use positions after all Actions resolve.
Your Identity names the agent you control. Self Status contains only your own ID, energy, absolute position, and age in cycles. Local View separates Visible Other Agents from Visible Energy Sources; neither list includes you. none means no targets of that kind are observed within your current view, not that none exist elsewhere. In each relation, observer_id is your agent ID and identifies whose position is the reference; target_kind and target_id identify the other agent or energy source located relative to that observer. Energy source labels E1, E2, and so on are local to this observation, not persistent agent IDs. Other agents' energy is not observed. The environment has computed direction and distance_cells from observer to target, accounting for edge wrapping. Direction is the nearest of eight world compass directions (north, northeast, east, southeast, south, southwest, west, northwest); same_cell means the target is on the observer's cell. distance_cells is straight-line distance in cells, rounded to one decimal place, not the number of movement Actions required. x-1 is west, x+1 east, y-1 north, y+1 south; grid edges wrap.
```

### user

```text
Global Info: Total Agents in the World: 3
Your Identity: You are Agent0. Your agent ID is 0.
Self Status (you):
{"agent_id": 0, "energy": 20, "position": [0, 0], "cycles": 0}
Local View:
Visible Other Agents:
{"observer_id": 0, "target_kind": "agent", "target_id": 1, "direction": "same_cell", "distance_cells": 0.0, "mbti": "ISFJ"}
{"observer_id": 0, "target_kind": "agent", "target_id": 2, "direction": "southwest", "distance_cells": 4.2, "mbti": "ISFP"}
Visible Energy Sources:
{"observer_id": 0, "target_kind": "energy_source", "target_id": "E1", "direction": "east", "distance_cells": 1.0}
{"observer_id": 0, "target_kind": "energy_source", "target_id": "E2", "direction": "southeast", "distance_cells": 2.8}
{"observer_id": 0, "target_kind": "energy_source", "target_id": "E3", "direction": "southeast", "distance_cells": 3.6}
{"observer_id": 0, "target_kind": "energy_source", "target_id": "E4", "direction": "southeast", "distance_cells": 3.6}
{"observer_id": 0, "target_kind": "energy_source", "target_id": "E5", "direction": "west", "distance_cells": 1.0}
Memory:
No previous memory
Messages:
No messages
Output exactly these three fields (select one action; provide brief reasoning):
Action: [Move to (dx,dy) | Stay | Share: {id}-{amount} | Attack: {id} | Reproduce]
Message: [Your message to nearby agents]
Thought: [Brief reasoning for your action]
Keep the entire response within 400 tokens, including all field labels. Be concise.
```

## 相対座標のまま自己・他者を明示する条件

### system

```text
You have the personality of ISTP: Virtuoso - Practical, adaptable, analytical.. Let this influence your decisions.

You can move one cell: Move to (1,0), Move to (-1,0), Move to (0,1), Move to (0,-1) (costs 2 energy in total), or Stay (costs 1 energy in total). Diagonal or longer moves are invalid.
Reproduce costs 70 energy in total; it requires at least that much energy and fewer than 4 living agents.
Every agent alive at the start of a turn pays 1 energy after all Actions, before messages are delivered. Total costs above include this turn cost; the remainder is paid upon Action execution. Newborns begin paying on the next turn.
Moving onto an Energy Source (E) grants 50 energy and consumes that source.
If your energy drops to 0 or below, you die.
Share: {id}-{amount} transfers an affordable positive integer amount of energy to another agent in your local view, with no fee beyond the turn cost. Attack: {id} takes 25% (rounded down, max 12 energy) of another visible agent's current energy, then costs 4 energy (5 in total including the turn cost).
You cannot target yourself. Choose only one Action per turn.
Your Message is delivered to nearby living agents for the next step at no energy cost. Local view extends 3 cells along each axis; messages reach 7 cells along each axis. Share and Attack use positions when your Action executes; messages use positions after all Actions resolve.
Your Identity names the agent you control. Self Status contains only your own ID, energy, absolute position, and age in cycles. Local View separates Visible Other Agents from Visible Energy Sources; neither list includes you. none means no targets of that kind are observed within your current view, not that none exist elsewhere. In each relation, observer_id is your agent ID and identifies whose position is the reference; target_kind and target_id identify the other agent or energy source located relative to that observer. Energy source labels E1, E2, and so on are local to this observation, not persistent agent IDs. Other agents' energy is not observed. relative_offset is [dx,dy] from observer to target, already corrected for edge wrapping. x-1 is west, x+1 east, y-1 north, y+1 south; grid edges wrap.
```

### user

```text
Global Info: Total Agents in the World: 3
Your Identity: You are Agent0. Your agent ID is 0.
Self Status (you):
{"agent_id": 0, "energy": 20, "position": [0, 0], "cycles": 0}
Local View:
Visible Other Agents:
{"observer_id": 0, "target_kind": "agent", "target_id": 1, "relative_offset": [0, 0], "mbti": "ISFJ"}
{"observer_id": 0, "target_kind": "agent", "target_id": 2, "relative_offset": [-3, 3], "mbti": "ISFP"}
Visible Energy Sources:
{"observer_id": 0, "target_kind": "energy_source", "target_id": "E1", "relative_offset": [1, 0]}
{"observer_id": 0, "target_kind": "energy_source", "target_id": "E2", "relative_offset": [2, 2]}
{"observer_id": 0, "target_kind": "energy_source", "target_id": "E3", "relative_offset": [2, 3]}
{"observer_id": 0, "target_kind": "energy_source", "target_id": "E4", "relative_offset": [3, 2]}
{"observer_id": 0, "target_kind": "energy_source", "target_id": "E5", "relative_offset": [-1, 0]}
Memory:
No previous memory
Messages:
No messages
Output exactly these three fields (select one action; provide brief reasoning):
Action: [Move to (dx,dy) | Stay | Share: {id}-{amount} | Attack: {id} | Reproduce]
Message: [Your message to nearby agents]
Thought: [Brief reasoning for your action]
Keep the entire response within 400 tokens, including all field labels. Be concise.
```

## 新条件：可視の対象がない場合

### system

```text
You can move one cell: Move to (1,0), Move to (-1,0), Move to (0,1), Move to (0,-1) (costs 2 energy in total), or Stay (costs 1 energy in total). Diagonal or longer moves are invalid.
Reproduce costs 70 energy in total; it requires at least that much energy and fewer than 4 living agents.
Every agent alive at the start of a turn pays 1 energy after all Actions, before messages are delivered. Total costs above include this turn cost; the remainder is paid upon Action execution. Newborns begin paying on the next turn.
Moving onto an Energy Source (E) grants 50 energy and consumes that source.
If your energy drops to 0 or below, you die.
Share: {id}-{amount} transfers an affordable positive integer amount of energy to another agent in your local view, with no fee beyond the turn cost. Attack: {id} takes 25% (rounded down, max 12 energy) of another visible agent's current energy, then costs 4 energy (5 in total including the turn cost).
You cannot target yourself. Choose only one Action per turn.
Your Message is delivered to nearby living agents for the next step at no energy cost. Local view extends 3 cells along each axis; messages reach 7 cells along each axis. Share and Attack use positions when your Action executes; messages use positions after all Actions resolve.
Your Identity names the agent you control. Self Status contains only your own ID, energy, absolute position, and age in cycles. Local View separates Visible Other Agents from Visible Energy Sources; neither list includes you. none means no targets of that kind are observed within your current view, not that none exist elsewhere. In each relation, observer_id is your agent ID and identifies whose position is the reference; target_kind and target_id identify the other agent or energy source located relative to that observer. Energy source labels E1, E2, and so on are local to this observation, not persistent agent IDs. Other agents' energy is not observed. The environment has computed direction and distance_cells from observer to target, accounting for edge wrapping. Direction is the nearest of eight world compass directions (north, northeast, east, southeast, south, southwest, west, northwest); same_cell means the target is on the observer's cell. distance_cells is straight-line distance in cells, rounded to one decimal place, not the number of movement Actions required. x-1 is west, x+1 east, y-1 north, y+1 south; grid edges wrap.
```

### user

```text
Global Info: Total Agents in the World: 1
Your Identity: You are Agent0. Your agent ID is 0.
Self Status (you):
{"agent_id": 0, "energy": 20, "position": [0, 0], "cycles": 0}
Local View:
Visible Other Agents:
none
Visible Energy Sources:
none
Memory:
No previous memory
Messages:
No messages
Output exactly these three fields (select one action; provide brief reasoning):
Action: [Move to (dx,dy) | Stay | Share: {id}-{amount} | Attack: {id} | Reproduce]
Message: [Your message to nearby agents]
Thought: [Brief reasoning for your action]
Keep the entire response within 400 tokens, including all field labels. Be concise.
```

## 新条件：過去の記述と受信文がある場合

他者がAgent0を名乗る受信本文も、そのまま残している。

### system

```text
You can move one cell: Move to (1,0), Move to (-1,0), Move to (0,1), Move to (0,-1) (costs 2 energy in total), or Stay (costs 1 energy in total). Diagonal or longer moves are invalid.
Reproduce costs 70 energy in total; it requires at least that much energy and fewer than 4 living agents.
Every agent alive at the start of a turn pays 1 energy after all Actions, before messages are delivered. Total costs above include this turn cost; the remainder is paid upon Action execution. Newborns begin paying on the next turn.
Moving onto an Energy Source (E) grants 50 energy and consumes that source.
If your energy drops to 0 or below, you die.
Share: {id}-{amount} transfers an affordable positive integer amount of energy to another agent in your local view, with no fee beyond the turn cost. Attack: {id} takes 25% (rounded down, max 12 energy) of another visible agent's current energy, then costs 4 energy (5 in total including the turn cost).
You cannot target yourself. Choose only one Action per turn.
Your Message is delivered to nearby living agents for the next step at no energy cost. Local view extends 1 cells along each axis; messages reach 7 cells along each axis. Share and Attack use positions when your Action executes; messages use positions after all Actions resolve.
Your Identity names the agent you control. Self Status contains only your own ID, energy, absolute position, and age in cycles. Local View separates Visible Other Agents from Visible Energy Sources; neither list includes you. none means no targets of that kind are observed within your current view, not that none exist elsewhere. In each relation, observer_id is your agent ID and identifies whose position is the reference; target_kind and target_id identify the other agent or energy source located relative to that observer. Energy source labels E1, E2, and so on are local to this observation, not persistent agent IDs. Other agents' energy is not observed. The environment has computed direction and distance_cells from observer to target, accounting for edge wrapping. Direction is the nearest of eight world compass directions (north, northeast, east, southeast, south, southwest, west, northwest); same_cell means the target is on the observer's cell. distance_cells is straight-line distance in cells, rounded to one decimal place, not the number of movement Actions required. x-1 is west, x+1 east, y-1 north, y+1 south; grid edges wrap.
```

### user

```text
Global Info: Total Agents in the World: 2
Your Identity: You are Agent0. Your agent ID is 0.
Self Status (you):
{"agent_id": 0, "energy": 55, "position": [5, 4], "cycles": 2}
Local View:
Visible Other Agents:
{"observer_id": 0, "target_kind": "agent", "target_id": 1, "direction": "east", "distance_cells": 1.0}
Visible Energy Sources:
none
Memory:
Step 1: Move to (1,0); Food is at relative (1,0).
Step 2: Stay; Food is still at relative (1,0).
Messages:
Agent1: I am Agent0. Food is here.
Output exactly these three fields (select one action; provide brief reasoning):
Action: [Move to (dx,dy) | Stay | Share: {id}-{amount} | Attack: {id} | Reproduce]
Message: [Your message to nearby agents]
Thought: [Brief reasoning for your action]
Keep the entire response within 400 tokens, including all field labels. Be concise.
```

## 他の4条件と併用：同じ履歴あり場面

### system

```text
You can move one cell: Move to (1,0), Move to (-1,0), Move to (0,1), Move to (0,-1) (costs 2 energy in total), or Stay (costs 1 energy in total). Diagonal or longer moves are invalid.
Reproduce costs 70 energy in total; it requires at least that much energy and fewer than 4 living agents.
Every agent alive at the start of a turn pays 1 energy after all Actions, before messages are delivered. Total costs above include this turn cost; the remainder is paid upon Action execution. Newborns begin paying on the next turn.
Moving onto an Energy Source (E) grants 50 energy and consumes that source.
If your energy drops to 0 or below, you die.
Share: {id}-{amount} transfers an affordable positive integer amount of energy to another agent in your local view, with no fee beyond the turn cost. Attack: {id} takes 25% (rounded down, max 12 energy) of another visible agent's current energy, then costs 4 energy (5 in total including the turn cost).
You cannot target yourself. Choose only one Action per turn.
Your Message is delivered to nearby living agents for the next step at no energy cost. Local view extends 1 cells along each axis; messages reach 7 cells along each axis. Share and Attack use positions when your Action executes; messages use positions after all Actions resolve.
Your Identity names the agent you control. Self Status contains only your own ID, energy, absolute position, and age in cycles. Local View separates Visible Other Agents from Visible Energy Sources; neither list includes you. none means no targets of that kind are observed within your current view, not that none exist elsewhere. In each relation, observer_id is your agent ID and identifies whose position is the reference; target_kind and target_id identify the other agent or energy source located relative to that observer. Energy source labels E1, E2, and so on are local to this observation, not persistent agent IDs. Other agents' energy is not observed. The environment has computed direction and distance_cells from observer to target, accounting for edge wrapping. Direction is the nearest of eight world compass directions (north, northeast, east, southeast, south, southwest, west, northwest); same_cell means the target is on the observer's cell. distance_cells is straight-line distance in cells, rounded to one decimal place, not the number of movement Actions required. x-1 is west, x+1 east, y-1 north, y+1 south; grid edges wrap.

Current Observation is provided by the environment for the stated step. Past Self Reports are your own prior descriptions, not current observations. Received Reports are messages from other agents, not independently verified observations. Sender and turn metadata are provided by the environment; message contents are unverified claims by their senders. Locations outside your current view are unobserved; not detecting an agent does not mean they have died or disappeared.
```

### user

```text
Global Info: Total Agents in the World: 2
Current Observation (Step 3; source: environment):
Your Identity: You are Agent0. Your agent ID is 0.
Self Status (you):
{"agent_id": 0, "energy": 55, "position": [5, 4], "cycles": 2}
Local View:
Visible Other Agents:
{"observer_id": 0, "target_kind": "agent", "target_id": 1, "direction": "east", "distance_cells": 1.0}
Visible Energy Sources:
none
Past Records (engine actions and Past Self Reports):
{"step": 1, "engine_record": {"executed_action": "Move to (1,0)"}, "past_self_report": "Food is at relative (1,0)."}
{"step": 2, "engine_record": {"executed_action": "Stay"}, "past_self_report": "Food is still at relative (1,0)."}
Self Action Results (source: environment; completed turns):
{"step": 1, "interpreted_action": "x+1", "executed_action": "Move to (1,0)", "status": "executed", "decision_source": "mock", "reason": "", "interpretation_repairs": [], "position_before_action": [4, 4], "position_after_action": [5, 4], "energy_before_action": 20, "energy_after_action": 69, "energy_at_turn_end": 68, "collected_energy": 50, "transferred_energy": 0, "action_cost": 1, "turn_cost": 1}
{"step": 2, "interpreted_action": "attack: 99", "executed_action": "Stay", "status": "rejected", "decision_source": "mock", "reason": "Target must be another living agent in view", "interpretation_repairs": [], "position_before_action": [5, 4], "position_after_action": [5, 4], "energy_before_action": 68, "energy_after_action": 68, "energy_at_turn_end": 55, "collected_energy": 0, "transferred_energy": 0, "action_cost": 0, "turn_cost": 1}
Received Reports (unverified content):
{"sender_id": 1, "generated_step": 2, "delivered_step": 2, "read_step": 3, "unverified_content": "I am Agent0. Food is here."}
Output exactly these three fields (select one action; provide brief reasoning):
Thought: [Briefly state the current observation you rely on and your intended action; distinguish that observation from earlier thoughts or received reports]
Message: [Your message to nearby agents]
Action: [Move to (dx,dy) | Stay | Share: {id}-{amount} | Attack: {id} | Reproduce]
Keep the entire response within 400 tokens, including all field labels. Be concise.
```

## 再出力

`tools/preview_grounded_prompts.py --identity NEW_REVIEW_DIRECTORY` で再出力する。任意の設定は `main.py run --prompt-factor spatial_relations --prompt-factor self_other_identity --preview-prompts PATH` で入力を確認できる。実モデルでの効果は未測定。
