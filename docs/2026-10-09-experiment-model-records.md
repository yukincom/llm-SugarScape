# 2026-10-09 実施日・モデル情報の自動記録

## 保存する情報

新規実験は `schema_version=2`。シミュレーションのルールは変更せず、`engine_version=2.0` を維持する。

`manifest.json` と `run.json` に次の情報を保存する。画面には実施日と実モデル名を表示し、詳細表示とmanifestのダウンロードも追加した。

| フィールド | 内容 |
| --- | --- |
| `execution_date` | 実験開始日の年月日。`Asia/Tokyo`で判定 |
| `timezone` | `Asia/Tokyo`。開始・終了時刻自体は従来どおりUTC |
| `config.model` | APIへの指定名。通常は `default_model` |
| `model.id` | 起動設定とローカルファイルを照合したモデルID、または絶対パス |
| `model.revision` | Hugging Face snapshotのrevision。通常のローカルフォルダーならnull |
| `model.weights` | 各重みファイルの名前・バイト数・SHA-256。ファイルの実内容から計算 |
| `model.quantization` | configにあるbits・group_size・mode |
| `model.status` | 照合結果。下表参照 |
| `model.source` | `local_server_launch_and_cache`。起動設定とキャッシュを使った照合であることを明示 |
| `model.snapshot` / `model.server_pid` | 照合した保存先とサーバーPID |

SHA-256は重みの内容を照合するための識別値。revisionが同じでもローカルで重みを変更すればSHA-256が変わる。どちらも生成結果の完全再現を保証するものではない。

API応答の `response_model` は新規記録から削除した。API名は `config.model` に保持し、集計表の `model` 列には照合した実モデルIDを出す。MLX・MLX-LMなどサーバー側ライブラリの版は自動保存しない。従来の実験プログラム側Python・ライブラリ・ソースhashの記録は継続する。

## 取得方法と確認範囲

このMacの既存 `http://127.0.0.1:8766/api/status` を読み取り、8080サーバーのPID・起動コマンド・モデル指定を照合する。対象は `http://127.0.0.1:8080/v1` またはlocalhost、API指定が `default_model` または起動モデルIDと一致する場合。管理APIのtoken・ログ・コマンド全文は保存しない。サーバーの起動・停止・モデル切替・新しいAPI経路の追加は行わない。

Hugging Face IDはローカルキャッシュの `refs/main` からsnapshotを解決する。キャッシュ位置は `HF_HUB_CACHE`、`HF_HOME`、`XDG_CACHE_HOME`、標準位置の順に解決する。サーバーと同じユーザー・キャッシュ設定での利用が前提。絶対パスで指定したモデルも対象となる。

現行MLX-LMが読む `model*.safetensors` をすべてSHA-256計算する。インデックスがある場合は参照先の欠落も検査する。開始時にPID・起動引数とファイル状態を照合し、ハッシュ計算後および実験終了時に再検査する。モデル、設定、tokenizer、refsなどがサーバー起動以降に変更された場合は、メモリ上のモデルと同じと判断できないため未確認にする。

これは起動設定とディスク上のファイルに基づく記録であり、メモリ内の重みを直接読み出した証明ではない。既存 `/v1/models` はキャッシュ一覧なので、実行モデルの証拠には使わない。開始・終了間のあらゆる一時的な変更を監視する機能ではない。

管理APIがない環境、Custom APIの外部接続先、別モデルへの動的要求は未確認扱いで実験を継続する。`--adapter-path` または `--draft-model` がある場合も、要求への適用を確認できていないため未確認とする。LoRAを使う実験は適用確認とその記録を追加してから実施する。

| `model.status` | 意味 |
| --- | --- |
| `recorded` | 上記の照合条件を満たして記録できた |
| `mock` | APIを呼ばない動作確認。実モデルはない |
| `unavailable` | 開始時点で照合できず、理由を `model.reason` に記録 |
| `changed_during_run` | 終了時にPID・起動設定またはファイルの変更を検出 |
| `unverified_after_run` | 終了時の検査失敗、または実験が中断・失敗した |
| `legacy_unrecorded` | 旧形式のため当時の実モデルを記録していない |

変更検出・終了時検査失敗では実験全体も `completed_with_errors` とする。モデル比較には、実験の `status=completed` と `model.status=recorded` の両方を確認する。画面は未確認状態を警告する。

## 集計と過去データ

`runs.csv` には実施日・時刻・実モデルID・状態・revision・重みSHA-256・量子化設定を出力する。複数の重みSHA-256はファイル名をキーとするJSONで1セルに保存する。重複した `response_models` 列は削除した。

schema 1も `export` / `aggregate` で読める。元のmanifest・journalは変更せず、旧events.csvの `response_model` 列も保持する。集計表の実モデルは空欄、状態は `legacy_unrecorded` にする。過去の実施日は保存済み開始時刻から日本時間へ変換し、時刻がなければ空欄にする。現在のモデル名や今日の日付を後付けしない。

## 検証

- `env MPLCONFIGDIR=.mplconfig .venv/bin/python -m unittest discover -s tests -v`：37件成功。日本時間の日付境界、分割重み、モデル・ファイル変更、取得失敗、秘密情報の除外、旧形式の再出力、Streamlit表示を含む。
- 実LLMは2個体・1ステップ、seed 42、MBTIなしで保存確認。最初はQwen3.5-2B-6bit、最終確認はその時点で8080に起動していたHuihui Gemma 4を使用した。各2判断、LLM・解析エラー0、`status=completed`、`model.status=recorded`。
- Qwen：revision `ba2bcf03dd5b502646de7e32b003cf538f2ca4d6`、重みSHA-256 `e2c78893f7cb9d1c176688861bb31614af7ee097ff5e6bbfc504b4230daef80b`。
- Gemma：revision `0305104730dfd6729d44a5caa06a06c0ba8520e2`、重み3ファイルを個別に記録。
- 両runのmanifest・run.json・runs.csvのモデル、revision、全重みSHA-256が一致すること、新しいevents.csvに重複モデル列がないこと、サーバーMLX版を追加していないことを確認。

保存先（Git対象外）：

- `outputs/model-record-validation/20261009T052343452395Z_0_ce0d5521/`：Qwen
- `outputs/model-record-validation/20261009T052722814440Z_0_c2adb403/`：Gemma
- `outputs/model-record-validation/runs.csv`：上記2件の集計

これらは保存機能の動作確認であり、モデルの判断傾向を比較する本実験ではない。
