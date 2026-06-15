#!/usr/bin/env bash
# Turnkey dividend data run: EDINET financials + IR-page crawl -> RAG store.
#
# Requires network egress to EDINET / the IR domains (not available in the
# sandbox — run on your machine or a Codespace) and a free EDINET v2
# Subscription-Key for the financial numbers.
#
# Usage:
#   export EDINET_API_KEY=...                 # https://api.edinet-fsa.go.jp
#   scripts/run_dividend_crawl.sh             # default: 3y EDINET + IR crawl
#   YEARS=5 scripts/run_dividend_crawl.sh     # deeper backfill
#   SKIP_CRAWL=1 scripts/run_dividend_crawl.sh  # EDINET numbers only
set -euo pipefail

cd "$(dirname "$0")/.."

OUT_EDINET="${OUT_EDINET:-local_docs/edinet}"
OUT_CRAWL="${OUT_CRAWL:-local_docs/crawl}"
DB_PATH="${DB_PATH:-.cache/investment_assistant/rag.sqlite}"
YEARS="${YEARS:-3}"
EDINET_REGISTRY="examples/source_registry_dividend_edinet.yaml"
IR_REGISTRY="examples/source_registry_dividend_ir.yaml"

echo "==> Dividend data run (EDINET ${YEARS}y + IR crawl)"

if [[ -z "${EDINET_API_KEY:-}" ]]; then
  echo "!! EDINET_API_KEY is not set — skipping EDINET financials."
  echo "   Get a free Subscription-Key at https://api.edinet-fsa.go.jp and re-run."
else
  echo "==> EDINET financials -> ${OUT_EDINET}/financials.csv"
  investment-assistant edinet-ingest \
    --registry "${EDINET_REGISTRY}" \
    --years "${YEARS}" \
    --output-dir "${OUT_EDINET}" \
    --db-path "${DB_PATH}"
fi

if [[ "${SKIP_CRAWL:-0}" != "1" ]]; then
  echo "==> IR-page crawl -> ${OUT_CRAWL} (domain/prefix-locked, robots-respecting)"
  investment-assistant crawl \
    --path "${IR_REGISTRY}" \
    --output-dir "${OUT_CRAWL}" \
    --db-path "${DB_PATH}"
fi

echo "==> RAG store contents:"
investment-assistant rag-stats --db-path "${DB_PATH}" || true

echo
echo "Done."
echo "  Financials (simulator input): ${OUT_EDINET}/financials.csv"
echo "  Point the simulator/API at it via financials_csv, or copy to the default path."
