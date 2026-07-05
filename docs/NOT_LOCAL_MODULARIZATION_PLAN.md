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

## 今回触らないもの

- `src/uttate/providers/openai_compatible.py`
- LM Studio API の送信 payload
- LM Studio の model auto-detect
- main branch の LM Studio 用 Stage 1 fidelity prompt

## 次の候補

1. direct conversion prompt を provider からさらに分離する。
2. Gemini / OpenAI provider だけ prompt builder module を参照する形にする。
3. not-local direct conversion を official / experimental の境界で整理する。
4. その後、main branch の LM Studio 向け core を別 module として導入する。
