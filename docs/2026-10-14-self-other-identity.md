# 自己・他者の識別を明示する比較条件

2026年10月14日。入力全文をユーザー確認後、関連29件・全体200件の自動テストが合格。その後の[実モデルによる短い比較](2026-10-14-self-other-identity-smoke.md)では、Agent2の自己・他者の取り違えが新条件で見られなくなった。1 seed・1ターンずつの結果であり、継続的な改善効果は未評価。

## 入力の変更

既存の `prompt_factors` に `self_other_identity` を追加した。CLIの既定はOFF。アプリでは[preview.34から方向・距離と併せて有効](2026-10-14-desktop-preview34.md)。新しいモデル呼出しや観測経路は増やさず、同じ凍結済み `AgentObservation` を整形する。

- `Your Identity` に制御対象の本人のIDを明記する。
- `Self Status (you)` に本人の `agent_id / energy / position / cycles` をまとめる。位置は従来と同じ絶対座標。
- `Local View` を `Visible Other Agents` と `Visible Energy Sources` に分ける。該当する可視対象がない場合は `none`。世界全体に対象が存在しないという意味にはしない。
- 各位置関係に `observer_id / target_kind / target_id` を付ける。observerは本人、targetは可視範囲にある他者または資源。
- 資源には可視資源の既存順で `E1`、`E2` 等を付ける。観測内だけのラベルで、永続IDや攻撃・共有に使う個体IDではない。同方向・同距離の別資源もそれぞれ残す。
- 他者のenergy、不可視の位置・状態は加えない。既存のMBTI表示があれば保持する。

単独では従来のトーラス補正済み相対座標を `relative_offset: [dx,dy]` として渡す。`spatial_relations` と併用した場合は、既存と同じ8方位・小数1桁の直線距離を渡す。計算処理は共有し、再実装しない。

`relative_coordinates` はLocal Viewの本人を `(0,0)` とする条件で、新条件ではその欄自体を自己状態へ統合するため、同時指定を拒否する。`provenance / action_outcomes / action_last / grounded_thought` とは組み合わせられる。有効な組合せは80通り。

ゲームのルール、UI、モデル設定、行動の解析・実行、観測範囲、記憶・受信本文は変更しない。`Action:`、`Message:`、`Thought:` と行動構文も既存のまま。元の入力と新しい入力を比較できるよう、新条件OFFでは従来のプロンプトと版情報を維持する。

## 比較と記録

主な比較は、同じ初期状態の `spatial_relations` と `spatial_relations + self_other_identity`。これにより座標計算を固定して自己・他者の表現を比べられる。ただし新条件はID宣言・欄分け・関係ラベル・空一覧表示をまとめた変更であり、各要素の効果は分離できない。

新条件ありの場合だけ、`wording_revision=2026-10-14-self-other-identity-v1` と `self_other_identity.version=1` を記録する。方向・距離の計算仕様は `spatial_relations.version=1` のまま。従来の比較用シェルスクリプトの実行対象は変えていない。

[英語の入力全文](2026-10-14-self-other-identity-prompts-review.md)と[50入力・100ハッシュの原文JSON](data/2026-10-14-self-other-identity-prompt-previews.json)を保存した。通常初回、端をまたぐ対象・同じマスの他者、可視対象なし、固定履歴の4場面で、基準・新単独・従来方向距離・方向距離＋新条件・他4条件との併用を確認できる。履歴中の応答は開発用の固定例で、実モデルの結果ではない。

無通信プレビューの再出力例（保存先は未作成のディレクトリを指定）：

```sh
MPLCONFIGDIR=.mplconfig .venv/bin/python tools/preview_grounded_prompts.py \
  --identity outputs/self-other-identity-review-next
```

任意の開始設定を確認する場合は、既存CLIに次を追加する。

```text
--prompt-factor spatial_relations --prompt-factor self_other_identity --preview-prompts NEW_PATH.json
```

## 検証の境界

実装時には通常の入力生成処理による無通信プレビューの作成、差分と構文の静的確認、自動テストを実施した。確認用スクリプトではHTTPセッション生成を拒否し、`llm_calls: 0` として出力した。その後、ユーザーの指示で実モデルの8判断を別途記録した。常駐サーバー操作とアプリ配布更新は実施していない。

新しい回帰テストを追加し、既存の組合せ・CLIプレビュー・保存メタデータのテストも更新した。本人と対象のID対応、凍結観測の使用、不可視情報の非開示、空一覧、同じマスと端をまたぐ関係、資源の多重性を確認した。過去の入力92件は本文・ハッシュ・プロトコルが一致し、有効な80組合せは固定応答による4ターンの比較で世界の挙動と乱数状態が一致した。

- 関連テスト：`MPLCONFIGDIR=.mplconfig PYTHONPATH=tests .venv/bin/python -m unittest test_self_other_identity test_spatial_relations test_prompt_factors test_prompt_preview` — 29件合格。
- 全体テスト：`MPLCONFIGDIR=.mplconfig .venv/bin/python -m unittest discover -s tests` — 200件合格。
- 保存した50入力・100ハッシュと記録されたソースハッシュの一致も確認した。

これらは固定応答・Mock等による実装検証であり、実モデルの理解や判断が改善した証拠ではない。

変更前の復旧点は `bfc53ea2a5d2866b5827f5c4734f323d5067a6b8`。既存のREADME編集や画像・原稿等は本変更に含めない。
