# Phase 2: 安全なデータ取得基盤

## 目的

Web上の投資関連データを扱う前段として、robots.txt、レート制限、キャッシュを備えた安全な取得経路を用意する。

## 方針

- 実ネットワーク取得は `investment_assistant.ingestion.SafeFetcher` 系に集約する。
- 取得前に対象サイトの `robots.txt` を確認する。
- domain単位で最小待機時間を設け、短時間の連続アクセスを避ける。
- HTTPレスポンスはSQLiteキャッシュに保存し、同じURLへの再取得を抑える。
- 単体テストでは実ネットワークを呼ばず、fake transportを使う。
- Gemini APIはこの段階では呼ばない。取得データの要約やRAG連携が必要になった場合も、必ず既存の `LlmService` 経由にする。


## コピペで動くローカル確認

以下はターミナルにそのまま貼り付けて実行できる。
1つ目のコマンドはrobots.txt確認だけを行い、対象URL本体は取得しない。
2つ目のコマンドはrobots.txtで許可される場合だけ本文を取得し、SQLiteキャッシュに保存する。

```bash
cd /path/to/Web-Scraping
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'

investment-assistant fetch-url --url https://example.com/ --dry-run
investment-assistant fetch-url --url https://example.com/ --preview-chars 300
```

別のWebサイトを確認する場合はURLだけを差し替える。
利用規約、robots.txt、レート制限、著作権、個人情報を尊重し、取得結果は必要最小限にする。

```bash
TARGET_URL="https://example.com/"
investment-assistant fetch-url --url "$TARGET_URL" --dry-run
investment-assistant fetch-url --url "$TARGET_URL" --preview-chars 500
```

### 取得結果を保存してRAGにindexする

`--save-text` を指定すると、robots.txtで許可された取得結果だけをローカルテキストとして保存する。
HTMLページでは `--extract-text` を併用すると、タグ、script、styleを除いた本文テキストに正規化してからpreviewと保存を行う。
`dry_run`、`blocked_by_robots`、`robots_unavailable` の場合は保存しない。
保存先の親ディレクトリは自動作成される。

```bash
mkdir -p local_docs
TARGET_URL="https://example.com/"
OUTPUT_PATH="local_docs/example.txt"

investment-assistant fetch-url \
  --url "$TARGET_URL" \
  --preview-chars 500 \
  --extract-text \
  --save-text "$OUTPUT_PATH"

investment-assistant rag-index-dir --path local_docs
investment-assistant rag-search --query "Example Domain" --limit 5
investment-assistant rag-search --query "Example Domain" --limit 5 --format table
investment-assistant rag-answer-context --query "Example Domain" --limit 5
```

`local_docs/` は実行時データ置き場として `.gitignore` 対象にしているため、通常はコミットしない。

## CLI

まずはURL単位で安全確認と取得を行う。

```bash
# robots.txtを確認するが、対象URL本体は取得しない
investment-assistant fetch-url --url https://example.com/funds --dry-run

# robots.txtで許可される場合のみ対象URLを取得し、結果をSQLiteキャッシュする
investment-assistant fetch-url --url https://example.com/funds --preview-chars 300

# 取得本文を保存して、後続のrag-index入力にする
investment-assistant fetch-url \
  --url https://example.com/funds \
  --preview-chars 300 \
  --extract-text \
  --include-metadata \
  --save-text local_docs/funds.txt
```

戻り値はJSONで、以下を含む。

- `source`: `dry_run`、`network`、`cache`、`blocked_by_robots`、`robots_unavailable` のいずれか。
- `allowed_by_robots`: robots.txt上の許可状態。robots.txtを取得できない場合は安全側に倒して `false` にする。
- `robots_url`: 確認したrobots.txt URL。
- `bytes_read`: 読み取ったバイト数。
- `text_preview`: レスポンス本文の先頭部分。
- `saved_path`: `--save-text` で保存できた場合の保存先パス。保存しない場合は `null`。
- `extracted_text`: `--extract-text` でHTML本文抽出を適用した場合は `true`。
- `metadata_included`: `--include-metadata` と `--save-text` を併用して、保存ファイルにfront matterを付与した場合は `true`。



## 取得ジョブ定義ファイル

複数URLをまとめて安全に取得する場合は、YAMLジョブを使う。
`fetch-job` も各URLごとにrobots.txtを確認し、許可された場合だけ保存する。
`--dry-run` では対象URL本文を取得せず、保存もしない。
`include_metadata: true` を指定すると、保存テキストの先頭に取得URL、取得時刻、HTTP status、content-type、HTML抽出有無を付与する。

```yaml
sources:
  - name: example
    url: https://example.com/
    output_path: local_docs/example.txt
    query_hint: Example Domain
    extract_text: true
    include_metadata: true
    preview_chars: 500
```

ターミナルでは次の順番で実行する。

```bash
investment-assistant fetch-job --path examples/fetch_job.yaml --dry-run
investment-assistant fetch-job --path examples/fetch_job.yaml
investment-assistant rag-index-dir --path local_docs
investment-assistant rag-search --query "Example Domain" --limit 5
investment-assistant rag-search-job \
  --path examples/fetch_job.yaml \
  --format table \
  --columns rank,source_url,fetched_at,text_preview \
  --save-report local_reports/rag_search_job.md
```

戻り値はJSONで、ジョブ全体の `sources_count` と、各sourceの `name`、`url`、`output_path`、`query_hint`、`fetch` 結果を含む。保存後は `rag-search-job` で各sourceの `query_hint` を使って検索確認でき、`--save-report` でMarkdown/JSONレポートとして保存できる。


### 保存テキストのメタデータ

`fetch-url --include-metadata --save-text` または fetch job の `include_metadata: true` を使うと、保存ファイルの先頭に次のようなfront matterを付与する。

```markdown
---
source_url: "https://example.com/"
fetched_at: 2026-06-06T00:00:00Z
status_code: 200
content_type: "text/html; charset=utf-8"
extracted_text: true
---

本文...
```

これにより、RAG検索結果JSONの `metadata`、`rag-search --format table`、`rag-answer-context` のcontext見出しから、取得元URLと取得条件を確認しやすくする。

## HTML抽出・正規化

`--extract-text` はGemini APIや外部サービスを呼ばず、Python標準ライブラリだけでHTMLを本文テキストへ変換する。
主な処理は以下。

- `<script>`、`<style>`、`<noscript>` の内容を除去する。
- HTMLタグを除去する。
- `&amp;` などのHTMLエンティティを復元する。
- 連続空白や改行を正規化する。
- `<title>` が本文の先頭見出しと重複しない場合は、先頭にtitleを追加する。

## 実装コンポーネント

- `transport.py`: 実HTTP transportとfake可能なprotocol。
- `robots.py`: robots.txt取得と許可判定。
- `rate_limit.py`: domain単位の最小待機時間。
- `http_cache.py`: SQLite HTTPレスポンスキャッシュ。
- `fetcher.py`: 上記を組み合わせた安全なfetch orchestration。

## 次の拡張候補

- 公式APIごとのclient追加。
- UIチャット画面で想定質問ボタンと自由質問入力を両立する設計。
- 取得ジョブ定義ファイルのスキーマ拡張。
- データソース別の利用規約メモ。
- RAG用チャンク化。ただしRAGでLLMを使う場合は既存のGemini予算ガードを必ず経由する。
