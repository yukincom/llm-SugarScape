# LLM SugarScape

ローカルLLMによる小規模なエージェント実験。行動・個体履歴・人口やエネルギーの推移をCSV/JSONに保存します。
元の着想は [Sugarscape-style simulation 論文](https://arxiv.org/abs/2508.12920)。ルールやプロンプトには独自変更があり、論文の厳密な再現ではありません。

## 起動

Python 3.11以上を使用します。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/streamlit run main.py
```

画面の初期接続先は `http://127.0.0.1:8080/v1`、モデル名は `default_model` です。先にローカルのOpenAI互換サーバーを起動してください。既存のMLXサーバーでは起動済みモデルを使用します。MockはAPIなしで全個体が待機する動作確認用です。Custom APIでは接続先とモデル名を変更できます。

## 小規模実験と集計

```bash
# 実LLM：2個体、3ステップ
.venv/bin/python main.py run --agents 2 --steps 3 --seed 42

# APIを使わず保存・集計経路を確認
.venv/bin/python main.py run --mock --agents 3 --steps 5

# seedを42、43、44と変えて逐次実行
.venv/bin/python main.py run --agents 3 --steps 10 --seed 42 --runs 3

# outputs直下の実験を1行ずつにまとめる
.venv/bin/python main.py aggregate --input outputs
```

各実験は `outputs/<一意のrun_id>/` に保存されます。`steps.csv` は時系列、`agents.csv` は個体履歴、`events.csv` は判断と実行結果、`run.json` はプロンプト・生応答を含む詳細、`manifest.json` は条件と実行状態です。`aggregate` は `runs.csv` を作ります。画像は `--images` で追加できます。

APIキーが必要な場合は画面か環境変数 `SUGARSCAPE_API_KEY` に設定します。キーは保存しません。CLIでは `SUGARSCAPE_BASE_URL` と `SUGARSCAPE_MODEL` も利用できます。

統計に使う前に `status` とエラー件数を確認してください。列の定義、ルール、旧データとの違い、検証結果は [データ仕様と開発記録](docs/2026-10-08-local-llm-data.md) を参照してください。

## テスト

```bash
.venv/bin/python -m unittest discover -s tests -v
```

[MIT License](LICENSE) · [実験記録（Note）](https://note.com/yukin_co/n/neb0a321d4539)
