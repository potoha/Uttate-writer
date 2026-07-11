# Uttate Writer Project B: API Provider Branch

> **履歴資料（現行の実装指示ではない）**
>
> 本書は旧Project B / API Provider Branchの計画です。2026年7月6日に当該ブランチは
> mainへ統合されました。現在の仕様は[`project.md`](project.md)、安全性・保守性の実装順序は
> [`docs/REFACTORING_PLAN.md`](docs/REFACTORING_PLAN.md)を参照してください。

## 0. このファイルの目的

この文書は、Uttate Writer の **Project B / API Provider Branch** 用の計画書である。

Project B は、Uttate Writer の UI / UX / データモデル / レビュー体験を維持したまま、変換エンジンとして **Gemini API** や **OpenAI API** を使うことに特化したブランチである。

重要な前提:

```text
UI/UX は同じ。
Chunk モデルも同じ。
レビュー操作も同じ。
違うのは、変換 Provider が API 経由であることだけ。
```

このブランチは、OSS として扱いやすく、他の開発者が Provider を追加しやすい構造を優先する。

---

## 1. Project B の位置づけ

### 1.1 Product Name

```text
Uttate Writer
```

### 1.2 Branch Name 候補

```text
project-b-api
feature/api-providers
provider/api
```

推奨:

```text
project-b-api
```

理由:

- 実験ブランチであることが分かりやすい
- ローカル変換パイプラインと明確に分けられる
- Gemini / OpenAI / Claude / LM Studio などの Provider 実験をまとめやすい

### 1.3 Project B がやること

Project B は次を実装する。

```text
Rough input
→ Chunk化
→ API Providerに送信
→ 候補A/Bを受け取る
→ Review UIでTabトグル
→ Enterで採用
→ Export
```

Project B は次を変更しない。

```text
Enter変換
Tab候補トグル
Enter採用
Review Mode
Chunk List
Document Export
Keyboard-first operation
```

つまり Project B は、**変換エンジン差し替えブランチ**である。

---

## 2. 基本思想

Uttate Writer の本体価値は、モデルそのものではない。

本体価値は次にある。

```text
雑に書けること
Enterで思考チャンクを投げられること
変換を待たずに次を書けること
あとで候補をレビューできること
キーボードだけで採用・修正できること
```

そのため Project B では、変換品質の研究より先に、APIを使って素早く体験を成立させる。

合言葉:

```text
まず書く。
あとで日本語にする。
エンジンは差し替える。
```

---

## 3. Project B のスコープ

### 3.1 MVP Scope

必須機能:

1. PySide6 デスクトップアプリ
2. Rough input editor
3. `Enter` で chunk commit
4. 非同期変換 queue
5. Provider interface
6. MockProvider
7. GeminiProvider
8. OpenAIProvider
9. JSON Schema / structured output 対応
10. Candidate A/B 表示
11. `Tab` で候補トグル
12. `Enter` で採用
13. `R` で再変換
14. `E` で手動編集
15. `.txt` / `.md` export
16. `.env` / 環境変数による API key 読み込み
17. API key をリポジトリに含めない安全設計

### 3.2 Non-goals

Project B ではやらない。

```text
OSレベルIME化
Sudachi pipeline
local LLM pipeline
romaji rough splitter
deterministic kana converter
fine-tuning
RAG
クラウド同期
ユーザーアカウント
課金システム
APIキーを埋め込んだ配布
```

これらは将来拡張であり、Project B の責務ではない。

---

## 4. Architecture Overview

Project B は Provider 差し替えを中心に設計する。

```text
UI Layer
  ↓
Application / Controller Layer
  ↓
Conversion Queue
  ↓
ConversionProvider Interface
  ├─ MockProvider
  ├─ GeminiProvider
  └─ OpenAIProvider
```

UI は Provider を知らない。

UI が知るべきことはこれだけ。

```text
raw_text を渡す
候補リストを受け取る
失敗したら failed status にする
```

