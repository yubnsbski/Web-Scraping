"""Build data gap dashboard artifacts from the reconciled ticker map."""

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

GAP_COLUMNS = (
    "ticker",
    "name",
    "segment",
    "current_price",
    "as_of",
    "missing_fields",
    "priority_score",
    "reason",
    "source_ref",
    "provider_id",
)


@dataclass(frozen=True)
class DataGapDashboardConfig:
    ticker_map_path: Path
    output_dir: Path
    generated_at: str | None = None
    max_priority_rows: int = 100
    mirror_dirs: tuple[Path, ...] = ()


def build_data_gap_dashboard(config: DataGapDashboardConfig) -> dict[str, Any]:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    rows = _read_csv(config.ticker_map_path)
    universe_count = len(rows)
    price_ready = [row for row in rows if _clean(row.get("current_price"))]
    yield_ready = [row for row in rows if _clean(row.get("dividend_yield_pct"))]
    gaps = [_gap_row(row) for row in rows if _missing_fields(row)]
    gaps.sort(key=lambda row: (-int(row["priority_score"]), row["ticker"]))
    segment_gap_counts = [
        {"segment": segment, "gap_count": count}
        for segment, count in sorted(
            Counter(row["segment"] for row in gaps).items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]
    missing_field_counts = [
        {"missing_field": field, "gap_count": count}
        for field, count in sorted(_missing_field_counter(rows).items())
    ]
    generated_at = config.generated_at or datetime.now().astimezone().isoformat(timespec="seconds")
    summary = {
        "universe_count": universe_count,
        "price_count": len(price_ready),
        "yield_ready_count": len(yield_ready),
        "yield_gap_count": universe_count - len(yield_ready),
        "price_gap_count": universe_count - len(price_ready),
        "price_coverage_pct": _percent(len(price_ready), universe_count),
        "yield_coverage_pct": _percent(len(yield_ready), universe_count),
        "gap_rate_pct": _percent(universe_count - len(yield_ready), universe_count),
        "latest_as_of": max((row.get("price_as_of", "") for row in rows), default=""),
        "source_data_write_executed": False,
        "external_fetch_executed": False,
        "auto_trading": False,
        "call_real_api": False,
    }
    payload: dict[str, Any] = {
        "schema_version": 2,
        "status": "needs_attention" if gaps else "ready",
        "generated_at": generated_at,
        "objective": "seamless_market_data_visualization",
        "summary": summary,
        "missing_field_counts": missing_field_counts,
        "segment_gap_counts": segment_gap_counts,
        "priority_gaps": gaps[: config.max_priority_rows],
        "notes": [
            "Universe comes from the reconciled JPX domestic stock ticker map.",
            "Yield gaps are data-completeness tasks, not investment advice.",
            "This artifact reads local CSV files only and does not fetch external data.",
        ],
    }
    prefix = "data_gap_dashboard"
    _write_json(config.output_dir / f"{prefix}.json", payload)
    _write_csv(config.output_dir / f"{prefix}.csv", gaps, GAP_COLUMNS)
    _write_text(config.output_dir / f"{prefix}.html", _html(payload))
    _write_text(config.output_dir / f"{prefix}.md", _md(payload))
    _mirror(config.output_dir, config.mirror_dirs, prefix)
    return payload


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: tuple[str, ...]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _clean(value: object) -> str:
    return str(value or "").strip()


def _missing_fields(row: dict[str, str]) -> list[str]:
    missing = []
    if not _clean(row.get("current_price")):
        missing.append("current_price")
    if not _clean(row.get("dividend_yield_pct")):
        missing.append("dividend_yield_pct")
    return missing


def _missing_field_counter(rows: list[dict[str, str]]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for row in rows:
        counter.update(_missing_fields(row))
    return counter


def _gap_row(row: dict[str, str]) -> dict[str, Any]:
    missing = _missing_fields(row)
    price_ready = "current_price" not in missing
    priority = 100 if price_ready else 80
    return {
        "ticker": row.get("ticker", ""),
        "name": row.get("name", ""),
        "segment": row.get("segment", ""),
        "current_price": row.get("current_price", ""),
        "as_of": row.get("price_as_of", ""),
        "missing_fields": ";".join(missing),
        "priority_score": priority,
        "reason": (
            "Price exists but yield evidence is missing."
            if price_ready
            else "Ticker is in the JPX domestic universe but price evidence is missing."
        ),
        "source_ref": "web/public/market-dashboard/ticker_data_map.csv",
        "provider_id": "local_ticker_map",
    }


def _percent(numerator: int, denominator: int) -> float:
    return round(numerator / denominator * 100, 2) if denominator else 0.0


def _html(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    missing_rows = "".join(
        f"<tr><td><code>{escape(row['missing_field'])}</code></td><td>{row['gap_count']}</td></tr>"
        for row in payload["missing_field_counts"]
    )
    priority_rows = "".join(
        "<tr>"
        f"<td><code>{escape(row['ticker'])}</code></td>"
        f"<td>{escape(row['name'])}</td><td>{escape(row['segment'])}</td>"
        f"<td>{escape(str(row['current_price']))}</td>"
        f"<td><code>{escape(row['missing_fields'])}</code></td>"
        f"<td>{row['priority_score']}</td></tr>"
        for row in payload["priority_gaps"]
    )
    css = (
        ":root{color-scheme:light;font-family:Inter,'Segoe UI',sans-serif;"
        "color:#172033;background:#f6f8fb}body{margin:0}.shell{max-width:1180px;"
        "margin:auto;padding:32px 22px}.grid{display:grid;grid-template-columns:"
        "repeat(auto-fit,minmax(220px,1fr));gap:14px}.card{background:white;border:"
        "1px solid #dbe3ee;border-radius:8px;padding:18px;margin:14px 0}.metric{"
        "font-size:28px;font-weight:850}table{width:100%;border-collapse:collapse}"
        "th,td{border-bottom:1px solid #e5eaf2;text-align:left;padding:9px}"
        "th{background:#f1f5f9}"
    )
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Data Gap Dashboard</title><style>{css}</style></head>"
        "<body><main class='shell'><h1>Data Gap Dashboard</h1>"
        "<p>Completeness view for the JPX domestic stock universe. Non-advisory, no "
        "trading, no external fetch.</p><section class='grid'>"
        "<article class='card'><h2>Universe</h2>"
        f"<div class='metric'>{summary['universe_count']:,}</div></article>"
        "<article class='card'><h2>Price coverage</h2>"
        f"<div class='metric'>{summary['price_coverage_pct']}%</div></article>"
        "<article class='card'><h2>Yield coverage</h2>"
        f"<div class='metric'>{summary['yield_coverage_pct']}%</div>"
        f"<p>{summary['yield_ready_count']:,}/{summary['universe_count']:,} ready</p>"
        "</article>"
        "<article class='card'><h2>Yield ready</h2>"
        f"<div class='metric'>{summary['yield_ready_count']:,}/"
        f"{summary['universe_count']:,}</div></article>"
        "<article class='card'><h2>Yield gaps</h2>"
        f"<div class='metric'>{summary['yield_gap_count']:,}</div></article>"
        "</section><section class='card'><h2>Missing Fields</h2><table><thead><tr>"
        f"<th>Field</th><th>Count</th></tr></thead><tbody>{missing_rows}</tbody></table>"
        "</section><section class='card'><h2>Priority Gaps</h2><table><thead><tr>"
        "<th>Ticker</th><th>Name</th><th>Segment</th><th>Price</th><th>Missing</th>"
        f"<th>Priority</th></tr></thead><tbody>{priority_rows}</tbody></table></section>"
        "</main></body></html>\n"
    )


def _md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    return (
        "# Data Gap Dashboard\n\n"
        f"- status: {payload['status']}\n"
        f"- universe_count: {summary['universe_count']}\n"
        f"- price_count: {summary['price_count']}\n"
        f"- yield_ready_count: {summary['yield_ready_count']}\n"
        f"- yield_gap_count: {summary['yield_gap_count']}\n"
        f"- price_coverage_pct: {summary['price_coverage_pct']}\n"
        f"- yield_coverage_pct: {summary['yield_coverage_pct']}\n"
        "- source_data_write_executed: false\n"
        "- external_fetch_executed: false\n"
        "- auto_trading: false\n"
    )


def _mirror(output_dir: Path, mirror_dirs: tuple[Path, ...], prefix: str) -> None:
    names = [f"{prefix}.csv", f"{prefix}.json", f"{prefix}.html", f"{prefix}.md"]
    for mirror_dir in mirror_dirs:
        mirror_dir.mkdir(parents=True, exist_ok=True)
        for name in names:
            source = output_dir / name
            if source.exists():
                shutil.copy2(source, mirror_dir / name)
