# Uttate Writer

Uttateは、ローマ字・ひらがな・英単語・タイポが混ざったラフ入力を、思考を止めずに書いた後で自然な日本語へ変換・レビューするデスクトップアプリです。

現在はM0（開発基盤）まで実装されています。空のPySide6ウィンドウ、設定の既定値とJSON読み書き、テスト・Lint環境を含みます。

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