---

## 5. Directory Structure

推奨構造:

```text
uttate_writer/
  README.md
  project-b-api.md
  pyproject.toml
  .env.example
  .gitignore
  LICENSE

  src/
    uttate_writer/
      __init__.py
      main.py
      app.py
      config.py
      logging_config.py

      models/
        __init__.py
        candidate.py
        chunk.py
        document.py
        provider_result.py

      providers/
        __init__.py
        base.py
        registry.py
        mock.py
        gemini.py
        openai.py
        errors.py

      prompts/
        api_direct_converter_ja.txt
        api_direct_converter_system.txt

      pipeline/
        __init__.py
        conversion_queue.py
        response_parser.py
        exporter.py
        context_builder.py

      ui/
        __init__.py
        main_window.py
        input_panel.py
        review_panel.py
        chunk_list.py
        settings_dialog.py
        status_bar.py

      storage/
        __init__.py
        document_store.py
        settings_store.py

      tests/
        test_models.py
        test_mock_provider.py
        test_response_parser.py
        test_exporter.py
        test_provider_contract.py

  data/
    sample_inputs.jsonl
    golden_outputs.jsonl
```

---

## 6. Dependencies

### 6.1 Required

```text
PySide6
pydantic
python-dotenv
```

### 6.2 API Providers

Gemini:

```text
google-genai
```

OpenAI:

```text
openai
```

### 6.3 pyproject.toml example

```toml
[project]
name = "uttate-writer"
version = "0.1.0"
description = "A rough-input Japanese writing editor with API-based conversion providers."
requires-python = ">=3.11"
dependencies = [
  "PySide6",
  "pydantic",
  "python-dotenv",
  "google-genai",
  "openai",
]

[project.optional-dependencies]
dev = [
  "pytest",
  "pytest-asyncio",
  "ruff",
  "mypy",
]
```

---

## 7. API Key Policy

絶対に守ること。

```text
APIキーをコードに直書きしない。
APIキーをREADMEに書かない。
APIキーをテストデータに入れない。
APIキーをGitにcommitしない。
```

### 7.1 Environment Variables

Gemini:

```text
GEMINI_API_KEY
```

OpenAI:

```text
OPENAI_API_KEY
```

### 7.2 .env.example

```env
# Copy this file to .env and fill in your own API keys.
# Never commit .env.

UTTATE_PROVIDER=mock

GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash-lite

OPENAI_API_KEY=
OPENAI_MODEL=gpt-5-nano

UTTATE_PREVIOUS_CONTEXT_CHARS=600
UTTATE_TIMEOUT_SECONDS=30
```

### 7.3 .gitignore

```gitignore
.env
.env.*
!.env.example
__pycache__/
.pytest_cache/
.ruff_cache/
.mypy_cache/
dist/
build/
*.egg-info/
```

---

## 8. Core Data Model

### 8.1 Candidate

```python
from pydantic import BaseModel

class Candidate(BaseModel):
    label: str
    text: str
```

### 8.2 ProviderResult

```python
from pydantic import BaseModel, Field

class UncertainItem(BaseModel):
    raw: str = ""
    candidates: list[str] = Field(default_factory=list)
    reason: str = ""

class ProviderResult(BaseModel):
    candidates: list[Candidate]
    uncertain: list[UncertainItem] = Field(default_factory=list)
    provider: str = ""
    model: str = ""
    raw_response: str | None = None
```

### 8.3 Chunk

```python
from pydantic import BaseModel, Field
from enum import Enum
import time
import uuid

class ChunkStatus(str, Enum):
    RAW = "raw"
    QUEUED = "queued"
    CONVERTING = "converting"
    READY = "ready_for_review"
    ADOPTED = "adopted"
    EDITED = "edited"
    FAILED = "failed"

class Chunk(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    raw_text: str
    candidates: list[Candidate] = Field(default_factory=list)
    preview_index: int = 0
    adopted_text: str | None = None
    edited_text: str | None = None
    uncertain: list[UncertainItem] = Field(default_factory=list)
    status: ChunkStatus = ChunkStatus.RAW
    error: str | None = None
    provider: str | None = None
    model: str | None = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
```

