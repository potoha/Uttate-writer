# Uttate Project

## 0. Project Summary

**Uttate** is an AI-assisted Japanese rough-input editor.

It is not a replacement for existing Japanese IMEs. Instead, it sits above them as a writing tool that allows users to type rough text quickly, using romaji, hiragana, English words, typos, and mixed notation, then converts that rough input into natural Japanese text.

The core idea is:

> Do not stop thinking to press Space and choose conversion candidates.  
> Write roughly first, then convert and review later.

Uttate treats the keyboard as a writing instrument. Its purpose is to reduce friction between thought and text.

---

## 1. Core Concept

Existing Japanese IMEs work like this:

```text
think
→ type romaji
→ convert phrase by phrase with Space
→ choose candidates
→ confirm
→ continue writing
```

This interrupts thought.

Uttate works like this:

```text
think
→ type rough text freely
→ press Enter to commit a thought chunk
→ AI converts the previous chunk in the background
→ user keeps writing the next chunk
→ later review and fix converted chunks
```

The important design principle is:

```text
Input should not be blocked by conversion.
Conversion should happen after input, not during input.
```

---

## 2. Product Name

Working name: **Uttate**

Concept phrase: **With(out) Space**

Meaning:

- without Space key conversion
- with mental space for thinking
- outside the existing IME layer
- a writing space beyond Space-key conversion

Possible copy:

```text
スペースキーで変換しない日本語入力。
思考を止めずに書き、あとから日本語にする。
```

---

## 3. Target User Experience

### 3.1 Input Mode

The user writes rough text in an editor-like window.

Allowed input examples:

```text
koreha nihongo nyuuryoku no mondai de,
ime ga hennkann wo tokidoki hasamu kara shikou ga tomaru
```

```text
keyboard ha bunbougu dakara input no stress wo saishouka shinakereba naranai
```

```text
Uttate ha ime no replacement janakute, kakukoto no friction wo herasu tool
```

The user presses `Enter` to commit the current chunk.

When `Enter` is pressed:

1. The raw chunk is appended to a conversion queue.
2. The user immediately continues writing the next chunk.
3. The previous chunk is converted asynchronously.

The user must not have to wait for conversion before continuing to write.

## Keybindings

Uttate Writer should be operable primarily from the keyboard.
The goal is to let the user write, review, switch candidates, and adopt conversions without moving their hands to the mouse.

The keybinding design should prioritize low cognitive load.
The user should not need to remember that “candidate A is one key and candidate B is another key.” Instead, candidates should be previewed cyclically.

### Input Mode

Input Mode is for rough writing.
The user should not edit carefully here. The purpose is to dump thoughts quickly.

```text
Enter
  Confirm the current rough-input chunk and send it to the conversion queue.
  The user can immediately continue typing the next chunk.

Shift + Enter
  Insert a normal line break without sending the chunk.

Ctrl + R
  Re-convert the current chunk.

Ctrl + K
  Switch to Review Mode.

Esc
  Cancel current input operation or close transient UI.
```

### Review Mode

Review Mode is for checking converted chunks after they have been processed.

Each chunk may have:

```text
- original raw input
- candidate A
- candidate B
- optionally, a manually edited version
```

The current preview should be visually displayed in place, while still allowing the user to return to the original.

```text
Tab
  Cycle to the next preview candidate.

Shift + Tab
  Cycle to the previous preview candidate.

Candidate cycle order:
  candidate A → candidate B → original raw input → candidate A ...

Enter
  Adopt the currently displayed preview candidate.

Ctrl + Enter
  Adopt the currently displayed preview candidate and move to the next unresolved chunk.

E
  Edit the currently displayed candidate in place.
  The cursor should remain at the current position when entering edit mode.

R
  Re-run conversion for the current chunk.

Esc
  Cancel preview changes and return to the previously adopted state.
```

### Optional Power User Shortcuts

These shortcuts may be implemented later, but they should not be required for normal use.

```text
Alt + 1
  Immediately adopt candidate A.

Alt + 2
  Immediately adopt candidate B.

Alt + 0
  Revert to original raw input.

Ctrl + Shift + R
  Re-run the full conversion pipeline for the current chunk.
```

### Design Rationale

`Tab` should not directly adopt candidate A.
Instead, `Tab` should behave as a candidate toggle key.

This keeps the interaction simple:

```text
Tab
  Preview another candidate.

Enter
  Decide.
```

