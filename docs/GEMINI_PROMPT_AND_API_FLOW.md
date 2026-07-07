# Gemini Prompt and API Flow

この文書は、Uttate Writer が Gemini API へ送っている prompt と request payload、受信後に UI へ表示するまでの流れを確認するための共有メモです。

前処理を含む全体仕様は `docs/API_PREPROCESSING_FLOW.md` が正です。この文書は Gemini に絞った実装参照用です。

## 実装ファイル

- `src/uttate/providers/gemini.py`
- `src/uttate/conversion/direct.py`
- `src/uttate/prompts/api_direct_converter_system.txt`
- `src/uttate/input_rules.py`
- `src/uttate/conversion/response_parser.py`

## 入口

Gemini 変換は `GeminiProvider.convert()` から始まります。

呼び出し側から渡る主な値:

- `raw_text`: UI で入力された変換対象文字列
- `previous_context`: 直前文脈。空の場合は prompt 内で `(なし)` になる
- `candidate_count`: 生成候補数。通常は `2`

空文字の `raw_text` と、0 以下の `candidate_count` は API 送信前に拒否されます。

## prompt 組み立てフロー

`GeminiProvider.convert()` は次の順で prompt を作ります。

1. `prepare_conversion_prompt()` を呼ぶ。
2. `mask_protected_input(raw_text.strip())` で特殊タグを placeholder に置き換える。
3. `protected_masks_prompt(masked.masks)` で placeholder の制約文を作る。
4. 候補数、直前文脈、保護 placeholder、入力本文を user prompt にまとめる。
5. `GeminiProvider._build_payload()` で Gemini REST payload に入れる。

`GeminiProvider.convert()` は `prepare_conversion_prompt()` に system prompt として空文字 `""` を渡しています。そのため、Gemini の user prompt には system prompt 本文を重複させず、Gemini payload の `systemInstruction.parts[].text` 側だけに system prompt を入れます。

## system prompt

Gemini に送る system prompt は `load_system_prompt()` が `src/uttate/prompts/api_direct_converter_system.txt` から読み込みます。

現在の内容:

```text
あなたは Uttate Writer の変換エンジンです。

ユーザーは、スペースなし・タイポあり・英語混じりのローマ字日本語を雑に入力します。
あなたの仕事は、その入力を自然な漢字かな交じり文へ変換することです。

これは創作や要約ではありません。
入力された考えを、できるだけ意味を保ったまま日本語の文にしてください。

制約:
- 入力にない意味を追加しない
- 過度に賢く言い換えない
- 明らかなタイポは文脈から補正してよい
- AI, IME, API, LLM, GPU, NPU などの略語は自然なら保持する
- Uttate, Uttate Writer などの固有名詞は保持する
- 入力に保護placeholderがある場合、そのplaceholderを候補内で必ず一字一句そのまま使う
- placeholderの中身はアプリ側で復元するため、推測・翻訳・変換・分割しない
- preserve_english / katakana_name / hiragana の保護指定はplaceholderとして渡される
- 候補1は忠実に、候補2は少し自然にする
- 判断できない語は uncertain に残す
- JSONのみ返す

出力形式:
{
  "candidates": [
    {"label": "faithful", "text": "..."},
    {"label": "natural", "text": "..."}
  ],
  "uncertain": []
}
```

## user prompt

`prepare_conversion_prompt()` が作る user prompt は次の形です。

```text
候補数: 2

直前の文脈:
(なし)

保護placeholder: (なし)

入力:
AIdenyuuryokuwosaisekkeisuru.
```

特殊タグがある場合、タグの中身は Gemini へ直接送りません。

入力例:

```text
\dedodamu\ to =English= to $tokiori$
```

Gemini に送る user prompt:

```text
候補数: 2

直前の文脈:
(なし)

保護placeholder:
- katakana_name: `__UTTATE_PROTECTED_0__`
- preserve_english: `__UTTATE_PROTECTED_1__`
- hiragana: `__UTTATE_PROTECTED_2__`

保護placeholderの制約:
- placeholder は出力候補内で必ずそのまま使う
- placeholder の中身はアプリ側で復元するため、推測・翻訳・変換しない
- placeholder を分割、削除、言い換え、大文字小文字変更しない

入力:
__UTTATE_PROTECTED_0__ to __UTTATE_PROTECTED_1__ to __UTTATE_PROTECTED_2__
```

アプリ内部の復元表:

```text
__UTTATE_PROTECTED_0__ -> デドダム
__UTTATE_PROTECTED_1__ -> English
__UTTATE_PROTECTED_2__ -> ときおり
```

