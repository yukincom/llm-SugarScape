# コードで算出した方向・距離の比較条件

2026年10月14日。復旧基準は `f28eb58`。ドギドの比較で使った「コードで計算した方向と距離を渡す」方式を、SSの独立した入力条件 `spatial_relations` として追加した。UIと世界ルールは維持し、プロンプトは英語。CLIの既定はOFFで、既存の `prompt_factors` と `--prompt-factor` から選択する。アプリでは[preview.34から自他識別と併せて有効](2026-10-14-desktop-preview34.md)。

## 入力の表現

現在のLocal Viewだけを次のように置換する。

```text
M=self
E: direction=east; distance_cells=1.0
E: direction=southeast; distance_cells=2.8
1: direction=same_cell; distance_cells=0.0
```

- 方位は世界の東西南北を基準にする8方向。SSに身体の向きは加えない。+xは東、+yは南で、既存の移動命令との対応を英語説明に残す。
- 距離は端の折り返しを補正した相対座標から求めるユークリッド距離 `hypot(dx,dy)`。小数1桁へ丸める。上下左右への行動回数とは異なる。
- 方位は最も近い45度刻みの方向。東を0度として最初の境界を22.5度に置き、以後45度ごとに区分が切り替わる。境界は角度が増える側へ含める。相対座標が(0,0)なら `same_cell` と距離0.0。
- 既存の周期境界補正をそのまま使う。偶数サイズで軸距離が盤面の半分の場合も、既存処理が選ぶ負の相対値を維持する。
- 資源・個体の順序、件数、ID、既存のMBTI表示を保つ。同じ方向・距離になった資源も統合しない。未対応のエンジン生成行は例外にし、黙って削除しない。

変換元は、全個体の判断開始前に確定した本人の可視範囲の観測。新たに世界全体を参照しない。可視性は従来どおり各軸で判定するため、視界3セルで相対(3,3)の対象は、表示距離が4.2でも可視になる。この距離を可視性・攻撃・共有の判定へ転用しない。

自己の絶対位置はLATEST Statusに残す。過去のThought、行動結果、受信メッセージに含まれる座標を削除・再計算せず、それぞれ選択された既存条件の表示を保つ。「結果を渡す」の対象は現在のLocal Viewであり、プロンプト全体から座標を除去する条件ではない。

## 比較条件

| 比較 | 変わる入力 |
| --- | --- |
| 既定 → `spatial_relations`単独 | 現在のLocal Viewとその読み方の説明 |
| `relative_coordinates`単独 → `spatial_relations`単独 | 相対座標から方向・距離への表現変更 |
| 旧5条件併用 → `relative_coordinates`を新条件へ置換 | 他4条件を固定した表現変更 |

`relative_coordinates` と `spatial_relations` は同じ欄の代替表現であり、同時指定すると設定エラーにする。残り4条件とは任意に併用できる。従来の32組合せに新しい16組合せが加わり、有効な組合せは48になる。出生個体にも条件が引き継がれる。

8方向と丸めた距離は元の座標より情報が粗い。たとえば相対(3,4)と(4,3)はどちらも `southeast, 5.0` になる。これは**計算の代行に加え、入力の表現と精度を変える比較**であり、行動の変化を計算負担だけの効果とは断定できない。

新条件が有効な記録は `prompt_id=local-grounded-v2+...spatial_relations`、`wording_revision=2026-10-14-spatial-relations-v1`。protocol内の `spatial_relations.version=1` と計算方法を保存する。既存条件のID、本文版、世界ルール、保存schemaは変えない。

## 実験前の確認

[英語全文の確認資料](2026-10-14-spatial-relations-prompts-review.md)と[全原文JSON](data/2026-10-14-spatial-relations-prompt-previews.json)を保存した。既存プリセット初回、端をまたぐ対象・同じマス・MBTIあり、可視対象なし、履歴ありの4場面を5比較条件で生成し、計50入力・100個の原文SHA-256を照合した。履歴は固定応答による人工例であり、モデルの行動結果ではない。

任意の開始条件も、既存のプレビュー機能で**通信なし**に確認できる。次は確認用ファイルのみを作る例。

```sh
.venv/bin/python main.py run --agents 4 --steps 30 --seed 42 \
  --grid-size 15 --initial-energy 20 --child-initial-energy 20 \
  --population-cap 4 --spawn-energy-count 2 --num-clusters 2 \
  --cluster-radius 0 --energy-spawn-rate 0 --view-range 3 --message-range 7 \
  --prompt-factor spatial_relations \
  --preview-prompts outputs/review-spatial-relations.json
```

`--preview-prompts`を外すと実験になるため、本文の確認前には外さない。他4条件を併用する場合は `--prompt-factor provenance --prompt-factor action_outcomes --prompt-factor action_last --prompt-factor grounded_thought` を加える。

確認資料全体の再出力は `tools/preview_grounded_prompts.py --spatial NEW_REVIEW_DIRECTORY`。従来資料はオプションなしで再出力できる。既存の資料は上書きしない。

## 検証結果と未実施の範囲

- 全体の **188テストが通過**。方位と丸め、端の折り返し、偶数盤面の半周、同じマス、同じ表示になる複数資源、MBTI、可視範囲、固定観測、過去の記述の保持、CLI、記録を含む。
- 従来の全32組合せについて、履歴あり・周期境界とMBTIありの2場面、計160入力・320ハッシュとprotocolが変更前後で一致。以前保存した42入力もテストで全文一致を確認した。
- 有効な全48組合せで4ターンの固定応答を使い、世界、既存の表示用データ、出生・配送・行動結果、世界と性格の乱数状態が一致。同時指定できない16組合せは拒否された。
- 旧併用・新併用の両方で、資源生成・履歴ありのプレビューが元の世界を変えず、次ターンで実際に生成される入力と一致することを確認した。
- 読み取り専用レビューでも修正を要する欠陥は見つからなかった。

検証記録は outputs/validation/2026-10-14-spatial-relations（`outputs/validation/2026-10-14-spatial-relations/`、当時のローカル検証資料・公開対象外） の `legacy32-before.json`、`legacy32-after.json`、`legacy32-comparison.json`、`review-verification.json`、`full-tests.log` に保存した。

これらは入力生成と世界ルールの検証であり、実モデルの理解・判断の改善は未測定。モデル接続・実モデル実験・デスクトップアプリのビルドと差し替えは行っていない。
