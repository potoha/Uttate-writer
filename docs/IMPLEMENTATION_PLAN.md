# Uttate Writer Project B 実装計画書

> **履歴資料（現行の実装指示ではない）**
>
> 本書は旧Project B / API Provider BranchのMVP実装計画です。ブランチ統合後の変更は
> [`../project.md`](../project.md)と[`REFACTORING_PLAN.md`](REFACTORING_PLAN.md)を優先し、
> 本書のマイルストーンやProvider構成を新規実装の根拠にしないでください。

## 1. 計画の方針

本計画は `project.md`、`project-b-api.md`、`docs/PROJECT_SCOPE.md` を基準に、
Project B / API Provider Branch のMVPを完成させるための実装順を定義する。

目標は、次の縦切りフローをGemini APIで成立させることだ。

```text
ラフ入力
-> Enterでチャンク確定
-> 入力を継続
-> API Providerがバックグラウンド変換
-> 候補A/B/原文をレビュー
-> 採用または編集
-> 最終文章を書き出し
```

旧計画ではM4途中としてSQLite辞書検索とローカルStage分割パイプラインを進めていた。
Project Bでは、その路線をMVP本線から外し、変換体験を成立させる最短経路へ計画を
組み替える。

## 2. 現在地

現行リポジトリには次の土台がある。

- Python 3.12、PySide6、pytest、pytest-qtの開発基盤
- `src/uttate/` パッケージ構成
- `Chunk` / `Document` / `ChunkStatus`
- Enter入力、チャンク一覧、レビュー欄を含むM2相当UI
- `MockProvider`
- Project B用の `ProviderResult` 契約
- Stage 1/LM Studio系コードを切除したdirect conversion queue
- 既存のテスト群

Project Bでの扱い:

- UI、モデル、Mock、キューは継続利用する。
- Stage 1 normalizer、LM Studio、辞書検索計画はMVP本線から切除済み。将来はLocal Pipeline Providerとして再導入できる。
- MVP本線はDirect API Conversionへ寄せる。
- `project-b-api.md` の考え方を、実装可能な小さなマイルストーンへ落とす。

## 3. 実装上の決定

- パッケージ名は現行どおり `uttate` を維持する。
- Pythonは現行どおりrepo-localな3.12環境を使い、グローバルPythonを侵襲しない。
- `Chunk` / `Document` は当面dataclassを維持し、必要な差分だけ追加する。
- Provider出力は共通の `ProviderResult` / `Candidate` / `UncertainItem` に正規化する。
- GeminiProviderを第一実Providerとし、OpenAIProviderを同じcontractで実装する。
- API呼び出しはUIスレッドで実行しない。
- Providerごとの違いは `providers/` と `pipeline/response_parser.py` に閉じ込める。
- API keyは `.env` または環境変数から読む。コード、README、テストデータへ直書きしない。
- 実APIテストは通常skipし、`RUN_API_TESTS=1` のときだけ走らせる。

## 4. マイルストーン

### B0: Project B文書と方針固定

目的: ローカルStage分割MVPからAPI Provider MVPへ、作るものと作らないものを固定する。

実装項目:

- `docs/PROJECT_SCOPE.md` をProject B前提へ更新する。
- `docs/IMPLEMENTATION_PLAN.md` をProject B前提へ更新する。
- ローカルパイプラインをMVP対象外かつ将来Provider候補として明記する。

完了条件:

- Gemini APIで縦切り体験を作ることがMVP本線として明文化されている。
- M4途中の辞書検索路線がMVP完成条件から外れている。

### B1: ProviderResult契約の導入

目的: UIがProvider種別に依存しない共通結果形式を固定する。

実装項目:

- `Candidate`
- `UncertainItem`
- `ProviderUsage`
- `ProviderResult`
- Provider共通エラー `ProviderError`
- 旧 `ConversionResult` の削除

推奨ファイル:

```text
src/uttate/providers/result.py
src/uttate/providers/errors.py
```

