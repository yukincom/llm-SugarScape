# LLM SugarScape

[![CI](https://github.com/yukincom/llm-SugarScape/actions/workflows/ci.yml/badge.svg)](https://github.com/yukincom/llm-SugarScape/actions/workflows/ci.yml)

ローカルLLMによる小規模なエージェント実験。行動・個体履歴・人口やエネルギーの推移をCSV/JSONに保存します。
元の着想は [Sugarscape-style simulation 論文](https://arxiv.org/abs/2508.12920)。ルールやプロンプトには独自変更があり、論文の厳密な再現ではありません。

## Macアプリ版をBOOTHで販売中

**[BOOTHでLLM SugarScapeを見る・購入する](https://graviton.booth.pm/items/8972362)**

このリポジトリは開発初期の公開プロトタイプです。ここから開発を進めたMacアプリ版（`0.1.0-preview.35`）を販売しています。販売版には、次の機能を追加しています。

- **ダブルクリックで起動**：Pythonを同梱したMacアプリ。ターミナルを使わず専用ウインドウで操作できます。
- **観察しやすい画面と日本語訳**：表情アイコン付きの盤面、発言・思考の逐次表示、終了後の日本語訳と原文の切り替え。
- **実験を保存して繰り返す**：シナリオプリセット、マイプリセットの登録、保存した実験の再表示・名前変更、Finderで保存先を開く機能。

**主な修正・改善（2026年10月14日）**

- **自分と他者・砂糖の区別**：本人のIDと状態、周囲の他者・砂糖を分けてLLMに渡し、本人から見た方向と距離も明示します。
- **移動指定の取り違えへの対応**：隣接する移動先を絶対座標で返した場合は、1マス移動だと一意に分かるものを補正。斜め移動を要求した場合は、同じターン内で「どちらへ先に進むか」を2択で聞き直し、選んだ1マスだけ進みます。
- **体力消費と攻撃の調整**：共有・攻撃を続けると体力消費を免れたルールを見直し、全個体に毎ターンの共通消費を追加。攻撃で奪う量とコストも調整しました。
- **表示・接続まわりの改善**：実行中の盤面サイズを固定し、応答を届いた順に表示。サーバーに接続できない場合は、実験を開始せず案内を表示します。

販売版はApple Silicon搭載Mac・macOS 26.2以降に対応します。LLMのモデル・推論サーバー、またはOpenAI互換APIは別途ご用意ください。対応環境やプレビュー版の注意点は販売ページをご確認ください。以下は、この公開プロトタイプをソースコードから動かす手順です。

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

GitHub Actionsでもpush・PR時に同じテストとMockのCSV出力・集約を実行します。実LLM接続の確認はローカルで行います。

[MIT License](LICENSE) · [実験記録（Note）](https://note.com/yukin_co/n/neb0a321d4539)
