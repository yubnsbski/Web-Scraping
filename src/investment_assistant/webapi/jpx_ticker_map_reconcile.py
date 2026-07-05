"""Reconcile ticker_data_map against a JPX domestic stock snapshot."""

from __future__ import annotations

import csv
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

TICKER_MAP_COLUMNS = (
    "ticker",
    "name",
    "segment",
    "data_status",
    "past_price_history",
    "history_rows",
    "history_period",
    "current_price",
    "price_as_of",
    "dividend_yield_pct",
    "yield_as_of",
    "next_action",
)
REPORT_COLUMNS = ("issue_type", "ticker", "name", "segment", "action")


@dataclass(frozen=True)
class TickerMapReconcileConfig:
    ticker_map_path: Path
    official_snapshot_path: Path
    output_dir: Path
    apply: bool = False
    generated_at: str | None = None
    mirror_dirs: tuple[Path, ...] = ()


def reconcile_ticker_data_map(config: TickerMapReconcileConfig) -> dict[str, Any]:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    existing_rows = _read_csv(config.ticker_map_path)
    official_rows = _read_csv(config.official_snapshot_path)
    existing_by_ticker = {row.get("ticker", ""): row for row in existing_rows if row.get("ticker")}
    official_by_ticker = {row.get("ticker", ""): row for row in official_rows if row.get("ticker")}
    existing_tickers = set(existing_by_ticker)
    official_tickers = set(official_by_ticker)
    extra_tickers = sorted(existing_tickers - official_tickers)
    missing_tickers = sorted(official_tickers - existing_tickers)
    reconciled_rows = [
        _reconciled_row(official_row, existing_by_ticker.get(official_row["ticker"]))
        for official_row in official_rows
        if official_row.get("ticker")
    ]
    report_rows = [
        _report_row("extra_removed", ticker, existing_by_ticker[ticker], "remove from ticker map")
        for ticker in extra_tickers
    ]
    report_rows.extend(
        _report_row("missing_added", ticker, official_by_ticker[ticker], "add placeholder row")
        for ticker in missing_tickers
    )
    if not extra_tickers and not missing_tickers:
        status = "pass"
    elif config.apply:
        status = "fixed"
    else:
        status = "needs_apply"
    generated_at = config.generated_at or datetime.now().astimezone().isoformat(timespec="seconds")
    summary = {
        "generated_at": generated_at,
        "status": status,
        "apply": config.apply,
        "official_domestic_stock_issues": len(official_rows),
        "input_ticker_map_rows": len(existing_rows),
        "reconciled_ticker_map_rows": len(reconciled_rows),
        "extra_removed_count": len(extra_tickers),
        "missing_added_count": len(missing_tickers),
        "source_data_write_executed": config.apply,
        "external_fetch_executed": False,
        "auto_trading": False,
        "call_real_api": False,
    }
    payload: dict[str, Any] = {
        "status": status,
        "title": "JPX Ticker Map Reconciliation",
        "summary": summary,
        "extra_tickers": extra_tickers,
        "missing_tickers": missing_tickers,
        "report_rows": report_rows,
    }
    prefix = "jpx_ticker_map_reconciliation"
    _write_json(config.output_dir / f"{prefix}.json", payload)
    _write_csv(config.output_dir / f"{prefix}.csv", report_rows, REPORT_COLUMNS)
    _write_text(config.output_dir / f"{prefix}.html", _report_html(payload))
    _write_text(config.output_dir / f"{prefix}.md", _report_md(payload))
    if config.apply:
        _write_csv(config.ticker_map_path, reconciled_rows, TICKER_MAP_COLUMNS)
        _write_json(config.ticker_map_path.with_suffix(".json"), reconciled_rows)
        _write_text(
            config.ticker_map_path.with_suffix(".html"),
            _ticker_map_html(reconciled_rows, summary),
        )
        _write_text(config.ticker_map_path.with_suffix(".md"), _ticker_map_md(summary))
    _mirror(
        config.output_dir,
        config.mirror_dirs,
        [f"{prefix}.csv", f"{prefix}.json", f"{prefix}.html", f"{prefix}.md"],
    )
    if config.apply:
        _mirror(
            config.ticker_map_path.parent,
            config.mirror_dirs,
            [
                "ticker_data_map.csv",
                "ticker_data_map.json",
                "ticker_data_map.html",
                "ticker_data_map.md",
            ],
        )
    return payload


def _reconciled_row(
    official_row: dict[str, str], existing_row: dict[str, str] | None
) -> dict[str, str]:
    if existing_row:
        row = {column: existing_row.get(column, "") for column in TICKER_MAP_COLUMNS}
        row["name"] = official_row.get("name", row.get("name", ""))
        row["segment"] = official_row.get("segment", row.get("segment", ""))
        return row
    return {
        "ticker": official_row.get("ticker", ""),
        "name": official_row.get("name", ""),
        "segment": official_row.get("segment", ""),
        "data_status": "missing",
        "past_price_history": "no",
        "history_rows": "0",
        "history_period": "",
        "current_price": "",
        "price_as_of": "",
        "dividend_yield_pct": "",
        "yield_as_of": "",
        "next_action": "collect_market_data",
    }


