"""Audit raw market sources against the cleaned JPX domestic universe."""

from __future__ import annotations

import csv
import json
import shutil
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

JsonDict = dict[str, Any]

_TICKER_COLUMNS = ("ticker", "code", "\u30b3\u30fc\u30c9", "ticker_or_fund_code", "fund_code")


@dataclass(frozen=True)
class SourceDriftAuditConfig:
    output_dir: Path
    reference_universe_path: Path = Path("local_docs/market/domestic_universe.csv")
    cleaned_map_path: Path = Path("web/public/market-dashboard/ticker_data_map.csv")
    current_prices_path: Path = Path("local_docs/market/current_prices.csv")
    market_financials_path: Path = Path("local_docs/market/yahoo_financials.csv")
    mirror_dirs: tuple[Path, ...] = field(default_factory=tuple)
    generated_at: str | None = None
    max_queue_rows: int = 100


def build_source_drift_audit(config: SourceDriftAuditConfig) -> JsonDict:
    """Build JSON/CSV/HTML/Markdown artifacts for source-vs-cleaned drift."""

    config.output_dir.mkdir(parents=True, exist_ok=True)
    reference_rows = _read_csv(config.reference_universe_path)
    cleaned_rows = _read_csv(config.cleaned_map_path)
    reference = _ticker_set(reference_rows)
    cleaned = _ticker_set(cleaned_rows)
    cleaned_extra = cleaned - reference
    cleaned_missing = reference - cleaned

    source_specs = (
        ("current_prices", config.current_prices_path),
        ("market_financials", config.market_financials_path),
    )
    sources = [
        _profile_source(source_id, path, reference)
        for source_id, path in source_specs
    ]
    queue_candidates = _build_action_queue(sources)
    queue = queue_candidates[: config.max_queue_rows]
    total_extra = sum(int(source["extra_ticker_count"]) for source in sources)
    total_missing = sum(int(source["missing_ticker_count"]) for source in sources)
    total_duplicates = sum(int(source["duplicate_ticker_count"]) for source in sources)
    source_with_drift = sum(1 for source in sources if source["status"] != "pass")
    cleaned_map_matches_reference = not cleaned_extra and not cleaned_missing
    status = (
        "pass"
        if source_with_drift == 0 and cleaned_map_matches_reference
        else "needs_attention"
    )
    payload: JsonDict = {
        "schema_version": 1,
        "status": status,
        "title": "Source Drift Audit",
        "generated_at": config.generated_at
        or datetime.now().astimezone().isoformat(timespec="seconds"),
        "summary": {
            "reference_count": len(reference),
            "cleaned_map_count": len(cleaned),
            "cleaned_map_matches_reference": cleaned_map_matches_reference,
            "cleaned_map_extra_count": len(cleaned_extra),
            "cleaned_map_missing_count": len(cleaned_missing),
            "source_count": len(sources),
            "source_with_drift_count": source_with_drift,
            "total_extra_ticker_count": total_extra,
            "total_missing_ticker_count": total_missing,
            "total_duplicate_ticker_count": total_duplicates,
            "action_candidate_count": len(queue_candidates),
            "action_queue_count": len(queue),
            "action_queue_complete": len(queue) == len(queue_candidates),
            "source_data_write_executed": False,
            "external_fetch_executed": False,
            "auto_trading": False,
            "call_real_api": False,
        },
        "sources": sources,
        "action_queue": queue,
        "notes": [
            "Raw source files are not modified by this audit.",
            "Reference universe is the JPX domestic stock universe.",
            "Extra tickers should be quarantined before downstream scoring or RAG ingestion.",
            "Missing tickers should be handled through an explicit data-entry or fetch workflow.",
        ],
    }
    _write_json(config.output_dir / "source_drift_audit.json", payload)
    _write_csv(config.output_dir / "source_drift_audit.csv", payload)
    _write_html(config.output_dir / "source_drift_audit.html", payload)
    _write_markdown(config.output_dir / "source_drift_audit.md", payload)
    _mirror_artifacts(config.output_dir, config.mirror_dirs)
    return payload


