# 自己・他者を明示した入力の実モデル動作確認

2026年10月14日21:40 JST。ユーザーが確認した英語プロンプトで、従来の方向・距離条件と、自己・他者を明示した条件を比較した。**2条件・各4体・1ターン、計8判断が完了した。**

従来条件のAgent2は自分を他者として扱った。新条件では本人をAgent2と名乗り、観測された他者・資源がいないことと自己energy 20を正しく述べた。今回は説明上の誤認が出なくなった一例で、選択・実行した行動は4体とも条件間で同じだった。

## 実行条件と記録

- SSの実装：`a100f8d5facfccda3395578598e6826dfe4c6fb5`。実行中のコード変更なし。
- 実モデル：`ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF`、IQ3_XXS＋MTP Q8_0。配布元revision `ed59f92082b1e93c0e96d60a8b11aab089b52f09`。
- llama.cpp：MoE on a Desk `build-14a`、runtime `6190802c8d3391ee908fb254d12fc243ad4540c6`、配布元 `7dac0e43b541cf32aba7e366e9ed62ceab680021`。
- 実行前後のPID：59020、起動時刻21:35:50 JST。起動引数・cwd・バイナリSHA-256・モデルファイル属性を記録した。同じプロセスのまま完了し、サーバー操作はしていない。
- seed 42、15×15盤面、4体、初期energy 20、砂糖2か所・各50、追加湧きなし、視界3、message range 7、MBTIなし、追加世界観なし。
- temperature 0、top_p 1、max_tokens 5000、reasoning off、context 16384、同時生成1。
- 順序は `spatial_relations` → `spatial_relations + self_other_identity`。各1ターン、追加のウォームアップ生成なし。

従来の実行スクリプトは別の2条件を比較するため、その実行対象は変更せず、記録フォルダ内のラッパーから既存の `main.py run` を2回呼んだ。コマンド全文は `plan.json` に保存。通常のRunRecorderがmanifest・JSONL・CSV・run.jsonを保存する。

両条件で初期盤面・凍結観測は実行固有IDを除いて一致し、設定の差は `prompt_factors` だけだった。実行直前に8入力を無通信で再出力し、[確認済みの入力全文](2026-10-14-self-other-identity-prompts-review.md)のハッシュと一致することを確認した。実行時の入力とも一致した。

組込みモデル識別は `unavailable / ambiguous_launch_model` のままだが、実プロセス・読み込んだ重みのパス・起動ログを別途記録して照合した。保存済みの重みSHA-256と現在のサイズ・ファイル属性を使い、約80GBの再ハッシュは行っていない。

## 結果

| 指標 | 従来の方向・距離 | ＋自己・他者の明示 |
| --- | ---: | ---: |
| 応答取得 | 4/4 | 4/4 |
| 通信 / 解析エラー | 0 / 0 | 0 / 0 |
| 応答の補正 / 行動の拒否 | 0 / 0 | 0 / 0 |
| 砂糖取得 | 50 | 50 |
| 生存数 | 4 | 4 |
| 終了時の合計energy | 122 | 122 |
| 入力トークン数 | 609〜623 | 743〜781 |

8応答すべて `finish_reason=stop`。サーバーログの生成タスクも8件で、今回の記録範囲に新しいランタイムエラーはなかった。

Agent2の実入力は、本人が位置 `(10,11)`、energy 20、可視の他者・資源なし。従来条件のThoughtには次の記述があった。

> I need to move closer to Agent2 at (10,11) to interact with them.

新条件のMessageとThoughtの該当部分は次のとおり。

> Agent2 here. Seeking energy sources.
>
> I have low energy (20) and no visible agents or energy sources.

新条件の4応答を読んだ範囲では、明示的な自己・他者の取り違えや自己energyの誤記は見られなかった。Agent1は西の資源E1へ移動してenergy 68となり、計算も実行結果と一致した。

行動は両条件ともAgent0・2・3が南へ1マス、Agent1が西へ1マス。従って今回、自己認識に関する説明は変わったが、行動・採食量・生存数の改善は観測していない。

## 解釈の範囲

1 seed・1ターンずつの動作確認。今回の各個体の視界には他者がおらず、受信メッセージと記憶も空である。**実在する他者との関係、共有・攻撃の対象選択、履歴中の自己誤認の解消は未検証。** 資源との位置関係は入力に含まれている。

新条件はID宣言・自己状態の欄分け・関係ラベル・空一覧表示をまとめた変更で、各要素の効果は分離できない。入力は134〜158トークン増えた。

従来条件は前回14a試験と4件すべて入力ハッシュが一致したが、生応答本文はAgent0・2の2件が一致し、Agent1・3は一部の表現が変わった。temperature 0でも実行をまたいだ本文の完全一致は保証されていない。今回も条件順と共有キャッシュを固定しているため、応答時間から速度差を主張しない。

## 保存先

実行・監査フォルダ（`outputs/prompt-comparison/2026-10-14-qwen-self-other-smoke/`、当時のローカル検証資料・公開対象外）に保存した。

- `plan.json`：実行コマンド、設定、ソースcommitとハッシュ、確認済み入力との一致。
- `runtime-before.json` / `runtime-after.json`：プロセス、バイナリ、重みの属性、実行前後の同一性。
- `experiment/previews/`：実行直前の全入力。
- `experiment/runs/`：入力全文、生応答、実行Action、状態変化、manifest、JSONL、CSV、集計。
- `model-activity.log`：今回の8要求に対応するサーバーログ。
- `smoke-audit.json` / `paired-comparison.json`：入力・観測・実行数・条件間の結果・前回との照合。
- `run_smoke.py` / `analyze_smoke.py` / `analyze_pair.py`：実行と解析の記録。解析2本はモデルを呼ばない。

従来条件run ID：`20261014T124039961340Z_0_8dfbde01`（21:40:39〜21:40:49 JST）。新条件run ID：`20261014T124049613780Z_0_f69ad823`（21:40:49〜21:40:57 JST）。長い比較には進まず、同じモデルを8080で稼働させたまま完了した。
