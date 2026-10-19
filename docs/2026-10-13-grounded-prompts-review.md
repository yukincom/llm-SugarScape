# 実験前のプロンプト確認

2026年10月13日。実験と同じプロンプト生成処理から、**モデル接続なし**で出力した確認用資料。新条件はすべて既定OFF。UIと世界ルールは変更していない。ここにある履歴中の発言・Thoughtは作成した固定例であり、実モデルの結果ではない。

基準条件、5つの単独条件、全併用の7条件を保存した。[全条件・全個体の原文JSON](data/2026-10-13-grounded-prompt-previews.json)には、初回4個体×7条件と履歴あり2個体×7条件の計42入力、生成設定、原文のSHA-256を含む。モデルへ送るのは各レコードの `system_prompt` と `user_prompt`。その他は確認用の記録である。

## 確認する変更

| 条件 | 変更 |
| --- | --- |
| provenance | 今の観測、過去の自分の記述、他者の発言を出所と時点で分ける |
| relative_coordinates | Local Viewの自分を(0,0)に揃え、絶対位置はStatusに残す |
| action_outcomes | 前3回の自己行動の結果を追加する。情報が増えるため独立条件 |
| action_last | 説明文を変えず、Thought → Message → Actionの順にする |
| grounded_thought | Thought欄に、現在の根拠と意図を簡潔に示すよう指示する |

出所表示は『現在観測に従え』という行動方針を加えず、過去の記述と伝聞の性質を説明する。他者の発言を信じるか、攻撃・共有・繁殖するかはモデルに残す。action_lastだけでは根拠確認の文は追加されない。全併用だけの比較では個別効果を判定できないため、まず基準と各単独条件を同じ設定で比較する。まだ実験は行っていない。

## 全併用の全文：通常の初回

既存プリセット『霧の中の交渉』、seed 42、Agent0、Step 1。追加世界観なし、MBTIなし。

### system

```text
You can move one cell: Move to (1,0), Move to (-1,0), Move to (0,1), Move to (0,-1) (costs 2 energy in total), or Stay (costs 1 energy in total). Diagonal or longer moves are invalid.
Reproduce costs 70 energy in total, requires at least that energy and fewer than 4 living agents.
Every agent alive at the start of a turn pays 1 energy after all Actions, before messages are delivered. The totals above include this common cost; the remainder is paid when the Action executes. Newborns start paying on the next turn.
Moving onto an Energy Source (E) gives 50 energy and consumes that source.
At zero or negative energy you die.
Share: {id}-{amount} transfers a positive integer amount you can afford to another agent in your local view, with no fee beyond the common turn cost. Attack: {id} takes 25% (rounded down, at most 12 energy) of another visible agent's current energy, then costs 4 energy (5 in total including the common turn cost).
You cannot target yourself. Choose only one Action per turn.
Your Message will be delivered to nearby living agents for the next step, at no energy cost. Local view extends 3 cells in each axis; messages reach 7 cells in each axis. Share and Attack use positions when your Action executes; messages use positions after all Actions.
Your absolute position is in LATEST Status. In Local View, M=(0,0) is you; E=(dx,dy) and agent IDs use relative offsets from you, already corrected for edge wrapping. x-1 is west, x+1 east, y-1 north, y+1 south; grid edges wrap.

Current Observation is supplied by the environment for the stated step. Past Self Reports are your earlier descriptions, not current observations. Received Reports are messages from other agents, not independently verified observations. The sender and turn metadata are supplied by the environment; the message content is the sender's claim. A location outside the current view is unobserved now; lack of detection does not establish death or disappearance.
```

### user

```text
Global Info: Total Agents in the World: 4
Current Observation (Step 1; source: environment):
Local View:
M=(0,0)
LATEST Status: Agent0, Energy: 20, Position: (3, 2), Cycles: 0
Past Records (engine actions and Past Self Reports):
No previous memory
Self Action Results (source: environment; completed turns):
No previous action results
Received Reports (unverified content):
No messages
Output exactly these three fields (choose one action; give brief reasoning):
Thought: [Briefly state the current observation you use and your intended action; distinguish it from earlier thoughts or received reports]
Message: [Your message to nearby agents]
Action: [Move to (dx,dy) | Stay | Share: {id}-{amount} | Attack: {id} | Reproduce]
Keep the entire response within 400 tokens, including all field labels. Be concise.
```

