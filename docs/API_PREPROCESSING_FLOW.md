# API Preprocessing Flow

この文書は、Uttate Writer が入力文字列をどのように前処理し、Local AI / 外部APIへ何を送り、戻ってきた結果をどう表示するかを共有するためのものです。

改善で送信内容、前処理、prompt、復元、表示が変わった場合は、この文書も同じ変更の中で更新してください。

## 全体像

Uttate の変換は、UI の入力欄から `ConversionQueue` を通って Provider に渡されます。Provider は大きく2種類あります。

- Local AI: `src/uttate/providers/local_ai.py` から LM Studio 互換APIへ送信
- 外部API: `src/uttate/providers/gemini.py` / `src/uttate/providers/openai.py` から Gemini / OpenAI へ送信

どちらも、特殊タグはAPIへ直接送らず、placeholderへマスクします。

例:

```text
\dedodamu\ ha =English= to $tokiori$
```

APIへ送る前:

```text
__UTTATE_PROTECTED_0__ ha __UTTATE_PROTECTED_1__ to __UTTATE_PROTECTED_2__
```

復元表:

```text
__UTTATE_PROTECTED_0__ -> デドダム
__UTTATE_PROTECTED_1__ -> English
__UTTATE_PROTECTED_2__ -> ときおり
```

復元表そのものはアプリ内部で保持します。タグ内の元文字列や変換後文字列は API payload へ含めません。

## 特殊タグの前処理

実装場所:

- `src/uttate/input_rules.py`
- `mask_protected_input(raw_text)`
- `MaskedProtectedInput.restore(text)`

対応タグ:

