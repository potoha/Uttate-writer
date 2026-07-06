# not-local モジュール化作業メモ

この作業では `not-local` を統合母体にし、外側の UI / 設定 / API provider 体験を保ったまま、
変換 core を段階的に差し替えられる形にする。

## 今回確定した方針

- `not-local` の入力体験は維持する。
- 特殊文字列の保護ルールは従来の not-local ルールを正式採用する。
  - `\text\`: カタカナ強制
  - `=text=`: 英語維持
  - `$text$`: ひらがな強制
- Gemini / OpenAI へ送る prompt は not-local の direct conversion 仕様を維持する。
- Gemini / OpenAI の prompt には特殊文字列の保護結果を入れる。
- LM Studio / OpenAI-compatible API 周りは pending とし、この段階では触らない。

## 今回切り出したモジュール

### `uttate.input_rules`

役割:

- 入力中の特殊文字列ルールを解析する。
- カタカナ強制、英語維持、ひらがな強制を扱う。
- prompt 生成や provider 実装から独立した入力ルール module にする。

主な API:

- `parse_protected_input(raw_text)`
- `protected_terms_prompt(terms)`
- `romaji_to_katakana(text)`
- `romaji_to_hiragana(text)`

互換:

- 既存の `uttate.protected_input` は wrapper として残す。
- 既存 import は壊さない。

### `uttate.conversion.direct`

役割:

- not-local の Gemini / OpenAI direct conversion 用 prompt と JSON schema を管理する。
- `uttate.input_rules` の保護済みテキストと保護指示を prompt に入れる。
- provider の HTTP payload 実装から prompt 組み立てを分離する。

互換:

- 既存の `uttate.providers.direct_conversion` は wrapper として残す。

### `uttate.conversion.response_parser`

役割:

- provider が返した JSON text を `ProviderResult` に変換する。
- markdown fence や前後説明つき JSON を許容しつつ、候補の形は厳密に検証する。

互換:

- 既存の `uttate.pipeline.response_parser` は wrapper として残す。

### `uttate.conversion.core`

役割:

- `ConversionRequest` と `ConversionCore` を定義し、main branch 由来の独自変換 core を受け入れる境界にする。
- 既存 provider は `DirectProviderCore` でこの境界へ adapter できる。
- UI / queue から見る結果 contract は従来どおり `ProviderResult` に揃える。

## 今回触らないもの

- `src/uttate/providers/openai_compatible.py`
- LM Studio API の送信 payload
- LM Studio の model auto-detect
- main branch の LM Studio 用 Stage 1 fidelity prompt

## ここまででできたこと

1. 入力ルールを `uttate.input_rules` に分離した。
2. direct conversion prompt を provider から `uttate.conversion.direct` に分離した。
3. Gemini / OpenAI provider は新しい conversion module を参照する形にした。
4. レスポンス parser を `uttate.conversion.response_parser` に分離した。
5. main branch の独自変換 core を `uttate.conversion.core` の境界から導入できる状態にした。
