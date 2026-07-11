# Agent 運用ルール

このリポジトリで作業する AI agent / Codex は、ソースコードやドキュメントの編集、調査、テスト補助を行う。ただし、Git の状態確認・履歴操作・リモート操作は人間が行う。

## 基本方針

- ファイルの作成・編集・削除は、依頼内容に必要な範囲で行う。
- テスト、lint、format、ビルドなど、Git 以外の検証コマンドは必要に応じて実行してよい。
- Git コマンドは実行しない。
- Git の状態や差分が必要な場合は、人間に実行してほしいコマンドを具体的に提示し、その出力を貼ってもらう。
- 作業後は、変更内容、検証結果、人間が実行すべき Git 手順を明示する。
- APIへ送る前処理、送信payload、prompt、応答復元、UI表示の流れを変更した場合は、同じ作業内で `docs/API_PREPROCESSING_FLOW.md` も更新する。
- `docs/REFACTORING_PLAN.md` の問題を実装する場合は、Phase順序、制約、必須テスト、完了条件、Terraからの報告要件に従い、実装と文書の状態を同じ作業内で一致させる。

## 禁止する Git コマンド

以下を含むすべての Git コマンドを実行しない。

```bash
git status
git diff
git add
git commit
git push
git pull
git fetch
git checkout
git switch
git branch
git merge
git rebase
git reset
git restore
git stash
git clean
git config
git remote
git tag
```

`git status` と `git diff` も agent 側では実行しない。必要な場合は、下記のように人間へ依頼する。

## Git 情報が必要な場合の依頼方法

Git の状態確認が必要な場合、agent は次のように依頼する。

```text
Git の状態を確認したいので、リポジトリのルートで次を実行して、出力を貼ってください。

```bash
git status -sb
```
```

差分確認が必要な場合、agent は次のように依頼する。

```text
差分を確認したいので、リポジトリのルートで次を実行して、出力を貼ってください。

```bash
git diff -- .
```
```

変更ファイルの概要だけ必要な場合、agent は次のように依頼する。

```text
変更ファイルの概要を確認したいので、リポジトリのルートで次を実行して、出力を貼ってください。

```bash
git diff --stat
```
```

## 作業完了時の報告形式

作業が終わったら、agent は必ず次の形式で報告する。

```text
## 変更内容
- 変更した内容を簡潔に説明する。

## 変更ファイル
- `path/to/file`: 変更理由

## 検証
- 実行したテスト・lint・ビルドなど
- 実行していない場合は、その理由

## 人間が実行する Git 手順
リポジトリのルートで次を実行してください。

```bash
git status -sb
git diff -- .
git add <変更ファイル>
git commit -m "<推奨コミットメッセージ>"
git push
```
```

## コミットメッセージ案

agent は、作業内容に応じてコミットメッセージ案を 1〜3 個提示する。

例:

```text
- docs: update agent operation rules
- fix: correct conversion pipeline error handling
- feat: add API-based conversion flow
```

## 注意

- agent は Git の実行結果を推測しない。
- `git status` や `git diff` の内容が必要な場合は、必ず人間にコマンド実行と出力共有を依頼する。
- 競合、未追跡ファイル、ブランチ差分、push 失敗などの判断は、人間が共有した Git 出力に基づいて行う。
- 破壊的な操作が必要そうな場合でも、agent は Git コマンドを実行せず、理由と手順だけを説明する。
