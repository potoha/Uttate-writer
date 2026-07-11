# 変換機能のモジュール化

> **履歴資料（現行の実装指示ではない）**
>
> 本書は旧`not-local`ブランチを統合した際のモジュール移行記録です。現行の変更では、
> ソースコードと[`REFACTORING_PLAN.md`](REFACTORING_PLAN.md)を優先し、本書のブランチ前提を
> 新しい設計判断として再利用しないでください。

この branch では `not-local` を統合母体として扱う。変換境界を provider の通信実装から
分離し、UI や Gemini / OpenAI direct API flow を書き換えずに main 由来の local conversion
を導入できる形にする。

## 安定モジュール

- `uttate.input_rules`: すべての変換経路で共有する特殊入力 marker。
- `uttate.conversion.direct`: not-local direct prompt / schema builder。
- `uttate.conversion.response_parser`: provider JSON parser と result validation。
- `uttate.conversion.core`: provider-neutral な request / core adapter 境界。
- `uttate.conversion.local_ai`: main由来のStage 1読み転写 prompt / schema / fidelity validation。

## 互換モジュール

旧 import 位置は wrapper として残す:

- `uttate.providers.direct_conversion`
- `uttate.pipeline.response_parser`
- `uttate.protected_input`

既存 provider / test code は維持しつつ、新規 code は `uttate.conversion` を参照できる。

## main 由来 local conversion の入口

main branch のStage 1読み転写 logic は `uttate.conversion.local_ai` として導入した。

1. `ReadingNormalizer` が main 由来の prompt / schema / fidelity validation を保持する。
2. `ReadingNormalizationProvider` が `ProviderResult` contract へ adapter する。
3. `uttate.providers.local_ai.LocalAIProvider` が LM Studio/OpenAI互換APIへJSON schema requestを送る。
4. Gemini / OpenAI prompt は not-local direct flow + marker protection を維持する。

`local_ai` は自然文候補A/Bではなく、Stage 1の忠実な読み転写を `faithful_reading` 候補として返す。
`lmstudio` は設定互換用の旧名として `local_ai` へ寄せる。ユーザー向けの選択肢には出さない。
OpenAI互換のHTTP通信実装は `local_ai` Provider内のJSON clientとして扱い、単独のProvider選択肢にはしない。


