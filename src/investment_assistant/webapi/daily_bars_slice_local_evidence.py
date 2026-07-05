"""Show local evidence candidates for Daily Bars Slice 001 without autofill."""

from __future__ import annotations

import csv
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Any

JsonDict = dict[str, Any]

JST = timezone(timedelta(hours=9))
DEFAULT_DASHBOARD_ROOT = Path("web/public/market-dashboard")
DEFAULT_MIRROR_ROOTS = (Path("web/dist/market-dashboard"), Path("local_docs/market"))
PREFIX = "daily_bars_backfill_batch001_slice001_local_evidence"
REVIEW_QUEUE = f"{PREFIX}_review_queue.csv"
INPUT_TEMPLATE = "daily_bars_backfill_batch001_slice001_input_template.csv"
READINESS_BACKLOG_JSON = "daily_bars_backfill_batch001_slice001_readiness_backlog.json"
DAILY_BARS_CSV = Path("local_docs/market/daily_bars.csv")
CURRENT_PRICES_CSV = Path("local_docs/market/current_prices.csv")
YAHOO_FINANCIALS_CSV = Path("local_docs/market/yahoo_financials.csv")
YIELD_ROADMAP_CSV = "yield_gap_batch_roadmap.csv"
REQUIRED_INPUT_FIELDS = (
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "source_provider",
    "source_url",
    "checked_at",
)
ROW_COLUMNS = (
    "ticker",
    "latest_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "ohlcv_candidate_available",
    "current_price",
    "current_price_as_of",
    "dps",
    "dividend_yield_percent",
    "yield_as_of",
    "source_ref",
    "provider_id",
    "source_url_gap",
    "checked_at_gap",
    "append_ready_candidate",
    "next_action",
)
FIELD_COLUMNS = (
    "ticker",
    "field",
    "local_candidate_available",
    "candidate_source",
    "can_fill_input_template",
    "reason",
)
REVIEW_QUEUE_COLUMNS = (
    "ticker",
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "source_provider",
    "source_url",
    "checked_at",
    "note",
    "candidate_source_ref",
    "review_status",
    "can_copy_to_input_template",
)


@dataclass(frozen=True)
class DailyBarsSliceLocalEvidenceConfig:
    dashboard_root: Path = DEFAULT_DASHBOARD_ROOT
    output_dir: Path | None = None
    input_template_path: Path | None = None
    readiness_backlog_path: Path | None = None
    daily_bars_path: Path = DAILY_BARS_CSV
    current_prices_path: Path = CURRENT_PRICES_CSV
    yahoo_financials_path: Path = YAHOO_FINANCIALS_CSV
    yield_roadmap_path: Path | None = None
    generated_at: str | None = None
    mirror_dirs: tuple[Path, ...] = DEFAULT_MIRROR_ROOTS


