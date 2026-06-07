#!/usr/bin/env bash
set -euo pipefail

cd /workspaces/Web-Scraping

for PORT in 8000 5173; do
  PID=$(lsof -ti :$PORT || true)
  if [ -n "$PID" ]; then
    echo "kill :$PORT $PID"
    kill -9 "$PID" || true
  fi
done

echo "start backend :8000"
investment-assistant serve --host 0.0.0.0 --port 8000 > /tmp/investment_backend.log 2>&1 &
BACKEND_PID=$!

echo "start frontend :5173"
cd web
npm run dev -- --host 0.0.0.0 > /tmp/investment_frontend.log 2>&1 &
FRONTEND_PID=$!

echo "backend pid:  $BACKEND_PID"
echo "frontend pid: $FRONTEND_PID"
echo "backend log:  /tmp/investment_backend.log"
echo "frontend log: /tmp/investment_frontend.log"
echo "open Codespaces port 5173"

tail -f /tmp/investment_backend.log /tmp/investment_frontend.log
