# Local dev quickstart（Windows PowerShell）

このメモは、現在の投資特化MVPをローカルで確認するための最短手順です。バックエンドは `backend/` ではなく、リポジトリ直下の `investment_assistant.webapi` を使います。

## 1. いつでも開ける起動方法（推奨）

PowerShell でリポジトリ直下から次を実行します。

```powershell
.\scripts\windows\Start-InvestmentAssistant.ps1
```

このスクリプトは、バックエンド `8000` とフロントエンド `5173` を二重起動しないように確認し、落ちている方だけを起動します。フロントは `0.0.0.0:5173` で起動するため、同じ Wi-Fi の端末からも開けます。

表示される URL の例:

```text
Local: http://127.0.0.1:5173/
LAN:   http://192.168.3.11:5173/
```

PCログオン後も自動で維持したい場合は、次を一度だけ実行します。

```powershell
.\scripts\windows\Install-InvestmentAssistantStartup.ps1 -StartNow
```

これにより Windows タスクスケジューラに `InvestmentAssistantLocalKeepAlive` が登録され、30秒ごとに `5173` / `8000` の生存確認と再起動を行います。

Yahoo! ファイナンス HTML フォールバックを個人利用前提の既存設定どおり有効にして常駐させる場合:

```powershell
.\scripts\windows\Install-InvestmentAssistantStartup.ps1 -StartNow -AllowRobotsBypass
```

停止したい場合:

```powershell
.\scripts\windows\Stop-InvestmentAssistant.ps1
```

ログオン時の自動起動を解除したい場合:

```powershell
.\scripts\windows\Uninstall-InvestmentAssistantStartup.ps1
```

ログは `local_docs\logs\runtime\` に出ます。

## 2. 手動でポートを空ける

```powershell
Get-Process -Id (Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue).OwningProcess -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Get-Process -Id (Get-NetTCPConnection -LocalPort 5173 -ErrorAction SilentlyContinue).OwningProcess -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
```

## 3. Python環境

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

## 4. バックエンド起動

```powershell
investment-assistant serve --port 8000
# または
python -m investment_assistant.webapi --port 8000
```

## 5. フロントエンド起動

別ターミナルで:

```powershell
cd web
npm install
npm run dev
```

ブラウザで `http://127.0.0.1:5173/` を開きます。

## 6. 品質チェック

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