def build_daily_bars_slice_local_evidence(
    config: DailyBarsSliceLocalEvidenceConfig,
) -> JsonDict:
    """Build local-only candidate evidence artifacts for the active slice."""
    root = Path(config.dashboard_root)
    output_dir = Path(config.output_dir or root)
    input_path = Path(config.input_template_path or root / INPUT_TEMPLATE)
    backlog_path = Path(config.readiness_backlog_path or root / READINESS_BACKLOG_JSON)
    roadmap_path = Path(config.yield_roadmap_path or root / YIELD_ROADMAP_CSV)
    generated_at = config.generated_at or _now_jst()

    template_rows = _read_csv(input_path)
    tickers = [str(row.get("ticker") or "").strip() for row in template_rows]
    tickers = [ticker for ticker in tickers if ticker]
    daily_rows = _latest_daily_bars(_read_csv(config.daily_bars_path), tickers)
    prices = _index_by_ticker(_read_csv(config.current_prices_path))
    financials = _index_by_ticker(_read_csv(config.yahoo_financials_path))
    roadmap = _index_by_ticker(_read_csv(roadmap_path))
    backlog = _read_json(backlog_path)
    backlog_summary = _as_dict(backlog.get("summary"))

    rows = [
        _evidence_row(
            ticker=ticker,
            daily=daily_rows.get(ticker, {}),
            price=prices.get(ticker, {}),
            financial=financials.get(ticker, {}),
            roadmap=roadmap.get(ticker, {}),
        )
        for ticker in tickers
    ]
    field_matrix = _field_matrix(rows)
    review_queue = _review_queue(rows)
    source_url_gaps = sum(1 for row in rows if row["source_url_gap"])
    checked_at_gaps = sum(1 for row in rows if row["checked_at_gap"])
    candidate_count = sum(1 for row in rows if row["ohlcv_candidate_available"])
    append_ready_candidates = sum(1 for row in rows if row["append_ready_candidate"])
    prepopulated_required_fields = sum(
        1
        for row in review_queue
        for field in ("date", "open", "high", "low", "close", "volume", "source_provider")
        if _clean(row.get(field))
    )
    remaining_review_fields = sum(
        1
        for row in review_queue
        for field in ("source_url", "checked_at")
        if not _clean(row.get(field))
    )

    status = "ready" if tickers and append_ready_candidates == len(tickers) else "needs_attention"
    summary: JsonDict = {
        "generated_at": generated_at,
        "status": status,
        "slice_id": str(backlog_summary.get("slice_id") or "daily-bars-batch001-slice001"),
        "template_rows": len(tickers),
        "local_ohlcv_candidate_rows": candidate_count,
        "local_ohlcv_candidate_ticker_count": candidate_count,
        "current_price_evidence_rows": sum(1 for row in rows if row["current_price"]),
        "yield_evidence_rows": sum(1 for row in rows if row["dps"]),
        "review_queue_rows": len(review_queue),
        "prepopulated_required_field_count": prepopulated_required_fields,
        "remaining_review_field_count": remaining_review_fields,
        "source_url_gap_count": source_url_gaps,
        "checked_at_gap_count": checked_at_gaps,
        "append_ready_candidates": append_ready_candidates,
        "readiness_backlog_blockers": _as_int(backlog_summary.get("blockers")),
        "input_template_autofill_allowed": False,
        "source_data_write_executed": False,
        "write_executed": False,
        "external_fetch_executed": False,
        "auto_trading": False,
        "call_real_api": False,
        "next_sprint_goal": _next_sprint_goal(
            candidate_count=candidate_count,
            template_count=len(tickers),
            source_url_gaps=source_url_gaps,
            checked_at_gaps=checked_at_gaps,
        ),
    }
    links = {
        "local_evidence_html": f"{PREFIX}.html",
        "local_evidence_json": f"{PREFIX}.json",
        "local_evidence_csv": f"{PREFIX}.csv",
        "field_matrix_csv": f"{PREFIX}_field_matrix.csv",
        "review_queue_csv": REVIEW_QUEUE,
        "input_template": INPUT_TEMPLATE,
        "readiness_backlog": "daily_bars_backfill_batch001_slice001_readiness_backlog.html",
        "intake_validation": "daily_bars_backfill_batch001_slice001_intake_validation.html",
        "sprint_review": "data_quality_sprint_review.html",
    }
    payload: JsonDict = {
        "status": status,
        "title": "Daily Bars Slice 001 Local Evidence",
        "generated_at": generated_at,
        "summary": summary,
        "evidence_rows": rows,
        "field_matrix": field_matrix,
        "review_queue": review_queue,
        "safe_flags": {
            "write_executed": False,
            "source_data_write_executed": False,
            "external_fetch_executed": False,
            "auto_trading": False,
            "call_real_api": False,
            "advisory_output": False,
            "input_template_autofill_allowed": False,
        },
        "links": links,
        "disclaimer": (
            "Local candidate evidence only. The input template is not autofilled "
            "because audited http(s) source_url and checked_at evidence are still required."
        ),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / f"{PREFIX}.json", payload)
    _write_csv(output_dir / f"{PREFIX}.csv", rows, ROW_COLUMNS)
    _write_csv(output_dir / f"{PREFIX}_field_matrix.csv", field_matrix, FIELD_COLUMNS)
    _write_csv(output_dir / REVIEW_QUEUE, review_queue, REVIEW_QUEUE_COLUMNS)
    _write_text(output_dir / f"{PREFIX}.html", _render_html(payload))
    _write_text(output_dir / f"{PREFIX}.md", _render_md(payload))
    _mirror(output_dir, tuple(Path(path) for path in config.mirror_dirs))
    return payload


