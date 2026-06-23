# Uttate Writer

Uttateは、ローマ字・ひらがな・英単語・タイポが混ざったラフ入力を、思考を止めずに書いた後で自然な日本語へ変換・レビューするデスクトップアプリです。

現在はM3（LM Studio接続とStage 1読み正規化）まで実装されています。通常起動ではローカルのLM Studioを使ってラフ入力を読みへ正規化し、`normalized` 状態でレビューできます。M2の決定的なMockもテスト用として残しています。

## M3のLM Studio設定

既定値は現在の開発環境に合わせています。

```json
{
  "provider": {
    "type": "lmstudio",
    "base_url": "http://127.0.0.1:1234/v1",
    "api_key": "lm-studio",
    "model": "",
    "timeout_seconds": 60,
    "reasoning_effort": "none"
  }
}
```

`model` が空の場合は `/v1/models` から最初のロード済みモデルを自動検出します。現在の開発環境では `qwen/qwen3.5-9b` が検出されます。モデル名を設定した場合は自動検出せず、その値を使用します。

`qwen/qwen3.5-9b` では `reasoning_effort` を `none` にし、LM Studioの `json_schema` 構造化出力を使用します。設定ファイルが存在しない場合も上記が既定値です。

## M2の操作

- 入力欄で `Enter`: 現在のラフ入力をチャンクとして送信
- 入力欄で `Shift+Enter`: 送信せずに改行
- 変換中も次のチャンクを入力可能
- 左の一覧でチャンクを選択すると、右のReviewに原文・正規化結果・候補A/Bを表示

M3の実LM Studio経路はStage 1で停止するため、候補A/Bはまだ生成しません。辞書検索はM4、漢字かな候補の生成はM5、採用・編集操作はM6で追加します。

## 必要なもの

- Windows PowerShell
- [`uv`](https://docs.astral.sh/uv/)

グローバルにインストール済みのPythonやpipは使用・変更しません。セットアップスクリプトがPython 3.12、仮想環境、キャッシュをすべてこのプロジェクト内へ作成します。

## 初回セットアップ

```powershell
.\scripts\bootstrap.ps1
```

作成されるローカル環境:

```text
.uv-python/  uv管理のPython 3.12
.venv/       Uttate専用の仮想環境
.uv-cache/   Uttate専用のパッケージキャッシュ
```

これらはGitの管理対象外です。

## アプリの起動

セットアップ後は、ローカルのPython 3.12環境を明示する次の1コマンドで起動できます。

```powershell
.\scripts\run.ps1
```

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

既定値は `uttate.config.AppSettings` に定義されています。設定ファイルの標準保存先は次のとおりです。

```text
%USERPROFILE%\.uttate\settings.json
```

環境変数 `UTTATE_CONFIG_DIR` を指定すると、保存ディレクトリを変更できます。APIキーは今後もリポジトリへコミットしません。

## プロジェクト文書

- [プロダクト仕様](project.md)
- [MVPスコープ](docs/PROJECT_SCOPE.md)
- [実装計画](docs/IMPLEMENTATION_PLAN.md)