判断:

- 既存コードのdataclass方針を尊重しつつ、JSON Schema生成が必要ならPydantic導入を検討する。
- 導入する場合もChunk/Documentの全面Pydantic化はこのマイルストーンでは行わない。

テスト:

- candidatesが空なら失敗
- candidate.textが空なら失敗
- uncertain省略時は空配列扱い
- usageは任意
- provider/modelが記録できる

完了条件:

- Mock/Gemini/OpenAIが同じ戻り値型を返せる。

### B2: Response ParserとPromptの整備

目的: 壊れがちなAPI応答を安全に共通形式へ正規化する。

実装項目:

- `pipeline/response_parser.py`
- direct JSON parse
- markdown fenced JSONの除去
- 余分な前後テキストからJSON object抽出
- schema validation
- 壊れた応答の明示的な失敗化
- API direct conversion用system prompt/user prompt

推奨ファイル:

```text
src/uttate/pipeline/response_parser.py
src/uttate/prompts/api_direct_converter_system.txt
src/uttate/prompts/api_direct_converter_user.txt
```

プロンプト要点:

- 創作、要約、補足ではなく変換である。
- 入力にない意味を追加しない。
- 候補1はfaithful、候補2はnatural。
- Uttate、IME、API、LLMなどの略語や固有名詞は自然なら保持する。
- JSONのみ返す。

テスト:

- 正常JSON
- fenced JSON
- 前後に説明が混ざったJSON
- invalid JSON
- candidates不足
- 空candidate

完了条件:

- Provider SDKの違いに関係なく、アプリ内部はProviderResultだけを扱える。

### B3: SettingsとAPI key安全設計

目的: OSSとして安全にProviderを切り替えられる設定基盤を作る。

実装項目:

- `.env.example`
- `.gitignore` の `.env` / `.env.*` 確認
- `python-dotenv` 導入の可否判断
- `UTTATE_PROVIDER`
- `GEMINI_API_KEY` / `GEMINI_MODEL`
- `OPENAI_API_KEY` / `OPENAI_MODEL`
- timeout、previous_context_chars
- ログ・エラー表示でのAPI keyマスク

テスト:

- 環境変数からProviderを選べる
- API key未設定時に分かりやすく失敗する
- secret値がrepr/log用文字列に出ない
- 既定値はmock

完了条件:

- API keyなしでもMockProviderでアプリが起動する。
- API keyをrepoに含めずGemini/OpenAIへ切り替えられる。

### B4: MockProviderを新契約へ移行

目的: 実APIなしでProject Bの縦切りUXを開発できる状態を保つ。

実装項目:

- MockProviderをProviderResult契約へ対応
- Project B代表入力の固定出力
- previous_contextを受け取れるinterface
- candidate_countの上限反映
- deterministic delayによる非同期UI検証

代表fixture:

```text
AIdenyuuryokuwosaisekkeisuru.
-> AIで入力を再設計する。

keyboardhabunbougudakara inputnostresswosaishoukashinakerebanaranai
-> キーボードは文房具だから、入力のストレスを最小化しなければならない。
```

テスト:

- API keyなしで変換できる
- 2候補を返す
- candidate_countが効く
- UI queueが既存どおり動く

完了条件:

- Mockだけで「連続入力 -> 変換 -> レビュー -> 採用 -> Export」まで通る。

### B5: GeminiProvider

目的: Project Bの第一実ProviderとしてGemini API変換を成立させる。

実装項目:

- `providers/gemini.py`
- `google-genai` dependency
- `GEMINI_API_KEY` 読み込み
- `GEMINI_MODEL` 読み込み
- timeout処理
- structured outputまたはJSON prompt
- safety block、empty response、invalid JSON、quota/rate limitのエラー変換
- raw API responseの既定非保存

テスト:

- SDK呼び出しをmockした正常系
- API key未設定
- empty response
- invalid JSON
- ProviderError変換
- `RUN_API_TESTS=1` のときだけ実API smoke test

