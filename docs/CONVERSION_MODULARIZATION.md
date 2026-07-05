# 変換機能のモジュール化

この branch では `not-local` を統合母体として扱う。変換境界を provider の通信実装から
分離し、UI や Gemini / OpenAI direct API flow を書き換えずに main 由来の local conversion
を導入できる形にする。

## 安定モジュール

- `uttate.input_rules`: すべての変換経路で共有する特殊入力 marker。
- `uttate.conversion.direct`: not-local direct prompt / schema builder。
- `uttate.conversion.response_parser`: provider JSON parser と result validation。
- `uttate.conversion.core`: provider-neutral な request / core adapter 境界。

## 互換モジュール

旧 import 位置は wrapper として残す:

- `uttate.providers.direct_conversion`
- `uttate.pipeline.response_parser`
- `uttate.protected_input`

既存 provider / test code は維持しつつ、新規 code は `uttate.conversion` を参照できる。

## main 由来 local conversion の入口

main branch の変換 logic は `uttate.conversion.core` の内側に導入する:

1. `ConversionRequest` を受け取る。
2. 既存 contract の `ProviderResult` を返す。
3. 入力 marker は `uttate.input_rules` で扱う。
4. Gemini / OpenAI prompt は not-local direct flow + marker protection を維持する。

LM Studio / OpenAI-compatible transport は、この段階では意図的に変更しない。message payload
の仕様は local API policy が確定するまで pending とする。
