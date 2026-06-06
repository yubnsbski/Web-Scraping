# Investment Assistant ダッシュボード（React + Vite）

このAIの調査支援機能（RAG検索 / AI回答 / スコアリング / 予測 / 安全な取得 / 予算・キャッシュ）を
ブラウザから操作するローカルUIです。**投資助言・自動売買・証券口座連携は行いません。** UIから実Gemini
APIを呼ぶことはありません（回答はローカル擬似クライアント）。

- フロントエンド: React + Vite + TypeScript（このディレクトリ）
- バックエンド: Python 標準ライブラリの JSON API（`investment_assistant.webapi`、依存追加なし）

## 起動手順

バックエンド（リポジトリルートで、`.venv` 有効化済み）:

```bash
investment-assistant serve --port 8000
# または: python -m investment_assistant.webapi --port 8000
```

フロントエンド（この `web/` ディレクトリで）:

```bash
npm install
npm run dev        # http://localhost:5173 （/api は :8000 にプロキシ）
```

本番配信（フロントをビルドしてPythonサーバから配信）:

```bash
npm run build      # web/dist を生成
investment-assistant serve --port 8000   # http://localhost:8000 で UI とAPIを同一ポート配信
```

## API（抜粋）

`GET /api/health`, `GET /api/budget`, `POST /api/rag/search`, `POST /api/orchestrate`,
`POST /api/scoring/rank`, `POST /api/forecast/evaluate|predict`, `POST /api/fetch-job/dry-run|run`,
`POST /api/cache/maintenance`。

取得（fetch-job）は必ず先に dry-run で robots.txt を確認してください。`node_modules/` と `dist/` は
コミットしません。
