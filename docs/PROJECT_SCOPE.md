# Uttate Writer Project B MVP Scope

## 1. 文書の目的

本書は `project.md` と `project-b-api.md` をもとに、Uttate Writer の
Project B / API Provider Branch で作るMVPの境界を定義する。

このブランチの目的は、ローカル小型モデルだけで変換品質を詰める研究をいったん
MVP本線から外し、Gemini APIを第一Providerとして「雑に書く、待たずに続ける、
あとで候補を選ぶ」体験を先に成立させることである。

既存の `docs/PROJECT_SCOPE.md` は、Stage 1読み正規化、SQLite辞書検索、
Stage 3漢字かな変換を中心にしたローカル変換パイプラインMVPを前提としていた。
Project Bではその方針を次のように作り直す。

```text
旧MVP:
  raw input
  -> Stage 1 reading normalization
  -> dictionary retrieval
  -> Stage 3 conversion
  -> review

Project B MVP:
  raw input
  -> direct API Provider conversion
  -> candidates A/B
  -> review
```

## 2. プロダクトの目的

Uttate Writer は、ローマ字、英単語、ひらがな、タイポ、スペースなし入力が混ざった
ラフな思考チャンクを、ユーザーが書く速度を止めずに後から日本語文へ変換し、
候補をレビューして採用できるキーボード中心のデスクトップエディタである。

Project Bで検証する中心仮説は次のとおり。

> 変換エンジンをAPI Providerとして交換可能にし、まず高品質な外部モデルで
> 縦切り体験を成立させれば、Uttate Writerの本体価値である入力UXとレビューUXを
> 早く検証できる。

Uttate Writerの本体価値はモデルそのものではなく、次の操作体験である。

```text
雑に書く
Enterで投げる
待たずに続ける
あとで選ぶ
必要なら直す
```

## 3. 現在地と方針転換

このブランチは、元のMVP進行でM4途中に相当する状態から再計画する。

活かすもの:

- PySide6によるスタンドアロンUI
- `Chunk` / `Document` のチャンク中心データモデル
- Enterでチャンク化し、UIを止めずに変換するキュー
- MockProviderによるネットワークなしの開発・テスト
- 候補A/B、原文、採用、編集、再変換、Exportというレビュー体験
- OpenAI互換Provider実装で得たJSON応答検証と失敗時の扱い

MVP本線から外すもの:

- Stage 1読み正規化を必須にすること
- Stage 2 SQLite/Sudachi辞書検索を必須にすること
- Stage 3変換を別Provider呼び出しとして必須にすること
- ローカル小型モデルの品質改善をMVP完成条件にすること

重要なのは、ローカル変換研究を捨てることではない。Project Bではそれを
Providerの一種として将来戻せるようにしつつ、MVPの完成条件から外す。

## 4. MVP成果物

Project B MVPは Python 3.12、PySide6、Provider抽象を使うデスクトップアプリとして
提供する。成果物には次を含める。

1. キーボード中心で操作できる2ペインUI
2. `Enter` によるチャンクcommitと非同期変換queue
3. API Providerを差し替えられるProvider interface
4. APIキーなしで動くMockProvider
5. Gemini APIで直接候補A/Bを返すGeminiProvider
6. OpenAI APIで同じ契約を満たすOpenAIProvider
7. Provider出力を共通形式へ正規化するResponse Parser
8. 候補A/B/原文のTab循環、Enter採用、E編集、R再変換
9. 採用済みチャンクのクリップボード、`.txt`、`.md` Export
10. `.env.example` と環境変数によるAPI key設定
11. API key、入力本文、API生レスポンスを不用意にログへ出さない安全設計
12. Mock中心の自動テストと、Gemini/OpenAI実API用の手動またはopt-inテスト

## 5. 機能スコープ

### 5.1 入力とチャンク管理

- 大きなラフ入力欄を提供する。
- `Enter` で現在の入力をチャンクとして確定し、変換キューへ送る。
- `Shift+Enter` で送信せずに改行する。
- 空白のみの入力はチャンクとして登録しない。
- 送信直後に入力欄を空け、変換中でも次の入力を受け付ける。
- チャンク一覧に状態、短い内容、選択状態を表示する。
- Provider失敗時も `raw_text` を必ず保持し、再変換できる。

### 5.2 API変換

