# Dividend data run set (EDINET + IR crawl)

A turnkey way to pull the data the dividend simulator and AI Chat need:

- **EDINET** → structured numbers (営業CF / 自己資本比率 / １株配当 / 配当性向) into
  `financials.csv` — the dividend simulator's input.
- **IR crawl** → qualitative text (配当方針 / 株主還元 / 中期経営計画) into the RAG
  store — grounding for AI Chat.

Both paths share the registry safety boundary: only `allowed: true` sources
with `source_type` of `public_api` (EDINET) or `issuer_ir` (crawl) run; the
crawler is locked to `allowed_domains` + `url_prefix` and follows robots.txt.

> Network note: the data sources are not reachable from the Claude Code sandbox
> (egress is proxy-filtered and EDINET needs a key), so run this on your machine
> or a Codespace where outbound HTTPS to EDINET / the IR domains is allowed.

## Files

| File | Purpose |
| --- | --- |
| `examples/source_registry_dividend_edinet.yaml` | 12 well-known dividend payers (EDINET, resolved by securities code — no URLs to verify) |
| `examples/source_registry_dividend_ir.yaml` | 6 IR-site crawl targets (verify each `url` before a live run) |
| `scripts/run_dividend_crawl.sh` | Runs both, indexes into the RAG store, prints a summary |

## One-shot run

```bash
# 1. EDINET v2 Subscription-Key (free): https://api.edinet-fsa.go.jp
export EDINET_API_KEY=...

# 2. Run everything (3y EDINET backfill + IR crawl + RAG index)
scripts/run_dividend_crawl.sh
#   YEARS=5 scripts/run_dividend_crawl.sh      # deeper backfill
#   SKIP_CRAWL=1 scripts/run_dividend_crawl.sh # EDINET numbers only
```

Output:

- `local_docs/edinet/financials.csv` — the simulator input (ticker, fiscal_year,
  operating_cf, equity_ratio, dividend_per_share, payout_policy).
- `local_docs/edinet/<ticker>/<doc_id>.txt` + crawled IR pages, indexed into
  `.cache/investment_assistant/rag.sqlite`.

## Step by step (if you prefer)

```bash
# EDINET financials (official filings)
investment-assistant edinet-ingest \
  --registry examples/source_registry_dividend_edinet.yaml \
  --years 3 --output-dir local_docs/edinet

# IR-page crawl (domain/prefix-locked, robots-respecting)
investment-assistant crawl \
  --path examples/source_registry_dividend_ir.yaml \
  --output-dir local_docs/crawl

# Inspect what landed
investment-assistant rag-stats
```

## See it work offline (no network, no key)

```bash
investment-assistant demo          # or: python -m investment_assistant.demo
```

Drives the real CLI paths with injected fakes through the whole chain — IR
crawl (fixture HTML) → RAG search → EDINET ingest (fake API) → `financials.csv`
→ dividend simulator + after-tax reverse calc — so you can confirm the pipeline
end to end before running it for real.

## Crawler note: PDFs and assets

The crawler classifies each discovered link: HTML **pages** are crawled, static
**assets** (css/js/images/fonts) are dropped, and **documents** (PDF 決算短信 /
有価証券報告書 / Excel) are surfaced under `documents` in the crawl report instead
of being fetched and mis-parsed as HTML. Use that list to pull the source PDFs
out of band if you need them.

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
- **More IR sites:** copy a block in `source_registry_dividend_ir.yaml`, set the
  current `url`, `allowed_domains`, and `url_prefix`. A stale URL is harmless —
  the crawler just returns no pages.
- **Nikkei 225:** `scripts/build_nikkei225_edinet_registry.py` generates a
  full-index EDINET registry.
