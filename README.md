# Uttate Writer

Uttate Writerは、ローマ字・ひらがな・英単語・タイポが混ざったラフ入力を、あとから自然な日本語へ変換・レビューするためのデスクトップアプリです。

日本語IMEの変換待ちで思考が止まる前に、まず雑に書き続ける。その後でAIに候補を出させ、人間がレビューして整える。Uttate Writerは、その書き方を試すためのMVPです。

```text
kyouhaAPIwotukattehenkannosikennwosuru
今日はAPIを使って、変換のテストをする。
```

## これは何か

このリポジトリは **Project B / API Provider Branch** です。
2026年7月6日：mainとマージしました。今後はmainブランチで開発を進めます。


もともとの青写真は、ローマ字・かな・英語混じりのラフ入力を日本語へ変換するための専用小型モデルを作り、QLoRA / SFTなどで追加学習し、最終的にはオンプレミスまたは完全ローカル環境で使える日本語入力支援ツールにすることです。

ただし、いきなり専用モデルへ進む前に、現在のMVPではProviderを差し替えられる形にして、まず「この入力体験は本当に楽になるのか」を検証しています。Gemini API / OpenAI API / LM Studio互換APIなどを使って、入力、変換、レビュー、データセット作成の流れを触れる状態にしています。

作者はAI支援・ノーコード寄りの進め方でこのMVPを育てている文系学生です。コードや設計にはまだ荒い部分がありますが、だからこそ早めに公開し、実際に触った人の感想、失敗例、改善案を集めたいと考えています。

## どういう人向けか

- 日本語IMEの変換待ちで思考が止まる感覚がある人
- ローマ字、かな、英単語が混ざったまま先に文章を書きたい人
- 誤字やタイポを気にせず、あとからまとめて整えたい人
- 日本語入力、IME、LLM、ローカルAI、小型モデルのファインチューニングに興味がある人
- 荒削りなOSSを触りながら、一緒に育ててみたい人

## 現在できること

- `Enter` で入力チャンクを送信し、UIを止めずに変換
- 変換中も次のチャンクを入力可能
- 右側のReviewで原文、候補、不確実箇所を確認
- UI上部で `Local AI` / `OpenAI` / `Google Gemini` を切り替え
- `.env` でProvider、モデル、APIキーを設定
- `local_ai` ProviderでLM StudioのOpenAI互換APIを使った読み転写を実行
- Gemini Provider / OpenAI Providerで自然文候補を生成
- 特殊タグで一部の語をカタカナ、英語、ひらがなとして保護
- QLoRA / SFT向けの教師データ作成CLI `uttate-curate` / `uttate-dataset` を利用

## まだ荒いところ

- UI / UXは実験段階です。
- 変換品質はProviderやモデルに依存します。
- 専用小型モデルはまだ本格運用前です。
- セキュリティレビューや配布体験は未整備です。
- 仕様や画面構成は変わる可能性が高いです。

公開時点では、安定した完成品というより「触れる研究プロトタイプ」に近い位置づけです。

## Quickstart

Windows + PowerShellを前提にしています。

```powershell
.\scripts\bootstrap.ps1
.\run.bat
```

セットアップスクリプトは、Python 3.12、仮想環境、キャッシュをすべてこのプロジェクト内へ作成します。グローバルにインストール済みのPythonやpipは使用・変更しません。

PowerShellから開発用スクリプトで起動する場合は、次のコマンドも使えます。

```powershell
.\scripts\run.ps1
```

作成されるローカル環境:

```text
.uv-python/  uv管理のPython 3.12
.venv/       Uttate専用の仮想環境
.uv-cache/   Uttate専用のパッケージキャッシュ
```

## APIキーとProvider設定

ローカルのAPIキーは `.env` に置きます。`.env` は `.gitignore` に入っているため、リポジトリへコミットされません。

OSS向けの雛形は `.env.example` です。

```env
UTTATE_PROVIDER=local_ai

GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash-lite

OPENAI_API_KEY=
OPENAI_MODEL=gpt-5-nano
OPENAI_BASE_URL=https://api.openai.com/v1

LMSTUDIO_BASE_URL=http://127.0.0.1:1234/v1
LMSTUDIO_API_KEY=lm-studio
LMSTUDIO_MODEL=

UTTATE_TIMEOUT_SECONDS=30
UTTATE_PREVIOUS_CONTEXT_CHARS=600
```