Project BではMVPの標準変換をDirect API Conversionとする。

```text
raw_text
previous_context
candidate_count
-> ConversionProvider
-> ProviderResult
-> Chunk candidates
```

Providerへ渡す入力:

- `raw_text`: ユーザーが入力した元チャンク
- `previous_context`: 直前までの採用済みまたは編集済み文章の末尾
- `candidate_count`: 通常2

Providerから受け取る出力:

- `candidates`: 最低1件、標準2件
- `uncertain`: 判断不能な語、読み、固有名詞など
- `provider`: Provider名
- `model`: モデル名
- `usage`: トークン数や推定コストを将来入れられる任意情報

候補の意味:

```text
faithful = 入力に忠実。意味追加を最小化する。
natural  = 少し自然。ただし新しい主張は足さない。
```

### 5.3 Provider

必須Provider:

- `mock`: APIキーなしで決定的な候補を返す。
- `gemini`: Gemini APIを使う第一実Provider。
- `openai`: OpenAI APIを使う第二実Provider。

任意または後続Provider:

- `openai-compatible`
- `lmstudio`
- `claude`
- `openrouter`
- `ollama`
- `local-pipeline`

UIはProviderの種類を知らない。UIは `raw_text` を渡し、候補とエラーを受け取るだけにする。

### 5.4 設定とAPI key

- Provider種別、モデル名、タイムアウト、直前文脈長を設定できる。
- API keyは `.env` または環境変数から読み込む。
- `.env.example` はコミットするが `.env` はコミットしない。
- API keyをsettings JSONへ平文保存しない。
- API keyをログ、エラー表示、テストフィクスチャ、README例へ出さない。

標準環境変数:

```text
UTTATE_PROVIDER=mock|gemini|openai
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash-lite
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5-nano
UTTATE_PREVIOUS_CONTEXT_CHARS=600
UTTATE_TIMEOUT_SECONDS=30
```

### 5.5 レビュー

- 原文、現在プレビュー中の候補、不確実箇所を表示する。
- `Tab` / `Shift+Tab` で「候補A -> 候補B -> 原文」を循環表示する。
- `Enter` で表示中の候補を採用する。
- `Ctrl+Enter` で採用して次の未解決チャンクへ移動する。
- `E` で現在の候補をその場で編集する。
- `R` で選択中チャンクを再変換する。
- `Esc` で未確定のプレビューまたは編集を取り消す。
- 不確実性を隠さず、該当箇所、候補、理由を表示する。

### 5.6 書き出し

- チャンク順に `edited_text` または `adopted_text` を連結する。
- 未採用チャンクは設定に従い候補Aまたは原文へフォールバックする。
- 最終文章をクリップボードへコピーできる。
- UTF-8の `.txt` または `.md` として保存できる。

### 5.7 OSS拡張性

Project BはProvider追加を歓迎する構造にする。

新しいProviderは次を満たす。

- 共通Provider interfaceを実装する。
- 共通ProviderResultを返す。
- UI層に依存しない。
- API keyや認証情報をコードに直書きしない。
- MockまたはContract Testで契約を検証できる。
- READMEに設定方法と送信されるデータの注意を追記できる。

## 6. MVP対象外

Project B MVPでは次をやらない。

- OSレベルIME化
- 任意アプリへのグローバル文字置換
- Stage 1/Stage 2/Stage 3分割パイプラインの完成
- Sudachi/SQLite辞書を変換品質の必須条件にすること
- ローカルLLMの最適化、モデル選定、推論高速化
- fine-tuning、LoRA/QLoRA、学習データ生成基盤
- RAG、Web検索、知識検索
- ユーザーアカウント、クラウド同期、課金
- プラグインマーケットプレイス
- APIキーを埋め込んだ配布
- 厳密なコスト計算や月次利用量ダッシュボード
- OSインストーラー、コード署名、自動更新

## 7. 非機能要件

### 応答性

- `Enter` 操作から次の入力を開始できる状態まで、UI処理は体感上即時であることを目標とする。
- API通信をUIスレッドで実行しない。
- 複数チャンクの処理中も入力、選択、スクロールを妨げない。

### 信頼性

- 1チャンクの失敗が他のチャンクやアプリ全体を停止させない。
- 状態遷移を明示し、queued、converting、ready、failedを区別する。
- 再変換時も原文と最後に採用した文章を失わない。
- 古いAPI応答が後着しても、新しい処理結果を上書きしない。

