"""Build non-destructive JPX domestic cleansing previews for raw market sources."""

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

_TICKER_COLUMNS = ("ticker", "code", "ticker_or_fund_code", "fund_code")
_PREFIX = "source_cleansing_preview"
_PREVIEW_FILENAMES = {
    "current_prices": "current_prices_jpx_domestic_clean_preview.csv",
    "market_financials": "market_financials_jpx_domestic_clean_preview.csv",
}


@dataclass(frozen=True)
class SourceCleansingPreviewConfig:
    output_dir: Path
    reference_universe_path: Path = Path("local_docs/market/domestic_universe.csv")
    current_prices_path: Path = Path("local_docs/market/current_prices.csv")
    market_financials_path: Path = Path("local_docs/market/yahoo_financials.csv")
    mirror_dirs: tuple[Path, ...] = field(default_factory=tuple)
    generated_at: str | None = None


def build_source_cleansing_preview(config: SourceCleansingPreviewConfig) -> JsonDict:
    """Write preview artifacts without modifying source CSV files."""

    config.output_dir.mkdir(parents=True, exist_ok=True)
    reference_rows, _ = _read_csv(config.reference_universe_path)
    reference = _ticker_set(reference_rows)
    source_specs = (
        ("current_prices", config.current_prices_path),
        ("market_financials", config.market_financials_path),
    )
    sources = [
        _build_source_preview(source_id, source_path, reference, config.output_dir)
        for source_id, source_path in source_specs
    ]
    total_dropped_rows = sum(int(source["dropped_row_count"]) for source in sources)
    total_dropped_tickers = sum(int(source["dropped_ticker_count"]) for source in sources)
    total_missing = sum(int(source["missing_ticker_count"]) for source in sources)
    total_duplicates = sum(int(source["duplicate_ticker_count"]) for source in sources)
    source_with_changes = sum(1 for source in sources if source["status"] != "pass")
    status = "ready" if source_with_changes == 0 else "needs_attention"
    payload: JsonDict = {
        "schema_version": 1,
        "status": status,
        "title": "Source Cleansing Preview",
        "generated_at": config.generated_at
        or datetime.now().astimezone().isoformat(timespec="seconds"),
        "summary": {
            "reference_count": len(reference),
            "source_count": len(sources),
            "source_with_changes_count": source_with_changes,
            "total_dropped_row_count": total_dropped_rows,
            "total_dropped_ticker_count": total_dropped_tickers,
            "total_missing_ticker_count": total_missing,
            "total_duplicate_ticker_count": total_duplicates,
            "source_data_write_executed": False,
            "external_fetch_executed": False,
            "auto_trading": False,
            "call_real_api": False,
        },
        "sources": sources,
        "notes": [
            "Raw source CSV files are never modified by this preview.",
            "Rows outside the JPX domestic stock universe are excluded from preview CSVs.",
            "Missing JPX domestic tickers are reported, not guessed or synthesized.",
            "Preview CSVs are intended for review before downstream scoring or ingestion.",
        ],
    }
    _write_json(config.output_dir / f"{_PREFIX}.json", payload)
    _write_csv(config.output_dir / f"{_PREFIX}.csv", payload)
    _write_html(config.output_dir / f"{_PREFIX}.html", payload)
    _write_markdown(config.output_dir / f"{_PREFIX}.md", payload)
    _mirror_artifacts(config.output_dir, config.mirror_dirs)
    return payload


def _build_source_preview(
    source_id: str,
    source_path: Path,
    reference: set[str],
    output_dir: Path,
) -> JsonDict:
    rows, fieldnames = _read_csv(source_path)
    ticker_column = _ticker_column(fieldnames)
    raw_tickers = _ticker_set(rows)
    preview_rows = [
        row
        for row in rows
        if _normalize_ticker(str(row.get(ticker_column) or "")) in reference
    ]
    preview_tickers = _ticker_set(preview_rows)
    dropped_rows = len(rows) - len(preview_rows)
    dropped_tickers = raw_tickers - reference
    missing_tickers = reference - raw_tickers
    duplicates = _duplicate_tickers(preview_rows)
    preview_filename = _PREVIEW_FILENAMES[source_id]
    preview_path = output_dir / preview_filename
    _write_preview_csv(preview_path, fieldnames, preview_rows)
    status = (
        "pass"
        if not dropped_tickers and not missing_tickers and not duplicates
        else "needs_attention"
    )
    return {
        "source_id": source_id,
        "source_path": str(source_path),
        "status": status,
        "raw_row_count": len(rows),
        "raw_ticker_count": len(raw_tickers),
        "clean_preview_row_count": len(preview_rows),
        "clean_preview_ticker_count": len(preview_tickers),
        "reference_count": len(reference),
        "kept_reference_coverage_pct": _percent(len(preview_tickers), len(reference)),
        "dropped_row_count": dropped_rows,
        "dropped_ticker_count": len(dropped_tickers),
        "missing_ticker_count": len(missing_tickers),
        "duplicate_ticker_count": len(duplicates),
        "dropped_ticker_sample": _sample_values(dropped_tickers),
        "missing_ticker_sample": _sample_values(missing_tickers),
        "duplicate_ticker_sample": duplicates[:10],
        "preview_filename": preview_filename,
        "preview_path": str(preview_path),
        "source_data_write_executed": False,
    }