注意:

- 実APIキーをREADME、Issue、ログ、テストデータへ貼らないでください。
- Gemini / OpenAIなどのAPI Providerを使う場合、入力テキストと直前文脈は選択したAPI事業者に送信されます。
- APIキーはsettings.jsonへ保存せず、環境変数または `.env` から読み込みます。
- UI上の選択肢は `Local AI` に一本化しています。`local_ai` はLM StudioのOpenAI互換APIを接続先として使い、既定では `http://127.0.0.1:1234/v1` を見ます。

Geminiの設定例:

```env
UTTATE_PROVIDER=gemini
GEMINI_API_KEY=your_api_key
GEMINI_MODEL=gemini-2.5-flash-lite
```

OpenAIの設定例:

```env
UTTATE_PROVIDER=openai
OPENAI_API_KEY=your_api_key
OPENAI_MODEL=gpt-5-nano
OPENAI_BASE_URL=https://api.openai.com/v1
```

Local AIの設定例:

```env
UTTATE_PROVIDER=local_ai
LMSTUDIO_BASE_URL=http://127.0.0.1:1234/v1
LMSTUDIO_API_KEY=lm-studio
LMSTUDIO_MODEL=
```

`LMSTUDIO_MODEL` が空の場合、Providerは `/v1/models` の先頭モデルを自動検出します。

`local_ai` は自然文候補A/Bではなく、Stage 1の忠実な読み転写を `faithful_reading` 候補として返します。

API Providerへ送る前に、特殊タグで保護した文字列は `__UTTATE_PROTECTED_0__` のようなplaceholderへ置き換えます。タグ内の元文字列や変換後文字列はGemini / OpenAI / Local AIへ送らず、応答を検証した後にアプリ側で機械的に復元します。

また、入力画面で `Space` を押すと挿入される ` | ` はUttate rough-input separatorとして扱います。Local AI payloadには、この区切りごとの機械読み候補を2種類入れます。

- `mechanical_strict`: 確実にローマ字として読めるものだけ、かな・英語交じりに機械変換
- `mechanical_typo_tolerant`: 拗音・撥音・促音以外の母音/子音ペア規則から外れる語を、タイポまたは日本語以外の可能性として扱う補助候補

### Local AI prompt profile

Local AIに送るsystem promptは、起動時に次のYAMLから読み込まれます。

```text
%USERPROFILE%\.uttate\registry\promptsf\local_ai_prompts.yaml
```

このYAMLを起動中に直接編集しても、直ちには反映されません。反映されるのは次回起動時です。

起動中にpromptを変更したい場合は、`F12` の設定画面にあるLocal-AI promptからprofileを選択し、`適用する (Ctrl+R)` または `変更して閉じる (Ctrl+Enter)` を使ってください。この場合はYAMLへ保存され、現在のLocal AI Providerにも直ちに反映されます。

Local AIのモデル名が自動検出または設定されたとき、そのモデル専用profileがなければ自動作成されます。組み込みdefault promptが更新された場合、旧default promptのまま未編集だったprofileは新しいdefault promptへ追従します。独自編集済みのprofileは上書きしません。

## 操作

- 入力欄で `Enter`: 現在のラフ入力をチャンクとして送信
- 入力欄で `Shift+Enter`: 送信せずに改行
- 変換中も次のチャンクを入力可能
- 画面上部のAIセレクタ: `Local AI` / `OpenAI` / `Google Gemini` を切り替え
- AIセレクタ横: 現在選択中のモデル名を表示
- 左の一覧でチャンクを選択すると、右のReviewに原文・候補・不確実箇所を表示

### 特殊タグ

入力中にタグで囲むと、その範囲の変換方針を強制できます。

```text
\dedodamu\   カタカナにする: デドダム
= English=   英語のまま保持: English
$tokiori$    ひらがなにする: ときおり
```

Gemini / OpenAI / Local AI使用時、これらのタグ内文字列はAPIへ直接送られず、placeholderとして送信されます。復元はアプリ側で行います。

タグ記号そのものを入力したい場合は、同じ記号を2回続けます。

