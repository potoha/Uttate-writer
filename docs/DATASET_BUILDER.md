# Dataset Builder Add-on

Uttate Writerの変換モデルをQLoRAなどで追加学習するための教師データ作成アドオンです。

このアドオンは、少数の人間確認済みseedデータから、入力ミス・母音抜け・ローマ字表記揺れ・英語日本語混じり文のバリエーションを作り、SFT向けのChatML風JSONLを生成します。

重要な方針は、**入力だけを水増しし、正解テキストはseedの値をそのまま使う**ことです。LLMやランダム処理で正解側を増やすと、誤った変換を学習させる危険があります。

## seedデータ形式

`.jsonl`, `.json`, `.csv` に対応しています。各レコードには次の4種類のテキストを入れます。

```json
{"id":"ex001","raw":"kyouhaAPIwotukattehenkannosikennwosuru","kana":"きょうはAPIをつかってへんかんのしけんをする","literal":"今日はAPIを使って変換の試験をする。","natural":"今日はAPIを使って、変換のテストをする。"}
```

| field | 内容 |
| --- | --- |
| `raw` | 生データ。ローマ字英語混じり、文節区切りスペースなしの文 |
| `kana` | 日本語化テキスト。英語かな混じり文 |
| `literal` | 変換後テキストA。生データの内容に忠実な漢字仮名交じり文 |
| `natural` | 変換後テキストB。文脈から自然な日本語に訂正した漢字仮名交じり文 |

`id` は任意ですが、評価データの漏洩を避けるため、実運用では安定したIDを付けてください。

## 使い方

```powershell
uv run uttate-dataset `
  --input data/seeds.jsonl `
  --output data/sft `
  --variants-per-seed 24 `
  --include-intermediate-task `
  --include-kana-tasks
```

Pythonモジュールとして直接実行することもできます。

```powershell
uv run python -m uttate.addons.dataset_builder `
  --input data/seeds.jsonl `
  --output data/sft
```

## 出力

```text
data/sft/
  train.jsonl
  valid.jsonl
  test.jsonl
  manifest.json
```

各JSONLは次のような `messages` 形式です。

```json
{
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "次の生データを..."},
    {"role": "assistant", "content": "今日はAPIを使って、変換のテストをする。"}
  ]
}
```

## 生成されるタスク

標準では次の3種類を作ります。

- `raw_to_literal`: 生データ → 変換後テキストA
- `raw_to_natural`: 生データ → 変換後テキストB
- `raw_to_both`: 生データ → A/Bを含むJSON

`--include-intermediate-task` を付けると、次も作ります。

- `raw_to_kana`: 生データ → 日本語化テキスト

`--include-kana-tasks` を付けると、次も作ります。

- `kana_to_literal`: 日本語化テキスト → 変換後テキストA
- `kana_to_natural`: 日本語化テキスト → 変換後テキストB
- `kana_to_both`: 日本語化テキスト → A/Bを含むJSON

## データ分割

train/valid/testへの分割は、seedレコード単位で先に行います。その後に各seedから入力バリエーションを生成します。

同じseed由来の入力揺れがtrainとvalid/testに混ざると、評価が不自然に高く見えるためです。

## 主なオプション

```text
--variants-per-seed       seedごとの入力揺れ数
--max-noise-ops           raw入力1件に入れる最大ノイズ操作数
--protected-terms         壊しすぎない英語/API用語のカンマ区切りリスト
--train-ratio             train比率
--valid-ratio             valid比率
--test-ratio              test比率
--seed                    乱数seed
```

MVPでは、まず100〜300件程度の人間確認済みseedを作り、各20〜50 variantを生成するのが現実的です。

## Dataset Curator: ホワイトリスト方式

Uttate Writerでは、入力ログを自動収集して教師データにする方針は採りません。
すべての入力はデフォルトでは不採用です。

教師データにしてよいものだけを、ユーザーが明示的に `candidate` として追加します。
その後、人間が安全チェックを完了し、`approved` にしたものだけをseedとしてexportできます。

基本方針:

```text
原則:
  すべての入力はデータセット不採用

例外:
  ユーザーが明示的に「教師データ候補に追加」し、
  さらにレビュー画面またはCLIで安全チェックを完了したものだけexport対象にする
```

匿名化で安全にするのではなく、最初から公開・共有してよい入力だけを採用します。
水増しは、必ず安全確認済みseedをexportした後に行います。

### Candidate形式

`uttate-curate add` は、まだ学習用に採用されていない中間データをJSONLへ保存します。

```json
{
  "id": "cand_20260701_000001",
  "status": "candidate",
  "raw": "kyouhaAPIwotukattehenkannosikennwosuru",
  "kana": "きょうはAPIをつかってへんかんのしけんをする",
  "literal": "今日はAPIを使って変換の試験をする。",
  "natural": "今日はAPIを使って、変換のテストをする。",
  "checks": {
    "no_personal_info": false,
    "no_private_project": false,
    "no_sensitive_content": false,
    "public_safe": false
  },
  "notes": ""
}
```

### Curator CLI

候補を追加します。

```powershell
uv run uttate-curate add `
  --store data/candidates.jsonl `
  --raw "kyouhaAPIwotukattehenkannosikennwosuru" `
  --kana "きょうはAPIをつかってへんかんのしけんをする" `
  --literal "今日はAPIを使って変換の試験をする。" `
  --natural "今日はAPIを使って、変換のテストをする。"
```

候補を確認します。

```powershell
uv run uttate-curate list --store data/candidates.jsonl
```

公開可能として承認します。

```powershell
uv run uttate-curate approve `
  --store data/candidates.jsonl `
  --id cand_20260701_000001 `
  --public-safe
```

個人ローカル学習用としてのみ承認します。

```powershell
uv run uttate-curate approve `
  --store data/candidates.jsonl `
  --id cand_20260701_000001 `
  --private-only
```

不採用にします。

```powershell
uv run uttate-curate reject `
  --store data/candidates.jsonl `
  --id cand_20260701_000001 `
  --notes "contains private project details"
```

簡易リスク検出を実行します。

```powershell
uv run uttate-curate check --store data/candidates.jsonl
```

### public exportとprivate export

public exportは、Hugging Face Datasetなどで共有する可能性があるseedを作るためのモードです。
次の条件をすべて満たす候補だけを出力します。

```text
status == "approved"
checks.no_personal_info == true
checks.no_private_project == true
checks.no_sensitive_content == true
checks.public_safe == true
```

```powershell
uv run uttate-curate export `
  --store data/candidates.jsonl `
  --output data/seeds.public.jsonl `
  --mode public
```

private exportは、ローカル個人学習用のseedを作るためのモードです。
最低条件は `status == "approved"` です。

```powershell
uv run uttate-curate export `
  --store data/candidates.jsonl `
  --output data/seeds.private.jsonl `
  --mode private
```

### public datasetに含めるべきでない例

次のような情報は、public datasetや共同ファインチューニング用データに含めないでください。

```text
個人名
住所
学校名
会社名
就活状況
未公開作品
研究メモ
APIキー
アクセストークン
病歴
服薬
家庭事情
特定個人を推測できる出来事
```
