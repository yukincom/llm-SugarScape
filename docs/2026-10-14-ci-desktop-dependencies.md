# CIのデスクトップ用依存関係

2026年10月14日。復旧点は `4a62c21`。

開発用リポジトリへのpush後、[CI run 38578245996](https://github.com/yukincom/dev-llm-sugarscape/actions/runs/38578245996)で210テスト中3件が `ModuleNotFoundError: No module named 'webview'` により失敗した。対象は `tests/test_desktop.py` のフォルダ選択・初回選択先のテスト。ローカルのMacにはデスクトップ用依存関係が入っていたため、全210件が合格していた。

CIは `requirements.txt` のみをインストールしていた。既存の `requirements-desktop.txt` を使うよう変更し、pipのキャッシュキーにも両方の依存定義を含める。Mac用パッケージ作成に使う `py2app` は `sys_platform == "darwin"` を指定し、Ubuntuではインストールしない。`pywebview` のバージョンは配布アプリと共通の6.2.1を維持する。

アプリ本体・プロンプト・配布ZIPには変更を加えない。CIのデスクトップテストはウインドウ作成やダイアログをMockに置き換えるため、実GUIの表示確認には相当しない。

修正後のローカル全210テストは合格（36.902秒）。依存定義を `packaging` で評価し、Darwinでは `pywebview` と `py2app`、Linuxでは `pywebview` が選ばれることを確認した。`git diff --check` も正常。Ubuntu上のインストールとテストは、修正commitのpush後にCIで確認する。
