# 2026-10-09 ブラウザ操作が不要なMacアプリ

## 要求と構成

アプリを開けば専用ウインドウで動くことを配布条件にする。Pythonの別途インストール、起動コマンド、ブラウザ操作を利用者に求めない。

- 画面と実験処理は既存の `app_ui.py` / `main.py` を使用する。実験エンジンと保存形式を新設しない。
- `desktop.py` はmacOSのWebKitを利用するpywebviewでウインドウを作る。Pythonはpy2appのstandaloneビルドに同梱する。
- アプリが画面用の子プロセスを1個だけ起動する。127.0.0.1の空きポートと毎回異なるパスを使用する。8501や8080の既存プロセスを探したり停止したりしない。
- ウインドウを閉じると自分で起動した子だけを終了する。親が突然消えた場合も子が終了する。
- 当初の保存先は `~/Library/Application Support/LLM SugarScape/experiments`。preview.4でユーザー指定により[アプリと同じフォルダ内のoutputs](2026-10-09-desktop-output-location.md)へ変更する。起動ログは従来のApplication Support配下に残す。
- LLMサーバーとモデルは従来どおり別途用意する。

## Pytraの判断

紹介された[Pytra](https://github.com/yaneurao/Pytra)はRustなどへの変換に対応する。ただし[Pythonとの差異](https://github.com/yaneurao/Pytra/blob/main/docs/ja/tutorial/python-differences.md)では `async` / `await` が対象外とされ、[対応モジュール](https://github.com/yaneurao/Pytra/blob/main/docs/ja/spec/spec-pylib-modules.md)にaiohttp・NumPy・Streamlit・Matplotlibはない。

現アプリ全体の自動変換には使わない。将来の候補は状態更新ロジックの移植だが、型と乱数の扱いを整理し、元の結果との比較が必要となる。今回はアプリの起動体験を先に整える。Pytraの実行・インストールはしていない。

ユーザーは検討後「pythonのままでいい」と決定した。既存のQwen実験（`2026-10-09_14-54-55_Qwen3.5-2B-6bit`、84判断・LLMエラー3件）では、記録上の全体時間100.655秒に対し、要求ごとの `latency_ms` の合計が100.523秒（99.87%）。この1回の実験では計算部分だけの移植による速度改善は小さいと判断した。アプリ容量も主にpyarrow・pandas・NumPy・描画ライブラリで、計算部分だけ移してもこれらは残る。

## 開発とビルド

[pywebviewのmacOS配布手順](https://pywebview.flowrl.com/guide/freezing)に従い、[py2app](https://py2app.readthedocs.io/en/latest/tutorial.html)を使用する。

```bash
.venv/bin/python -m pip install -r requirements-desktop.txt
.venv/bin/python desktop.py
.venv/bin/python tools/build_desktop.py
.venv/bin/python tools/build_release.py
```

`-A` は開発用aliasビルドで、別のMacへ渡す配布物には使わない。配布候補は `dist/desktop/LLM SugarScape.app`。preview.4以降は実験出力を `SUGARSCAPE_OUTPUT_DIR`、起動ログ・キャッシュの親を `SUGARSCAPE_DATA_DIR` で指定できる。

## 検証状況

py2app 0.28.10 / pywebview 6.2.1でstandaloneビルドが成功した。実行ファイルはarm64、バンドルに `libpython3.11.dylib` を同梱し、alias設定はfalse。アプリ外を参照するシンボリックリンクはなかった。初回のバンドルサイズは約408MB。Mach-O 227ファイルの読み取りではOS標準以外の絶対パス依存は0件。同梱バイナリの必要OSの最大値に合わせ、現在の候補はmacOS 26.2以降を対象とする。

配布形態でのみ出た不具合として、Streamlitの開発モード自動判定を明示的に無効化し、文字列で読み込まれるuvicorn・anyioのバックエンドと、pandasの拡張から使うcmathを同梱対象に追加した。py2appが同名のliblzmaを重ねてコピーする際の破損は、バンドル内の正常なPillow側ライブラリを使用して修正し、アドホック署名後に `codesign --verify --deep --strict` を必須にした。開発者署名・公証とは区別する。

起動・終了処理の読み取りレビューではP1/P2指摘なし。ユーザーのレビューと起動方法への修正指示を受けて、自動テスト53件が成功した。配布アーカイブの署名確認を追加した後の対象テスト4件も成功した。開発者署名・公証・別のMacでの起動は未確認。

配布アプリ本体で説明用サンプルの盤面・台詞・人口グラフを表示し、Step 2の死亡記号を目視確認した。Mock 3個体・2ターンを完了し、保存先の一覧から読み直せた。ネイティブ保存ダイアログで書き出したCSVは自動保存したファイルとバイト単位で一致した。終了後、専用ポート63403の待受はなくなり、`codesign --verify --deep --strict` も成功した。既存の8080・8501には起動停止操作を行っていない。

この検証は開発用aliasではなくPython同梱のアプリで行った。利用中のMacはmacOS 26.6.1。別のMacでの初回起動、Gatekeeper経由の配布、実LLM接続はこのデスクトップ版では未検証。Electronについても既存のPythonエンジンを残して置き換え可能だが、現時点ではpywebview版として保存する。