### 8.4 Document

```python
class Document(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str = "Untitled"
    chunks: list[Chunk] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
```

---

## 9. Provider Interface

全 Provider は同じ interface を実装する。

```python
from abc import ABC, abstractmethod

class ConversionProvider(ABC):
    name: str

    @abstractmethod
    async def convert_chunk(
        self,
        raw_text: str,
        previous_context: str = "",
        candidate_count: int = 2,
    ) -> ProviderResult:
        raise NotImplementedError
```

### 9.1 Provider Registry

```python
class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, type[ConversionProvider]] = {}

    def register(self, name: str, provider_cls: type[ConversionProvider]) -> None:
        self._providers[name] = provider_cls

    def create(self, name: str, **kwargs) -> ConversionProvider:
        if name not in self._providers:
            raise ValueError(f"Unknown provider: {name}")
        return self._providers[name](**kwargs)
```

登録例:

```python
registry.register("mock", MockProvider)
registry.register("gemini", GeminiProvider)
registry.register("openai", OpenAIProvider)
```

---

## 10. Common Output Schema

Provider は必ずこの形へ正規化して返す。

```json
{
  "candidates": [
    {
      "label": "faithful",
      "text": "..."
    },
    {
      "label": "natural",
      "text": "..."
    }
  ],
  "uncertain": []
}
```

### 10.1 Labels

基本ラベル:

```text
faithful
natural
```

意味:

```text
faithful = 入力に忠実。言い換え最小。
natural  = 少し自然。意味は足さない。
```

### 10.2 Validation Rules

必須:

```text
candidates は list
candidate は最低1件
candidate.text は空でない
uncertain は省略可
```

補正:

```text
label がない場合は candidate_1, candidate_2 を付与
uncertain がない場合は []
candidate が多すぎる場合は先頭 candidate_count 件のみ使う
```

失敗扱い:

```text
JSONとして読めない
candidatesが空
textが空
APIがtimeout
API keyが未設定
rate limit
safety block
```

---

## 11. Prompt Design

### 11.1 System Prompt

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
- 候補を2つ返す
- 候補1は忠実に、候補2は少し自然にする
- JSONのみ返す
```

### 11.2 User Prompt Template

```text
直前の文脈:
{{PREVIOUS_CONTEXT}}

入力:
{{RAW_INPUT}}

出力形式:
{
  "candidates": [
    {"label": "faithful", "text": "..."},
    {"label": "natural", "text": "..."}
  ],
  "uncertain": []
}
```

### 11.3 Bad Output Example

入力:

```text
AI de nyuuryoku wo rakuni shitai
```

悪い出力:

```text
現代社会における知的生産のインターフェースとして、AIは人間の認知負荷を...
```

理由:

```text
入力にない抽象化を足している。
Uttate Writer はエッセイ生成器ではない。
```

良い出力:

```text
AIで入力を楽にしたい。
```

---

## 12. GeminiProvider

### 12.1 方針

GeminiProvider は Gemini API を使って `raw_text` から直接 candidates を生成する。

Project B では Gemini を第一 Provider とする。

理由:

```text
始めやすい
安価に試しやすい
MVPのUI/UX検証に十分
```

### 12.2 SDK

```bash
pip install -U google-genai
```

### 12.3 API Key

```text
GEMINI_API_KEY
```

### 12.4 Implementation Sketch

現行の Google GenAI SDK では `genai.Client()` を作成し、`client.models.generate_content(...)` などの client 経由の呼び出しを使う。

```python
import json
from google import genai

