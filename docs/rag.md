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
investment-assistant rag-search --query "投資判断" --limit 5
investment-assistant rag-answer-context --query "自動売買" --limit 5
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

### `rag-search`

保存済みチャンクをローカルキーワード検索する。

```bash
investment-assistant rag-search --query "投資判断" --limit 5
```

### `rag-answer-context`

LLMを呼ばずに、引用付き回答の材料になるcontextを返す。

```bash
investment-assistant rag-answer-context --query "自動売買" --limit 5
```

## 実装コンポーネント

- `chunker.py`: 文書読み込み、content hash生成、チャンク分割。
- `store.py`: SQLiteへの文書・チャンク保存。
- `search.py`: ローカルキーワード検索と引用用context生成。

## 次の拡張候補

- ディレクトリ単位の再帰index。
- HTML抽出結果やsafe ingestion結果との連携。
- BM25やベクトル検索への差し替え。
- LlmService経由の引用付き回答生成。
