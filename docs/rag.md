# Phase 3: ローカルRAG基盤

## 目的

Gemini APIを呼ばずに、ローカル文書をチャンク化・保存・検索し、引用付き回答の材料を作る。

## 方針

- まずは外部API・ベクトルDB・Gemini APIなしで動かす。
- 文書はUTF-8のMarkdownまたはテキストファイルとして読み込む。
- チャンクにはsource path、chunk index、content hashを付与する。
- SQLiteに文書とチャンクを保存する。
- 検索は単純なローカルキーワード検索から始める。
- LLM回答生成が必要になった場合は、必ず既存の `LlmService` を経由して予算管理・キャッシュ・フォールバックを適用する。

## コピペで動くローカル確認

```bash
mkdir -p local_docs
cat > local_docs/sample.md <<'EOF'
# サンプル投資メモ

これはRAGテスト用のローカル文書です。
投資判断はユーザー本人が行います。
自動売買は行いません。
EOF

investment-assistant rag-index --path local_docs/sample.md
investment-assistant rag-index-dir --path local_docs
investment-assistant rag-search --query "投資判断" --limit 5
investment-assistant rag-answer-context --query "自動売買" --limit 5
```

## safe ingestion結果をRAGに渡す

`fetch-url --extract-text --save-text` で保存したローカルファイルは、そのまま `rag-index` の入力にできる。
Gemini APIは呼ばず、保存済みテキストをローカルSQLiteへチャンク保存する。

```bash
mkdir -p local_docs
TARGET_URL="https://example.com/"
OUTPUT_PATH="local_docs/example.txt"

investment-assistant fetch-url \
  --url "$TARGET_URL" \
  --preview-chars 500 \
  --extract-text \
  --include-metadata \
  --save-text "$OUTPUT_PATH"

investment-assistant rag-index-dir --path local_docs
investment-assistant rag-search --query "Example Domain" --limit 5
investment-assistant rag-answer-context --query "Example Domain" --limit 5
```

## CLI

### `rag-index`

ローカルファイルをチャンク化してSQLiteに保存する。

```bash
investment-assistant rag-index --path local_docs/sample.md
```

主なオプション:

- `--db-path`: SQLite DBの保存先。デフォルトは `.cache/investment_assistant/rag.sqlite`。
- `--max-chars`: 1チャンクの最大文字数。
- `--overlap-chars`: 隣接チャンクの重なり文字数。


### `rag-index-dir`

ディレクトリ配下の `.txt`、`.md`、`.markdown` を再帰的にまとめてSQLiteに保存する。
`.env`、SQLite DB、`.cache/`、`data/`、`artifacts/`、`models/` などは対象外にする。

```bash
investment-assistant rag-index-dir --path local_docs
```

主なオプション:

- `--db-path`: SQLite DBの保存先。デフォルトは `.cache/investment_assistant/rag.sqlite`。
- `--max-chars`: 1チャンクの最大文字数。
- `--overlap-chars`: 隣接チャンクの重なり文字数。

戻り値はJSONで、`files_indexed`、`chunks_indexed`、`indexed_sources`、`skipped_files` を含む。

### `rag-search`

保存済みチャンクをローカルキーワード検索する。`--include-metadata` 付きで保存したfront matterは本文チャンクから除外し、検索結果JSONの `metadata` として返す。ターミナルで読みやすく確認したい場合は `--format table` を使い、必要な列だけに絞る場合は `--columns` を使う。

```bash
investment-assistant rag-search --query "投資判断" --limit 5
investment-assistant rag-search --query "投資判断" --limit 5 --format table
investment-assistant rag-search \
  --query "投資判断" \
  --limit 5 \
  --format table \
  --columns rank,source_url,fetched_at,text_preview
```

### `rag-search-job`

`fetch-job` の `query_hint` を使って、ジョブ内の各sourceをまとめてRAG検索確認する。`query_hint` がないsourceは `name` を検索語に使う。Gemini APIは呼ばない。`--save-report` を指定すると、tableはMarkdown、jsonはJSONとして保存する。

```bash
investment-assistant rag-search-job --path local_jobs/fetch_job.yaml
investment-assistant rag-search-job \
  --path local_jobs/fetch_job.yaml \
  --format table \
  --columns rank,source_url,fetched_at,text_preview \
  --save-report local_reports/rag_search_job.md
investment-assistant rag-search-job \
  --path local_jobs/fetch_job.yaml \
  --format json \
  --save-report local_reports/rag_search_job.json
```

### `rag-answer-context`

LLMを呼ばずに、引用付き回答の材料になるcontextを返す。front matterに `source_url`、`fetched_at`、`status_code`、`content_type` がある場合は、context見出しに並べて表示する。

```bash
investment-assistant rag-answer-context --query "自動売買" --limit 5
```

## 実装コンポーネント

- `chunker.py`: 文書読み込み、content hash生成、チャンク分割。
- `store.py`: SQLiteへの文書・チャンク保存。
- `search.py`: ローカルキーワード検索と引用用context生成。

## 次の拡張候補

- UIチャット画面で想定質問ボタンと自由質問入力を両立する設計。
- HTML抽出結果やsafe ingestion結果との連携強化。
- BM25やベクトル検索への差し替え。
- LlmService経由の引用付き回答生成。