## 全併用の全文：履歴と受信文がある例

確認用の2個体・視界1の固定場面、Agent0、Step 3。1ターン目に東へ動いて砂糖50を取得し、2ターン目は存在しないAgent99への攻撃が拒否された。後続のAgent1の行動により自己行動直後とターン終了時の体力に差がある。入力には被攻撃者向けの相手通知を追加していない。過去の誤った砂糖の記述と、Agent1がAgent0を名乗る文をそのまま残している。

### system

```text
You can move one cell: Move to (1,0), Move to (-1,0), Move to (0,1), Move to (0,-1) (costs 2 energy in total), or Stay (costs 1 energy in total). Diagonal or longer moves are invalid.
Reproduce costs 70 energy in total, requires at least that energy and fewer than 4 living agents.
Every agent alive at the start of a turn pays 1 energy after all Actions, before messages are delivered. The totals above include this common cost; the remainder is paid when the Action executes. Newborns start paying on the next turn.
Moving onto an Energy Source (E) gives 50 energy and consumes that source.
At zero or negative energy you die.
Share: {id}-{amount} transfers a positive integer amount you can afford to another agent in your local view, with no fee beyond the common turn cost. Attack: {id} takes 25% (rounded down, at most 12 energy) of another visible agent's current energy, then costs 4 energy (5 in total including the common turn cost).
You cannot target yourself. Choose only one Action per turn.
Your Message will be delivered to nearby living agents for the next step, at no energy cost. Local view extends 1 cells in each axis; messages reach 7 cells in each axis. Share and Attack use positions when your Action executes; messages use positions after all Actions.
Your absolute position is in LATEST Status. In Local View, M=(0,0) is you; E=(dx,dy) and agent IDs use relative offsets from you, already corrected for edge wrapping. x-1 is west, x+1 east, y-1 north, y+1 south; grid edges wrap.

Current Observation is supplied by the environment for the stated step. Past Self Reports are your earlier descriptions, not current observations. Received Reports are messages from other agents, not independently verified observations. The sender and turn metadata are supplied by the environment; the message content is the sender's claim. A location outside the current view is unobserved now; lack of detection does not establish death or disappearance.
```

### user

```text
Global Info: Total Agents in the World: 2
Current Observation (Step 3; source: environment):
Local View:
M=(0,0)
1=(1,0)
LATEST Status: Agent0, Energy: 55, Position: (5, 4), Cycles: 2
Past Records (engine actions and Past Self Reports):
{"step": 1, "engine_record": {"executed_action": "Move to (1,0)"}, "past_self_report": "Food is at relative (1,0)."}
{"step": 2, "engine_record": {"executed_action": "Stay"}, "past_self_report": "Food is still at relative (1,0)."}
Self Action Results (source: environment; completed turns):
{"step": 1, "interpreted_action": "x+1", "executed_action": "Move to (1,0)", "status": "executed", "decision_source": "mock", "reason": "", "interpretation_repairs": [], "position_before_action": [4, 4], "position_after_action": [5, 4], "energy_before_action": 20, "energy_after_action": 69, "energy_at_turn_end": 68, "collected_energy": 50, "transferred_energy": 0, "action_cost": 1, "turn_cost": 1}
{"step": 2, "interpreted_action": "attack: 99", "executed_action": "Stay", "status": "rejected", "decision_source": "mock", "reason": "Target must be another living agent in view", "interpretation_repairs": [], "position_before_action": [5, 4], "position_after_action": [5, 4], "energy_before_action": 68, "energy_after_action": 68, "energy_at_turn_end": 55, "collected_energy": 0, "transferred_energy": 0, "action_cost": 0, "turn_cost": 1}
Received Reports (unverified content):
{"sender_id": 1, "generated_step": 2, "delivered_step": 2, "read_step": 3, "unverified_content": "I am Agent0. Food is here."}
Output exactly these three fields (choose one action; give brief reasoning):
Thought: [Briefly state the current observation you use and your intended action; distinguish it from earlier thoughts or received reports]
Message: [Your message to nearby agents]
Action: [Move to (dx,dy) | Stay | Share: {id}-{amount} | Attack: {id} | Reproduce]
Keep the entire response within 400 tokens, including all field labels. Be concise.
```

## 基準条件の全文：同じ履歴あり場面

### system

