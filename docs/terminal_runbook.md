# ターミナルにコピペできるAI伴奏運用Runbook

## 目的

ユーザーがローカル環境のターミナルへそのまま貼り付けて動かせる形で、セットアップ、確認、スクレイピング、RAG、スコアリング、品質チェックを進める。
Codexは作業提案や完了報告で、できるだけ1つのbashブロックにまとまったコマンドを提示する。

## 運用ルール

- コマンドはホームディレクトリから貼り付けても、`Web-Scraping/pyproject.toml` を探してリポジトリルートへ移動する形にする。
- 変数を書き換えれば再利用できる形にする。
- `.env`、APIキー、個人情報、取得データ、RAG DB、SQLite DBはコミットしない。
- Webサイト確認は必ず `fetch-url --dry-run` でrobots.txt確認を先に行う。
- `fetch-url --extract-text --save-text` は、robots.txtで許可されたHTML取得結果を本文テキストに正規化して保存する。
- Gemini APIを使う作業は、必ず `LlmService` 経由かつ明示的な `--call-real-api` 付きに限定する。
- 投資判断は断定せず、自動売買は行わない。

## 0. リポジトリへ移動する共通ブロック

`fatal: not a git repository` や Python 2.7 の `No module named pytest` が出た場合は、ホームディレクトリで実行している可能性が高い。
まず次を貼り付けて、`pyproject.toml` があるリポジトリルートへ移動する。

```bash
if test -f pyproject.toml; then
  REPO_DIR="$PWD"
else
  REPO_MARKER="$(find "$HOME" -name pyproject.toml -path "*/Web-Scraping/pyproject.toml" -print 2>/dev/null | head -n 1)"
  REPO_DIR="$(dirname "$REPO_MARKER")"
fi
cd "$REPO_DIR"
pwd
test -f pyproject.toml
git status --short
```

## 1. 初回セットアップ

```bash
if test -f pyproject.toml; then
  REPO_DIR="$PWD"
else
  REPO_MARKER="$(find "$HOME" -name pyproject.toml -path "*/Web-Scraping/pyproject.toml" -print 2>/dev/null | head -n 1)"
  REPO_DIR="$(dirname "$REPO_MARKER")"
fi
cd "$REPO_DIR"
pwd
test -f pyproject.toml

python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

## 2. 毎回の作業開始チェック

```bash
if test -f pyproject.toml; then
  REPO_DIR="$PWD"
else
  REPO_MARKER="$(find "$HOME" -name pyproject.toml -path "*/Web-Scraping/pyproject.toml" -print 2>/dev/null | head -n 1)"
  REPO_DIR="$(dirname "$REPO_MARKER")"
fi
cd "$REPO_DIR"
test -f pyproject.toml
source .venv/bin/activate

git status --short
git branch --show-current
python --version

# 新しいCLIコマンドがinvalid choiceになる場合は、editable installを更新する
python -m pip install -e '.[dev]' --force-reinstall
hash -r

investment-assistant budget --json
investment-assistant fetch-job --help
investment-assistant rag-index-dir --help
investment-assistant rag-search-job --help

# それでもinvalid choiceが出る場合は、作業ツリーが古い可能性を確認する
python - <<'PY'
import investment_assistant.cli as cli
print(cli.__file__)
PY
rg -n 'fetch-job|rag-index-dir|rag-search-job' src/investment_assistant/cli.py
```

## 3. Webサイトを安全に確認してRAGに入れる

`TARGET_URL` と `QUERY` だけ差し替える。
`--dry-run` の結果が `allowed_by_robots: true` のときだけ、次の保存ステップで本文が保存される。
`robots_unavailable` や `blocked_by_robots` の場合は保存されず、無理に取得しない。

```bash
if test -f pyproject.toml; then
  REPO_DIR="$PWD"
else
  REPO_MARKER="$(find "$HOME" -name pyproject.toml -path "*/Web-Scraping/pyproject.toml" -print 2>/dev/null | head -n 1)"
  REPO_DIR="$(dirname "$REPO_MARKER")"
