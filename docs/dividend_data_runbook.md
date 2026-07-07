# Dividend data run set (EDINET)

A turnkey way to pull the data the dividend simulator and AI Chat need:

- **EDINET** → structured numbers (営業CF / 自己資本比率 / １株配当 / 配当性向) into
  `financials.csv` — the dividend simulator's input, and the filing text is
  indexed into the RAG store as grounding for AI Chat.

Only `allowed: true` sources with `source_type: public_api` (EDINET) run.

> Network note: EDINET is not reachable from the Claude Code sandbox (egress is
> proxy-filtered and EDINET needs a key), so run this on your machine or a
> Codespace where outbound HTTPS to EDINET is allowed.

## Files

| File | Purpose |
| --- | --- |
| `examples/source_registry_dividend_edinet.yaml` | 12 well-known dividend payers (EDINET, resolved by securities code — no URLs to verify) |

## One-shot run

```bash
# 1. EDINET v2 Subscription-Key (free): https://api.edinet-fsa.go.jp
export EDINET_API_KEY=...

# 2. EDINET financials (3y backfill), indexed into the RAG store
investment-assistant edinet-ingest \
  --registry examples/source_registry_dividend_edinet.yaml \
  --years 3 --output-dir local_docs/edinet

# Inspect what landed
investment-assistant rag-stats
```

Output:

- `local_docs/edinet/financials.csv` — the simulator input (ticker, fiscal_year,
  operating_cf, equity_ratio, dividend_per_share, payout_policy).
- `local_docs/edinet/<ticker>/<doc_id>.txt`, indexed into
  `.cache/investment_assistant/rag.sqlite`.

## See it work offline (no network, no key)

```bash
investment-assistant demo          # or: python -m investment_assistant.demo
```

Drives the real CLI paths with injected fakes through the whole chain — EDINET
ingest (fake API) → `financials.csv` → RAG index/search → dividend simulator +
after-tax reverse calc — so you can confirm the pipeline end to end before
running it for real.

## Feeding the simulator

The simulator/API read `financials_csv` (default
`local_docs/edinet/financials.csv`). Point the Simulate tab / `/api/portfolio/*`
at the produced file, or pass `financials_csv` in the request body. With real
EDINET data loaded, the dividend band (Bollinger lower), safety score, and
split-adjusted dividend series are all driven by official filings.

## Market prices (Stooq / Yahoo Finance)

`/api/market/prices` and the Simulate tab's「市場価格を更新」fetch the latest close
per ticker. The data source follows the selected `provider_id`:

- `stooq_public_csv` (default) — Stooq snapshot CSV.
- `yfinance` — Yahoo Finance v8 chart JSON (Tokyo `.T` symbols).

Pick it in the UI's「価格ソース」selector, pass `provider_id` in the request body,
or set the default for headless use:

```bash
export MARKET_PRICE_PROVIDER=yfinance   # or stooq_public_csv
```

Personal-use, on-demand quotes only — respect each source's terms; production use
of a market-data provider needs the provider marked as contracted.

### OHLCV history and intraday (Yahoo Finance)

Scrape daily OHLCV bars, or today's minute-bars, for explicit tickers or every
ticker in a registry (`--max 0` = all). One `<ticker>.csv` is written per ticker.

```bash
# Daily OHLCV (Yahoo v8 chart JSON)
investment-assistant market-ohlcv --tickers 8306,7203 --range 1mo --output-dir local_docs/ohlcv
investment-assistant market-ohlcv --registry examples/source_registry_nikkei225_edinet.yaml \
  --max 0 --output-dir local_docs/ohlcv

# Today's minute-bars (finance.yahoo.co.jp __PRELOADED_STATE__)
investment-assistant market-intraday --tickers 2914,8306 --output-dir local_docs/intraday
```

The intraday series is only available for the current trading day (the page
resets next day), so pull it after the session the same day. Personal use only —
no redistribution or sale; fetches honor robots.txt and rate limits, so do not
use this to poll for real-time data.

In the web UI, the Simulate tab's「市場データ取得」panel calls the same fetch via
`POST /api/market/ohlcv` and `POST /api/market/intraday` (`tickers` list or
comma string, max 50; `range` for OHLCV), with loading / error / empty / failed-
ticker states surfaced. Yahoo is `development_only`, so these endpoints return
400 in `runtime_mode=production` unless the provider is contracted.

## Customising the universe

- **More tickers:** copy a block in `source_registry_dividend_edinet.yaml`,
  change `ticker` / `company`. EDINET resolves by securities code, so no URL is
  needed.
- **Nikkei 225:** `scripts/build_nikkei225_edinet_registry.py` generates a
  full-index EDINET registry.