この復元表は request payload には含めません。

## Gemini API request

Gemini は SDK ではなく `httpx` で REST API に送信します。

URL:

```text
https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
```

`model` に `models/` prefix が付いている場合は、URL 組み立て前に取り除きます。

headers:

```json
{
  "Content-Type": "application/json",
  "x-goog-api-key": "<GEMINI_API_KEY>"
}
```

payload:

```json
{
  "systemInstruction": {
    "parts": [
      {
        "text": "<src/uttate/prompts/api_direct_converter_system.txt の内容>"
      }
    ]
  },
  "contents": [
    {
      "role": "user",
      "parts": [
        {
          "text": "<prepare_conversion_prompt() で作った user prompt>"
        }
      ]
    }
  ],
  "generationConfig": {
    "temperature": 0.2,
    "maxOutputTokens": 1024,
    "responseMimeType": "application/json",
    "responseSchema": {
      "type": "object",
      "properties": {
        "candidates": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "label": {"type": "string"},
              "text": {"type": "string"}
            },
            "required": ["label", "text"]
          }
        },
        "uncertain": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "raw": {"type": "string"},
              "candidates": {"type": "array", "items": {"type": "string"}},
              "reason": {"type": "string"}
            },
            "required": ["raw", "candidates", "reason"]
          }
        }
      },
      "required": ["candidates", "uncertain"]
    }
  }
}
```

## retry と error

送信は最大 3 回試行します。

- timeout: 即 `ProviderError("Gemini timed out after ... seconds.")`
- HTTP 503: 残り試行がある場合だけ `1秒`, `2秒` と待って retry
- その他 HTTP error: `ProviderError("Gemini API returned HTTP ...")`
- 接続失敗: `ProviderError("Could not connect to Gemini API.")`

HTTP error の詳細は最大 300 文字までログ用 message に含めます。API key は message に含めません。

## Gemini response から ProviderResult まで

受信後は次の順で処理します。

1. `_response_json()` で response body を JSON object として読む。
2. `_output_text()` で model 出力文字列を取り出す。
3. `parse_provider_result()` で JSON 文字列を `ProviderResult` に変換する。
4. `restore_masked_provider_result()` で placeholder をアプリ内部の復元表から戻す。
5. `ProviderResult` が conversion queue 経由で UI に表示される。

`_output_text()` は次の順で出力を探します。

1. `response_data["output_text"]`
2. `response_data["candidates"][0]["content"]["parts"][].text` を連結

Gemini の通常レスポンスでは 2 の形を想定しています。`output_text` は proxy や互換 endpoint 用の fallback です。

## 期待する model output

Gemini から取り出す text は、次の JSON 文字列である必要があります。

```json
{
  "candidates": [
    {
      "label": "faithful",
      "text": "__UTTATE_PROTECTED_0__と__UTTATE_PROTECTED_1__と__UTTATE_PROTECTED_2__"
    },
    {
      "label": "natural",
      "text": "__UTTATE_PROTECTED_0__は__UTTATE_PROTECTED_1__と__UTTATE_PROTECTED_2__を使う"
    }
  ],
  "uncertain": []
}
```

復元後に UI へ出る候補:

```text
デドダムとEnglishとときおり
デドダムはEnglishとときおりを使う
```

## 重要な注意

- Gemini へ raw API key を prompt に入れない。
- 特殊タグの中身と復元後文字列は Gemini へ送らない。
- placeholder は Gemini の返答内で壊さず、そのまま戻させる。
- system prompt は `systemInstruction` にだけ入れる。
- user prompt は候補数、直前文脈、保護 placeholder 指示、masked input だけを入れる。
- Gemini が返した JSON は `parse_provider_result()` で検証してから UI に渡す。
- placeholder 復元は Gemini ではなくアプリ側で行う。

## 関連テスト

Gemini prompt / payload flow を変えた場合は、少なくとも次を確認してください。

```powershell
$env:UV_CACHE_DIR='.uv-cache'
$env:UV_PYTHON_INSTALL_DIR='.uv-python'
$env:QT_QPA_PLATFORM='offscreen'
uv run --offline pytest -q tests/test_providers.py
```

全体確認:

```powershell
$env:UV_CACHE_DIR='.uv-cache'
$env:UV_PYTHON_INSTALL_DIR='.uv-python'
$env:QT_QPA_PLATFORM='offscreen'
uv run --offline ruff check .
uv run --offline pytest -q
```