def _evidence_row(
    *,
    ticker: str,
    daily: JsonDict,
    price: JsonDict,
    financial: JsonDict,
    roadmap: JsonDict,
) -> JsonDict:
    has_ohlcv = all(
        _clean(daily.get(field))
        for field in ("date", "open", "high", "low", "close", "volume")
    )
    source_ref = _first_text(
        price.get("source_ref"),
        roadmap.get("source_ref"),
        "local_docs/market/daily_bars.csv" if has_ohlcv else "",
    )
    provider_id = _first_text(price.get("provider_id"), roadmap.get("provider_id"))
    return {
        "ticker": ticker,
        "latest_date": _clean(daily.get("date")),
        "open": _clean(daily.get("open")),
        "high": _clean(daily.get("high")),
        "low": _clean(daily.get("low")),
        "close": _clean(daily.get("close")),
        "volume": _clean(daily.get("volume")),
        "ohlcv_candidate_available": has_ohlcv,
        "current_price": _first_text(
            price.get("price"), roadmap.get("current_price"), financial.get("price")
        ),
        "current_price_as_of": _clean(price.get("as_of")),
        "dps": _first_text(financial.get("dps"), roadmap.get("current_dividend_per_share")),
        "dividend_yield_percent": _first_text(
            financial.get("dividend_yield_percent"), roadmap.get("yield_pct")
        ),
        "yield_as_of": _clean(roadmap.get("as_of")),
        "source_ref": source_ref,
        "provider_id": provider_id,
        "source_url_gap": True,
        "checked_at_gap": True,
        "append_ready_candidate": False,
        "next_action": (
            "Review the local OHLCV candidate, attach an audited http(s) source_url "
            "and checked_at, then rerun Slice 001 intake validation."
            if has_ohlcv
            else "Locate reviewed OHLCV evidence before editing the input template."
        ),
    }


def _field_matrix(rows: list[JsonDict]) -> list[JsonDict]:
    matrix: list[JsonDict] = []
    for row in rows:
        ticker = str(row["ticker"])
        for field in REQUIRED_INPUT_FIELDS:
            if field == "date":
                available = bool(row.get("latest_date"))
                source = "local_docs/market/daily_bars.csv" if available else ""
                reason = (
                    "local candidate exists; audited source_url and checked_at still required"
                    if available
                    else "missing local candidate"
                )
            elif field in {"open", "high", "low", "close", "volume"}:
                available = bool(row.get(field))
                source = "local_docs/market/daily_bars.csv" if available else ""
                reason = (
                    "local candidate exists; audited source_url and checked_at still required"
                    if available
                    else "missing local candidate"
                )
            elif field == "source_provider":
                available = bool(row.get("provider_id") or row.get("source_ref"))
                source = str(row.get("source_ref") or "")
                reason = (
                    "local provider/source_ref exists; reviewed provider value still required"
                    if available
                    else "missing local provider/source_ref"
                )
            elif field == "source_url":
                available = False
                source = ""
                reason = "missing audited http(s) source_url"
            else:
                available = False
                source = ""
                reason = "missing reviewed checked_at timestamp"
            matrix.append(
                {
                    "ticker": ticker,
                    "field": field,
                    "local_candidate_available": available,
                    "candidate_source": source,
                    "can_fill_input_template": False,
                    "reason": reason,
                }
            )
    return matrix