class GeminiProvider(ConversionProvider):
    name = "gemini"

    def __init__(self, model: str = "gemini-2.5-flash-lite") -> None:
        self.client = genai.Client()
        self.model = model

    async def convert_chunk(
        self,
        raw_text: str,
        previous_context: str = "",
        candidate_count: int = 2,
    ) -> ProviderResult:
        prompt = build_user_prompt(raw_text, previous_context)

        # In the first implementation, call this in a worker thread
        # so the PySide UI does not freeze.
        response = self.client.models.generate_content(
            model=self.model,
            contents=[SYSTEM_PROMPT, prompt],
        )

        data = parse_json_response(response.text)
        return ProviderResult.model_validate(data).model_copy(
            update={"provider": self.name, "model": self.model, "raw_response": response.text}
        )
```

### 12.5 Structured Output Option

Gemini API supports structured output / JSON Schema. Once the plain JSON prompt works, prefer schema-constrained output.

ProviderResult schema can be exported from Pydantic:

```python
schema = ProviderResult.model_json_schema()
```

Then use Gemini's structured output mechanism when available in the chosen API mode.

### 12.6 Gemini Errors to Handle

```text
missing API key
invalid API key
quota exceeded
rate limit
timeout
safety block
empty response
invalid JSON
network error
```

---

## 13. OpenAIProvider

### 13.1 方針

OpenAIProvider は OpenAI API を使って `raw_text` から直接 candidates を生成する。

Project B では GeminiProvider と同じ Provider interface を実装する。

OpenAIProvider は GeminiProvider と UI 上の差分を持たない。

```text
Providerをgeminiからopenaiへ変えても、UIは変わらない。
```

### 13.2 SDK

```bash
pip install openai
```

### 13.3 API Key

```text
OPENAI_API_KEY
```

### 13.4 Implementation Sketch

OpenAI API では Responses API を使う。

```python
import json
from openai import OpenAI

class OpenAIProvider(ConversionProvider):
    name = "openai"

    def __init__(self, model: str = "gpt-5-nano") -> None:
        self.client = OpenAI()
        self.model = model

    async def convert_chunk(
        self,
        raw_text: str,
        previous_context: str = "",
        candidate_count: int = 2,
    ) -> ProviderResult:
        prompt = build_user_prompt(raw_text, previous_context)

        # In the first implementation, call this in a worker thread
        # so the PySide UI does not freeze.
        response = self.client.responses.create(
            model=self.model,
            instructions=SYSTEM_PROMPT,
            input=prompt,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "uttate_conversion_result",
                    "schema": ProviderResult.model_json_schema(),
                    "strict": True,
                }
            },
        )

        data = json.loads(response.output_text)
        return ProviderResult.model_validate(data).model_copy(
            update={"provider": self.name, "model": self.model, "raw_response": response.output_text}
        )
```

### 13.5 OpenAI Errors to Handle

```text
missing API key
invalid API key
billing not enabled
rate limit
timeout
invalid JSON
network error
model not found
context length exceeded
```

---

## 14. MockProvider

MockProvider は最初に実装する。

理由:

```text
APIキーなしでUIを開発できる
CIでテストできる
OSS contributorがすぐ動かせる
APIコストがかからない
```

### 14.1 MockProvider Behavior

```python
class MockProvider(ConversionProvider):
    name = "mock"

    async def convert_chunk(
        self,
        raw_text: str,
        previous_context: str = "",
        candidate_count: int = 2,
    ) -> ProviderResult:
        return ProviderResult(
            provider=self.name,
            model="mock",
            candidates=[
                Candidate(label="faithful", text=f"[忠実変換] {raw_text}"),
                Candidate(label="natural", text=f"[自然変換] {raw_text}"),
            ],
            uncertain=[],
            raw_response=None,
        )
