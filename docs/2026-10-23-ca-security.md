# 2026-10-23 CA更新と配布アプリの再構築

## 対象と根拠

[Python Securityの告知](https://discuss.python.org/t/information-for-python-users-regarding-emudhra-emsign-ca-certificate-security-incident/109576)と[certifiのアドバイザリ](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2)に対応する。certifiは影響のないemSignルートとの互換性も考慮した2026.10.19、pipは26.2.2を使用する。uvを同じビルド環境へ入れる場合の下限は0.13.4。今回の構築ではuvを使用しない。

既存の公開preview.37 ZIPを展開し、同梱Pythonで検証した。certifi 2026.7.22のCA束とpy2appの`openssl.ca/cert.pem`の両方に、削除対象の **emSign ECC Root CA - G3** が存在した。アプリの実際の`__boot__.py`が設定するCAパスを適用したPython標準SSL・aiohttpの検証用contextでも、同じルートが信頼されていた。ホスト側certifiを更新するだけでは、この配布物は更新されない。

- 対象ZIP: `LLM-SugarScape-0.1.0-preview.37-Mac-arm64.zip`
- 対象ZIP SHA-256: `d1bf59152cb301a3b8f34f84a03d194ba723153c8e7b4497b4e15a912c620289`
- G3証明書のDER SHA-256: `86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b`
- 旧配布物: Python 3.11.14 / OpenSSL 3.6.2。pip・ensurepip・uvの同梱は検出しなかった。

これは信頼ストアの影響確認であり、攻撃や情報流出があったという判定ではない。既存ZIP・公開タグ・実験記録は書き換えず、新しい配布物を作る。

## セットアップと通信

`tools/bootstrap_environment.py`はPython Securityが公開した固定URLからpip wheelを取得し、公式SHA-256と一致することを確認してから、インデックスを使用せずローカルwheelを導入する。以降の依存解決には更新済みpipを使用する。ホストの古い信頼ストアが混ざらないよう、[pipの公式オプション](https://pip.pypa.io/en/stable/topics/https-certificates/) `--use-deprecated=legacy-certs`で更新済みvendored certifiを使用する。TLS検証は有効なままで、`--trusted-host`・`verify=False`等は使用しない。

```bash
python3.11 tools/bootstrap_environment.py --desktop
```

API接続確認とChat Completionsは共通の`tls_security.tls_context()`を使う。証明書チェーンとホスト名の検証を維持し、検証失敗時に別の信頼設定で再試行しない。HTTPのローカル推論サーバーは従来どおり利用できる。

ソース実行では更新済みcertifiと従来利用可能だったOpenSSLのCAを読み込み、G3だけを除いたcontextを作る。`SSL_CERT_FILE`で指定したCAファイル、`SSL_CERT_DIR`のOpenSSLハッシュ形式のCAディレクトリも利用できる。macOS/Linuxでのコロン区切りの複数ディレクトリ指定に対応する。明示設定にG3が含まれる場合は、設定ファイルを示すエラーとして停止する。CAディレクトリは接続時の遅延読込へ渡さず、起動時に各CAを検査して取り込む。PEM形式を保持し、OpenSSLの`TRUSTED CERTIFICATE`に含まれる信頼用途・拒否属性も保つ。環境変数はプロセス起動前に設定する。

certifiの下限は実行時にも確認する。pip・uvの下限はセットアップ・ビルド時の検査で、配布アプリにはインストーラーを含めない。

## 配布ビルド

ビルドは毎回専用の一時ディレクトリを使う。py2appへ更新済みCAファイルと空のCAディレクトリを明示し、生成後にも同梱OpenSSL用CAを置き換える。バージョン別の出力先・既存ZIPを上書きしない。

`tools/verify_desktop.py`は以下を照合する。

- 実際の`__boot__.py`のCA設定とその呼出し、余分なCAファイルがないこと。
- 同梱certifiとOpenSSL用CAの内容が構築元の更新済みCAと一致すること。
- standalone設定、外部へのシンボリックリンクがないこと、製品ソース・素材のSHA-256。
- 同梱Pythonで標準SSL・aiohttp・APIの実際のcontextを起動し、G3不在・ホスト名検証・証明書検証を確認すること。
- pip・ensurepip・uvが実行環境に存在しないこと。

アドホック署名を検証したアプリからZIP・SHA-256・検証JSONを生成する。配布用開発者署名・公証は従来どおり未実施。

## 検証

CA更新時点で全232テスト成功。通常HTTPS成功、未知CAとホスト名不一致の拒否、独自CAファイル・単一/複数ハッシュ形式ディレクトリでのHTTPS成功、通常ローカルHTTP成功、G3がCAディレクトリにある場合の拒否、明示的なserverAuth拒否の維持、ブートストラップの不一致ハッシュ拒否を確認した。

preview.38のstandaloneアプリをクリーンビルドし、署名検証・製品ソース照合・同梱Python/標準SSL/aiohttp/API contextのG3不在検証が成功した。この時点の確認はTLS・配布構造の中間チェックポイントで、Rust移行後の通常機能検証と最終配布物の照合は別途実施する。