def _profile_source(source_id: str, path: Path, reference: set[str]) -> JsonDict:
    rows = _read_csv(path)
    tickers = _ticker_set(rows)
    extra = tickers - reference
    missing = reference - tickers
    duplicate_tickers = _duplicate_tickers(rows)
    duplicate_count = len(duplicate_tickers)
    coverage_pct = (
        round(((len(reference & tickers) / len(reference)) * 100.0), 2)
        if reference
        else 0.0
    )
    status = "pass" if not extra and not missing and duplicate_count == 0 else "needs_attention"
    return {
        "source_id": source_id,
        "path": str(path),
        "status": status,
        "row_count": len(rows),
        "ticker_count": len(tickers),
        "reference_count": len(reference),
        "coverage_pct": coverage_pct,
        "extra_ticker_count": len(extra),
        "missing_ticker_count": len(missing),
        "duplicate_ticker_count": duplicate_count,
        "extra_tickers": _sample_values(extra, limit=None),
        "missing_tickers": _sample_values(missing, limit=None),
        "duplicate_tickers": duplicate_tickers,
        "extra_ticker_sample": _sample_values(extra),
        "missing_ticker_sample": _sample_values(missing),
        "duplicate_ticker_sample": duplicate_tickers[:10],
        "next_action": _next_action(extra, missing, duplicate_count),
    }


def _build_action_queue(sources: list[JsonDict]) -> list[JsonDict]:
    queue: list[JsonDict] = []
    for source in sources:
        source_id = str(source["source_id"])
        path = str(source["path"])
        for ticker in source["extra_tickers"]:
            queue.append(
                {
                    "source_id": source_id,
                    "issue_type": "extra_ticker",
                    "ticker": ticker,
                    "priority": 10,
                    "reason": "Ticker exists in raw source but not in JPX domestic universe.",
                    "source_ref": path,
                }
            )
        for ticker in source["missing_tickers"]:
            queue.append(
                {
                    "source_id": source_id,
                    "issue_type": "missing_ticker",
                    "ticker": ticker,
                    "priority": 20,
                    "reason": "Ticker exists in JPX domestic universe but not in raw source.",
                    "source_ref": path,
                }
            )
        for ticker in source["duplicate_tickers"]:
            queue.append(
                {
                    "source_id": source_id,
                    "issue_type": "duplicate_ticker",
                    "ticker": ticker,
                    "priority": 30,
                    "reason": "Ticker appears more than once in raw source.",
                    "source_ref": path,
                }
            )
    queue.sort(key=lambda row: (int(row["priority"]), str(row["source_id"]), str(row["ticker"])))
    return queue


def _next_action(extra: set[str], missing: set[str], duplicate_count: int) -> str:
    actions: list[str] = []
    if extra:
        actions.append("quarantine extra tickers")
    if missing:
        actions.append("fill missing JPX domestic tickers")
    if duplicate_count:
        actions.append("deduplicate raw source rows")
    return "; ".join(actions) if actions else "keep monitoring"


def _read_csv(path: Path) -> list[JsonDict]:
    for encoding in ("utf-8-sig", "utf-8", "cp932"):
        try:
            with path.open(newline="", encoding=encoding) as handle:
                return [dict(row) for row in csv.DictReader(handle)]
        except UnicodeError:
            continue
    return []


def _ticker_set(rows: list[JsonDict]) -> set[str]:
    return {
        ticker
        for row in rows
        if (ticker := _normalize_ticker(_first_value(row, _TICKER_COLUMNS)))
    }