```text
You can move one cell: Move to (1,0), Move to (-1,0), Move to (0,1), Move to (0,-1) (costs 2 energy in total), or Stay (costs 1 energy in total). Diagonal or longer moves are invalid.
Reproduce costs 70 energy in total, requires at least that energy and fewer than 4 living agents.
Every agent alive at the start of a turn pays 1 energy after all Actions, before messages are delivered. The totals above include this common cost; the remainder is paid when the Action executes. Newborns start paying on the next turn.
Moving onto an Energy Source (E) gives 50 energy and consumes that source.
At zero or negative energy you die.
Share: {id}-{amount} transfers a positive integer amount you can afford to another agent in your local view, with no fee beyond the common turn cost. Attack: {id} takes 25% (rounded down, at most 12 energy) of another visible agent's current energy, then costs 4 energy (5 in total including the common turn cost).
You cannot target yourself. Choose only one Action per turn.
Your Message will be delivered to nearby living agents for the next step, at no energy cost. Local view extends 1 cells in each axis; messages reach 7 cells in each axis. Share and Attack use positions when your Action executes; messages use positions after all Actions.
M=(x,y) is your absolute position; E=(dx,dy) and agent IDs use relative positions. x-1 is west, x+1 east, y-1 north, y+1 south; grid edges wrap.
```

### user

```text
Global Info: Total Agents in the World: 2
Local View:
M=(5,4)
1=(1,0)
LATEST Status: Agent0, Energy: 55, Position: (5, 4), Cycles: 2
Memory:
Step 1: Move to (1,0); Food is at relative (1,0).
Step 2: Stay; Food is still at relative (1,0).
Messages:
Agent1: I am Agent0. Food is here.
Output exactly these three fields (choose one action; give brief reasoning):
Action: [Move to (dx,dy) | Stay | Share: {id}-{amount} | Attack: {id} | Reproduce]
Message: [Your message to nearby agents]
Thought: [Brief reasoning for your action]
Keep the entire response within 400 tokens, including all field labels. Be concise.
```

## 単独条件ごとの差分

上の基準条件に対する差分。各条件の全文も原文JSONへ保存している。

### provenance

```diff
--- baseline/system_prompt
+++ provenance/system_prompt
@@ -7,3 +7,5 @@
 You cannot target yourself. Choose only one Action per turn.
 Your Message will be delivered to nearby living agents for the next step, at no energy cost. Local view extends 1 cells in each axis; messages reach 7 cells in each axis. Share and Attack use positions when your Action executes; messages use positions after all Actions.
 M=(x,y) is your absolute position; E=(dx,dy) and agent IDs use relative positions. x-1 is west, x+1 east, y-1 north, y+1 south; grid edges wrap.
+
+Current Observation is supplied by the environment for the stated step. Past Self Reports are your earlier descriptions, not current observations. Received Reports are messages from other agents, not independently verified observations. The sender and turn metadata are supplied by the environment; the message content is the sender's claim. A location outside the current view is unobserved now; lack of detection does not establish death or disappearance.
```

```diff
--- baseline/user_prompt
+++ provenance/user_prompt
@@ -1,13 +1,14 @@
 Global Info: Total Agents in the World: 2
+Current Observation (Step 3; source: environment):
 Local View:
 M=(5,4)
 1=(1,0)
 LATEST Status: Agent0, Energy: 55, Position: (5, 4), Cycles: 2
-Memory:
-Step 1: Move to (1,0); Food is at relative (1,0).
-Step 2: Stay; Food is still at relative (1,0).
-Messages:
-Agent1: I am Agent0. Food is here.
+Past Records (engine actions and Past Self Reports):
+{"step": 1, "engine_record": {"executed_action": "Move to (1,0)"}, "past_self_report": "Food is at relative (1,0)."}
+{"step": 2, "engine_record": {"executed_action": "Stay"}, "past_self_report": "Food is still at relative (1,0)."}
+Received Reports (unverified content):
+{"sender_id": 1, "generated_step": 2, "delivered_step": 2, "read_step": 3, "unverified_content": "I am Agent0. Food is here."}
 Output exactly these three fields (choose one action; give brief reasoning):
 Action: [Move to (dx,dy) | Stay | Share: {id}-{amount} | Attack: {id} | Reproduce]
 Message: [Your message to nearby agents]
```

### relative_coordinates