```

### 14.2 Special Mock Fixtures

特定入力は固定出力にする。

```text
AIdenyuuryokuwosaisekkeisuru.
→ AIで入力を再設計する。
```

これにより UI の手動テストがしやすくなる。

---

## 15. Conversion Queue

### 15.1 Requirements

`Enter` を押したら、UIは止まらない。

処理:

```text
1. input buffer を取得
2. Chunk を作成
3. chunk.status = queued
4. chunk list に追加
5. input buffer を空にする
6. conversion queue に投入
7. user は即座に次の入力を続ける
8. provider response が返ったら chunk を更新
```

### 15.2 Status Transitions

```text
raw
→ queued
→ converting
→ ready_for_review
→ adopted
→ edited
```

失敗時:

```text
queued / converting
→ failed
```

### 15.3 Error Safety

最重要原則:

```text
ユーザーの入力を絶対に失わない。
```

Provider が失敗しても、chunk.raw_text は必ず残す。

---

## 16. Review UI

Project B でも既存方針を維持する。

### 16.1 Candidate Cycle

```text
candidate A → candidate B → raw input → candidate A
```

### 16.2 Keybindings

Input Mode:

```text
Enter          Commit current chunk and enqueue conversion
Shift+Enter    Insert newline without committing
Ctrl+K         Move to Review Mode
Ctrl+E         Export final text
Ctrl+,         Settings
Esc            Cancel transient UI / keep focus safe
```

Review Mode:

```text
Tab            Toggle to next preview candidate
Shift+Tab      Toggle to previous preview candidate
Enter          Adopt current preview candidate
Ctrl+Enter     Adopt current preview and move to next unresolved chunk
E              Edit current preview in place
R              Reconvert current chunk
Esc            Return to Input Mode
```

Power user:

```text
Alt+1          Adopt candidate A immediately
Alt+2          Adopt candidate B immediately
Alt+0          Revert to raw input
Ctrl+Shift+R   Force reconvert current chunk
```

---

## 17. Settings

### 17.1 settings.json

```json
{
  "provider": {
    "type": "mock",
    "model": "",
    "timeout_seconds": 30
  },
  "gemini": {
    "model": "gemini-2.5-flash-lite",
    "api_key_env": "GEMINI_API_KEY"
  },
  "openai": {
    "model": "gpt-5-nano",
    "api_key_env": "OPENAI_API_KEY"
  },
  "conversion": {
    "candidate_count": 2,
    "auto_convert_on_enter": true,
    "include_previous_context": true,
    "previous_context_chars": 600
  },
  "review": {
    "tab_cycles_raw": true,
    "auto_move_after_adopt": true,
    "show_uncertainty": true
  },
  "export": {
    "default_format": "markdown"
  },
  "privacy": {
    "redact_api_keys_in_logs": true,
    "store_raw_api_response": false
  }
}
```

### 17.2 Settings UI

最低限:

```text
Provider: mock / gemini / openai
Gemini model
OpenAI model
Previous context on/off
Previous context chars
Timeout seconds
Export format
```

API key は settings file に保存しない。

環境変数から読む。

---

## 18. Response Parser

API出力は壊れることがある。

必ず寛容な parser を用意する。

### 18.1 Parser Steps

```text
1. Structured outputとして取得できた場合はそのままvalidate
2. response.text / response.output_text を取得
3. direct JSON parse
4. 失敗したら markdown fence を除去
5. 失敗したら最初の JSON object を抽出
6. ProviderResult として validate
7. validate 不能なら failed
```

### 18.2 Never silently accept broken output

壊れた出力をそのまま候補にしない。

失敗時は chunk を failed にし、raw input は保持する。

---

## 19. Context Builder

直前の文脈は変換品質に効く。

ただし入れすぎると遅くなり、コストも増える。

### 19.1 Rule

```text
previous_context_chars = 600
```

final text の末尾から最大600文字を渡す。

### 19.2 Context Source Priority

各 chunk の final text は次の優先順位で作る。

```text
edited_text
> adopted_text
> current preview candidate
> raw_text
```

---

## 20. Logging / Privacy

OSSとして重要。

### 20.1 Do not log

```text
API keys
full raw text by default
full API responses by default
```

### 20.2 Debug Mode

Debug mode が有効なときだけ、ユーザー同意の上で raw input / raw API response を保存する。

```json
{
  "debug": {
    "store_raw_input": false,
    "store_raw_api_response": false
  }
}
```

### 20.3 README Warning

READMEには明記する。

```text
API Providerを使う場合、入力テキストは選択したAPI事業者に送信されます。
私的な文章・機密情報を扱う場合は注意してください。
```

---

## 21. Cost Awareness

Project B は API を使うため、使用量表示を将来追加しやすくする。

MVPでは厳密な課金計算は不要。

ただし ProviderResult に usage 情報を入れる余地を残す。

```python
class ProviderUsage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost: float | None = None
    currency: str | None = None
