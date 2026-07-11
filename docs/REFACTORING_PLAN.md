# Uttate Writer 安全性・保守性リファクタリング計画

## 1. 目的

この計画は、2026年7月11日の全体点検で確認した設定、データセット、終了処理、
変換忠実性、配布、UI責務の問題を、既存の入力・レビュー体験を維持しながら段階的に
解消するための実行手順である。

実装担当は Terra を想定する。各Phaseは、原則として単独で実装・検証・レビューできる
大きさに分ける。前のPhaseの完了条件を満たしてから次へ進む。

## 2. 現在の基準状態

2026年7月11日の読み取り専用検証結果:

- `pytest`: 168 passed
- `ruff check .`: 成功
- `ruff format --check .`: 18ファイルで失敗
- `uv build --offline`: wheel / sdist生成成功
- 展開したwheel: 標準テーマが含まれず、CSS読込結果が空になる

この数値は実装開始時に再確認する。差分スナップショットは現在状態そのものではないため、
Git状態の根拠にしない。

### 実装状況（2026-07-11）

| Phase | 状態 | 実施内容 / 残作業 |
| --- | --- | --- |
| 0 | 完了 | 問題の再現テストと全体検証を実施。 |
| 1 | 完了 | credential非保存、設定優先順位、atomic settings保存を実装。 |
| 2 | 完了 | review/candidate形式分離、schema検証、atomic JSONL保存、legacy candidateからreviewへのコピー移行を実装。 |
| 3 | 完了 | 非匿名化exportを廃止し、実出力フィールドごとの確認または完全匿名化を必須化。 |
| 4 | 一部完了 | placeholder検証、前文context、`store: false`を実装。実際のmechanical normalized textをdatasetへ運ぶ契約は未実施。 |
| 5 | 完了 | 明示終了とworker drainを実装。 |
| 6 | 完了 | built-in themeのpackage化とユーザーtheme保存先分離を実装。 |
| 7 | 一部完了 | Provider切替の保存・失敗時表示復元を実装。WindowCoordinator等の大規模責務分離は未実施。 |
| 8 | 一部完了 | lintと全テストは通過。未変更の既存9ファイルのformat、typecheck/coverage導入は未実施。 |

## 3. 変更時に守る制約

- `ReviewHUD`、`InputPanel`、`DebugConsole` を1つのウィンドウへ統合しない。
- 各画面は種類ごとに1つのトップレベルウィンドウを再利用し、既存インスタンスを前面へ出す。
- InputPanelのProvider選択、モデル表示、Settings、Send/Convert、always-on-top操作を維持する。
- whitelist状態と匿名化状態を別の概念として扱う。匿名化・undoでwhitelistを変更しない。
- `+` / `＋` による撥音境界、protected input、Stage 1の既存契約を維持する。
- APIキーを設定JSON、ログ、テストfixture、exportデータへ保存しない。
- Python、uv cache、仮想環境はリポジトリ内に限定する。
- 目的外のリネーム、全面整形、互換shim削除を安全性修正へ混ぜない。
- Gitコマンドと `export-diff.ps1` は実行しない。

## 4. 実施順序

```text
Phase 0: 基準固定
  -> Phase 1: 秘密情報と設定
  -> Phase 2: データ保存形式と耐久性
  -> Phase 3: 匿名化export安全性
  -> Phase 4: 変換忠実性と前文コンテキスト
  -> Phase 5: アプリ終了処理
  -> Phase 6: テーマと配布物
  -> Phase 7: Provider切替とUI責務分離
  -> Phase 8: 品質ゲートと文書整理
```

Phase 1から6は既知の不具合修正を優先する。大規模なクラス分割は、動作を固定するテストが
揃った後のPhase 7で行う。

## 5. Phase 0: 基準固定

### 目的

修正前の動作と失敗条件をテストで固定し、リファクタリング中の仕様逸脱を検出できるようにする。

### 作業

1. 現在の全テスト、lint、format、build結果を再取得する。
2. 次の問題を再現する失敗テストを先に追加する。
   - `compatible_api_key` がsettings.jsonへ保存される。
   - 2種類のdataset形式が同じ保存先を使う。
   - redactionが一部だけでもexport可能になる。
   - protected placeholderの欠落・改変・重複が受理される。
   - `previous_context_chars` がProvider呼出しへ渡らない。
   - 全表示ウィンドウを閉じてもアプリが終了しない。
   - wheelから標準テーマを読み込めない。
3. 失敗テストは問題を正確に再現する最小ケースに限定する。

### 主な対象

- `tests/test_config.py`
- `tests/test_dataset_collection.py`
- `tests/test_m2_ui.py`
- `tests/test_protected_input.py`
- `tests/test_providers.py`
- `tests/test_theme_management.py`
- 新規のpackaging smoke test

