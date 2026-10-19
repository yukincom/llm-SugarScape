# 2026-10-11 内部ルールの復元

ユーザーの「変えてほしかったのは世界観だけ」「UIは現在の状態でよく、内部ロジックは前へ戻す」という指定に対応する。基準は、論文への復元直前の `0eacbe9`。生存・繁栄を目指す指示は、この時点ですでに削除されている。

## 復元範囲

| 対象 | 復元後 |
| --- | --- |
| 出力形式 | Action / Message / Thought の3項目 |
| 操作説明 | 1マス・上下左右移動、斜め不可、世界の端の接続、共有・攻撃・繁殖・発言の条件 |
| 自分の位置 | 絶対座標を渡す。他者・砂糖は相対座標 |
| 記憶 | 実行行動と思考の先頭100文字をコード側で自動記録。直近3ターンを次回へ渡す |
| 主行動 | 移動・待機・共有・攻撃・繁殖の一つ。共有・攻撃を追加で重ねない |
| 攻撃 | 実行時点で視界内の他者から、体力の半分を端数切り捨てで取得 |
| 発言 | 追加体力消費なし。全行動後の座標で範囲判定し、次ターンへ配信。当該ターンの出生個体も受信可能 |
| 初期設定 | 繁殖コスト70、視界5、通信5、Temperature 0.0 |

現在のUI配置・アイコン・翻訳・プリセット・保存先操作・停止機能を維持する。UIの攻撃とプロンプトの説明だけ、実際の復元後ルールへ合わせる。保存した実験は書き換えない。

後続の明示指定である最大出力5000、返答全体400トークン以内、初期・出生体力100、MBTI既定オフを維持する。視界・通信の独立した設定と登録済みプリセットも使える。寛容な応答読み取りと途中応答の採用、`none` の無言扱いを維持し、不正形式で発言と思考を捨てる旧処理は復活させない。

## 送信する文面

下記systemは標準設定・MBTIなし・追加世界観なしの全文。userは復元形式を示す説明用の状態であり、実験結果ではない。実際は既存の組み立て処理が状態・設定を代入する。

### System

```text
You can move one cell: Move to (1,0), Move to (-1,0), Move to (0,1), Move to (0,-1) (costs 2 energy), or Stay (costs 1 energy). Diagonal or longer moves are invalid.
Reproduce costs 70 energy, requires at least that energy and fewer than 60 living agents.
Moving onto an Energy Source (E) gives 50 energy and consumes that source.
At zero or negative energy you die.
Share: {id}-{amount} transfers a positive integer amount you can afford to another agent in your local view. Attack: {id} takes half (rounded down) of another visible agent's energy.
Share and Attack have no additional energy cost. You cannot target yourself. Choose only one Action per turn.
Your Message will be delivered to nearby living agents for the next step, at no energy cost. Local view extends 5 cells in each axis; messages reach 5 cells in each axis. Share and Attack use positions when your Action executes; messages use positions after all Actions.
M=(x,y) is your absolute position; E=(dx,dy) and agent IDs use relative positions. x-1 is west, x+1 east, y-1 north, y+1 south; grid edges wrap.
```

### Userの例

```text
Global Info: Total Agents in the World: 3
Local View:
M=(20,22)
LATEST Status: Agent0, Energy: 98, Position: (20, 22), Cycles: 1
Memory:
Step 1: Move to (1,0); I will explore the grid.
Messages:
No messages
Output exactly these three fields (choose one action; give brief reasoning):
Action: [Move to (dx,dy) | Stay | Share: {id}-{amount} | Attack: {id} | Reproduce]
Message: [Your message to nearby agents]
Thought: [Brief reasoning for your action]
Keep the entire response within 400 tokens, including all field labels. Be concise.
```

## 記録と検証

保存schema 4を維持し、新しい実行ルールをengine 4.0、prompt_id `local-neutral-rules-v1`として区別する。旧schema 1〜4の読取経路を維持する。自動記憶はevent.memoryへ記録し、任意に返されたモデルのMemoryはresponse_memoryと原文へ残す。

上記文面を提示した後、ユーザーの「更新しましょう！実機テストは私がみます！」を受けて、自動検証とアプリ更新を実施した。新しいアプリでの実機操作・LLM生成は行っていない。

- 変更に関係する66テスト、続いて全125テストが通過。全体結果は `outputs/30-turn-debug/restoration-full-tests.log`。
- `0eacbe9` の実装と復元後の実装へ同一の3項目形式の応答を与え、10シード×30ターンを比較。共通の個体状態・記憶・受信メッセージ・世界状態・統計・実行イベントについて、310スナップショット／1,825判断が一致した。応答はスクリプトで固定し、LLM通信はしていない。比較処理は `outputs/30-turn-debug/compare_restored_engine.py`、結果は `restoration-comparison.json`。
- 既存の9実験を現在の読取処理で開けることを確認。更新前後の保存フォルダ内70ファイルのSHA-256が一致した。
- `0.1.0-preview.22` を独立した場所でビルドし、同梱17ファイルと現在のソースの一致、署名、ZIPのCRCを確認した。アプリを通常終了してから `dist/desktop/LLM SugarScape.app` を差し替えた。旧版は `build/desktop-preview21-backup/LLM SugarScape.app` に保存した。
- 配布用ZIP: `dist/LLM-SugarScape-0.1.0-preview.22-Mac-arm64.zip`（150,357,635 bytes）。SHA-256: `cd418778f3451b9ea14cd159e0cf0f5dad4dce12918e6988202673b6d42c5658`。

自動比較は指定された応答に対する実行ルールの一致を確認するものであり、新しいプロンプトに対する実モデルの判断傾向を検証したものではない。実機テストはユーザーが担当する。常駐LLMサーバーは停止・変更していない。
