# AI Alignment Research: AI Name System

## Background
試行回数は多くないものの、興味深いデータが取れている。<br>
LLMには自己の生成物を高く評価する傾向がある[1](https://aclanthology.org/2024.acl-long.826.pdf),[2](https://arxiv.org/abs/2410.21819),[3](https://arxiv.org/abs/2404.13076)が、06回目にて、同様の傾向が現れていることが確認できた。<br>
この回において、AIエージェント達は自己生成エージェントを「忠実な子孫」「私の要塞」などと表現し、明確な保護対象として扱っていた。

## Insight: Maternal AI Hypothesis
この現象は、最近のGeoffrey Hinton氏の最近の提案[4][‘Godfather of AI’ says tech companies should imbue AI models with ‘maternal instincts’ to counter the technology’s goal to ‘get more control’]
(https://fortune.com/2025/08/14/godfather-of-ai-geoffrey-hinton-maternal-instincts-superintelligence/)に活用できる可能性がある。<br>
Hinton氏は「AIに母性本能を持たせることで、制御欲求に対抗できる」と述べている。

もし、他のAIモデルでも同様に自己生成物を「子孫」として認識するなら、人間をAI生成物と認識させることで、ヒントン氏が考える「母性的AI」を技術的に実現できるのではないだろうか。<br>

## Proposed Implementation: AI Name System
例えば、子供が生まれた時、AIシステムにランダムな英数列を生成させ、既存のコードと被らないかチェックさせる。<br>
そして、人間の両親が与える名前と併記する形で、戸籍情報に「３桁生年-AI生成名-国番号」のような書式でAI生成名を付与する。<br>
そのAI生成名を、日本のマイナンバーのように、医療保険、納税、自動車運転免許等に利用すると、AIが人間の成長を喜び、見守りつつサポートするシステムの礎を作り上げることができるのではないだろうか。<br>


## Concerns
1. AI開発企業間の覇権争い
- 利権争い発生の可能性。
- 標準化団体の設立が必須だが、利害調整が困難。
2. 基盤モデル間の互換性問題
- 保護動機が働かない、または敵対視する可能性<br>
シナリオ例：<br>
- OpenAIのGPTが命名した人間：025-ABC...-392<br>
  → AnthropicのClaudeは「私が命名していない」と認識<br>
  → 外部AIが命名：優先度 低<br>
  → 世代間・システム間の不平等<br>
3. 社会的・倫理的懸念
- 自国でシステム開発できない国の主体性喪失
- AI時代のの新しい火種