### 忠実性

- 入力にない主張や情報を追加しない。
- 候補Aは意味保存を最優先する。
- 候補Bも新しい主張を足さない。
- 判断不能な表記は無理に確定せず、不確実性として残す。

### プライバシー

- API Provider利用時、入力テキストが選択したProviderへ送信されることをREADMEと設定UIで明示する。
- raw inputとraw API responseは既定では保存しない。
- debug保存はユーザーが明示的に有効化した場合だけにする。
- API keyはログとエラー表示で必ず伏せる。

### テスト容易性

- MockProviderでネットワークなしに主要フローを再現できる。
- Provider Contract Testで各Providerの戻り値を検証できる。
- 実APIテストは通常CIではskipし、明示フラグがあるときだけ実行する。

## 8. 技術境界

- UI: PySide6
- 言語: Python 3.12
- 設定: 環境変数、`.env`、ローカルsettings
- Gemini SDK: `google-genai`
- OpenAI SDK: `openai`
- HTTP補助: 必要に応じて `httpx`
- 応答検証: ProviderResult schemaとResponse Parser
- テスト: pytest、pytest-qt
- パッケージ構成: 現行の `src/uttate/` を維持する
- 非同期実行: Qt worker/thread poolでProvider呼び出しをUIスレッドから分離する

## 9. 状態遷移

Project BのMVP状態は、既存の詳細状態を残しつつ、API直変換に合わせて単純化する。

標準:

```text
raw
  -> queued
  -> converting
  -> ready_for_review
  -> adopted | edited

queued / converting
  -> failed

ready_for_review / adopted / edited / failed
  -> queued
  -> converting
```

既存互換:

```text
normalizing
normalized
retrieving_dictionary
```

これらはLocal Pipeline Provider用の内部状態として将来利用してよいが、Project B MVPの
完了条件には含めない。

## 10. MVP受け入れ基準

以下を満たしたときProject B MVP完成とする。

1. ユーザーがラフ入力を `Enter` で3チャンク以上連続送信でき、先行チャンクの変換完了を待たずに次を入力できる。
2. MockProviderで各チャンクが変換され、候補A/B/原文をレビューできる。
3. GeminiProviderで少なくとも代表入力3件を実API変換できる。
4. OpenAIProviderで同じProvider contractを満たす。
5. Providerをmock/gemini/openaiで切り替えてもUIコードとChunkモデルが分岐しない。
6. API key未設定、timeout、rate limit、不正JSON、空応答でraw inputが失われず、チャンクがfailedになる。
7. レビュー画面で候補A、候補B、原文を循環し、採用、編集、再変換ができる。
8. 採用済み文章をクリップボード、`.txt`、`.md` のいずれにも出力できる。
9. API keyがリポジトリ、ログ、テスト出力に含まれない。
10. READMEにMock/Gemini/OpenAIの起動方法、API利用時の送信データ注意、テスト方法が記載されている。
11. Provider追加手順がドキュメント化され、OSS contributorが新Providerを追加しやすい。

## 11. 代表手動テスト入力

Project Bでは完全一致より、意味保存、候補提示、レビュー可能性を重視する。

```text
AIdenyuuryokuwosaisekkeisuru.
```

期待:

```text
AIで入力を再設計する。
```

```text
keyboardhabunbougudakara inputnostresswosaishoukashinakerebanaranai
```

期待:

```text
キーボードは文房具だから、入力のストレスを最小化しなければならない。
```

```text
uttatewriterha ime noreplacementjanakute kakukotono frictionwoherasutool
```

期待:

```text
Uttate WriterはIMEの代替ではなく、書くことのフリクションを減らすツールである。
```

```text
haikukoushiennokeikenwo PR nitsunageru
```

期待:

```text
俳句甲子園の経験をPRにつなげる。
```

## 12. スコープ判断の原則

実装中に迷った場合は、次の順で判断する。

1. 「入力を止めない -> 後からレビューする」の体験完成に必須か。
2. Provider交換可能性を壊さないか。
3. API keyとユーザー入力の安全性を損なわないか。
4. Mockで再現できる小さな実装か。
5. 必須でなければMVP後のバックログへ送る。

モデル精度の追求より、まず一連のUXループが途切れず動くことを優先する。