```text
\\  -> \ 1文字
==  -> = 1文字
$$  -> $ 1文字
```

## Dataset Curator / Builder

Uttate Writerは、入力ログを自動で教師データ化しません。

すべての入力はデフォルトでは不採用で、ユーザーが明示的に候補へ追加し、安全確認したものだけをseedとしてexportします。この仕組みは、将来的な専用小型モデルのファインチューニングへつなげるための入口です。

想定している教師データは、主に次の4種類です。

- 生データ: ローマ字・英語混じり・タイポ混じりのラフ入力
- 日本語化テキスト: ひらがな・カタカナ・英語が混ざった読み寄りテキスト
- 変換後テキストA: 入力内容に忠実な漢字かな交じり文
- 変換後テキストB: 文脈から自然に整えた漢字かな交じり文

候補を追加します。

```powershell
uv run uttate-curate add `
  --store data/candidates.jsonl `
  --raw "kyouhaAPIwotukattehenkannosikennwosuru" `
  --kana "きょうはAPIをつかってへんかんのしけんをする" `
  --literal "今日はAPIを使って変換の試験をする。" `
  --natural "今日はAPIを使って、変換のテストをする。"
```

公開可能なseedとして承認し、exportします。

```powershell
uv run uttate-curate approve `
  --store data/candidates.jsonl `
  --id cand_20260701_000001 `
  --public-safe

uv run uttate-curate export `
  --store data/candidates.jsonl `
  --output data/seeds.public.jsonl `
  --mode public
```

exportしたseedからSFT用JSONLを生成します。

```powershell
uv run uttate-dataset `
  --input data/seeds.public.jsonl `
  --output data/sft `
  --variants-per-seed 24 `
  --include-intermediate-task `
  --include-kana-tasks
```

詳細は [Dataset Builder Add-on](docs/DATASET_BUILDER.md) を参照してください。

## 開発と検証

テスト:

```powershell
.\scripts\test.ps1
```

Lintとフォーマット:

```powershell
.\scripts\lint.ps1
```

自動修正・整形が必要な場合は、ローカル仮想環境のRuffを直接使います。

```powershell
.\.venv\Scripts\ruff.exe check --fix .
.\.venv\Scripts\ruff.exe format .
```

設定ファイルの標準保存先:

```text
%USERPROFILE%\.uttate\settings.json
```

環境変数 `UTTATE_CONFIG_DIR` を指定すると、保存ディレクトリを変更できます。

## コミュニティにお願いしたいこと

Issue、感想、雑なアイデア、失敗報告、変換例、UI改善案などを歓迎します。

特に助かるもの:

- 実際に打ちにくい、または変換したいラフ入力の例
- 変換結果の成功例・失敗例
- Providerごとの挙動報告
- Windows環境での起動報告
- UI / UXの改善案
- 小型モデル化やデータセット設計への知見

## ロードマップ

短期:

- MVPとして使えるUI / UXを整える
- 入力、変換、レビュー、コピーの流れを気持ちよくする
- Gemini / OpenAI / LM Studio Providerの挙動を安定させる
- 失敗時の表示、ログ、設定まわりを改善する
- 触ってくれた人からフィードバックを集める

中期:

- seedデータの作成と公開可能な教師データ整備
- QLoRA / SFT向けのデータセット生成を改善
- 小型モデルでの変換品質を検証
- Stage分割パイプラインを再整理
- ローカル推論で実用に近い速度と品質を目指す

最終的にやりたいこと:

- 専用小型モデルによるラフ入力から自然な日本語への変換
- オンプレミス / 完全ローカルでの実行
- APIに入力テキストを送らずに使える構成
- 日本語入力の「変換待ち」を減らす、新しいIME的な書き方の実験

## プロジェクト文書

- [プロダクト仕様](project.md)
- [Project B計画](project-b-api.md)
- [MVPスコープ](docs/PROJECT_SCOPE.md)
- [実装計画](docs/IMPLEMENTATION_PLAN.md)
- [Dataset Builder Add-on](docs/DATASET_BUILDER.md)
- [Conversion Modularization](docs/CONVERSION_MODULARIZATION.md)

## License

Apache License 2.0です。詳細は [LICENSE](LICENSE) を参照してください。