def _review_queue(rows: list[JsonDict]) -> list[JsonDict]:
    queue: list[JsonDict] = []
    for row in rows:
        has_candidate = bool(row.get("ohlcv_candidate_available"))
        queue.append(
            {
                "ticker": row["ticker"],
                "date": row["latest_date"] if has_candidate else "",
                "open": row["open"] if has_candidate else "",
                "high": row["high"] if has_candidate else "",
                "low": row["low"] if has_candidate else "",
                "close": row["close"] if has_candidate else "",
                "volume": row["volume"] if has_candidate else "",
                "source_provider": row["provider_id"] if has_candidate else "",
                "source_url": "",
                "checked_at": "",
                "note": (
                    "Review local candidate, add audited http(s) source_url and "
                    "checked_at before copying to input template."
                    if has_candidate
                    else "Locate reviewed OHLCV evidence first."
                ),
                "candidate_source_ref": row["source_ref"],
                "review_status": "needs_source_review" if has_candidate else "missing_candidate",
                "can_copy_to_input_template": False,
            }
        )
    return queue


def _latest_daily_bars(rows: list[JsonDict], tickers: list[str]) -> dict[str, JsonDict]:
    ticker_set = set(tickers)
    latest: dict[str, JsonDict] = {}
    for row in rows:
        ticker = str(row.get("ticker") or "").strip()
        if ticker not in ticker_set:
            continue
        current = latest.get(ticker)
        if current is None or str(row.get("date") or "") > str(current.get("date") or ""):
            latest[ticker] = row
    return latest


def _index_by_ticker(rows: list[JsonDict]) -> dict[str, JsonDict]:
    indexed: dict[str, JsonDict] = {}
    for row in rows:
        ticker = str(row.get("ticker") or "").strip()
        if ticker:
            indexed[ticker] = row
    return indexed


def _read_csv(path: Path) -> list[JsonDict]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _read_json(path: Path) -> JsonDict:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: JsonDict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[JsonDict], fieldnames: tuple[str, ...]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _mirror(output_dir: Path, mirror_dirs: tuple[Path, ...]) -> None:
    filenames = (
        f"{PREFIX}.json",
        f"{PREFIX}.html",
        f"{PREFIX}.md",
        f"{PREFIX}.csv",
        f"{PREFIX}_field_matrix.csv",
        REVIEW_QUEUE,
    )
    for mirror in mirror_dirs:
        mirror.mkdir(parents=True, exist_ok=True)
        for filename in filenames:
            source = output_dir / filename
            if source.is_file():
                shutil.copy2(source, mirror / filename)


def _render_html(payload: JsonDict) -> str:
    summary = _as_dict(payload["summary"])
    links = _as_dict(payload["links"])
    cards = [
        ("Local OHLCV candidates", str(summary["local_ohlcv_candidate_rows"]), "candidate rows"),
        ("Source URL gaps", str(summary["source_url_gap_count"]), "http(s) evidence required"),
        ("checked_at gaps", str(summary["checked_at_gap_count"]), "review timestamp required"),
        ("Review queue", str(summary["review_queue_rows"]), "candidate rows, no autofill"),
        ("Autofill", "0", "input_template_autofill_allowed=false"),
    ]
    card_html = "".join(
        "<article class='card'>"
        f"<h2>{escape(title)}</h2><div class='metric'>{escape(metric)}</div>"
        f"<p>{escape(detail)}</p></article>"
        for title, metric, detail in cards
    )
    link_html = "".join(
        f"<a class='btn' href='{escape(str(link))}'>{escape(str(label))}</a>"
        for label, link in links.items()
    )
    rows = "".join(
        "<tr>"
        f"<td><code>{escape(str(row['ticker']))}</code></td>"
        f"<td>{escape(str(row['latest_date']))}</td>"
        f"<td>{escape(str(row['open']))}</td>"
        f"<td>{escape(str(row['high']))}</td>"
        f"<td>{escape(str(row['low']))}</td>"
        f"<td>{escape(str(row['close']))}</td>"
        f"<td>{escape(str(row['volume']))}</td>"
        f"<td>{escape(str(row['source_url_gap']))}</td>"
        f"<td>{escape(str(row['checked_at_gap']))}</td>"
        f"<td>{escape(str(row['next_action']))}</td>"
        "</tr>"
        for row in payload["evidence_rows"]
    )
    css = (
        ":root{color-scheme:light;font-family:Inter,'Noto Sans JP','Segoe UI',sans-serif;"
        "background:#f6f8fb;color:#172033}body{margin:0}.shell{max-width:1180px;"
        "margin:auto;padding:32px 22px}.grid{display:grid;grid-template-columns:"
        "repeat(auto-fit,minmax(220px,1fr));gap:14px}.card{background:white;"
        "border:1px solid #dbe3ee;border-radius:8px;padding:18px;margin:14px 0}"
        ".metric{font-size:30px;font-weight:850}.btn{display:inline-flex;margin:6px;"
        "padding:10px 12px;border:1px solid #cbd5e1;border-radius:8px;color:#0f172a;"
        "text-decoration:none;font-weight:800}table{width:100%;border-collapse:collapse}"
        "th,td{border-bottom:1px solid #e5eaf2;text-align:left;padding:9px}"
        "th{background:#f1f5f9}.warn{color:#b42318;font-weight:800}"
    )
    return (
        "<!doctype html><html lang='ja'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{escape(str(payload['title']))}</title><style>{css}</style></head>"
        "<body><main class='shell'><p><strong>Daily Bars Backfill</strong></p>"
        f"<h1>{escape(str(payload['title']))}</h1>"
        "<p>Local-only candidate evidence. No external fetch, no source write, "
        "no advice, no trading.</p>"
        f"<section class='grid'>{card_html}</section><nav>{link_html}</nav>"
        "<section class='card'><h2>Slice 001 candidates</h2><table><thead><tr>"
        "<th>Ticker</th><th>Date</th><th>Open</th><th>High</th><th>Low</th>"
        "<th>Close</th><th>Volume</th><th>source_url gap</th>"
        "<th>checked_at gap</th><th>Next action</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></section>"
        "<section class='card'><h2>Review queue</h2>"
        "<p>Use the review queue CSV to check local OHLCV candidates, then add "
        "audited http(s) source_url and checked_at before any input-template copy.</p>"
        f"<p><a class='btn' href='{REVIEW_QUEUE}'>review_queue_csv</a></p></section>"
        f"<p>Generated {escape(str(payload['generated_at']))}</p>"
        "</main></body></html>"
    )