### 完了条件

- 既存168テストは維持される。
- 追加テストが、それぞれ意図した既知問題だけを理由に失敗する。
- baseline結果を `agent-work-logs/agent-notes.md` に事実と推測を分けて記録する。

## 6. Phase 1: 秘密情報と設定の一貫性

### 目的

秘密情報の平文保存を止め、`defaults < settings.json < .env < 実環境変数` の優先順位と
設定のround-tripを一致させる。

### 作業

1. `save_settings()` でProvider dataclass全体を一度dict化する方式をやめ、保存可能な非秘密項目を
   明示列挙する。
2. 少なくとも次を保存対象から除外する。
   - `gemini_api_key`
   - `openai_api_key`
   - `compatible_api_key`
3. Provider設定のmergeを、項目ごとに同じ優先順位で処理する共通helperへ寄せる。
4. 保存したmodel、base URL、timeout、context文字数が、環境変数で上書きされない限り
   再読込されるようにする。
5. 旧 `mock` / `lmstudio` から `local_ai` へのalias互換は維持する。
6. 壊れたsettings.jsonで起動不能になる問題は、勝手に初期化せず、バックアップと明確な
   エラー通知を行う方針で処理する。
7. settings保存を一時ファイル、flush、可能ならfsync、atomic replaceへ変更する。

### 主な対象

- `src/uttate/config.py`
- `src/uttate/ui/settings_window.py`
- `tests/test_config.py`
- `.env.example`
- `README.md`

### 必須テスト

- 3種類すべてのAPIキーがsettings.jsonに存在しない。
- JSONの全非秘密Provider項目がround-tripする。
- `.env` がJSONに勝ち、実環境変数が `.env` に勝つ。
- 旧Provider aliasが引き続き `local_ai` へ移行される。
- 書込み失敗時に既存settings.jsonが失われない。

### 完了条件

- settings.jsonにcredentialが保存されない。
- 設定優先順位がdocstring、README、テストで一致する。
- format/lint/全テストが通る。

## 7. Phase 2: Dataset保存形式の分離と耐久性

### 目的

旧Curator形式とCollection形式の衝突をなくし、保存中断・同時更新による破損を防ぐ。

### 事前判断

保存先は次の2項目へ分離する。

- `candidate_store_path`: 旧 `raw/kana/literal/natural` 形式
- `review_store_path`: Dataset Collectionのreview item形式

既存の `capture_store_path` は読み込み時だけのlegacy migration sourceとし、新規保存では使わない。
内容がある既存storeは、新しいreview形式へ移行する。

### 作業

1. 両JSONL形式に `schema` と `schema_version` を追加する。
2. 読込み時に期待形式を検証し、異なる形式を黙って正規化しない。
3. `capture_store_path` の既存値は、新しいreview形式へ移行する。
   - 空または存在しない場合は、新しいreview storeを作成する。
   - 旧candidate形式はreview itemへ明示的に変換し、元ファイルを保持する。
   - 判定不能・混在時は書込みを止め、元ファイルを保持する。
4. JSONL保存をrepository層へ集約する。
5. 一時ファイル、flush/fsync、atomic replaceを使用する。
6. UI内の更新は単一repository ownerで直列化する。CLIとの同時更新を許す場合はlockを追加する。
7. ID生成を同時更新で重複しない方式へ変更する。既存IDとの互換は維持する。
8. `save_conversion_history`、`auto_create_candidates`、`capture_enabled`、
   `collection_enabled` の意味を整理する。

推奨する最終仕様:

- `collection_enabled`: Dataset Collection UIとreview storeを有効化
- `auto_create_candidates`: 通常のaccept時にもreview itemを自動作成
- `capture_enabled`: 明示的な「acceptして記録」操作を許可
- `save_conversion_history`: 承認前を含む変換履歴を、review candidateとは別の履歴storeへ保存する

### 主な対象

- `src/uttate/config.py`
- `src/uttate/addons/dataset_collection.py`
- `src/uttate/addons/dataset_curator.py`
- `src/uttate/ui/main_window.py`
- `src/uttate/ui/settings_window.py`
- `tests/test_config.py`
- `tests/test_dataset_collection.py`
- `tests/test_dataset_curator.py`
- `tests/test_m2_ui.py`

### 完了条件

- 2形式が同じファイルへ書かれない。
- 異形式・混在ファイルを破壊せず停止できる。
- OFFにした収集設定でテキストが保存されない。
- accept、明示記録、auto-createの各挙動がテストで区別される。
- 中断した書込みで直前の正常ファイルが残る。

## 8. Phase 3: 匿名化とexport安全性

### 目的

「redaction履歴がある」ことではなく、実際にexportされる全テキストが確認済みであることを
安全条件にする。