- `\dedodamu\`: カタカナ化して復元する
- `=English=`: 英語表記のまま復元する
- `$tokiori$`: ひらがな化して復元する
- `\\`, `==`, `$$`: タグではなくリテラル記号として扱う

処理の考え方:

1. 入力文字列から特殊タグを探す。
2. タグ内の文字列をアプリ側で機械変換する。
3. APIに渡す文字列では `__UTTATE_PROTECTED_N__` へ置き換える。
4. APIから戻った候補内のplaceholderを、アプリ側で復元する。

## Local AI Flow

Local AI は、LLM に rough input 全文の reading を生成させません。Stage 1 は `MechanicalReadingNormalizer` による deterministic な読み正規化を primary path とし、LLM は曖昧な候補選択と Stage 2 の漢字かな交じり候補生成だけに使います。

主な実装場所:

- `src/uttate/providers/local_ai.py`
- `src/uttate/conversion/local_ai.py`
- `src/uttate/prompts/reading_normalizer.txt`

処理順:

1. UI入力が `LocalAIProvider.convert()` に渡る。
2. `ReadingNormalizer` が `_prepare_local_ai_input(raw_text)` を呼ぶ。
3. `_prepare_local_ai_input()` が特殊タグをplaceholderへマスクする。
4. Stage 1: `MechanicalReadingNormalizer` が masked text を完全被覆する `segment_plan` / `segments` を作り、読めるローマ字をかなへ変換する。
5. Stage 1 では `mechanical_strict` / `mechanical_typo_tolerant` は補助情報ではなく primary path の一部として扱う。高信頼で読める語は正規化し、低信頼の語は raw を保持して `suspicious_spans` に記録する。
6. Stage 1.5: `ambiguous_spans` がある場合だけ、LM Studio互換APIへ候補選択 payload を送る。LLM は全文を書き換えず、提示された候補から選ぶだけ。
7. Stage 2: Stage 1 / 1.5 の `mechanical_normalized` または `resolved_normalized` を、かな・英語混じり入力として LM Studio互換APIへ送る。Stage 2 は読み転写ではなく、明らかな名詞・動詞語幹・形容詞語幹・サ変名詞・複合語・技術用語を積極的に漢字化する漢字変換段階。
8. Stage 2 の返答JSONを `ProviderResult` に変換し、placeholderを復元する。
9. Stage 2 が失敗、invalid JSON、placeholder欠落、空候補などになった場合でも provider error だけにせず、`mechanical_normalized` を `mechanical_normalized` 候補として表示する。

Stage 1 の内部結果例:

入力:

```text
nihonngo | henkan | =tool= | koreha | bennrina | \siromono\ | dane.
```

masked:

```text
nihonngo | henkan | __UTTATE_PROTECTED_0__ | koreha | bennrina | __UTTATE_PROTECTED_1__ | dane.
```

Stage 1 result:

```json
{
  "original_raw": "nihonngo | henkan | __UTTATE_PROTECTED_0__ | koreha | bennrina | __UTTATE_PROTECTED_1__ | dane.",
  "mechanical_normalized": "にほんご | へんかん | __UTTATE_PROTECTED_0__ | これは | べんりな | __UTTATE_PROTECTED_1__ | だね.",
  "segments": [
    {
      "id": 0,
      "raw": "nihonngo",
      "reading": "にほんご",
      "kind": "text",
      "type": "japanese_romaji",
      "confidence": 0.95
    }
  ],
  "ambiguous_spans": [],
  "suspicious_spans": []
}
```

Stage 1 validation:

- `segments.raw` を連結すると `original_raw` と完全一致する。
- `segments.reading` を連結すると `mechanical_normalized` と完全一致する。
- placeholder / boundary segment の `reading` は `raw` と完全一致する。
- confidence は 0 以上 1 以下。
- `ambiguous_spans` / `suspicious_spans` は存在する segment id のみ参照する。

Stage 1.5 に送る payload 例:

```json
{
  "task": "resolve_ambiguous_readings_only",
  "mechanical_normalized": "これは | to | input | する",
  "ambiguous_spans": [
    {
      "id": 1,
      "raw": "to",
      "current_reading": "と",
      "candidates": [
        {"reading": "と", "type": "japanese_particle", "reason": "Japanese particle candidate"},
        {"reading": "to", "type": "english", "reason": "English word candidate"}
      ]
    }
  ],
  "rules": {
    "choose_only_from_candidates": true,
    "do_not_rewrite_full_text": true,
    "do_not_add_text": true,
    "preserve_placeholders": true
  }
}
```

Stage 1.5 では、unknown id、候補にない reading、不正 confidence、JSON parse 失敗、placeholder / boundary 変更をすべて無視します。invalid response はエラーにせず、Stage 1 の `mechanical_normalized` で続行します。

Stage 2 に送る payload 例:

```json
{
  "task": "aggressive_kanji_conversion_from_normalized_reading",
  "conversion_stage": "stage2_kanji_conversion",
  "input_text": "にほんご | へんかん | __UTTATE_PROTECTED_0__ | これは | べんりな | __UTTATE_PROTECTED_1__ | だね.",
  "normalized_input": "にほんご | へんかん | __UTTATE_PROTECTED_0__ | これは | べんりな | __UTTATE_PROTECTED_1__ | だね.",
  "candidate_count": 2,
  "labels": ["faithful", "natural"],
  "kanji_conversion_policy": {
    "convert_common_nouns": true,
    "convert_verb_stems": true,
    "convert_adjective_stems": true,
    "convert_sahen_nouns": true,
    "convert_compound_words": true,
    "convert_technical_terms": true,
    "preserve_particles_in_hiragana": true,
    "preserve_auxiliaries_in_hiragana": true,
    "preserve_okurigana": true,
    "preserve_english": true,
    "preserve_placeholders": true,
    "avoid_unnecessary_hiragana": true,
    "do_not_add_meaning": true,
    "keep_casual_style": true
  },
  "protected_placeholders": [
    {
      "placeholder": "__UTTATE_PROTECTED_0__",
      "kind": "preserve_english",
      "instruction": "Copy this placeholder exactly. It will be restored after validation."
    }
  ]
}
```

Stage 2 から期待する返答:

```json
{
  "candidates": [
    {
      "label": "faithful",
      "text": "日本語変換__UTTATE_PROTECTED_0__、これは便利な__UTTATE_PROTECTED_1__だね。"
    },
    {
      "label": "natural",
      "text": "日本語変換ツール、これは便利な__UTTATE_PROTECTED_1__だね。"
    }
  ],
  "uncertain": []
}
```

Stage 2 では、placeholder と英語表記を保持しつつ、日本語部分は標準的な漢字かな英語交じり文へ変換します。助詞、助動詞、送り仮名、文末表現はひらがなでよく、入力にない意味、主語、目的語、説明は足しません。候補テキストが空でないこと、markdown fence や前置きがあっても JSON object を抽出できること、placeholder を壊していないことを確認します。復元後のUIにはplaceholderではなく、アプリ内部の復元結果が表示されます。

Stage 2 の実行有無と fallback 理由は debug log で確認できます。

```text
[local-ai] stage1 mechanical normalized: ...
[local-ai] stage1 ambiguous count: ...
[local-ai] stage2 request input: ...
[local-ai] stage2 raw response: ...
[local-ai] stage2 parsed candidates count: ...
[local-ai] stage2 fallback used: true/false
```

## 外部API Flow

外部APIは Gemini / OpenAI 共通の direct conversion flow です。Local AI と違い、自然な漢字かな交じり文の候補を返します。

主な実装場所:

- `src/uttate/conversion/direct.py`
- `src/uttate/providers/gemini.py`
- `src/uttate/providers/openai.py`
- `src/uttate/prompts/api_direct_converter_system.txt`
- `src/uttate/conversion/response_parser.py`

処理順:

1. UI入力が `GeminiProvider.convert()` または `OpenAIProvider.convert()` に渡る。
2. `prepare_conversion_prompt()` が特殊タグをplaceholderへマスクする。
3. APIへ送るpromptを組み立てる。
4. Gemini / OpenAI へ送信する。
5. 返答JSONを `parse_provider_result()` で `ProviderResult` に変換する。
6. `restore_masked_provider_result()` が候補文と uncertain 内のplaceholderを復元する。
7. UIには candidate として表示される。

外部APIへ渡すprompt例:

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
__UTTATE_PROTECTED_0__ ha __UTTATE_PROTECTED_1__ to __UTTATE_PROTECTED_2__
```