完了条件:

- GeminiProviderで代表入力3件を変換し、候補A/BをレビューUIに表示できる。

### B6: OpenAIProvider

目的: Provider交換可能性を実証し、Gemini専用構造にしない。

実装項目:

- `providers/openai.py`
- `openai` dependency
- `OPENAI_API_KEY` 読み込み
- `OPENAI_MODEL` 読み込み
- Responses APIまたは現在のSDKに合ったJSON Schema出力
- Response Parserとの統合
- OpenAI固有エラーのProviderError変換

テスト:

- SDK呼び出しをmockした正常系
- API key未設定
- model not found
- rate limit
- invalid JSON
- `RUN_API_TESTS=1` のときだけ実API smoke test

完了条件:

- Provider設定をopenaiに変えても、UIとChunkモデルを変更せずに同じ操作ができる。

### B7: Provider RegistryとQueue統合

目的: mock/gemini/openaiを同じUIフローで切り替えられるようにする。

実装項目:

- `providers/registry.py`
- settingsからProvider生成
- conversion queueへprevious_contextを渡す
- chunk IDと処理世代による古い結果の破棄
- failed状態と再変換
- provider/model/errorをchunkへ記録するか、UI表示用view modelへ載せる

テスト:

- provider切り替え
- 3チャンク連続送信
- 変換中も入力可能
- 古い応答が新しい結果を上書きしない
- failedから再変換できる

完了条件:

- Provider種別が変わっても、Enter commit、async conversion、reviewが同じコード経路で動く。

### B8: Review / ExportのProject B仕上げ

目的: API変換結果をユーザーが最後まで文章として扱える状態にする。

実装項目:

- 候補A/B/原文の循環表示
- Enter採用
- Ctrl+Enterで採用して次へ
- E編集
- R再変換
- Esc取消
- uncertain表示
- clipboard export
- `.txt` / `.md` export
- 未採用fallback設定

テスト:

- Tab循環順
- Shift+Tab逆順
- 採用状態
- 編集状態
- 再変換
- Exportのfallback
- 日本語UTF-8出力

完了条件:

- キーボードだけで入力、変換、比較、採用、編集、書き出しまで完了できる。

### B9: README、Contributor導線、MVP判定

目的: OSSとして試せる、壊れ方が分かる、Providerを追加しやすい状態にする。

実装項目:

- README quickstart
- Mock mode起動手順
- Gemini mode設定手順
- OpenAI mode設定手順
- API利用時のプライバシー注意
- API key安全注意
- Provider追加ガイド
- 手動テスト入力
- 実APIテストのopt-in方法
- 既知制約とMVP後バックログ

テスト/確認:

- 新規環境でMock起動
- Gemini smoke
- OpenAI smoke
- API keyがログやgit管理対象に出ない
- `docs/PROJECT_SCOPE.md` の受け入れ基準確認

完了条件:

- Project B MVPを第三者がMockで起動できる。
- API keyを用意した人がGemini/OpenAIで変換体験を試せる。

## 5. 依存関係と実施順

```text
B0 文書と方針固定
  -> B1 ProviderResult契約
    -> B2 Response Parser / Prompt
      -> B3 Settings / API key安全設計
        -> B4 MockProvider移行
          -> B5 GeminiProvider
          -> B6 OpenAIProvider
            -> B7 Registry / Queue統合
              -> B8 Review / Export仕上げ
                -> B9 README / MVP判定
```

B5とB6はB1からB3完了後に並行可能。ただしB5を先に完了させ、Geminiで体験検証を
早く行う。

## 6. 既存ローカルパイプラインの扱い

既存のStage 1 normalizer、LM Studio provider、辞書検索計画はProject B MVP本線から切除した。
ただし将来のLocal Pipeline Providerとして再実装できる余地は残す。

扱い:

