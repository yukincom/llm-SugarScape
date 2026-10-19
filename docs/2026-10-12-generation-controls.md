# 生成パラメーターと推論の送信設定

`0.1.0-preview.25` で「LLM / API」に追加。モデルが対応するパラメーターを利用者が選び、接続テスト、実験、表示用の日本語訳に反映する。

| 設定 | 動作 |
| --- | --- |
| Temperatureを送信 / Top-pを送信 | 個別に切替。オフの項目はJSONから省く。入力値は残す |
| 推論：モデルに任せる | 推論の設定を送らず、接続先の既定動作に任せる |
| 推論：オン / オフ | 選んだ送信方式で推論の有効・無効を要求する |
| 推論の強さ | `minimal` / `low` / `medium` / `high` / `xhigh` / `max`。オンの場合に送る |
| 推論の送信方式：OpenAI方式 | オンは `reasoning_effort` に選択した強さ、オフは `none` |
| 推論の送信方式：ローカルのテンプレート方式 | `chat_template_kwargs.enable_thinking` に真偽値。オンの場合は同じ辞書に `reasoning_effort` を加える |
| 出力上限の送信形式 | 上限値を `max_tokens` または `max_completion_tokens` の片方だけで送る |

モデル名から設定を自動変更せず、対応しない指定へのエラーで再試行もしない。使える強さや推論オフへの対応はモデル・サーバーによって異なる。HTTP 400では送信設定の確認を案内する。

従来の既定動作は維持する（Temperature/Top-pを送信、推論はモデルに任せる、上限は `max_tokens`）。設定変更で古い接続テスト結果は無効になる。旧データ・同梱プリセットに送信設定がない場合、プリセット切替時には現在の送信設定を保持する。新たに登録したプリセットには保存された実験の設定を含める。

実験の `manifest.json` / `run.json` に6項目を保存する。翻訳は同じ送信制御を使い、翻訳専用の数値（Temperature 0、Top-p 1、出力上限8192）は従来どおり。翻訳キャッシュにも送信制御を記録する。APIキーは記録しない。

## 接続先の例

OpenAI Chat Completionsでは、`max_completion_tokens` は表示される出力と推論トークンの合計上限。推論の強さの対応範囲はモデルごとに異なり、推論を使う場合にTemperature/Top-pを受け付けないモデルもある。[Chat Completions API](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create) と [モデル別の案内](https://developers.openai.com/api/docs/guides/latest-model) を確認して選択する。

2026-10-12に確認したローカルMLX環境では、サーバー起動時の `chat_template_kwargs` にリクエスト側の指定が上書きされる。モデルのテンプレートが対応していれば、サーバーを再起動せず要求ごとに切り替えられる。確認したQwen3.8テンプレートの推論強さは `low` / `medium` / `xhigh`。サーバー・モデル固有の実装であり、すべてのローカルAPIの共通仕様ではない。

CLIでも `--no-send-temperature` / `--no-send-top-p`、`--reasoning-mode on`、`--reasoning-format openai`、`--reasoning-effort medium`、`--max-tokens-parameter max_completion_tokens` を指定できる。推論方式以外の既存の接続先・モデル指定は共通。

## 検証

実際の要求生成を通す模擬HTTPテストで、省略と送信の独立切替、各推論方式、出力上限の排他指定、接続確認と実験の一致、翻訳、設定保存を検査した。Streamlit AppTestでは無効化した入力値の保持、接続成功表示の無効化、画面移動・プリセット切替後の保持を確認した。

- `python -m unittest discover -s tests -v`：全133件成功。
- 新しいCLI引数を指定した1個体・1ターンのMock実行：正常完了。実LLMとの通信なし。

実LLMへの生成要求と配布アプリの実画面での動作確認は、この変更の自動テストに含めない。
