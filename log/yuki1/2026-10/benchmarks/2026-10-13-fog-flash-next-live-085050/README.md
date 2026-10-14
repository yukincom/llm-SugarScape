# Flash Next 計測レポートと検証データ

2026年10月13日の「霧の中の交渉」seed 42再実験をまとめた、moe-on-a-desk開発者向けの日本語資料です。

まず [日本語レポート](REPORT.ja.md) をご覧ください。実験72要求は173.15秒で完了し、応答時間中央値2.04秒、MTP採用率73.76％でした。捕捉区間のMTPエラーは0件です。攻撃成立0回のため攻撃コストの効果は判定せず、観測・自己ID・実行結果の理解に関する事例を添えています。

| 保存場所 | 内容 |
| --- | --- |
| `REPORT.ja.md` | 条件、計測、前回比較、行動事例、攻撃調整の評価と提案 |
| `figures/` | 日本語の行動比較図と性能・メモリ推移図 |
| `run/` | 今回の入力、原応答、実行結果、表示用日本語訳 |
| `baseline-seed42/` | 比較に使った前回の同じ初期配置の記録 |
| `runtime.log`・`desktop.log` | 今回の計測区間に追記されたログ |
| `log-chunks.jsonl`・`resource-samples.jsonl` | 採取時刻付きのログ断片と資源状態 |
| `analysis/` | 集計JSON・CSV、代表事例、集計と図の再生成用スクリプト |
| `capture-manifest.json`・`final-verification.json` | 実行実体、計測方法、実行前後の照合 |
| `build-manifest.json`・`models-manifest.json` | ランタイム版・パッチ・モデル情報 |
| `previous-weight-verification.json` | 過去に実施した重み全体のハッシュ検証 |
| `frozen-app-source/` | 実行したアプリのソース。アプリ再配布物やモデル重みは含まない |
| `context/` | ルール調整・応答補正・前回比較の記録 |
| `original-file-sha256.json` | ローカル原本のハッシュと、共有用コピーでの変更有無 |
| `SHA256SUMS.txt` | 共有用ファイルのSHA-256 |

## 集計の再生成

展開先で `python analysis/analyze_capture.py` を実行すると、保存記録から集計を再生成します。Python標準ライブラリだけを使い、LLMへ要求しません。

`python analysis/render_figures.py` で図を再生成できます。matplotlib・numpyと、日本語フォントのHiragino Sans、Noto Sans CJK JP、IPAexGothicのいずれかが必要です。生成済みのPNGを見るだけなら追加ソフトは不要です。

## 共有用データの扱い

レポートと図は日本語です。モデルの英語の原応答・元ログ・ソースコードは検証のため原言語を保っています。共有用コピーでは個人のローカルパスを `/Users/USER` に置換し、無関係な作業ファイル一覧と差分は除いています。原本のハッシュと共有用ファイルのハッシュは異なる場合があります。

今回、アプリコード・設定・モデルを変更していません。資料は未投稿です。