This is more natural than assigning separate adoption keys to each candidate, because the user can compare candidates by repeatedly pressing one key. It also scales better if more than two candidates are added later.

The basic review action should feel like turning pages:

```text
Tab → Tab → Tab
```

and then deciding:

```text
Enter
```

The core interaction is:

```text
write roughly
↓
press Enter to send chunk
↓
continue writing
↓
review later
↓
press Tab to compare candidates
↓
press Enter to adopt
```



---

## 4. MVP Scope

The first MVP should not implement a real OS-level IME.

The MVP is a standalone desktop app with:

1. A rough input editor
2. Enter-based chunk conversion
3. LM Studio / OpenAI-compatible API provider
4. Two-stage conversion pipeline
5. Simple local dictionary lookup
6. Review UI with candidate adoption
7. Export final text to clipboard or `.txt`/`.md`

Do not implement:

- OS-level IME integration
- global text replacement in arbitrary apps
- RAG
- user account system
- cloud sync
- complex plugin marketplace
- full model training pipeline

---

## 5. Technical Direction

### 5.1 Recommended MVP Stack

Use a stack that is easy to prototype quickly.

Recommended initial implementation:

```text
Python + PySide6
```

Reasons:

- fast prototyping
- simple desktop UI
- easy HTTP requests to LM Studio
- easy dictionary and JSON handling
- easy later experimentation with local preprocessing

Possible later production stack:

```text
Tauri + React + Rust backend
```

But do not start there unless required.

### 5.2 LLM Provider

The app should talk to LLMs through a provider abstraction.

Supported providers in MVP:

```text
LM Studio provider
OpenAI-compatible provider
Mock provider for tests
```

Provider interface:

```python
class LLMProvider:
    def complete_json(self, messages: list[dict], schema: dict | None = None) -> dict:
        raise NotImplementedError
```

LM Studio should be treated as an OpenAI-compatible local server.

Default local base URL:

```text
http://localhost:1234/v1
```

Do not hardcode model names.

Use app settings:

```json
{
  "provider": "lmstudio",
  "base_url": "http://localhost:1234/v1",
  "api_key": "lm-studio",
  "model": "local-model-name"
}
```

---

## 6. Conversion Pipeline

The current best pipeline is not direct raw-to-kanji conversion.

The pipeline should be:

```text
Raw mixed input
↓
Stage 1: Reading Normalization by LLM
↓
Hiragana + English mixed reading text
↓
Stage 2: Dictionary Candidate Retrieval
↓
Relevant lexical candidates only
↓
Stage 3: Kanji-Kana Conversion by LLM
↓
Candidate A / Candidate B / uncertainties
↓
Review UI
```

### 6.1 Why this pipeline?

Raw mixed input may contain:

- romaji
- English words
- hiragana
- katakana
- kanji
- typos
- missing vowels
- missing consonants
- key-position typos
- ambiguous particles
- proper nouns containing particle-like strings

Examples:

```text
igarashi
```

This may be:

```text
いがらし
五十嵐
```

It should not be incorrectly segmented as:

```text
い が らし
```

Another example:

```text
kouka
```

Possible outputs:

```text
効果
硬貨
校歌
高架
降下
```

Rules alone cannot reliably disambiguate these cases.

Therefore, the first LLM pass should perform reading normalization, not kanji conversion.

---

## 7. Stage 1: Reading Normalization

### 7.1 Purpose

Convert rough romaji/English/mixed input into readable hiragana + English mixed text.

Do not convert to kanji yet.

Example input:

```text
kouyatteenglishtonihonngoro-majigasojimagiridekakaretterunollmnasidebunsetdukasurunohtotemomuzukasikunai
```

Expected normalized output:

```text
こうやって English と にほんごローマじが ごじまじりで かかれてるのを LLM なしで ぶんせつかするのは とても むずかしくない？
```

The reading normalization does not need to be perfect, but it should recover enough structure for dictionary lookup.

### 7.2 Stage 1 Prompt

Use a strict prompt.

```text
あなたは日本語ラフ入力の読み正規化エンジンです。

入力には、ローマ字、日本語、英単語、タイポ、記号が混ざっています。
入力の意味を変えずに、漢字変換はせず、ひらがなと必要な英語表記を混ぜた読みやすい形に戻してください。

制約:
- 漢字にはしない
- 意味を足さない
- 英単語・略語・固有名詞らしいものは無理に日本語訳しない
- 判断できない語は原形に近く残す
- 句読点は必要最小限で補う
- 出力はJSONのみ

出力形式:
{
  "normalized": "...",
  "segments": [
    {
      "raw": "...",
      "reading": "...",
      "type": "kana|english|name_like|unknown|symbol|particle|verb|noun",
      "confidence": 0.0
    }
  ],
  "uncertain": [
    {
      "raw": "...",
      "reason": "..."
    }
  ]
}
```

