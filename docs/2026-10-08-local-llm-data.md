# 2026-10-08 ローカルLLM接続とデータ記録

## 範囲・接続

既存の `Simulation` / `main()` / Streamlit入口を共用し、HTTP接続先を設定可能にした。記録・CSV出力は `run_data.py` に分離。HTTP要求も実験の反復も逐次実行する。既存の `batch_experiment_parallel()` は互換入口として残し、内部は逐次実行する。

標準接続は `http://127.0.0.1:8080/v1/chat/completions`、`model=default_model`、temperature 0、max_tokens 384、タイムアウト120秒。サーバーの起動・停止・モデル切替は行わない。キーなしならAuthorizationヘッダーを送らない。再試行はせず、HTTP・通信・形式・生成打ち切りの失敗を記録する。URLへのキー・ユーザー情報・クエリ埋め込みは禁止。

リポジトリに欠けていた `requirements.txt` を追加し、動作確認した直接依存のバージョンを固定した。各実験にはPythonとパッケージバージョン、Git HEAD・dirtyフラグ、主要ソースのSHA-256を保存する。通常終了はCLI終了コード0、エラーを含む完了／実行失敗は2。複数runは最初の非正常runで停止。UIでも失敗を成功と表示しない。

## ファイルと結合キー

データ形式は `schema_version=1`、修正後のルールは `engine_version=2.0`。UTC時刻とランダム識別子から一意run IDを作り、再実行でも上書きしない。

| ファイル | 粒度・用途 |
| --- | --- |
| `manifest.json` | 条件、seed、開始終了時刻、状態、実装由来。APIキー除外 |
| `steps.jsonl` | 初期状態step 0と、完了した各stepを追記する一次記録 |
| `steps.csv` | run ID × step。人口・資源・energy・行動率・累積件数・stepごとの増分 |
| `agents.csv` | run ID × step × id。初期個体・新生児・死亡個体を含む全既知個体 |
| `events.csv` | run ID × step × agent_id。要求・解析パラメータ・実行結果・応答情報 |
| `run.json` | 条件・最終集計・全step。system/user prompt、生応答、資源座標を含む |
| `runs.csv` | `aggregate` で作る1実験1行の比較表。条件全文・ソースhash・状態を含む |

すべてUTF-8。CSVの真偽値は `True` / `False`、未提供値は空欄。JSONの未提供値はnull。step 0の行動件数は0。資源は1個50 energy。

`steps.csv` の通常の件数は累積、`*_this_step` は当該stepのみ。`alive_start` は開始人数。死亡個体は `agents.csv` で以後も終状態を保つ。人口には `alive == True` を使い、個体総数や死亡数にはidの重複除去が必要。

`events.csv` の `kind` は解析結果（move/stay/share/attack/reproduce）、失敗時は実装が選ぶstay。元の要求文字列は `requested_action`、実行結果は `executed_action`。`dx` / `dy` / `amount` は該当要求だけに入り、拒否値も残る。前後座標は `x_before` / `y_before` / `x_after` / `y_after`。

`energy_before` / `energy_after` は当該個体の行動適用直前・直後であり、step全体の前後ではない。他個体の行動でその後も変わりうる。最終状態は `agents.csv`。`energy_transferred` は共有では送信量、攻撃では獲得量。取得量とコストは `energy_collected` / `energy_cost`。出生による追加energyは `child_initial_energy` × 出生数。

## 指標・エラー

- `total_actions`：各step開始時の生存個体数の累積。拒否・fallbackも意思決定機会に含む。
- `valid_decisions`：HTTP/応答/構文の解析成功件数。実行条件の判定は別なので、拒否も含む。
- `shares` / `attacks` / `reproductions`：実行成功件数。要求のみ・拒否は含まない。
- `coop_rate` / `attack_rate` / `repro_rate`：各成功件数 ÷ `total_actions`。分母0なら0。
- `llm_errors`：HTTP・通信・応答構造・生成打ち切りエラー。`parse_errors`：行動構文の解析失敗。
- `rejected_actions`：解析できたが実行条件を満たさない行動。
- `decision_source`：llm / mock / fallback。`action_status`：executed / rejected / fallback / skipped_dead。
- `status`：running / completed / completed_with_errors / failed / interrupted。