fi
cd "$REPO_DIR"
test -f pyproject.toml
source .venv/bin/activate

mkdir -p local_docs
TARGET_URL="https://example.com/"
OUTPUT_PATH="local_docs/example.txt"
QUERY="Example Domain"

investment-assistant fetch-url \
  --url "$TARGET_URL" \
  --dry-run

investment-assistant fetch-url \
  --url "$TARGET_URL" \
  --preview-chars 500 \
  --extract-text \
  --include-metadata \
  --save-text "$OUTPUT_PATH"

if test -f "$OUTPUT_PATH"; then
  investment-assistant rag-index-dir --path local_docs
  investment-assistant rag-search --query "$QUERY" --limit 5
  investment-assistant rag-search --query "$QUERY" --limit 5 --format table
  investment-assistant rag-search \
    --query "$QUERY" \
    --limit 5 \
    --format table \
    --columns rank,source_url,fetched_at,text_preview
  investment-assistant rag-answer-context --query "$QUERY" --limit 5
else
  echo "保存ファイルがないためRAG indexをスキップしました: $OUTPUT_PATH"
fi
```


## 3.5 複数URLをfetch-jobでまとめて保存してRAGに入れる

ジョブファイルを使うと、複数URLを同じ手順で安全に保存できる。
まず `--dry-run` でrobots.txt確認だけを行い、その後に保存、最後に `rag-index-dir` でまとめてindexする。

```bash
if test -f pyproject.toml; then
  REPO_DIR="$PWD"
else
  REPO_MARKER="$(find "$HOME" -name pyproject.toml -path "*/Web-Scraping/pyproject.toml" -print 2>/dev/null | head -n 1)"
  REPO_DIR="$(dirname "$REPO_MARKER")"
fi
cd "$REPO_DIR"
test -f pyproject.toml
source .venv/bin/activate

mkdir -p local_docs local_jobs
cat > local_jobs/fetch_job.yaml <<'YAML'
sources:
  - name: example
    url: https://example.com/
    output_path: local_docs/example.txt
    query_hint: Example Domain
    extract_text: true
    include_metadata: true
    preview_chars: 500
YAML

investment-assistant fetch-job --path local_jobs/fetch_job.yaml --dry-run
investment-assistant fetch-job --path local_jobs/fetch_job.yaml
investment-assistant rag-index-dir --path local_docs
investment-assistant rag-search --query "Example Domain" --limit 5
investment-assistant rag-search --query "Example Domain" --limit 5 --format table
mkdir -p local_reports
investment-assistant rag-search-job \
  --path local_jobs/fetch_job.yaml \
  --format table \
  --columns rank,source_url,fetched_at,text_preview \
  --save-report local_reports/rag_search_job.md
investment-assistant rag-search-job \
  --path local_jobs/fetch_job.yaml \
  --format json \
  --save-report local_reports/rag_search_job.json
investment-assistant rag-answer-context --query "Example Domain" --limit 5
```

## 4. ローカル文書だけでRAGを試す

ネットワークを使わずにRAGの動作確認をする。

```bash
if test -f pyproject.toml; then
  REPO_DIR="$PWD"
else
  REPO_MARKER="$(find "$HOME" -name pyproject.toml -path "*/Web-Scraping/pyproject.toml" -print 2>/dev/null | head -n 1)"
  REPO_DIR="$(dirname "$REPO_MARKER")"
fi
cd "$REPO_DIR"
test -f pyproject.toml
source .venv/bin/activate

mkdir -p local_docs
cat > local_docs/sample.md <<'DOC'
# サンプル投資メモ

これはRAGテスト用のローカル文書です。
投資判断はユーザー本人が行います。
自動売買は行いません。
DOC