- `local-pipeline` Provider候補として将来戻す。
- 既存テストがProject Bの進行を妨げる場合は、対象を明確に分ける。
- READMEでは「local pipelineはexperimental/future」として扱う。
- Gemini/OpenAI ProviderのUI契約を壊さない範囲でのみ残す。

この方針により、OSSとしての拡張余地を残しながら、MVPの最短ゴールを曇らせない。

## 7. テスト戦略

### Unit Tests

- ProviderResult validation
- Response Parser
- Settings/env loading
- API key masking
- Context Builder
- Export fallback
- Provider Registry

### Provider Contract Tests

全Providerに共通で確認する。

- `convert_chunk` がProviderResultを返す
- candidateが最低1件ある
- candidate textが空でない
- provider/modelが記録される
- 失敗時はProviderErrorへ変換される
- raw inputは失われない

### UI / Integration Tests

- MockProviderで3チャンク連続送信
- 変換中の入力継続
- Tab/Shift+Tab循環
- Enter採用
- E編集
- R再変換
- failed表示と再実行
- clipboard/file export

### Real API Smoke Tests

通常はskipする。

```text
RUN_API_TESTS=1
UTTATE_PROVIDER=gemini
GEMINI_API_KEY=...
```

確認内容:

- 代表入力がProviderResultへ正規化される
- UIが固まらない
- raw inputが失われない
- API keyがログに出ない

LLM出力は完全一致させない。合否はJSON構造、候補の非空性、意味保存、操作可能性で判断する。

## 8. リスクと対策

| リスク | 影響 | 対策 |
| --- | --- | --- |
| Gemini応答がJSONから外れる | チャンクが変換不能になる | structured output優先、Response Parser、failed表示、再変換 |
| APIが遅い | 入力体験を損なう | UIスレッド分離、timeout、状態表示、入力欄即時クリア |
| API key漏洩 | OSSとして致命的 | `.env`除外、ログマスク、README注意、テストfixture禁止 |
| ProviderごとにUI分岐する | 拡張性が落ちる | ProviderResult契約とRegistryを先に固定 |
| モデルが文章を盛る | Uttateの目的に反する | faithful/naturalラベル、プロンプト回帰例、原文表示 |
| 既存Stage分割コードと衝突 | 実装が散る | Local Pipeline Provider候補として分離し、MVP本線に入れない |
| 実APIテストがCIで不安定 | 開発速度が落ちる | 実APIはopt-in、通常はMockとSDK mockで検証 |
| 古い応答が後着する | 誤候補を表示する | chunk IDと処理世代で破棄 |

## 9. 各マイルストーン共通の完了定義

- 実装項目が動作する。
- 正常系と主要失敗系のテストがある。
- UIを変更した場合はキーボード操作とフォーカスを確認する。
- Providerを追加してもUI層が分岐しない。
- API key、`.env`、raw API responseを誤ってコミットしない。
- 文書とREADMEが実装差分に追随している。
- 後続工程をブロックする既知の重大不具合がない。

## 10. MVP後のバックログ

- Local Pipeline Provider復帰
- Stage 1 reading normalizationのProvider化
- SQLite/Sudachi辞書Providerまたはhint layer
- Provider別のコスト表示
- 詳細なsettings UI
- ショートカット変更
- `Alt+1` / `Alt+2` / `Alt+0` の直接採用
- 詳細な辞書管理画面
- 複数ドキュメント管理
- 配布用パッケージ、インストーラー、コード署名、自動更新
- 変換品質の定量評価
- 小型ローカルモデルのfine-tuning

## 11. 次の実装着手点

B0は本書とスコープ文書の更新で完了とする。

次に着手するなら、B1から始める。

最小の最初の実装単位:

1. `ProviderResult` / `Candidate` / `UncertainItem` を追加する。
2. MockProviderを新契約へ対応させる。
3. Response Parserのテストを書き、壊れたJSONをfailedにできるようにする。
4. その後GeminiProviderへ進む。

この順番なら、APIキーなしで既存UIを壊さずにProject Bの土台を作れる。