def _duplicate_tickers(rows: list[JsonDict]) -> list[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        ticker = _normalize_ticker(_first_value(row, _TICKER_COLUMNS))
        if ticker:
            counts[ticker] += 1
    return sorted(ticker for ticker, count in counts.items() if count > 1)


def _first_value(row: JsonDict, columns: tuple[str, ...]) -> str:
    for column in columns:
        value = str(row.get(column) or "").strip()
        if value:
            return value
    return ""


def _normalize_ticker(value: str) -> str:
    return str(value or "").strip().upper()


def _sample_values(values: set[str], *, limit: int | None = 10) -> list[str]:
    ordered = sorted(values)
    return ordered if limit is None else ordered[:limit]


def _write_json(path: Path, payload: JsonDict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _write_csv(path: Path, payload: JsonDict) -> None:
    fieldnames = [
        "source_id",
        "issue_type",
        "ticker",
        "priority",
        "reason",
        "source_ref",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(payload["action_queue"])


def _write_html(path: Path, payload: JsonDict) -> None:
    summary = payload["summary"]
    cards = [
        ("Reference", f"{summary['reference_count']:,}"),
        ("Sources With Drift", summary["source_with_drift_count"]),
        ("Extra Tickers", summary["total_extra_ticker_count"]),
        ("Missing Tickers", summary["total_missing_ticker_count"]),
    ]
    card_html = "".join(
        "<article class='card'>"
        f"<h2>{escape(str(label))}</h2><div class='metric'>{escape(str(value))}</div>"
        "</article>"
        for label, value in cards
    )
    source_rows = "".join(
        "<tr>"
        f"<td><code>{escape(str(row['source_id']))}</code></td>"
        f"<td>{escape(str(row['status']))}</td>"
        f"<td>{escape(str(row['ticker_count']))}</td>"
        f"<td>{escape(str(row['coverage_pct']))}%</td>"
        f"<td>{escape(str(row['extra_ticker_count']))}</td>"
        f"<td>{escape(str(row['missing_ticker_count']))}</td>"
        f"<td>{escape(str(row['duplicate_ticker_count']))}</td>"
        "</tr>"
        for row in payload["sources"]
    )
    queue_rows = "".join(
        "<tr>"
        f"<td><code>{escape(str(row['source_id']))}</code></td>"
        f"<td>{escape(str(row['issue_type']))}</td>"
        f"<td><code>{escape(str(row['ticker']))}</code></td>"
        f"<td>{escape(str(row['priority']))}</td>"
        f"<td>{escape(str(row['reason']))}</td>"
        "</tr>"
        for row in payload["action_queue"]
    )
    css = (
        ":root{color-scheme:light;font-family:Inter,'Segoe UI',sans-serif;"
        "color:#172033;background:#f6f8fb}body{margin:0}.shell{max-width:1180px;"
        "margin:auto;padding:32px 22px}.grid{display:grid;grid-template-columns:"
        "repeat(auto-fit,minmax(220px,1fr));gap:14px}.card{background:white;"
        "border:1px solid #dbe3ee;border-radius:8px;padding:18px;margin:14px 0}"
        ".metric{font-size:28px;font-weight:850}table{width:100%;border-collapse:"
        "collapse}th,td{border-bottom:1px solid #e5eaf2;text-align:left;padding:9px}"
        "th{background:#f1f5f9}.notice{font-weight:700;color:#44546a}"
    )
    html = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{escape(str(payload['title']))}</title><style>{css}</style></head>"
        "<body><main class='shell'>"
        f"<h1>{escape(str(payload['title']))}</h1>"
        "<p class='notice'>Raw source vs cleaned JPX domestic universe. "
        "No source write, no external fetch, no trading.</p>"
        f"<section class='grid'>{card_html}</section>"
        "<section class='card'><h2>Source Summary</h2><table><thead><tr>"
        "<th>Source</th><th>Status</th><th>Tickers</th><th>Coverage</th>"
        "<th>Extra</th><th>Missing</th><th>Duplicates</th>"
        f"</tr></thead><tbody>{source_rows}</tbody></table></section>"
        "<section class='card'><h2>Action Queue</h2><table><thead><tr>"
        "<th>Source</th><th>Issue</th><th>Ticker</th><th>Priority</th><th>Reason</th>"
        f"</tr></thead><tbody>{queue_rows}</tbody></table></section>"
        "</main></body></html>"
    )
    path.write_text(html, encoding="utf-8")


def _write_markdown(path: Path, payload: JsonDict) -> None:
    summary = payload["summary"]
    lines = [
        "# Source Drift Audit",
        "",
        f"- status: {payload['status']}",
        f"- generated_at: {payload['generated_at']}",
        f"- reference_count: {summary['reference_count']}",
        f"- cleaned_map_count: {summary['cleaned_map_count']}",
        f"- sources_with_drift: {summary['source_with_drift_count']}",
        f"- total_extra_ticker_count: {summary['total_extra_ticker_count']}",
        f"- total_missing_ticker_count: {summary['total_missing_ticker_count']}",
        f"- total_duplicate_ticker_count: {summary['total_duplicate_ticker_count']}",
        "",
        "## Sources",
    ]
    for source in payload["sources"]:
        lines.append(
            "- "
            f"{source['source_id']}: {source['status']}, "
            f"extra={source['extra_ticker_count']}, "
            f"missing={source['missing_ticker_count']}, "
            f"duplicates={source['duplicate_ticker_count']}"
        )
    lines.extend(["", "## Queue Sample"])
    for row in payload["action_queue"][:20]:
        lines.append(
            "- "
            f"{row['source_id']} {row['issue_type']} {row['ticker']}: {row['reason']}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _mirror_artifacts(output_dir: Path, mirror_dirs: tuple[Path, ...]) -> None:
    filenames = (
        "source_drift_audit.json",
        "source_drift_audit.csv",
        "source_drift_audit.html",
        "source_drift_audit.md",
    )
    for mirror_dir in mirror_dirs:
        mirror_dir.mkdir(parents=True, exist_ok=True)
        for filename in filenames:
            shutil.copy2(output_dir / filename, mirror_dir / filename)