### 7.3 Stage 1 Example

Input:

```text
keyboardhabunbougudakara inputnostresswosaishoukashinakerebanaranai
```

Expected JSON:

```json
{
  "normalized": "keyboard は ぶんぼうぐ だから input の stress を さいしょうか しなければならない",
  "segments": [
    {"raw": "keyboard", "reading": "keyboard", "type": "english", "confidence": 0.95},
    {"raw": "ha", "reading": "は", "type": "particle", "confidence": 0.90},
    {"raw": "bunbougu", "reading": "ぶんぼうぐ", "type": "noun", "confidence": 0.90},
    {"raw": "dakara", "reading": "だから", "type": "particle", "confidence": 0.90},
    {"raw": "input", "reading": "input", "type": "english", "confidence": 0.95},
    {"raw": "stress", "reading": "stress", "type": "english", "confidence": 0.95},
    {"raw": "saishouka", "reading": "さいしょうか", "type": "noun", "confidence": 0.88}
  ],
  "uncertain": []
}
```

---

## 8. Stage 2: Dictionary Candidate Retrieval

### 8.1 Purpose

Use the normalized reading text to retrieve only relevant dictionary candidates.

Do not pass the full dictionary to the LLM.

The dictionary is not RAG. It is not used to retrieve knowledge.

The dictionary only supplies possible surface forms for readings.

```text
Dictionary = notation candidates
LLM = context-based selection
```

### 8.2 Dictionary Entry Format

Use JSONL or SQLite.

Recommended internal format:

```json
{
  "reading": "ぶんぼうぐ",
  "surface": "文房具",
  "pos": "noun",
  "priority": 0.8,
  "source": "common"
}
```

Proper noun example:

```json
{
  "reading": "ぎんかのかい",
  "surface": "銀化の会",
  "pos": "proper_noun",
  "priority": 0.98,
  "source": "user"
}
```

English/katakana example:

```json
{
  "reading": "keyboard",
  "surface": "キーボード",
  "pos": "loanword",
  "priority": 0.7,
  "source": "common"
}
```

### 8.3 Candidate Retrieval Rules

Given normalized text and segments:

1. Search exact reading matches.
2. Search long n-gram matches first.
3. Prioritize user dictionary.
4. Prioritize project dictionary.
5. Prioritize recently adopted forms.
6. Limit candidate count.

Candidate limits:

```text
max_terms: 30
max_candidates_per_term: 5
max_total_candidates: 80
```

Candidate output passed to Stage 3:

```json
[
  {
    "reading": "ぶんぼうぐ",
    "candidates": [
      {"surface": "文房具", "priority": 0.8, "source": "common"}
    ]
  },
  {
    "reading": "さいしょうか",
    "candidates": [
      {"surface": "最小化", "priority": 0.9, "source": "common"}
    ]
  }
]
```

---

## 9. Stage 3: Kanji-Kana Conversion

### 9.1 Purpose

Use:

- original raw input
- normalized reading text
- dictionary candidates
- previous accepted context

Then output two candidate Japanese conversions.

### 9.2 Stage 3 Prompt

```text
あなたは日本語入力変換エンジンです。

ローマ字・英語混じりのラフ入力を、自然な漢字かな交じり文に変換してください。

入力には以下が与えられます。
- original_raw: 元の入力
- normalized_reading: ひらがな英語混じりに正規化された読み
- dictionary_candidates: 読みに対応する表記候補
- previous_context: 直前の確定済み文章

制約:
- 入力にない意味を足さない
- 主張を強めすぎない
- dictionary_candidates が文脈に合う場合は優先する
- 候補が不自然なら使わなくてよい
- 英語略語は無理に翻訳しない
- 判断できない固有名詞は無理に漢字化しない
- 候補を2つ出す
- 出力はJSONのみ

出力形式:
{
  "candidate_1": "...",
  "candidate_2": "...",
  "uncertain": [
    {
      "span": "...",
      "candidates": ["..."],
      "reason": "..."
    }
  ]
}
```