### 作業

1. export対象フィールドを1か所で定義する。
2. 各フィールドについて、未確認・確認済み・redaction済みを区別する安全状態を持つ。
3. redactionが1件あるだけでは匿名化済みにしない。
4. 同じPIIが複数フィールドまたは同一フィールド内に複数ある場合を検出する。
5. export前に全対象フィールドの残存候補と安全状態を再検証する。
6. `allow_non_anonymized_export` を廃止し、匿名化されていないexportを禁止する。
7. whitelist、reject、redaction、undoを独立した状態遷移として維持する。
8. redaction履歴には元文字列を保持するため、review store自体が機密データであることをUIと文書へ明記する。

### 必須テスト

- converted_textだけをredactしても、raw_inputにPIIが残ればexportを拒否する。
- 同じ文字列の一部出現箇所だけをredactした場合に拒否する。
- 全export対象が安全確認済みならexportできる。
- redactionとundoでwhitelist状態が変化しない。
- 非匿名化itemを含むexportは、設定やUI操作によらず拒否される。

### 完了条件

- export可否が実際の出力フィールドと一致する。
- export summaryが「redaction件数」ではなく安全確認結果を表示する。
- privacy動作が `README.md` とdataset文書に反映される。

## 9. Phase 4: 変換忠実性と前文コンテキスト

### 目的

protected inputの欠落・複製を防ぎ、設定済みの前文コンテキストを実際の変換へ渡す。

### 作業

1. Provider結果の各候補について、期待するplaceholderがそれぞれ正確に1回存在することを
   復元前に検証する。
2. 欠落、改変、重複した候補は受理せず、chunkを明示的な失敗状態にする。
3. raw/source echoの検証境界をProvider共通処理へまとめる。
4. `ConversionRequest` をqueueの正式な入力契約にする。
5. Documentから採用済み・編集済みテキストだけを順序どおりに集め、
   `previous_context_chars` の末尾文字数へ制限する。
6. 変換開始時のProviderとcontextをworkerに固定し、処理中のProvider切替の影響を受けないようにする。
7. `normalized_input` とlegacy `kana` にraw textを代入しない。実際の正規化結果をChunkまたは
   ProviderResultへ持たせる。
8. OpenAI Responses APIでは常に `store: false` を送る。

### 主な対象

- `src/uttate/input_rules.py`
- `src/uttate/conversion/direct.py`
- `src/uttate/conversion/core.py`
- `src/uttate/conversion/response_parser.py`
- `src/uttate/pipeline/queue.py`
- `src/uttate/models.py`
- `src/uttate/ui/main_window.py`
- `src/uttate/providers/openai.py`
- 関連テストとAPI flow文書

### 完了条件

- placeholderの欠落・重複・改変がすべて拒否される。
- bounded previous contextがLocal AI、Gemini、OpenAIへ同じ契約で渡る。
- datasetのnormalized/kana項目が実データに基づく。
- Stage 1とprotected inputの既存テストが維持される。

## 10. Phase 5: アプリ終了処理

### 目的

全UIを閉じた後に不可視プロセスが残らず、処理中workerも安全に終了するようにする。

### 作業

1. 明示的な `quit_application()` をwindow coordinatorへ追加する。
2. 最後の主要ウィンドウを閉じる操作と、終了メニュー/shortcutを同じ終了経路へ接続する。
3. 新規enqueueを停止してからworkerをdrainまたはcancelする。
4. UI thread上の固定2秒blockを避け、完了通知または明示的な終了確認を使う。
5. 終了時にSettingsWindowやDatasetReviewWindowを含む全管理ウィンドウを閉じる。
6. 「InputPanelだけを閉じてもReviewHUDは残す」という既存動作は維持する。

### 完了条件

- 全主要ウィンドウを閉じるとevent loopが終了する。
- 変換中の終了でクラッシュ、signal送信先消失、不可視worker残留がない。
- 個別ウィンドウのcloseとアプリ終了がテストで区別される。

## 11. Phase 6: テーマと配布物

### 目的

wheelインストール版でも標準テーマを利用でき、ユーザーテーマをread-onlyなpackage領域へ
書き込まないようにする。

### 作業

1. built-in themeを `src/uttate` 配下のpackage dataへ移す。
2. built-in資産を `importlib.resources` で読む。
3. ユーザー作成・import・生成CSSは `~/.uttate/themes` 等のconfig領域へ保存する。
4. built-in themeはread-only、ユーザーthemeは編集可能として扱う。
5. built-inとユーザーthemeの同名衝突規則を定義する。
6. Hatchのwheel/sdist include/excludeを明示し、不要な内部文書や作業ファイルを配布対象から外す。
7. wheelを展開した隔離環境でtheme presetとCSSを確認するsmoke testを追加する。

