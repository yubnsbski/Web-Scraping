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

## CLI

まずはURL単位で安全確認と取得を行う。

```bash
# robots.txtを確認するが、対象URL本体は取得しない
investment-assistant fetch-url --url https://example.com/funds --dry-run

# robots.txtで許可される場合のみ対象URLを取得し、結果をSQLiteキャッシュする
investment-assistant fetch-url --url https://example.com/funds --preview-chars 300
```

戻り値はJSONで、以下を含む。

- `source`: `dry_run`、`network`、`cache`、`blocked_by_robots` のいずれか。
- `allowed_by_robots`: robots.txt上の許可状態。
- `robots_url`: 確認したrobots.txt URL。
- `bytes_read`: 読み取ったバイト数。
- `text_preview`: レスポンス本文の先頭部分。

## 実装コンポーネント

- `transport.py`: 実HTTP transportとfake可能なprotocol。
- `robots.py`: robots.txt取得と許可判定。
- `rate_limit.py`: domain単位の最小待機時間。
- `http_cache.py`: SQLite HTTPレスポンスキャッシュ。
- `fetcher.py`: 上記を組み合わせた安全なfetch orchestration。

## 次の拡張候補

- 公式APIごとのclient追加。
- HTML抽出・正規化。
- 取得ジョブ定義ファイル。
- データソース別の利用規約メモ。
- RAG用チャンク化。ただしRAGでLLMを使う場合は既存のGemini予算ガードを必ず経由する。
