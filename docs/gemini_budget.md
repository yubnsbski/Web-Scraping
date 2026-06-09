# Gemini API無料枠管理

## 目的

Gemini APIの無料枠を超えないように、呼び出しを一元管理する。

## 必須ルール

- Gemini APIは `llm/service.py` 経由でのみ使用する。
- API呼び出し前にキャッシュを確認する。
- キャッシュミス時のみ予算確認を行う。
- 日次・月次上限に達した場合はフォールバックする。
- 使用量はSQLiteに記録する。

## フォールバック

- `cached_or_skip`: キャッシュがあれば返し、なければスキップする。
- `local_summary`: ローカルの簡易要約を返す。
- `skip_llm`: LLM処理をスキップする。


## Phase 1仕上げの運用コマンド

`config/gemini.yaml` から `LlmService` を組み立てる factory を用意し、CLIから予算確認とスモークテストを実行できる。

```bash
investment-assistant budget --json
investment-assistant smoke --prompt "hello"
```

- `budget` はGemini APIを呼ばず、SQLiteに記録された日次・月次使用量だけを表示する。
- `smoke` はfake clientを使い、実Gemini APIを呼ばずに `LlmService` のキャッシュ・予算管理経路を検証する。


## Phase 1.5: 実Gemini APIの手動確認

本番Gemini API連携は `GeminiClient` に閉じ込め、通常の単体テストでは呼ばない。手動確認時だけ optional dependency と `GEMINI_API_KEY` を用意し、以下を実行する。

```bash
python -m pip install -e '.[gemini]'
export GEMINI_API_KEY=your_api_key
investment-assistant gemini-live --prompt "短く挨拶して" --call-real-api
```

`--call-real-api` を必須にすることで、誤って無料枠を消費することを防ぐ。実API呼び出しも `LlmService` 経由なので、キャッシュ確認、予算確認、SQLite使用量記録、フォールバックが適用される。
