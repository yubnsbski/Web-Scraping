# Local dev quickstart（Windows PowerShell）

このメモは、現在の投資特化MVPをローカルで確認するための最短手順です。バックエンドは `backend/` ではなく、リポジトリ直下の `investment_assistant.webapi` を使います。

## 1. ポートを空ける

```powershell
Get-Process -Id (Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue).OwningProcess -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Get-Process -Id (Get-NetTCPConnection -LocalPort 5173 -ErrorAction SilentlyContinue).OwningProcess -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
```

## 2. Python環境

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

## 3. バックエンド起動

```powershell
investment-assistant serve --port 8000
# または
python -m investment_assistant.webapi --port 8000
```

## 4. フロントエンド起動

別ターミナルで:

```powershell
cd web
npm install
npm run dev
```

ブラウザで `http://127.0.0.1:5173/` を開きます。

## 5. 品質チェック

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy src
```

フロントエンド:

```powershell
cd web
npm run build
```

## 注意

- `.env`、APIキー、個人情報、`.cache/`、`data/`、`local_docs/`、`.venv/`、`web/node_modules/`、`web/dist/` はコミットしません。
- 実Gemini APIを使う場合も、必ず `llm/service.py` 経由の既存ガード付き経路を使います。
- 本ツールは投資助言・売買推奨・自動売買・証券口座注文連携を行いません。
