#!/usr/bin/env bash
# investment-assistant VM セットアップ / 更新スクリプト (冪等)。
# VM 上で ubuntu ユーザーとして実行する:
#   bash ~/Web-Scraping/ops/cloud/setup-app.sh
# 初回は cloud-init が自動実行する。コード更新時に再実行すれば最新化される。
set -euo pipefail

REPO_DIR="${REPO_DIR:-$HOME/Web-Scraping}"
cd "$REPO_DIR"

# コード更新 (VM はコミットしないので ff-only で常に成功する)
git pull --ff-only

# Python 仮想環境 + パッケージ (gemini / forecast / embeddings 込み)
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -e ".[gemini,forecast,embeddings]" -q

# フロントエンドのビルド (web/dist から配信される)
if command -v npm >/dev/null 2>&1; then
  (cd web && npm ci --no-audit --no-fund && npm run build)
else
  echo "WARN: npm が無いためフロントエンドをビルドできません" >&2
fi

# systemd サービス登録 (常駐 + 自動再起動 + OS再起動後も自動起動)
sudo cp ops/cloud/investment-assistant.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable investment-assistant
sudo systemctl restart investment-assistant

# tailnet 限定 HTTPS: https://invest-vm.<tailnet>.ts.net -> 127.0.0.1:8000
# (tailscale のバージョンで serve の構文が違うため両方試す)
sudo tailscale serve --bg --https=443 http://127.0.0.1:8000 \
  || sudo tailscale serve --bg 8000

echo "setup done."
echo "health check: curl -s http://127.0.0.1:8000/api/health"