def _read_csv(path: Path) -> tuple[list[JsonDict], list[str]]:
    for encoding in ("utf-8-sig", "utf-8", "cp932"):
        try:
            with path.open(newline="", encoding=encoding) as handle:
                reader = csv.DictReader(handle)
                rows = [dict(row) for row in reader]
                return rows, list(reader.fieldnames or [])
        except UnicodeError:
            continue
    return [], []


def _ticker_column(fieldnames: list[str]) -> str:
    lower_to_original = {field.lower(): field for field in fieldnames}
    for candidate in _TICKER_COLUMNS:
        if candidate in lower_to_original:
            return lower_to_original[candidate]
    raise ValueError(f"CSV is missing a ticker column. fieldnames={fieldnames}")


def _ticker_set(rows: list[JsonDict]) -> set[str]:
    tickers: set[str] = set()
    for row in rows:
        ticker = _normalize_ticker(_first_value(row, _TICKER_COLUMNS))
        if ticker:
            tickers.add(ticker)
    return tickers


def _duplicate_tickers(rows: list[JsonDict]) -> list[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        ticker = _normalize_ticker(_first_value(row, _TICKER_COLUMNS))
        if ticker:
            counts[ticker] += 1
    return sorted(ticker for ticker, count in counts.items() if count > 1)


def _first_value(row: JsonDict, columns: tuple[str, ...]) -> str:
    lower_to_original = {str(key).lower(): key for key in row}
    for column in columns:
        original = lower_to_original.get(column)
        value = str(row.get(original) or "").strip() if original is not None else ""
        if value:
            return value
    return ""


def _normalize_ticker(value: str) -> str:
    return str(value or "").strip().upper()


def _sample_values(values: set[str], *, limit: int = 10) -> list[str]:
    return sorted(values)[:limit]


def _percent(numerator: int, denominator: int) -> float:
    return round(numerator / denominator * 100, 2) if denominator else 0.0


def _write_preview_csv(path: Path, fieldnames: list[str], rows: list[JsonDict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: JsonDict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _write_csv(path: Path, payload: JsonDict) -> None:
    fieldnames = [
        "source_id",
        "source_path",
        "status",
        "raw_row_count",
        "clean_preview_row_count",
        "dropped_row_count",
        "dropped_ticker_count",
        "missing_ticker_count",
        "duplicate_ticker_count",
        "preview_filename",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(payload["sources"])


def _write_html(path: Path, payload: JsonDict) -> None:
    summary = payload["summary"]
    cards = [
        ("Reference", f"{summary['reference_count']:,}"),
        ("Dropped Rows", summary["total_dropped_row_count"]),
        ("Missing Tickers", summary["total_missing_ticker_count"]),
        ("Preview Sources", summary["source_count"]),
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
        f"<td>{escape(str(row['raw_row_count']))}</td>"
        f"<td>{escape(str(row['clean_preview_row_count']))}</td>"
        f"<td>{escape(str(row['dropped_row_count']))}</td>"
        f"<td>{escape(str(row['missing_ticker_count']))}</td>"
        f"<td>{escape(str(row['kept_reference_coverage_pct']))}%</td>"
        f"<td><code>{escape(str(row['preview_filename']))}</code></td>"
        "</tr>"
        for row in payload["sources"]
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
        "<p class='notice'>JPX domestic clean previews. Raw CSVs are not modified; "
        "no external fetch, no API call, no trading.</p>"
        f"<section class='grid'>{card_html}</section>"
        "<section class='card'><h2>Preview Summary</h2><table><thead><tr>"
        "<th>Source</th><th>Status</th><th>Raw rows</th><th>Preview rows</th>"
        "<th>Dropped</th><th>Missing</th><th>Coverage</th><th>Preview file</th>"
        f"</tr></thead><tbody>{source_rows}</tbody></table></section>"
        "</main></body></html>"
    )
    path.write_text(html, encoding="utf-8")


def _write_markdown(path: Path, payload: JsonDict) -> None:
    summary = payload["summary"]
    lines = [
        "# Source Cleansing Preview",
        "",
        f"- status: {payload['status']}",
        f"- generated_at: {payload['generated_at']}",
        f"- reference_count: {summary['reference_count']}",
        f"- source_count: {summary['source_count']}",
        f"- total_dropped_row_count: {summary['total_dropped_row_count']}",
        f"- total_missing_ticker_count: {summary['total_missing_ticker_count']}",
        f"- source_data_write_executed: {str(summary['source_data_write_executed']).lower()}",
        f"- external_fetch_executed: {str(summary['external_fetch_executed']).lower()}",
        f"- auto_trading: {str(summary['auto_trading']).lower()}",
        "",
        "## Sources",
    ]
    for source in payload["sources"]:
        lines.append(
            "- "
            f"{source['source_id']}: raw_rows={source['raw_row_count']}, "
            f"preview_rows={source['clean_preview_row_count']}, "
            f"dropped_rows={source['dropped_row_count']}, "
            f"missing={source['missing_ticker_count']}, "
            f"preview={source['preview_filename']}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _mirror_artifacts(output_dir: Path, mirror_dirs: tuple[Path, ...]) -> None:
    filenames = (
        f"{_PREFIX}.json",
        f"{_PREFIX}.csv",
        f"{_PREFIX}.html",
        f"{_PREFIX}.md",
        *_PREVIEW_FILENAMES.values(),
    )
    for mirror_dir in mirror_dirs:
        mirror_dir.mkdir(parents=True, exist_ok=True)
        for filename in filenames:
            source = output_dir / filename
            if source.exists():
                shutil.copy2(source, mirror_dir / filename)