def _render_md(payload: JsonDict) -> str:
    summary = _as_dict(payload["summary"])
    lines = [
        "# Daily Bars Slice 001 Local Evidence",
        "",
        f"Generated: {payload['generated_at']}",
        "",
        f"- Status: {summary['status']}",
        "- Local OHLCV candidates: "
        f"{summary['local_ohlcv_candidate_rows']}/{summary['template_rows']}",
        f"- Review queue rows: {summary['review_queue_rows']}",
        f"- Prepopulated required fields: {summary['prepopulated_required_field_count']}",
        f"- Remaining review fields: {summary['remaining_review_field_count']}",
        f"- Source URL gaps: {summary['source_url_gap_count']}",
        f"- checked_at gaps: {summary['checked_at_gap_count']}",
        f"- Input template autofill allowed: {summary['input_template_autofill_allowed']}",
        "",
        "| Ticker | Date | Close | Volume | Next action |",
        "|---|---|---:|---:|---|",
    ]
    for row in payload["evidence_rows"]:
        lines.append(
            f"| {row['ticker']} | {row['latest_date']} | {row['close']} | "
            f"{row['volume']} | {row['next_action']} |"
        )
    return "\n".join(lines) + "\n"


def _next_sprint_goal(
    *,
    candidate_count: int,
    template_count: int,
    source_url_gaps: int,
    checked_at_gaps: int,
) -> str:
    if candidate_count < template_count:
        return "Locate local OHLCV candidates for all Slice 001 tickers."
    if source_url_gaps or checked_at_gaps:
        return (
            "Attach reviewed http(s) source_url and checked_at evidence to the "
            "candidate rows before rerunning intake validation."
        )
    return "Rerun Slice 001 intake validation and inspect append dry run."


def _first_text(*values: object) -> str:
    for value in values:
        text = _clean(value)
        if text:
            return text
    return ""


def _clean(value: object) -> str:
    return str(value or "").strip()


def _as_dict(value: object) -> JsonDict:
    return value if isinstance(value, dict) else {}


def _as_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _now_jst() -> str:
    return datetime.now(JST).isoformat(timespec="seconds")
