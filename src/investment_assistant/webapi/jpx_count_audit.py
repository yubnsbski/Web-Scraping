"""JPX count audit artifacts for the market dashboard."""

from __future__ import annotations

import csv
import json
import shutil
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

DOMESTIC_STOCK_MARKER = "\u5185\u56fd\u682a\u5f0f"
DEFAULT_SOURCE_URL = (
    "https://www.jpx.co.jp/markets/statistics-equities/misc/"
    "tvdivq0000001vg2-att/data_j.xls"
)
DEFAULT_COMPANY_COUNT_URL = "https://www.jpx.co.jp/listing/co/index.html"
CHECK_COLUMNS = ("check_id", "status", "actual", "expected", "evidence", "next_action")


@dataclass(frozen=True)
class JpxCountAuditConfig:
    dashboard_root: Path
    output_dir: Path | None = None
    expected_listed_issues: int = 4437
    expected_domestic_stock_issues: int = 3716
    expected_listed_companies: int = 3897
    listed_issues_as_of: str = "2026-06-30"
    listed_companies_as_of: str = "2026-07-02"
    generated_at: str | None = None
    mirror_dirs: tuple[Path, ...] = ()


def build_jpx_count_audit(config: JpxCountAuditConfig) -> dict[str, Any]:
    output_dir = config.output_dir or config.dashboard_root
    output_dir.mkdir(parents=True, exist_ok=True)
    ticker_map_path = config.dashboard_root / "ticker_data_map.csv"
    review_path = config.dashboard_root / "data_quality_sprint_review.json"
    entry_path = config.dashboard_root / "market_dashboard_entry.html"

    ticker_rows = _read_csv(ticker_map_path)
    ticker_counts = Counter(row.get("ticker", "") for row in ticker_rows if row.get("ticker"))
    duplicates = sorted(ticker for ticker, count in ticker_counts.items() if count > 1)
    domestic_rows = [
        row for row in ticker_rows if DOMESTIC_STOCK_MARKER in str(row.get("segment", ""))
    ]
    review_summary = _read_json(review_path).get("summary", {}) if review_path.exists() else {}
    entry_html = entry_path.read_text(encoding="utf-8-sig") if entry_path.exists() else ""
    generated_at = config.generated_at or datetime.now().astimezone().isoformat(timespec="seconds")

    checks = [
        _check(
            "ticker_map_rows_match_domestic_stock_issues",
            len(ticker_rows),
            config.expected_domestic_stock_issues,
            "ticker_data_map.csv row count should represent JPX domestic stock issues.",
            "Regenerate the ticker map from the JPX listed-issues universe.",
        ),
        _check(
            "ticker_map_segments_match_domestic_stock_issues",
            len(domestic_rows),
            config.expected_domestic_stock_issues,
            "ticker_data_map.csv segment filter contains domestic stock issue rows.",
            "Review segment normalization before using the universe as a denominator.",
        ),
        _check(
            "sprint_review_uses_domestic_stock_denominator",
            review_summary.get("domestic_stock_count"),
            config.expected_domestic_stock_issues,
            "data_quality_sprint_review.json summary.domestic_stock_count.",
            "Refresh the sprint review so Completeness uses the JPX domestic universe.",
        ),
        _check(
            "entry_screen_shows_listed_issue_and_domestic_counts",
            _entry_claim(
                entry_html,
                config.expected_listed_issues,
                config.expected_domestic_stock_issues,
            ),
            "present",
            "market_dashboard_entry.html should show both JPX listed issues and domestic stocks.",
            "Update the entry screen copy to make the denominator explicit.",
        ),
        _check(
            "no_duplicate_tickers_in_ticker_map",
            len(duplicates),
            0,
            "ticker_data_map.csv should not duplicate ticker identifiers.",
            "Deduplicate ticker_data_map.csv before downstream joins.",
        ),
    ]
    status = "pass" if all(row["status"] == "pass" for row in checks) else "needs_attention"
    payload: dict[str, Any] = {
        "status": status,
        "title": "JPX Listed Issue Count Audit",
        "generated_at": generated_at,
        "summary": {
            "status": status,
            "listed_issues_as_of": config.listed_issues_as_of,
            "listed_issues_source_url": DEFAULT_SOURCE_URL,
            "jpx_listed_issues": config.expected_listed_issues,
            "jpx_domestic_stock_issues": config.expected_domestic_stock_issues,
            "listed_companies_as_of": config.listed_companies_as_of,
            "listed_companies_source_url": DEFAULT_COMPANY_COUNT_URL,
            "jpx_listed_companies": config.expected_listed_companies,
            "local_ticker_map_rows": len(ticker_rows),
            "local_domestic_stock_rows": len(domestic_rows),
            "duplicate_ticker_count": len(duplicates),
            "sprint_review_domestic_stock_count": review_summary.get("domestic_stock_count"),
            "entry_screen_count_claim": _entry_claim(
                entry_html,
                config.expected_listed_issues,
                config.expected_domestic_stock_issues,
            ),
            "source_data_write_executed": False,
            "external_fetch_executed": False,
            "auto_trading": False,
            "call_real_api": False,
        },
        "checks": checks,
        "duplicate_tickers": duplicates,
        "notes": [
            "Listed companies and listed issues are different denominators.",
            "Completeness should use JPX domestic stock issues, not listed companies.",
            "This audit reads local artifacts only and does not fetch, trade, "
            "or write source data.",
        ],
    }

    prefix = "jpx_listed_issue_count_audit"
    _write_json(output_dir / f"{prefix}.json", payload)
    _write_csv(output_dir / f"{prefix}.csv", checks, CHECK_COLUMNS)
    _write_text(output_dir / f"{prefix}.html", _html(payload))
    _write_text(output_dir / f"{prefix}.md", _md(payload))
    _mirror(output_dir, config.mirror_dirs, prefix)
    return payload


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: tuple[str, ...]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _check(
    check_id: str,
    actual: object,
    expected: object,
    evidence: str,
    next_action: str,
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "status": "pass" if actual == expected else "fail",
        "actual": actual,
        "expected": expected,
        "evidence": evidence,
        "next_action": "Keep monitoring." if actual == expected else next_action,
    }


