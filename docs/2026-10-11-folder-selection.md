# 2026-10-11 保存設定とフォルダ選択

- LLM設定を「実験設定」内のエージェント・砂糖・世界設定と同列に置く。
- 最後の「保存設定」に「保存先を選ぶ」・現在のパス・「盤面画像も保存する」をまとめる。保存した実験の一覧も同じ保存先を使う。
- 現行コードには保存先の入力欄とファイルのダウンロードはあるが、フォルダ選択の処理はないことを確認した。既存のpywebview 6.2.1が備える `FileDialog.FOLDER` を使用する。このバージョンのmacOS実装は `setCanCreateDirectories_(True)` によりフォルダ新規作成も有効にする。
- 初回はアプリが入っているフォルダから開き、一度選択した後は現在の保存先から開く。キャンセルでは現在の保存先を維持する。まだ存在しない保存先の場合は、最も近い既存の親フォルダから開く。選択ボタンはデスクトップ版だけで表示し、開発用ブラウザ画面は既存のパス入力を使う。
- フォルダ選択・新規作成画面とアプリのメニューを日本語表示にする。[Appleの対応言語設定](https://developer.apple.com/documentation/bundleresources/information-property-list/cfbundlelocalizations)に従い、`CFBundleDevelopmentRegion` と `CFBundleLocalizations` を `ja` に設定し、pywebviewの `localization` にメニュー翻訳を渡す。
- 新しい通信サーバー・HTTP経路・外部依存は追加しない。画面のボタンは[Streamlit Components v2](https://docs.streamlit.io/develop/concepts/custom-components/components-v2/examples)、ウインドウ連携とダイアログは[pywebviewの公開API](https://pywebview.flowrl.com/api/)を使用する。

## 確認状態

- コード確認後、ユーザーの「進めて」を受けて実行。全98テスト成功（16.264秒）。ネイティブダイアログの返り値、実際のComponents v2イベント、手入力後の保持、ページ変更後の設定保持、選んだ場所への画像保存を確認。
- 実画面で見つけた2点を修正：トリガー値を同名の既定状態値が覆う問題、選択直後にボタンへ渡す開始フォルダが古いままになる問題。実際のイベントを流す回帰テストを追加。
- preview.15のMacアプリで、日本語の「新規フォルダ」「作成」「キャンセル」「開く」、初回のアプリ所在フォルダ、次回の選択済みフォルダを確認。日本語名のフォルダを作成し、キャンセル後にも保存先が保持されることを確認。
- 3個体・1ターンのMockを実画面から2回実行。両方 `completed`、CSV・JSONと初期／最終盤面のPNGを選択先へ保存。最初の実行は開始準備を含め約250秒、同じ設定の再実行は約0.37秒。初回の遅延原因は未特定。LLMへの生成リクエストは行っていない。
- アプリを更新し、確認用の設定を初期状態へ戻した。既存90ファイルのSHA-256一致を確認。過去のアプリとZIPはビルド用フォルダに退避。
- standaloneアプリの同梱ソース一致、日本語設定、署名検証、ZIP内の全ファイルのCRC確認に成功。
- ZIP: `dist/LLM-SugarScape-0.1.0-preview.15-Mac-arm64.zip`（151,910,379バイト）。SHA-256: `8819b3afa7eaaf31e25da9b2a3ef026a424b560e76a6d62ce25fefeb9f2955e0`。
- 確認記録: `outputs/ui15-validation/final-tests.log`、`native-dialog-ja.png`、`native-save-check.json`、`data-preservation-check.json`、`final-package-check.json`。
