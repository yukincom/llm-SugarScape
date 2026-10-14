# Flash Nextの相対座標指示の比較記録

2026年10月13日、霧の中の交渉をseed 42で再実行した記録です。前回の観測優先指示に、トーラス補正済みの相対座標から1歩を選ぶ1段落だけを追加しました。

- [日本語レポート](REPORT.ja.md)
- [追加した指示](additional-instruction.txt)
- [全設定](prepared-config.json)
- [今回の実験](run/run.json) と [比較元](baseline-seed42/run.json)
- [集計](analysis/summary.json) と [照合結果](analysis/validation.json)
- [観測・応答・実行の代表例](analysis/behavior-evidence.json)

実験はユーザーが開始し、観測担当は保存ファイルとプロセス情報を読み取りました。観測担当によるAPI要求、モデル切替、本体コードの変更はありません。

同梱の `analysis/analyze_capture.py` は標準ライブラリだけで保存済みデータを再集計します。図の再生成にはMatplotlibと日本語フォントが必要です。

共有用ZIPでは個人のホームディレクトリ名を置換しています。`original-file-sha256.json` が元ファイルと共有版の違いを示し、`SHA256SUMS.txt` が共有版の整合性を確認するための一覧です。原文の入出力は英語のまま保存しています。外部への提出は行っていません。