def _entry_claim(html: str, listed_issues: int, domestic_stock_issues: int) -> str:
    listed_claim = f"{listed_issues:,}" in html
    domestic_claim = f"{domestic_stock_issues:,}" in html
    return "present" if listed_claim and domestic_claim else "missing"


def _html(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    check_rows = "".join(
        "<tr>"
        f"<td><code>{escape(str(row['check_id']))}</code></td>"
        f"<td>{escape(str(row['status']))}</td>"
        f"<td>{escape(str(row['actual']))}</td>"
        f"<td>{escape(str(row['expected']))}</td>"
        f"<td>{escape(str(row['evidence']))}</td>"
        "</tr>"
        for row in payload["checks"]
    )
    css = (
        ":root{color-scheme:light;font-family:Inter,'Segoe UI',sans-serif;"
        "color:#172033;background:#f6f8fb}body{margin:0}.shell{max-width:1120px;"
        "margin:auto;padding:32px 22px}.grid{display:grid;grid-template-columns:"
        "repeat(auto-fit,minmax(220px,1fr));gap:14px}.card{background:white;border:"
        "1px solid #dbe3ee;border-radius:8px;padding:18px;margin:14px 0}.metric{"
        "font-size:28px;font-weight:850}table{width:100%;border-collapse:collapse}"
        "th,td{border-bottom:1px solid #e5eaf2;text-align:left;padding:9px}"
        "th{background:#f1f5f9}.pass{color:#047857}.needs_attention,.fail{color:#b45309}"
    )
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{escape(str(payload['title']))}</title><style>{css}</style></head>"
        "<body><main class='shell'>"
        f"<h1>{escape(str(payload['title']))}</h1>"
        "<p>Repeatable audit for JPX listed issue counts. No external fetch, no source data "
        "write, and no trading.</p><section class='grid'>"
        "<article class='card'><h2>Audit status</h2>"
        f"<div class='metric {escape(str(payload['status']))}'>"
        f"{escape(str(payload['status']))}</div>"
        "</article><article class='card'><h2>Listed issues</h2>"
        f"<div class='metric'>{summary['jpx_listed_issues']:,}</div>"
        f"<p>as of {escape(str(summary['listed_issues_as_of']))}</p></article>"
        "<article class='card'><h2>Domestic stocks</h2>"
        f"<div class='metric'>{summary['jpx_domestic_stock_issues']:,}</div>"
        "</article><article class='card'><h2>Listed companies</h2>"
        f"<div class='metric'>{summary['jpx_listed_companies']:,}</div>"
        f"<p>as of {escape(str(summary['listed_companies_as_of']))}</p></article>"
        "</section><section class='card'><h2>Checks</h2><table><thead><tr>"
        "<th>Check</th><th>Status</th><th>Actual</th><th>Expected</th><th>Evidence</th>"
        f"</tr></thead><tbody>{check_rows}</tbody></table></section>"
        f"<section class='card'><h2>Sources</h2><p><a href='{DEFAULT_SOURCE_URL}'>"
        f"JPX listed issues file</a></p><p><a href='{DEFAULT_COMPANY_COUNT_URL}'>"
        "JPX listed companies page</a></p></section></main></body></html>\n"
    )


def _md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# JPX Listed Issue Count Audit",
        "",
        f"- status: {payload['status']}",
        f"- JPX listed issues: {summary['jpx_listed_issues']:,}",
        f"- JPX domestic stock issues: {summary['jpx_domestic_stock_issues']:,}",
        f"- JPX listed companies: {summary['jpx_listed_companies']:,}",
        "- source_data_write_executed: false",
        "- external_fetch_executed: false",
        "- auto_trading: false",
        "",
        "## Checks",
    ]
    lines.extend(
        f"- {row['check_id']}: {row['status']} ({row['actual']} / {row['expected']})"
        for row in payload["checks"]
    )
    return "\n".join(lines) + "\n"


def _mirror(output_dir: Path, mirror_dirs: tuple[Path, ...], prefix: str) -> None:
    names = [path.name for path in output_dir.glob(f"{prefix}.*")]
    for mirror_dir in mirror_dirs:
        mirror_dir.mkdir(parents=True, exist_ok=True)
        for name in names:
            source = output_dir / name
            if source.exists():
                shutil.copy2(source, mirror_dir / name)
