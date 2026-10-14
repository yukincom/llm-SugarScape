# Flash Next 追加指示の比較記録

[日本語レポート](REPORT.ja.md)からご覧ください。2026年10月13日、engine 5.1・seed 42で、現在の観測を優先する追加指示だけを変えた2試行を比較しました。

- [実際に加えた英語の指示](additional-instructions.txt)
- [追加前の実験](baseline-seed42/run.json)・[追加後の実験](run/run.json)
- [集計](analysis/summary.json)・[設定差分](configuration-validation.json)・[検証結果](analysis/validation.json)
- [代表的な入力と応答](analysis/behavior-evidence.json)
- [行動の図](figures/behavior.png)・[速度の図](figures/runtime.png)

記憶の保存方法、入力順、攻撃の数値、コードは同一です。比較の間にサーバープロセスが変わり、追加後の実験中に実験外の2要求も記録されたため、速度の因果比較には使えません。

集計は標準Pythonで `python analysis/analyze_capture.py`。図はmatplotlib・numpyと日本語フォントが必要です。LLMへの追加要求はありません。共有用ZIPのハッシュは `SHA256SUMS.txt`、原本との対応は `original-file-sha256.json` にあります。