investment-assistant rag-index --path local_docs/sample.md
investment-assistant rag-index-dir --path local_docs
investment-assistant rag-search --query "投資判断" --limit 5
investment-assistant rag-search --query "投資判断" --limit 5 --format table
investment-assistant rag-answer-context --query "自動売買" --limit 5
```

## 5. 投資スコアリングをローカルCSVで試す

Gemini API、外部API、証券口座、実注文機能は使わない。

```bash
if test -f pyproject.toml; then
  REPO_DIR="$PWD"
else
  REPO_MARKER="$(find "$HOME" -name pyproject.toml -path "*/Web-Scraping/pyproject.toml" -print 2>/dev/null | head -n 1)"
  REPO_DIR="$(dirname "$REPO_MARKER")"
fi
cd "$REPO_DIR"
test -f pyproject.toml
source .venv/bin/activate

investment-assistant scoring-validate --path examples/funds.csv
investment-assistant scoring-rank --path examples/funds.csv --limit 3
```

手元のCSVで試す場合は、次を貼り付ける。

```bash
if test -f pyproject.toml; then
  REPO_DIR="$PWD"
else
  REPO_MARKER="$(find "$HOME" -name pyproject.toml -path "*/Web-Scraping/pyproject.toml" -print 2>/dev/null | head -n 1)"
  REPO_DIR="$(dirname "$REPO_MARKER")"
fi
cd "$REPO_DIR"
test -f pyproject.toml
source .venv/bin/activate

mkdir -p local_data
cat > local_data/funds.csv <<'CSV'
name,expense_ratio,annual_return,volatility,diversification_score
低コスト全世界株式,0.12,0.065,0.18,0.95
高コストテーマ型,1.20,0.080,0.35,0.45
債券バランス型,0.35,0.030,0.08,0.80
CSV

investment-assistant scoring-validate --path local_data/funds.csv
investment-assistant scoring-rank --path local_data/funds.csv --limit 3
```

## 6. 品質チェック

commit前はこのブロックをそのまま実行する。

```bash
if test -f pyproject.toml; then
  REPO_DIR="$PWD"
else
  REPO_MARKER="$(find "$HOME" -name pyproject.toml -path "*/Web-Scraping/pyproject.toml" -print 2>/dev/null | head -n 1)"
  REPO_DIR="$(dirname "$REPO_MARKER")"
fi
cd "$REPO_DIR"
test -f pyproject.toml
source .venv/bin/activate

python -m pytest -q
ruff check .
mypy src
```

## 7. commitとpush

commit、pushまで自動承認されている作業では、品質チェック後にこの流れで進める。
remoteが未設定の場合は `git push` が失敗するため、先に `git remote -v` を確認する。
`origin` がすでにある環境では `git remote add origin ...` を再実行しない。

```bash
if test -f pyproject.toml; then
  REPO_DIR="$PWD"
else
  REPO_MARKER="$(find "$HOME" -name pyproject.toml -path "*/Web-Scraping/pyproject.toml" -print 2>/dev/null | head -n 1)"
  REPO_DIR="$(dirname "$REPO_MARKER")"
fi
cd "$REPO_DIR"
test -f pyproject.toml

git status --short
git add README.md docs src tests examples
git commit -m "作業内容を短く説明"
git remote -v
git remote get-url origin >/dev/null 2>&1 || \
  git remote add origin git@github.com:YOUR_ACCOUNT/YOUR_REPOSITORY.git
git push -u origin HEAD
```

originの接続先が間違っている場合だけ、GitHub等で作ったリポジトリURLに差し替えてから `set-url` を実行する。

```bash
if test -f pyproject.toml; then
  REPO_DIR="$PWD"
else
  REPO_MARKER="$(find "$HOME" -name pyproject.toml -path "*/Web-Scraping/pyproject.toml" -print 2>/dev/null | head -n 1)"
  REPO_DIR="$(dirname "$REPO_MARKER")"
fi
cd "$REPO_DIR"
test -f pyproject.toml

git remote -v
git remote set-url origin git@github.com:YOUR_ACCOUNT/YOUR_REPOSITORY.git
git remote -v
git push -u origin HEAD
```