def _report_row(
    issue_type: str,
    ticker: str,
    source_row: dict[str, str],
    action: str,
) -> dict[str, str]:
    return {
        "issue_type": issue_type,
        "ticker": ticker,
        "name": source_row.get("name", ""),
        "segment": source_row.get("segment", ""),
        "action": action,
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: tuple[str, ...]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _report_html(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    rows = "".join(
        "<tr>"
        f"<td>{escape(row['issue_type'])}</td><td><code>{escape(row['ticker'])}</code></td>"
        f"<td>{escape(row['name'])}</td><td>{escape(row['segment'])}</td>"
        f"<td>{escape(row['action'])}</td></tr>"
        for row in payload["report_rows"]
    )
    css = _css()
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{escape(payload['title'])}</title><style>{css}</style></head>"
        "<body><main class='shell'>"
        f"<h1>{escape(payload['title'])}</h1><section class='grid'>"
        "<article class='card'><h2>Status</h2>"
        f"<div class='metric'>{summary['status']}</div></article>"
        "<article class='card'><h2>Official</h2>"
        f"<div class='metric'>{summary['official_domestic_stock_issues']:,}</div></article>"
        "<article class='card'><h2>Input</h2>"
        f"<div class='metric'>{summary['input_ticker_map_rows']:,}</div></article>"
        "<article class='card'><h2>Reconciled</h2>"
        f"<div class='metric'>{summary['reconciled_ticker_map_rows']:,}</div></article></section>"
        "<section class='card'><h2>Corrections</h2><table><thead><tr>"
        "<th>Type</th><th>Ticker</th><th>Name</th><th>Segment</th><th>Action</th>"
        f"</tr></thead><tbody>{rows}</tbody></table></section></main></body></html>\n"
    )


def _ticker_map_html(rows: list[dict[str, str]], summary: dict[str, Any]) -> str:
    table_rows = "".join(
        "<tr>"
        f"<td><code>{escape(row['ticker'])}</code></td><td>{escape(row['name'])}</td>"
        f"<td>{escape(row['segment'])}</td><td>{escape(row['data_status'])}</td>"
        f"<td>{escape(row['next_action'])}</td></tr>"
        for row in rows
    )
    css = _css()
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Ticker Data Map</title><style>{css}</style></head><body><main class='shell'>"
        "<h1>Ticker Data Map</h1><p>JPX domestic stock universe aligned ticker map.</p>"
        "<section class='grid'>"
        f"<article class='card'><h2>Rows</h2><div class='metric'>{len(rows):,}</div></article>"
        "<article class='card'><h2>Extra removed</h2>"
        f"<div class='metric'>{summary['extra_removed_count']}</div></article>"
        "<article class='card'><h2>Missing added</h2>"
        f"<div class='metric'>{summary['missing_added_count']}</div></article>"
        "</section><section class='card'><table><thead><tr><th>Ticker</th><th>Name</th>"
        f"<th>Segment</th><th>Status</th><th>Next action</th></tr></thead><tbody>{table_rows}"
        "</tbody></table></section></main></body></html>\n"
    )


def _report_md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    return (
        "# JPX Ticker Map Reconciliation\n\n"
        f"- status: {summary['status']}\n"
        f"- official_domestic_stock_issues: {summary['official_domestic_stock_issues']}\n"
        f"- input_ticker_map_rows: {summary['input_ticker_map_rows']}\n"
        f"- reconciled_ticker_map_rows: {summary['reconciled_ticker_map_rows']}\n"
        f"- extra_removed_count: {summary['extra_removed_count']}\n"
        f"- missing_added_count: {summary['missing_added_count']}\n"
        f"- source_data_write_executed: {str(summary['source_data_write_executed']).lower()}\n"
    )


def _ticker_map_md(summary: dict[str, Any]) -> str:
    return (
        "# Ticker Data Map\n\n"
        f"- rows: {summary['reconciled_ticker_map_rows']}\n"
        f"- extra_removed_count: {summary['extra_removed_count']}\n"
        f"- missing_added_count: {summary['missing_added_count']}\n"
        "- denominator: JPX domestic stock issues\n"
    )


def _css() -> str:
    return (
        ":root{color-scheme:light;font-family:Inter,'Segoe UI',sans-serif;"
        "color:#172033;background:#f6f8fb}body{margin:0}.shell{max-width:1180px;"
        "margin:auto;padding:32px 22px}.grid{display:grid;grid-template-columns:"
        "repeat(auto-fit,minmax(220px,1fr));gap:14px}.card{background:white;border:"
        "1px solid #dbe3ee;border-radius:8px;padding:18px;margin:14px 0}.metric{"
        "font-size:28px;font-weight:850}table{width:100%;border-collapse:collapse}"
        "th,td{border-bottom:1px solid #e5eaf2;text-align:left;padding:9px}"
        "th{background:#f1f5f9}"
    )


def _mirror(source_dir: Path, mirror_dirs: tuple[Path, ...], names: list[str]) -> None:
    for mirror_dir in mirror_dirs:
        mirror_dir.mkdir(parents=True, exist_ok=True)
        for name in names:
            source = source_dir / name
            if source.exists():
                shutil.copy2(source, mirror_dir / name)