### 完了条件

- 展開wheelだけでdefault/paper/glass themeとbase CSSを読める。
- site-packagesへの書込みを行わない。
- source checkout、editable install、wheel installで同じテーマ選択結果になる。

## 12. Phase 7: Provider切替とUI責務分離

### 目的

重大修正を固定した後、巨大UIクラスの責務を段階的に分離する。

### 抽出候補

- `WindowCoordinator`: トップレベルウィンドウの生成、再利用、focus、always-on-top、終了
- `ProviderSession`: Provider生成、切替、永続化、失敗時rollback、表示同期
- `ReviewController`: review selection、candidate edit、accept/reject/reconvert
- `DatasetReviewService`: candidate記録、status、redaction、summary、export
- Settings tab別Widget/Presenter: General、Appearance、HUD、Dataset、Prompts、Shortcuts

### 作業原則

1. `MainWindow` はcomposition rootとして残す。
2. 一度に1責務だけを抽出する。
3. Signal/Slot境界を先にテストしてから移す。
4. Provider切替は「生成成功後に、settings、queue、両selector、保存」を一括commitする。
5. 失敗時はInputPanelとProviderPanelの両方を直前状態へ戻す。
6. 既存の独立トップレベルウィンドウを親子Widgetへ統合しない。

### 完了条件

- `MainWindow` がdatasetファイルI/OやProvider固有生成を直接行わない。
- `SettingsWindow` がテーマpackage I/Oやprompt保存処理を直接抱えない。
- Provider切替が再起動後も維持され、失敗時にUI表示が分裂しない。
- 全UIテストが維持される。

## 13. Phase 8: 品質ゲートと文書整理

### 作業

1. 現在format checkに失敗する18ファイルを、機能変更と分離した単独作業で整形する。
2. type checkerとしてPyrightまたはmypyを導入し、まずconfig、models、dataset境界を対象にする。
3. pytest coverageを導入し、初期値は現状値を下回らない閾値にする。
4. Provider障害テストを追加する。
   - timeout
   - RequestError
   - 429 / 5xx
   - 不正JSON
   - 空候補
5. Dataset BuilderのCSV、空入力、seed、mutation、再現性、CLI境界テストを追加する。
6. Qtテストの固定sleepをsignal待ちまたは同期primitiveへ置き換える。
7. Project B / branch / Mock Providerの古い記述を現行main向けに整理する。
8. `promptsf` は即時renameせず、旧パス読込みと新パス移行を含む別migrationとして扱う。
9. compatibility re-export shimは0.2.0まで残し、deprecatedとして明記してから削除する。
   旧計画文書は削除せず、`docs/history/`へ移動するか冒頭で履歴資料と明記する。

### 完了条件

- lint、format、typecheck、pytest、wheel smoke testがすべて成功する。
- README、API flow、dataset文書が実装と一致する。
- 古い計画文書は「履歴」か「現行仕様」かが明示される。

## 14. Phaseごとの共通検証

PowerShellでリポジトリルートから実行する。

```powershell
$env:UV_PYTHON_INSTALL_DIR = Join-Path (Get-Location) ".uv-python"
$env:UV_CACHE_DIR = Join-Path (Get-Location) ".uv-cache"
$env:UV_PROJECT_ENVIRONMENT = Join-Path (Get-Location) ".venv"
$env:QT_QPA_PLATFORM = "offscreen"

uv run --offline ruff check .
uv run --offline ruff format --check .
uv run --offline pytest
uv build --offline
```

Phaseの対象テストを先に実行し、その後に全テストを実行する。ネットワークを使う実APIテストは
通常テストへ混ぜず、明示的なopt-inにする。

## 15. Terraからの報告要件

各Phase完了時に次を報告する。

- 変更した問題IDと目的
- 変更ファイルと各ファイルの役割
- 旧データ・旧設定への互換性とmigration結果
- 実行したテスト、lint、format、buildと結果
- 実行しなかった確認と理由
- 残ったリスク、次Phaseへ渡す判断
- 参照した差分スナップショットの生成時刻と精度

Git操作は行わない。差分確認が必要な場合は、人間に `export-diff.ps1` の実行を依頼する。

## 16. 確定した判断

1. 内容がある旧 `capture_store_path` は新しいreview形式へ移行する。
2. `save_conversion_history` は実装する。
3. `allow_non_anonymized_export` は完全に禁止し、設定とUIから削除する。
4. OpenAI Responses APIへ常に `store: false` を付ける。
5. compatibility shimは0.2.0まで保持する。旧計画文書は履歴資料として残す。

これらは実装前に確定した方針である。各Phaseは、安全側の既定値と既存UI契約を維持しながら
この判断を変更せずに進める。方針変更が必要になった場合は、実装を止めて人間の判断を求める。
