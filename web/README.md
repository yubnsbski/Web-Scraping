# Investment Assistant ダッシュボード（React + Vite）

日本株と投信に特化した、単一ユーザー向けの非助言PWAです。保有分析、条件フィルタ型の候補抽出、NISA枠、配当/分配金見込み、根拠付き投資レポートをブラウザから操作します。

本ツールは**投資助言・売買推奨・自動売買・証券口座注文連携を行いません**。候補抽出は、条件に一致した比較対象を提示するだけです。最終的な投資判断はユーザー本人が行います。

- フロントエンド: React + Vite + TypeScript（この `web/` ディレクトリ）
- バックエンド: Python 標準ライブラリの JSON API（`investment_assistant.webapi`）
- Gemini API: UIから直接呼ばず、必要な場合も必ず `llm/service.py` 経由

## 画面

- `Dashboard`: 投資状況の概要
- `Holdings`: 保有CSVの取込、評価額、損益、NISA枠、配当/分配金見込み
- `Candidates`: 日本株と投信の条件フィルタ型候補抽出
- `Detail`: 銘柄・投信の根拠付き確認
- `Report`: 根拠と計算式付きの投資月次レポート
- `Evidence`: RAGに登録済みの出典検索

## 起動手順

バックエンド（リポジトリルートで、`.venv` 有効化済み）:

```bash
investment-assistant serve --port 8000
# または: python -m investment_assistant.webapi --port 8000
```

フロントエンド（この `web/` ディレクトリで）:

```bash
npm install
npm run dev
```

開発時は `http://localhost:5173` を開きます。Viteの `/api` は `127.0.0.1:8000` にプロキシされます。

本番配信（フロントをビルドしてPythonサーバから配信）:

```bash
npm run build
investment-assistant serve --port 8000
```

この場合は `http://localhost:8000` でUIとAPIを同一ポート配信します。

## 入力CSV

保有CSVの必須列:

```csv
asset_type,ticker_or_fund_code,name,quantity,avg_cost,account_type,tax_wrapper,source
```

任意列:

```csv
current_price,annual_income,distribution_per_unit
```

投信プロファイルCSVの必須列:

```csv
fund_code,name,asset_class,expense_ratio,distribution_policy,nisa_eligible,provider_id
```

任意列:

```csv
diversification_score
```

## API（投資MVP）

- `POST /api/holdings/import`
- `POST /api/portfolio/analyze`
- `POST /api/candidates/screen`
- `POST /api/reports/investment-monthly`
- `POST /api/rag/search`
- `POST /api/orchestrate`
- `POST /api/fetch-job/dry-run`
- `POST /api/fetch-job/run`
- `POST /api/manual-doc/save`
- `POST /api/cache/maintenance`

市場価格取得はprovider policyの対象です。本番モードでは、契約済みとして明示されていないproviderを拒否します。

## コミットしないもの

`web/node_modules/`、`web/dist/`、`.cache/`、`data/`、`local_docs/`、`.venv/`、APIキーや個人情報を含むファイルはコミットしません。