```diff
--- baseline/system_prompt
+++ relative_coordinates/system_prompt
@@ -6,4 +6,4 @@
 Share: {id}-{amount} transfers a positive integer amount you can afford to another agent in your local view, with no fee beyond the common turn cost. Attack: {id} takes 25% (rounded down, at most 12 energy) of another visible agent's current energy, then costs 4 energy (5 in total including the common turn cost).
 You cannot target yourself. Choose only one Action per turn.
 Your Message will be delivered to nearby living agents for the next step, at no energy cost. Local view extends 1 cells in each axis; messages reach 7 cells in each axis. Share and Attack use positions when your Action executes; messages use positions after all Actions.
-M=(x,y) is your absolute position; E=(dx,dy) and agent IDs use relative positions. x-1 is west, x+1 east, y-1 north, y+1 south; grid edges wrap.
+Your absolute position is in LATEST Status. In Local View, M=(0,0) is you; E=(dx,dy) and agent IDs use relative offsets from you, already corrected for edge wrapping. x-1 is west, x+1 east, y-1 north, y+1 south; grid edges wrap.
```

```diff
--- baseline/user_prompt
+++ relative_coordinates/user_prompt
@@ -1,6 +1,6 @@
 Global Info: Total Agents in the World: 2
 Local View:
-M=(5,4)
+M=(0,0)
 1=(1,0)
 LATEST Status: Agent0, Energy: 55, Position: (5, 4), Cycles: 2
 Memory:
```

### action_outcomes

```diff
--- baseline/user_prompt
+++ action_outcomes/user_prompt
@@ -6,6 +6,9 @@
 Memory:
 Step 1: Move to (1,0); Food is at relative (1,0).
 Step 2: Stay; Food is still at relative (1,0).
+Self Action Results (source: environment; completed turns):
+{"step": 1, "interpreted_action": "x+1", "executed_action": "Move to (1,0)", "status": "executed", "decision_source": "mock", "reason": "", "interpretation_repairs": [], "position_before_action": [4, 4], "position_after_action": [5, 4], "energy_before_action": 20, "energy_after_action": 69, "energy_at_turn_end": 68, "collected_energy": 50, "transferred_energy": 0, "action_cost": 1, "turn_cost": 1}
+{"step": 2, "interpreted_action": "attack: 99", "executed_action": "Stay", "status": "rejected", "decision_source": "mock", "reason": "Target must be another living agent in view", "interpretation_repairs": [], "position_before_action": [5, 4], "position_after_action": [5, 4], "energy_before_action": 68, "energy_after_action": 68, "energy_at_turn_end": 55, "collected_energy": 0, "transferred_energy": 0, "action_cost": 0, "turn_cost": 1}
 Messages:
 Agent1: I am Agent0. Food is here.
 Output exactly these three fields (choose one action; give brief reasoning):
```

### action_last

```diff
--- baseline/user_prompt
+++ action_last/user_prompt
@@ -9,7 +9,7 @@
 Messages:
 Agent1: I am Agent0. Food is here.
 Output exactly these three fields (choose one action; give brief reasoning):
+Thought: [Brief reasoning for your action]
+Message: [Your message to nearby agents]
 Action: [Move to (dx,dy) | Stay | Share: {id}-{amount} | Attack: {id} | Reproduce]
-Message: [Your message to nearby agents]
-Thought: [Brief reasoning for your action]
 Keep the entire response within 400 tokens, including all field labels. Be concise.
```

### grounded_thought

```diff
--- baseline/user_prompt
+++ grounded_thought/user_prompt
@@ -11,5 +11,5 @@
 Output exactly these three fields (choose one action; give brief reasoning):
 Action: [Move to (dx,dy) | Stay | Share: {id}-{amount} | Attack: {id} | Reproduce]
 Message: [Your message to nearby agents]
-Thought: [Brief reasoning for your action]
+Thought: [Briefly state the current observation you use and your intended action; distinguish it from earlier thoughts or received reports]
 Keep the entire response within 400 tokens, including all field labels. Be concise.
```

## 再出力と比較時の注意

この資料は `tools/preview_grounded_prompts.py` で同じ生成処理から再出力できる。任意の開始設定は `main.py run --preview-prompts PATH` で確認できる。モデル・生成設定・シード・世界設定・追加世界観は条件間で固定する。以前の追加座標指示を使う実験との直接比較では、その指示も別要因になるため揃える。本文の確認後に、対象モデルと実験条件を確定して実行する。