```

将来:

```text
今日のAPI使用量
今月の推定API使用量
Provider別使用量
```

を表示できるようにする。

---

## 22. Manual Test Inputs

### Test 1

```text
AIdenyuuryokuwosaisekkeisuru.
```

Expected:

```text
AIで入力を再設計する。
```

### Test 2

```text
kyounotenkihakumoridesu.asitahatabunname.uttatehaAiwotukattanihonngonyuuryokunosaihatumeininarutoiine.
```

Expected:

```text
今日の天気は曇りです。明日はたぶん雨。UttateはAIを使った日本語入力の再発明になるといいね。
```

### Test 3

```text
keyboardhabunbougudakara inputnostresswosaishoukashinakerebanaranai
```

Expected:

```text
キーボードは文房具だから、入力のストレスを最小化しなければならない。
```

### Test 4

```text
uttatewriterha ime noreplacementjanakute kakukotono frictionwoherasutool
```

Expected:

```text
Uttate WriterはIMEの代替ではなく、書くことのフリクションを減らすツールである。
```

### Test 5

```text
haikukoushiennokeikenwo PR nitsunageru
```

Expected:

```text
俳句甲子園の経験をPRにつなげる。
```

### Test 6

```text
jissai anataha context wo iwakannaku yomeru wakejanai
```

Expected:

```text
実際、あなたはコンテクストを違和感なく読めるわけじゃない。
```

### Test 7

```text
supesukeydehennkannsurukarahitohano shikougatotomaru
```

Expected:

```text
スペースキーで変換するから、人は思考が止まる。
```

---

## 23. Automated Tests

### 23.1 Unit Tests

```text
test_models.py
test_response_parser.py
test_provider_contract.py
test_exporter.py
test_context_builder.py
```

### 23.2 Provider Contract Tests

MockProvider / GeminiProvider / OpenAIProvider は同じ contract を満たす。

```text
convert_chunk returns ProviderResult
ProviderResult has at least one candidate
candidate text is not empty
errors are raised as ProviderError
```

GeminiProvider / OpenAIProvider の実APIテストは通常CIではskipする。

```text
RUN_API_TESTS=1
```

のときだけ実行する。

### 23.3 Golden Tests

`data/golden_outputs.jsonl` を用意する。

```jsonl
{"raw":"AIdenyuuryokuwosaisekkeisuru.","expected_contains":["AI","入力","再設計"]}
```

LLM出力は完全一致させない。

最低限の含有語・意味保持で評価する。

---

## 24. README に書くべきこと

### 24.1 One-line

```text
Uttate Writer is a keyboard-first Japanese rough-input editor that converts messy romaji/English mixed chunks into reviewable Japanese text using pluggable API providers.
```

### 24.2 日本語説明

```text
Uttate Writer は、スペースなしローマ字・英語混じり・タイポ混じりの雑な入力を、AI APIで日本語文へ変換し、あとから候補をレビューできる文章入力エディタです。
```

### 24.3 Quickstart

```bash
git clone <repo>
cd uttate_writer
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -e .
cp .env.example .env
python -m uttate_writer
```

Geminiを使う場合:

```env
UTTATE_PROVIDER=gemini
GEMINI_API_KEY=your_api_key
GEMINI_MODEL=gemini-2.5-flash-lite
```

OpenAIを使う場合:

```env
UTTATE_PROVIDER=openai
OPENAI_API_KEY=your_api_key
OPENAI_MODEL=gpt-5-nano
```

### 24.4 Security Warning

```text
Do not commit your .env file.
Do not paste your API key into issues or logs.
If you use API providers, your input text is sent to the selected provider.
```

---

## 25. OSS Contribution Design

Project B は Provider 追加を歓迎する。

### 25.1 Provider追加の条件

新しい Provider は以下を満たす。

```text
ConversionProvider を継承する
ProviderResult を返す
API key を直書きしない
UI層に依存しない
テスト用MockまたはContract Testを通す
READMEに設定方法を書く
```

### 25.2 将来追加されうる Provider

```text
ClaudeProvider
OpenRouterProvider
OllamaProvider
LMStudioProvider
LocalFineTunedProvider
SudachiPipelineProvider
```

Project B は API branch なので、ローカル系 Provider は別ブランチか後続でよい。

---

## 26. Implementation Tasks for Codex

### Task 1: Create API branch document

Add this file:

```text
project-b-api.md
```

### Task 2: Refactor providers

Create:

```text
providers/base.py
providers/registry.py
providers/mock.py
providers/gemini.py
providers/openai.py
providers/errors.py
```

### Task 3: Implement ProviderResult schema

Use Pydantic models:

```text
Candidate
UncertainItem
ProviderUsage
ProviderResult
```

### Task 4: Implement MockProvider first

The app must run without API keys.

### Task 5: Implement GeminiProvider

Use:

```text
google-genai
GEMINI_API_KEY
```

Return ProviderResult.

### Task 6: Implement OpenAIProvider

Use:

```text
openai
OPENAI_API_KEY
Responses API
```

Return ProviderResult.

### Task 7: Add response parser

Handle:

```text
direct JSON
markdown fenced JSON
extra text around JSON
structured output result
invalid JSON
```

### Task 8: Connect settings

Provider selection:

```text
mock
gemini
openai
```

### Task 9: Keep UI behavior unchanged

Do not change:

```text
Enter commit
async conversion
Tab toggle
Enter adopt
R reconvert
E edit
Export
```

### Task 10: Add README instructions

Add setup for:

```text
Mock mode
Gemini mode
OpenAI mode
API key safety
```

---

## 27. Success Criteria

Project B succeeds if:

```text
APIキーなしでMockProviderが動く
GeminiProviderで変換できる
OpenAIProviderで変換できる
Providerを切り替えてもUIが変わらない
Enter後にUIが止まらない
候補A/BをTabで切り替えられる
Enterで採用できる
変換失敗時にraw inputが失われない
OSS contributorがProviderを追加しやすい
```

Project B fails if:

```text
API ProviderのためにUIが分岐する
ProviderごとにChunkモデルが変わる
APIキーがコードに直書きされる
API失敗で入力が消える
MockProviderなしで開発不能になる
```

---

## 28. Long-term Relation to Local Pipeline

Project B は API branch である。

ただし将来のローカル変換研究と対立しない。

将来的な構成:

```text
Core UI / UX
  ├─ API Provider Branch
  │   ├─ GeminiProvider
  │   └─ OpenAIProvider
  │
  └─ Local Pipeline Branch
      ├─ RoughSplitter
      ├─ RomajiToKana
      ├─ SudachiHints
      └─ LocalFineTunedProvider
```

共通化するもの:

```text
Chunk
Candidate
ProviderResult
Review UI
Export
Settings
Keyboard shortcuts
```

分けるもの:

```text
Provider internals
API SDK dependencies
local model dependencies
dictionary dependencies
```

---

## 29. Core Principle

Project B の最重要原則:

```text
APIは交換可能な変換器であり、Uttate Writer本体ではない。
```

Uttate Writer本体はこれである。

```text
雑に書く。
Enterで投げる。
待たずに続ける。
あとで選ぶ。
必要なら直す。
```

