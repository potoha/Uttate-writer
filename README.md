# Uttate Writer

Uttate Writerは、ローマ字・ひらがな・英単語・タイポが混ざったラフ入力を、思考を止めずに書いた後で自然な日本語へ変換・レビューするデスクトップアプリです。

このブランチは **Project B / API Provider Branch** です。ローカル小型モデル用のStage分割パイプラインはいったんMVP本線から外し、Gemini APIやOpenAI APIを差し替え可能なProviderとして扱う設計へ整理しています。

現在の実装状態:

- 標準Providerは `mock`
- `Enter` でチャンクを送信し、UIを止めずに変換
- `run.bat` でローカル環境から起動
- MockProviderで候補A/Bを表示
- Gemini Providerは実装済み
- OpenAI Providerは実装済み
- LM Studio / OpenAI互換Providerは実装済み
- UI上部で Mock / LM Studio / OpenAI / Google Gemini を切り替え可能
- `.env` にAPIキーを置けるが、実ファイルはGit管理外
- QLoRAなどの追加学習に使う教師データ作成CLI `uttate-curate` / `uttate-dataset` を追加

## Quickstart

```powershell
.\scripts\bootstrap.ps1
.\run.bat
```

セットアップスクリプトは、Python 3.12、仮想環境、キャッシュをすべてこのプロジェクト内へ作成します。グローバルにインストール済みのPythonやpipは使用・変更しません。

PowerShellから開発用スクリプトで起動する場合は、従来どおり次のコマンドも使えます。

```powershell
.\scripts\run.ps1
```

作成されるローカル環境:

```text
.uv-python/  uv管理のPython 3.12
.venv/       Uttate専用の仮想環境
.uv-cache/   Uttate専用のパッケージキャッシュ
```

## APIキー

ローカルのAPIキーは `.env` に置きます。`.env` は `.gitignore` に入っているため、リポジトリへコミットされません。

OSS向けの雛形は `.env.example` です。

```env
UTTATE_PROVIDER=mock
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash-lite
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5-nano
OPENAI_BASE_URL=https://api.openai.com/v1
LMSTUDIO_BASE_URL=http://127.0.0.1:1234/v1
LMSTUDIO_API_KEY=lm-studio
LMSTUDIO_MODEL=
```

注意:

- 実APIキーをREADME、Issue、ログ、テストデータへ貼らないでください。
- API Providerを使う場合、入力テキストは選択したAPI事業者に送信されます。
- Geminiを使う場合は `.env` で `UTTATE_PROVIDER=gemini` に変更し、`GEMINI_API_KEY` に自分のキーを入れてください。
- OpenAIを使う場合は `.env` で `UTTATE_PROVIDER=openai` に変更し、`OPENAI_API_KEY` に自分のキーを入れてください。
- LM StudioはOpenAI互換APIとして扱います。既定では `http://127.0.0.1:1234/v1` を見ます。

Geminiのローカル設定例:

```env
UTTATE_PROVIDER=gemini
GEMINI_API_KEY=your_api_key
GEMINI_MODEL=gemini-2.5-flash-lite
```

OpenAIのローカル設定例:

```env
UTTATE_PROVIDER=openai
OPENAI_API_KEY=your_api_key
OPENAI_MODEL=gpt-5-nano
OPENAI_BASE_URL=https://api.openai.com/v1
```

LM Studioのローカル設定例:

```env
UTTATE_PROVIDER=lmstudio
LMSTUDIO_BASE_URL=http://127.0.0.1:1234/v1
LMSTUDIO_API_KEY=lm-studio
LMSTUDIO_MODEL=
```

`LMSTUDIO_MODEL` が空の場合、Providerは `/v1/models` の先頭モデルを自動検出します。

## 操作

- 入力欄で `Enter`: 現在のラフ入力をチャンクとして送信
- 入力欄で `Shift+Enter`: 送信せずに改行
- 変換中も次のチャンクを入力可能
- 画面上部のAIセレクタ: `Mock` / `LM Studio` / `OpenAI` / `Google Gemini` を切り替え
- AIセレクタ横: 現在選択中のモデル名を表示
- 左の一覧でチャンクを選択すると、右のReviewに原文・候補A/B・不確実箇所を表示

### 特殊タグ

入力中にタグで囲むと、その範囲の変換方針を強制できます。

```text
\dedodamu\   カタカナにする: デドダム
= English=   英語のまま保持: English
$tokiori$    ひらがなにする: ときおり
```

タグ記号そのものを入力したい場合は、同じ記号を2回続けます。

```text
\\  -> \ 1文字
==  -> = 1文字
$$  -> $ 1文字
```

## Dataset Curator / Builder

Uttate Writerは、入力ログを自動で教師データ化しません。
すべての入力はデフォルトでは不採用で、ユーザーが明示的に候補へ追加し、安全確認したものだけをseedとしてexportします。

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

## テスト

```powershell
.\scripts\test.ps1
```

## Lintとフォーマット

```powershell
.\scripts\lint.ps1
```

自動修正・整形が必要な場合は、ローカル仮想環境のRuffを直接使います。

```powershell
.\.venv\Scripts\ruff.exe check --fix .
.\.venv\Scripts\ruff.exe format .
```

## 設定

設定ファイルの標準保存先は次のとおりです。

```text
%USERPROFILE%\.uttate\settings.json
```

環境変数 `UTTATE_CONFIG_DIR` を指定すると、保存ディレクトリを変更できます。APIキーはsettings.jsonへ保存せず、環境変数または `.env` から読み込みます。

## プロジェクト文書

- [プロダクト仕様](project.md)
- [Project B計画](project-b-api.md)
- [MVPスコープ](docs/PROJECT_SCOPE.md)
- [実装計画](docs/IMPLEMENTATION_PLAN.md)
- [Dataset Builder Add-on](docs/DATASET_BUILDER.md)
