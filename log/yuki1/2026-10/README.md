# 2026年10月の実LLM実験

2026年10月9〜14日に保存した40件の実験記録です。2026年10月15日に公開アーカイブへ移しました。

- [実験一覧（CSV）](index.csv) / [条件・集計・重複の一覧（JSON）](index.json)
- [ファイル別SHA-256](SHA256SUMS.txt)
- [Macアプリ版（BOOTH）](https://graviton.booth.pm/items/8972362)

## まず読むなら

- [preview.35の30ターン実験](desktop/2026-10-14_22-40-29_default_model/)：斜め移動の再選択を2回実施した記録。原文は `run.json`、日本語訳は `translations.ja.json` にあります。
- [直前の30ターン実験](desktop/2026-10-14_22-04-42_default_model/)
- [Qwen 125B / Gemma 26Bの比較](benchmarks/2026-10-12-fog-qwen125b-12a-vs-gemma26b/REPORT.ja.md)
- [Flash Nextの観察](benchmarks/2026-10-13-fog-flash-next-live-085050/REPORT.ja.md)
- [観測を優先する指示を加えた実験](benchmarks/2026-10-13-fog-flash-next-observation-priority/REPORT.ja.md)
- [端の折り返しと1マス移動の指示を加えた実験](benchmarks/2026-10-13-fog-flash-next-torus-step-live-154207/REPORT.ja.md)
- [preview.35の速度・負荷の集計](measurements/preview35/report.json) / [測定値](measurements/preview35/samples.jsonl)

## 収録内容

| 場所 | 内容 |
| --- | --- |
| `desktop/` | Macアプリから実行した31件 |
| `cli/` | 開発画面などから保存した3件 |
| `benchmarks/` | モデル比較6件と、その後の実験の比較用コピー・レポート・図・計測記録 |
| `measurements/` | preview.35の速度・負荷測定 |
| `packages/` | 以前に作成した配布用ZIP4点から、開発ソースを除いて取り出した記録 |

同じ `run_id` の比較用コピーや過去の配布パッケージを含むため、フォルダ数と実験数は一致しません。40件は `run_id` で重複を除いた数です。過去のパッケージにはローカルパスを置き換えた版などがあり、今回も当時の内容を保っています。実験本体のJSON・JSONL・CSV・日本語訳と、収録した補助資料は元ファイルのままです。

`run.json` は入力・原出力・行動結果を含む全記録、`steps.jsonl` はターンごとの逐次記録、`manifest.json` は条件と実行状態です。`steps.csv`、`agents.csv`、`events.csv` は集計用、`translations.ja.json` または `events_jp.csv` は表示用の日本語訳です。古い記録には一部のファイルがありません。

## 読み比べるときの注意

- 完了29件、エラーを含む完了8件、途中停止3件を収録しています。接続に失敗して全判断を待機へ置き換えた2件も失敗記録として残しており、モデルの行動結果ではありません。
- モデル・プロンプト・内部ルールの版・初期条件は実験ごとに異なります。単純な性能順位や改善効果としては比較できません。
- `default_model` はAPI側の呼出名です。実モデルを照合できた場合だけ `model.id` 等に記録しています。未確認・照合失敗の状態を推測で書き換えていません。
- Mock、固定応答、単体・画面・ビルドの開発テスト、接続やプロンプトの短い開発用smoke確認は含めていません。
- 過去レポートのローカルパスやコマンドは当時の記録です。参照される開発版ソースや開発用スクリプトは、この公開ログには同梱していません。