エラー・不正行動は待機（cost 1）として進行し、モデルが選んだ待機と区別する。エラーを含むrunは `completed_with_errors`。拒否のみなら `completed` であり、拒否率も観測対象となる。エラー後の状態はfallbackの影響を受けるため、モデル比較には原則 `completed`、`mode=llm`、同設定・同実装のrunを使う。`aggregate` は比較表のみを作り、条件の違う実験を自動平均したり有意差を計算したりしない。

`response_model` はサーバー報告値そのもの。今回のMLXは別名 `default_model` を返すため、これだけでは実モデルを識別できない。起動引数・ログで確認したモデル名を研究記録にも併記する。seedは環境・MBTI・繁殖の乱数用であり、LLM出力の完全再現を保証しない。

## ルールと修正

各stepはメッセージ受信、資源生成、全生存個体の観測・判断収集、ID順の行動適用、次step用メッセージ配信、記録の順。各判断は同じ更新前の世界を見る。適用順による先着効果は残り、`action_order` に記録する。

- 移動は上下左右1マス、cost 2。負数・空白を受理し、斜め・長距離は拒否。座標と視界はトーラス。
- 待機cost 1。共有・攻撃の追加costは0。共有は視界内の別の生存個体へ正の整数かつ保有量以下。攻撃は相手のenergy半分（切捨て）の移転。
- 繁殖は生存中・保有energyがcost以上・現在の生存数が上限未満の場合のみ。出生・親子・costを同時記録。子は次stepから判断。costと等しいenergyの場合は出生後に親が死亡する。
- energyが0以下で死亡を一度だけ記録。既存設定（初期150、繁殖cost70、子150）は維持するため、出生によるenergyの純増は意図的に残る。
- MBTI無効時は親・子の両方で人格文とMBTIを除く。世界観を追加しても基本ルールを保持。抽選重みは旧コード由来であり、現実人口の正確な推定として検証したものではない。
- モデルのMessageを次stepに届け、Thoughtを通信内容に置き換えない。
- 描画は固定色で、実験用乱数を消費しない。資源は有限サンプリングで重複・満杯時の無限ループを避ける。

プロンプトも実装ルールに合わせて整理した。初期配置アルゴリズムとプロンプトが変わったため、旧 `log/`、`old_ver/` や以前のJSONと同一条件の結果として混ぜない。旧ログ変換は今回の対象外。

## 中断・再出力

```bash
.venv/bin/python main.py export outputs/<run_id>
.venv/bin/python main.py aggregate --input outputs
```

完了stepごとにjournalとmanifestを保存し、終了時にCSVとrun.jsonを生成する。例外・Ctrl+Cでは直前までに完了したstepを出力する。ハード終了ではmanifestがrunningのまま残りうるが、`export` で復旧可能。最終行だけの不完全JSONはrunning/interrupted/failed時に限り無視し、復旧フラグを残す。中間行の破損・run IDやstep順の不整合はエラー。完了step数はjournalを基準に再計算する。未完了stepの途中の判断は復旧対象外。再開実行は未実装。

## 検証結果

2026-10-08、Python 3.11.14の専用 `.venv` で確認。

- 回帰テスト21件：移動、出生死亡、親子、人口・行動率、共有攻撃、MBTI、通信、HTTP/形式エラー、seedと描画、CSV、中断復旧、キー非保存。
- Streamlit AppTest：初期表示、Mockの5個体×2step、結果表示、ウィジェット更新後の結果保持。
- 実8080：2個体×3step、seed42、population_cap4、6判断すべてHTTP200・正常解析・実行成功。LLM/解析エラー0。step CSV4行、個体CSV8行、行動CSV6行。総energy341（初期300＋取得50−消費9）で整合。
- サーバー起動引数のモデルは `isetnefret/Huihui-gemma-4-26B-A4B-it-qat-q4_0-unquantized-abliterated-mlx-4Bit`。応答のmodelは `default_model`。PID98192の引数・cwd・ログを確認。停止・再起動・切替はしていない。
- 実run：`outputs/local-smoke/20261008T132041233502Z_0_c9d0ec16/`。同じ親フォルダーに、サンドボックスの通信制限時の失敗runも状態付きで保持。`runs.csv` で区別できる。いずれもGit対象外。

これらは実行・データ整合のスモーク確認であり、性格差・協力性・生存傾向について統計的結論は出していない。
