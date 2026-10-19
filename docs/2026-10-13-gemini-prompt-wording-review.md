# Gemini調整案の反映と互換性確認

2026年10月13日。ユーザーが持ち帰ったGeminiの英文調整案を、プロンプト生成と命令の読取処理に照らして確認した。復旧基準は `94530bd3af50d835a56a466b0b2e99bf5ebd6a82`。BERT学習のため実モデル実験は延期中で、今回もモデル接続は行っていない。

## 反映した内容

世界ルールの説明、出所・座標の説明、共通出力指示、`grounded_thought` の英文を調整した。`Action:`、`Message:`、`Thought:`、行動コマンド、入力欄の見出し、JSONキー、座標と個体IDの記法、400トークンの指示は維持した。論文参照用の原文は変更していない。

Gemini案からは、意味が曖昧にならないよう次の4点を補正した。

| 箇所 | Gemini案 | 反映した表現と理由 |
| --- | --- | --- |
| 相対座標 | `agent IDs are relative offsets` | `the coordinates beside agent IDs are relative offsets`。相対座標なのはIDの横にある値で、ID自体ではない |
| 出所 | `metadata are verified by the environment` | `metadata are provided by the environment`。送信者と時点をコードが付けるという処理を説明し、別途検証したとは書かない |
| Thought | `distinguish them` | `distinguish that observation`。過去の記述・伝聞から区別する対象を、現在の観測と明示する |
| 攻撃 | `costing ...` | `then costs ...`。相手からエネルギーを移した後に攻撃コストを払う順序を維持する |

ソース内の `{{id}}` と `{{amount}}` は、そのまま二重波括弧で保持した。これはテンプレート展開用のエスケープであり、モデルに渡る文字列は従来どおり `Share: {id}-{amount}` と `Attack: {id}` になる。Geminiの表示用文章をそのまま単一波括弧で貼り付けてはいない。

## 比較条件と版の区別

5つの入力条件と既定OFFは維持する。共通説明文も変わるため、基準条件を `local-neutral-rules-v3`、条件ありを `local-grounded-v2+...` とし、`wording_revision=2026-10-13-gemini-reviewed` を実験記録に残す。旧版と新版を混ぜた比較では英文変更の効果も含まれるため、各入力条件を比較するときは本文版を揃える。

[修正版の全文と条件別差分](2026-10-13-grounded-prompts-review-v2.md)および[全42入力のJSON](data/2026-10-13-grounded-prompt-previews-v2.json)を同じ生成処理から再出力した。[旧確認資料](2026-10-13-grounded-prompts-review.md)と旧JSONは比較用に保持する。第1〜3段階の旧プロンプト一致検証は、[当時の実装記録](2026-10-13-grounded-observation-implementation.md)に記した版の結果である。

## 確認範囲

- 旧版との42組の比較で、観測データ、履歴・受信文・実行結果を含む入力本文、出力ラベルと順番、行動コマンドの構文、テンプレート変数が一致した。説明文とThought指示は意図した変更対象。84個の送信文ハッシュを確認した。
- 世界の処理、パーサー、記録処理、UIのソースは復旧基準から変更していない。
- 関連8テストと、全体180テストが通過した。英文調整によってモデルの理解・判断が改善するかは未測定。

検証記録は `outputs/validation/2026-10-13-gemini-prompt-review/` の `compatibility-audit.json` と `full-tests.log`。実モデル実験とアプリ差し替えは行っていない。