### 9.3 Stage 3 Example

Input to Stage 3:

```json
{
  "original_raw": "keyboardhabunbougudakara inputnostresswosaishoukashinakerebanaranai",
  "normalized_reading": "keyboard は ぶんぼうぐ だから input の stress を さいしょうか しなければならない",
  "dictionary_candidates": [
    {"reading": "keyboard", "candidates": [{"surface": "キーボード", "priority": 0.8}]},
    {"reading": "ぶんぼうぐ", "candidates": [{"surface": "文房具", "priority": 0.9}]},
    {"reading": "input", "candidates": [{"surface": "入力", "priority": 0.8}]},
    {"reading": "stress", "candidates": [{"surface": "ストレス", "priority": 0.8}]},
    {"reading": "さいしょうか", "candidates": [{"surface": "最小化", "priority": 0.9}]}
  ],
  "previous_context": ""
}
```

Expected output:

```json
{
  "candidate_1": "キーボードは文房具だから、入力のストレスを最小化しなければならない。",
  "candidate_2": "キーボードは文房具である以上、入力のストレスはできるだけ最小化されるべきだ。",
  "uncertain": []
}
```

Note:

Candidate 1 should be more faithful.  
Candidate 2 may be slightly more natural, but must not add new claims.

---

## 10. Data Model

### 10.1 Chunk

Use a chunk-based document model.

```python
@dataclass
class Chunk:
    id: str
    raw_text: str
    normalized: str | None
    segments: list[dict]
    dictionary_candidates: list[dict]
    candidate_1: str | None
    candidate_2: str | None
    adopted_text: str | None
    uncertain: list[dict]
    status: str
    created_at: float
    updated_at: float
```

Possible statuses:

```text
raw
normalizing
normalized
retrieving_dictionary
converting
ready_for_review
adopted
edited
failed
```

### 10.2 Document

```python
@dataclass
class Document:
    id: str
    title: str
    chunks: list[Chunk]
    created_at: float
    updated_at: float
```

Final export is created by joining `adopted_text` for all adopted chunks.

If a chunk has no adopted text, fall back to candidate_1 or raw_text depending on settings.

---

## 11. UI Design

### 11.1 Main Layout

Use a two-pane layout.

```text
┌──────────────────────────────────────────────┐
│ Uttate                                       │
├───────────────────────┬──────────────────────┤
│ Draft / Chunk List    │ Input / Review Panel │
│                       │                      │
│ 01 adopted            │ [Input Mode]         │
│ 02 ready_for_review   │ rough text editor    │
│ 03 converting         │                      │
│ 04 raw                │                      │
└───────────────────────┴──────────────────────┘
```

### 11.2 Input Mode

Input mode should prioritize speed.

- Large plain text area
- `Enter` commits current chunk
- `Shift+Enter` inserts newline without commit
- conversion runs asynchronously
- status appears beside chunk list

### 11.3 Review Mode

Review mode shows selected chunk.

```text
Raw:
keyboardhabunbougudakara inputnostresswosaishoukashinakerebanaranai

Normalized:
keyboard は ぶんぼうぐ だから input の stress を さいしょうか しなければならない

Candidate A:
キーボードは文房具だから、入力のストレスを最小化しなければならない。

Candidate B:
キーボードは文房具である以上、入力のストレスはできるだけ最小化されるべきだ。

Uncertain:
none
```

Actions:

```text
Adopt A
Adopt B
Edit
Reconvert
Shorten
Smooth connection
Register selected term to dictionary
```

---

## 12. Keyboard-First Operation

The app must be usable without a mouse.

Default shortcuts:

```text
Ctrl+J       Input mode
Ctrl+K       Review mode
Enter        Commit chunk in input mode
Shift+Enter  Insert newline
Tab          toggle 
R            Reconvert
E            Edit current output
S            Shorten
N            Smooth connection with neighboring chunks
D            Add selected term to dictionary
Ctrl+E       Export final text
Ctrl+,       Settings
```

All shortcuts should be configurable later.

---

## 13. Dictionary Design

### 13.1 Dictionary Types

```text
common dictionary
user dictionary
project dictionary
recent adoption dictionary
```

### 13.2 User Dictionary Learning

When the user edits or adopts a term, the app may offer to register it.

Example:

```text
ぎんかのかい → 銀化の会
Uttate → Uttate
haiku koushien → 俳句甲子園
```

Dictionary learning should be explicit in MVP.

