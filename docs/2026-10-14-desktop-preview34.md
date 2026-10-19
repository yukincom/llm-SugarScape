# preview.34 — 自他識別と方向・距離の入力を有効化

2026年10月14日。ユーザーの「有効にして！ビルド、差し替え！」に基づくアプリ更新。変更前の復旧点は `f214796`。

## アプリの変更

アプリの既存設定処理で `spatial_relations` と `self_other_identity` を常時有効にする。同梱・登録済みプリセットから始めた場合も、この入力形式を使う。検証済みの英語プロンプト本文は変更しない。本人ID、自己状態、可視範囲の他者・資源を分け、他者・資源には本人からの方向と距離を渡す。

世界ルール、行動構文、モデル接続先と生成設定は従来どおり。CLIと比較用スクリプトの既定条件も維持する。アプリで新しく作る実験には、既存のmanifest・run.jsonへ有効な入力条件が記録される。過去の保存データは書き換えない。

## 検証・差し替え

- 関連45テスト、全体200テストが合格。アプリで開始したMock実験の入力本文とmanifestの条件記録、視界・通信範囲を確認した。ログは `outputs/desktop-preview34/scoped-tests.log` と `full-tests.log`。
- `dist/desktop-preview34-staging/LLM SugarScape.app` にstandaloneビルドを作成。同梱ソース・画像34ファイルのSHA-256が現在のソースと一致。Python同梱、alias=false、build番号34を確認し、アドホック署名と `codesign --verify --deep --strict` が成功した。
- `dist/desktop/LLM SugarScape.app` をpreview.34へ差し替えた。旧preview.33は `build/desktop-preview33-backup/LLM SugarScape.app` に退避。保存実験226ファイルは差し替え後・実アプリ確認後ともSHA-256が更新前と一致した。
- 配布ZIPは `dist/LLM-SugarScape-0.1.0-preview.34-Mac-arm64.zip`（150,464,441 bytes）。全20,587エントリーのCRCが正常。SHA-256: `1794e4ddfa8abe7c6ffef90991fc925c1a9339162889764a4b54827ebf71efc7`。
- 差し替えたアプリを起動し、画面のpreview.34表示と3体・1ターンのMock実験完了を確認。実アプリが生成した全3入力に本人ID・自己状態・可視他者・可視資源の欄があり、保存メタデータの2条件と `wording_revision=2026-10-14-self-other-identity-v1` も一致した。記録は `outputs/desktop-preview34/native-smoke/2026-10-14_22-00-20_Mock/`、確認結果は `outputs/desktop-preview34/native-smoke-verification.json`。
- 確認後は5ターン・LLM接続モード・通常の保存先へ戻し、起動画面で待機。アプリ実行後の署名検証も成功した。

今回の実アプリの標準配置では可視他者は0件、方向・距離付きの資源関係は合計10件。可視他者を含む入力はUI自動テストで確認した。アプリ確認は無通信のMock実験であり、実モデルでの理解・判断については[先行する8判断の比較記録](2026-10-14-self-other-identity-smoke.md)の範囲まで。常駐8080のモデルサーバーは停止・再起動・設定変更していない。