Gemini payload:

- URL: `/v1beta/models/{model}:generateContent`
- system prompt: `systemInstruction.parts[].text`
- user prompt: `contents[].parts[].text`
- JSON schema: `generationConfig.responseSchema`
- JSON only: `generationConfig.responseMimeType = application/json`

OpenAI payload:

- URL: `/v1/responses`
- system prompt: `instructions`
- user prompt: `input`
- JSON schema: `text.format.schema`

外部APIから期待する返答:

```json
{
  "candidates": [
    {
      "label": "faithful",
      "text": "__UTTATE_PROTECTED_0__は__UTTATE_PROTECTED_1__と__UTTATE_PROTECTED_2__を使う"
    },
    {
      "label": "natural",
      "text": "__UTTATE_PROTECTED_0__は__UTTATE_PROTECTED_1__と__UTTATE_PROTECTED_2__を使います"
    }
  ],
  "uncertain": []
}
```

受信後:

- markdown fence や前置きがあっても、最初のJSON objectを抽出する。
- `candidates` が空なら provider error とする。
- 各 candidate の `text` が空なら provider error とする。
- candidate と uncertain のplaceholderを復元する。

表示:

```text
デドダムはEnglishとときおりを使う
デドダムはEnglishとときおりを使います
```

## UI表示まで

共通の表示経路:

1. Provider が `ProviderResult` を返す。
2. `ConversionQueue` が対象 chunk を更新する。
3. `ChunkListWidget` に候補が表示される。
4. 選択中 chunk は `ReviewPanel` に raw / candidate / uncertain / error として表示される。
5. ユーザーが採用すると、採用候補が clipboard にコピーされる。

この時点で、特殊タグ placeholder は表示されない想定です。表示に placeholder が残る場合は、Providerの復元処理またはモデル返答がplaceholderを壊していないかを確認してください。

## 改善時の更新ポイント

前処理やAPI送信仕様を変える場合は、次を同時に更新してください。

- この文書
- `README.md` のユーザー向け説明
- `src/uttate/prompts/*.txt` のモデル向け指示
- 関連テスト
  - `tests/test_protected_input.py`
  - `tests/test_local_ai_preprocessing.py`
  - `tests/test_local_ai_conversion.py`
  - `tests/test_providers.py`

確認コマンド:

```powershell
$env:UV_CACHE_DIR='.uv-cache'
$env:UV_PYTHON_INSTALL_DIR='.uv-python'
$env:QT_QPA_PLATFORM='offscreen'
uv run --offline ruff check .
uv run --offline pytest -q
```
