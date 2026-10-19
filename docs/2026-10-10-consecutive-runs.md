# 同じウィンドウでの連続実験

## 原因と修正

開始時に `session_state.result` は削除していたが、前回の結果表示には消去の更新を送っていなかった。次の実験の応答待ち中、ブラウザーには前回の完了表示・会話が残っていた。

既存の実験実行処理はそのまま使い、進行中と結果の表示を固定した2つの `st.empty()` に収めた。開始時に前回の結果を消し、実験が返るまで結果側には書き込まない。完了後は進行中の表示を消して新しい結果を表示する。開始失敗時も以前の結果は復活しない。保存済みの実験と接続・実験設定は維持する。

表示領域の `empty()` の直後に同じ場所へ `container()` を作るだけでは、Streamlitの送信キューで消去が後続更新へ合成される場合があるため、別々の固定位置を使う。

## 確認

- 既存UIテストを拡張し、同じセッションで2回実行して新しいrun ID・初期体力・結果だけが表示されること、言語と表示個体が初期値になること、設定と前回の保存ファイルを維持することを確認。
- サンプル表示後の開始失敗、その後の再実行成功を確認する回帰テストを追加。
- UIの9テスト成功。全体87テストも成功（15.753秒）。
- 実ブラウザーでも同じ画面からMock実験を2回実行。2回目の実行をゲートで待たせ、前回の完了表示・会話・集計が消え、新しい開始準備だけが表示されることを確認。その後ゲートを開いて2回目の完了を確認。
- ブラウザー検証の2実験は別run IDで保存され、1回目の6ファイルは2回目の実行後もSHA-256が一致。
- 検証でLLM通信は行っていない。常駐LLMサーバーは停止・変更していない。

検証記録: `outputs/restart-validation/browser-check.json`、画面: `outputs/restart-validation/preview11-second-start.png`。

## 配布アプリ

- `0.1.0-preview.11` を別フォルダでビルド・検証後、ユーザーの許可を受けて `dist/desktop/LLM SugarScape.app` へ反映。旧版は `build/desktop-preview10-backup/LLM SugarScape.app` に保存。
- 同梱ソース7ファイルの一致、CFBundleVersion 11、ad-hoc署名のdeep/strict検証に成功。
- `dist/LLM-SugarScape-0.1.0-preview.11-Mac-arm64.zip` を作成。150,249,370 bytes。
- SHA-256: `1250d218436765b830e1b10939b7a00e1fd306fa534563b11622057350b06ead`。
- ZIP全エントリーのCRC、チェックサム、同梱UIソースの一致、実験データを含まないことを確認。

## アプリ反映後の確認

- ユーザーの中断許可後に旧アプリを閉じ、専用ポート61326の終了を確認。常駐LLMの8080は同じPID 63810で稼働。
- Qwen3.5-2B-6bitの実験は17ターン・51判断を保存済みだった。元のmanifestを `outputs/restart-validation/interrupted-before-finalize/manifest.json` に保存し、既存の `RunRecorder.finish()` で `interrupted` / `user_approved_app_update` として終了・出力した。終了時モデル照合は未実施として記録。
- `steps.jsonl` の全バイトは不変。以前の出力26ファイル中、終了状態を記録したmanifest以外の25ファイルはSHA-256が一致。中断した実験を更新版の保存一覧から開き、記録を読めることも確認。
- 更新版の実アプリで、再起動を挟まずMockを2回実行。各1ターン・3判断が完了し、別run IDで `outputs/restart-validation/native-runs/` に保存。
- 検証後は表示を消し、通常の保存先・LLM接続・3個体・30ターン・最大出力10,000トークンへ戻して開始画面で待機。新しいLLM実験は開始していない。
- 反映後の署名検証、同梱ソース7ファイルの一致を確認。

詳細: `outputs/restart-validation/install-check.json`。実アプリの2回目: `outputs/restart-validation/preview11-native-second-run.png`。更新後の開始画面: `outputs/restart-validation/preview11-ready.png`。