Do not auto-register everything.

### 13.3 Dictionary Storage

Use SQLite for MVP.

Table:

```sql
CREATE TABLE lexicon_entries (
    id TEXT PRIMARY KEY,
    reading TEXT NOT NULL,
    surface TEXT NOT NULL,
    pos TEXT,
    priority REAL DEFAULT 0.5,
    source TEXT DEFAULT 'user',
    created_at REAL,
    updated_at REAL,
    usage_count INTEGER DEFAULT 0
);
```

Index:

```sql
CREATE INDEX idx_lexicon_reading ON lexicon_entries(reading);
```

---

## 14. Settings

Config file example:

```json
{
  "provider": {
    "type": "lmstudio",
    "base_url": "http://localhost:1234/v1",
    "api_key": "lm-studio",
    "model": "local-model-name"
  },
  "conversion": {
    "candidate_count": 2,
    "auto_convert_on_enter": true,
    "use_dictionary": true,
    "max_dictionary_terms": 30,
    "max_candidates_per_term": 5
  },
  "review": {
    "auto_adopt_candidate_1": false,
    "show_raw_text": true,
    "show_normalized_text": true,
    "show_uncertainty": true
  }
}
```

---

## 15. Suggested File Structure

```text
Uttate/
  README.md
  project.md
  pyproject.toml
  src/
    Uttate/
      __init__.py
      main.py
      app.py
      config.py
      models.py
      providers/
        __init__.py
        base.py
        lmstudio.py
        openai_compatible.py
        mock.py
      pipeline/
        __init__.py
        normalizer.py
        lexicon.py
        converter.py
        queue.py
      prompts/
        reading_normalizer.txt
        kanji_converter.txt
      ui/
        __init__.py
        main_window.py
        input_panel.py
        review_panel.py
        chunk_list.py
      storage/
        __init__.py
        database.py
        lexicon_store.py
        document_store.py
      tests/
        test_normalizer.py
        test_lexicon.py
        test_pipeline.py
  data/
    sample_lexicon.jsonl
    sample_inputs.jsonl
```

---

## 16. Implementation Tasks for Codex

### Task 1: Create basic PySide6 app

Create a desktop window with:

- input text area
- chunk list
- review panel
- status bar

### Task 2: Implement data models

Create:

- `Chunk`
- `Document`
- status constants

### Task 3: Implement provider abstraction

Create:

- `LLMProvider`
- `LMStudioProvider`
- `MockProvider`

The mock provider should return deterministic JSON for tests.

### Task 4: Implement Stage 1 normalizer

Input: raw text  
Output: normalized JSON

For MVP, use LLM provider.

### Task 5: Implement SQLite lexicon

Create:

- schema
- add entry
- search by reading
- search n-grams from normalized text

### Task 6: Implement Stage 3 converter

Input:

- raw text
- normalized text
- dictionary candidates
- previous context

Output:

- candidate_1
- candidate_2
- uncertain

### Task 7: Implement async conversion queue

When user presses Enter:

1. create chunk
2. append to list
3. enqueue conversion
4. allow continued input
5. update chunk when done

### Task 8: Implement review actions

- adopt candidate A
- adopt candidate B
- edit adopted text
- reconvert
- export final document

### Task 9: Add sample data

Add sample dictionary entries:

```json
{"reading": "ぶんぼうぐ", "surface": "文房具", "pos": "noun", "priority": 0.9, "source": "sample"}
{"reading": "さいしょうか", "surface": "最小化", "pos": "noun", "priority": 0.9, "source": "sample"}
{"reading": "にほんご", "surface": "日本語", "pos": "noun", "priority": 0.9, "source": "sample"}
{"reading": "ろーまじ", "surface": "ローマ字", "pos": "noun", "priority": 0.9, "source": "sample"}
{"reading": "ぶんせつか", "surface": "分節化", "pos": "noun", "priority": 0.9, "source": "sample"}
{"reading": "きーぼーど", "surface": "キーボード", "pos": "noun", "priority": 0.9, "source": "sample"}
{"reading": "すぺーすきー", "surface": "スペースキー", "pos": "noun", "priority": 0.9, "source": "sample"}
{"reading": "はいくこうしえん", "surface": "俳句甲子園", "pos": "proper_noun", "priority": 0.95, "source": "sample"}
{"reading": "ぎんかのかい", "surface": "銀化の会", "pos": "proper_noun", "priority": 0.95, "source": "sample"}
{"reading": "あうとすぺーす", "surface": "Uttate", "pos": "proper_noun", "priority": 0.95, "source": "sample"}
```

