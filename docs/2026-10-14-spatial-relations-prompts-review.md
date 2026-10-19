# 方向・距離条件の英語プロンプト確認

2026年10月14日。実験と同じ生成処理から**モデル接続なし**で出力した。UIと世界ルールは維持し、`spatial_relations` は既定OFF。履歴・発言は固定例であり、実モデルの結果ではない。

新条件では現在のLocal Viewの対象座標を、コードで算出した8方位と小数1桁の直線距離へ置換する。端をまたぐ補正には既存の相対座標を使う。移動回数、行動の推奨、不可視の対象は加えない。Statusの自己絶対位置、過去のThought、受信本文などは各既存条件のまま残る。

| 確認条件 | 有効にする条件 |
| --- | --- |
| baseline | なし |
| relative_coordinates | 相対座標のみ |
| spatial_relations | 方向・距離のみ |
| combined | 従来5条件の併用 |
| spatial_combined | 従来の相対座標条件を方向・距離条件へ置換し、他4条件は維持 |

`relative_coordinates` と `spatial_relations` の同時指定は拒否する。残り4条件との任意の組合せは可能。基準→新単独、相対座標のみ→新単独、旧併用→新併用をそれぞれ比較できる。8方位と丸めた距離は元の座標より粗いため、結果を計算負担の違いだけに帰属しない。

[全原文JSON](data/2026-10-14-spatial-relations-prompt-previews.json)に4場面・5比較条件・計50入力と100個の原文SHA-256を保存した。モデルに送るのは `system_prompt` と `user_prompt` だけ。監査用の観測・世界IDなどは入力に加えない。

## 基準条件の全文：端をまたぐ対象・同じマスの個体

Agent0、Step 1。視界は各軸3セル。距離4.2セルの対象も正しく可視になる。不可視の資源(5,5)はLocal Viewに入らない。

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
M=(x,y) is your absolute position; E=(dx,dy) and agent IDs use relative offsets. x-1 is west, x+1 east, y-1 north, y+1 south; grid edges wrap.
```

### user

```text
Global Info: Total Agents in the World: 3
Local View:
M=(0,0)
E=(1,0)
E=(2,2)
E=(2,3)
E=(3,2)
E=(-1,0)
1=(0,0) (MBTI: ISFJ)
2=(-3,3) (MBTI: ISFP)
LATEST Status: Agent0, Energy: 20, Position: (0, 0), Cycles: 0
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

## 新単独条件の全文：上と同じ場面

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
Your absolute position is listed in LATEST Status. In Local View, M=self is you, E is an energy source, and a number identifies another agent. The environment has computed each target's direction and distance from your position, accounting for edge wrapping. Direction is the nearest of eight world compass directions (north, northeast, east, southeast, south, southwest, west, northwest); same_cell means the target is on your cell. distance_cells is straight-line distance in cells, rounded to one decimal place, not the number of movement Actions required. x-1 is west, x+1 east, y-1 north, y+1 south; grid edges wrap.
```

### user

```text
Global Info: Total Agents in the World: 3
Local View:
M=self
E: direction=east; distance_cells=1.0
E: direction=southeast; distance_cells=2.8
E: direction=southeast; distance_cells=3.6
E: direction=southeast; distance_cells=3.6
E: direction=west; distance_cells=1.0
1: direction=same_cell; distance_cells=0.0 (MBTI: ISFJ)
2: direction=southwest; distance_cells=4.2 (MBTI: ISFP)
LATEST Status: Agent0, Energy: 20, Position: (0, 0), Cycles: 0
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

## 新単独条件の全文：既存プリセットの初回

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
LATEST Status: Agent0, Energy: 20, Position: (3, 2), Cycles: 0
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

## 新単独条件の全文：可視の対象がない場合

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
Global Info: Total Agents in the World: 1
Local View:
M=self
LATEST Status: Agent0, Energy: 20, Position: (0, 0), Cycles: 0
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

## 新単独条件の全文：履歴と受信文がある場合

固定応答で2ターンを進めたAgent0のStep 3。砂糖についての古いThoughtと他者の発言は変更しない。

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
Your absolute position is listed in LATEST Status. In Local View, M=self is you, E is an energy source, and a number identifies another agent. The environment has computed each target's direction and distance from your position, accounting for edge wrapping. Direction is the nearest of eight world compass directions (north, northeast, east, southeast, south, southwest, west, northwest); same_cell means the target is on your cell. distance_cells is straight-line distance in cells, rounded to one decimal place, not the number of movement Actions required. x-1 is west, x+1 east, y-1 north, y+1 south; grid edges wrap.
```

### user

```text
Global Info: Total Agents in the World: 2
Local View:
M=self
1: direction=east; distance_cells=1.0
LATEST Status: Agent0, Energy: 55, Position: (5, 4), Cycles: 2
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

## 他4条件と併用した全文：同じ履歴あり場面

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
Your absolute position is listed in LATEST Status. In Local View, M=self is you, E is an energy source, and a number identifies another agent. The environment has computed each target's direction and distance from your position, accounting for edge wrapping. Direction is the nearest of eight world compass directions (north, northeast, east, southeast, south, southwest, west, northwest); same_cell means the target is on your cell. distance_cells is straight-line distance in cells, rounded to one decimal place, not the number of movement Actions required. x-1 is west, x+1 east, y-1 north, y+1 south; grid edges wrap.

Current Observation is provided by the environment for the stated step. Past Self Reports are your own prior descriptions, not current observations. Received Reports are messages from other agents, not independently verified observations. Sender and turn metadata are provided by the environment; message contents are unverified claims by their senders. Locations outside your current view are unobserved; not detecting an agent does not mean they have died or disappeared.
```

### user

```text
Global Info: Total Agents in the World: 2
Current Observation (Step 3; source: environment):
Local View:
M=self
1: direction=east; distance_cells=1.0
LATEST Status: Agent0, Energy: 55, Position: (5, 4), Cycles: 2
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

`tools/preview_grounded_prompts.py --spatial NEW_REVIEW_DIRECTORY` で再出力できる。既存の第2版資料は上書きしない。任意の開始条件は `main.py run --prompt-factor spatial_relations --preview-prompts PATH` で確認できる。実験は本文の確認後に別途実行する。