---

## 17. Initial Test Inputs

Use these as manual tests.

### Test 1

```text
keyboardhabunbougudakara inputnostresswosaishoukashinakerebanaranai
```

Expected:

```text
キーボードは文房具だから、入力のストレスを最小化しなければならない。
```

### Test 2

```text
Uttateha ime noreplacementjanakute kakukotono frictionwoherasutool
```

Expected:

```text
UttateはIMEの代替ではなく、書くことのフリクションを減らすツールである。
```

### Test 3

```text
haikukoushiennokeikenwo PR nitsunageru
```

Expected:

```text
俳句甲子園の経験をPRにつなげる。
```

### Test 4

```text
kouyatte english to nihonngo ro-maji ga majitteirutokini llm nashi de bunsetsukasurunohamuzukashii
```

Expected:

```text
こうやってEnglishと日本語ローマ字が混じっているときに、LLMなしで分節化するのは難しい。
```

### Test 5

```text
jissai anataha context wo iwakannaku yomeru wakejanai
```

Expected:

```text
実際、あなたはコンテクストを違和感なく読めるわけじゃない。
```

---

## 18. Design Constraints

### 18.1 Do not over-generate

Uttate is not a writing assistant that invents content.

It should convert and lightly normalize what the user already wrote.

Bad behavior:

```text
現代社会における知的生産のインターフェースとして、AIは...
```

when the input only says:

```text
AI de nyuuryoku wo rakuni shitai
```

### 18.2 Preserve user intention

Prefer faithful conversion over beautiful rewriting.

Candidate A:

- faithful
- conservative
- minimal addition

Candidate B:

- more natural
- slightly smoother
- still no new claims

### 18.3 Keep uncertainty visible

Do not hide uncertainty.

If the model is unsure, return uncertainty to the review UI.

Example:

```json
{
  "span": "ginnga",
  "candidates": ["銀化", "銀河"],
  "reason": "固有名詞として複数候補があります"
}
```

---

## 19. Future Direction

### 19.1 Model Strategy

Initial development uses existing small LLMs through LM Studio.

Later options:

```text
small conversion-specific LLM
LoRA / QLoRA tuning
separate Reading Normalizer model
separate Kanji Converter model
NPU-oriented inference
```

Ideal final local runtime:

```text
Convert model:
  small, fast, always running
  raw → hiragana/English → kanji-kana conversion

Review model:
  larger, slower, called on demand
  reconversion, tone control, shortening, smoothing
```

### 19.2 Possible Training Approach

Do not train from scratch at first.

Recommended research path:

```text
1. Use existing models with prompts
2. Build paired data
3. Evaluate small models
4. QLoRA tune 0.5B–3B models
5. Compare model-only vs model + dictionary
6. Only later consider training a specialized seq2seq model
```

Training data can be generated by corrupting normal Japanese text.

Example pair:

```json
{
  "input": "ki-bo-do ha bunbougu dakara nyuuryoku no stress wo saishouka shinakereba naranai",
  "output": "キーボードは文房具だから、入力のストレスを最小化しなければならない。"
}
```

Corruption types:

```text
romaji conversion
missing vowels
missing consonants
keyboard-neighbor typos
mixed English words
mixed hiragana
missing spaces
extra spaces
particle ambiguity
proper nouns
```

---

## 20. Non-Goals

Uttate is not:

- a chatbot
- a full IDE assistant
- a full OS-level IME in MVP
- a RAG knowledge assistant
- a grammar checker only
- a Japanese learning app
- a generic text rewriting app

Uttate is:

```text
A rough-input Japanese writing tool that converts thought chunks into reviewable Japanese text.
```

---

## 21. Development Priority

Build in this order:

1. Basic UI
2. Chunk data model
3. Enter-to-queue conversion
4. Mock provider
5. LM Studio provider
6. Reading normalization prompt
7. Dictionary lookup
8. Kanji conversion prompt
9. Review mode
10. Export
11. User dictionary
12. Keyboard shortcuts
13. Tests
14. Packaging

Do not optimize model performance before the UX loop works.

The first milestone is:

```text
Type rough romaji/English mixed text.
Press Enter.
Continue typing.
Previous chunk is converted in background.
Review candidate A/B.
Adopt one.
Export final Japanese text.
```

