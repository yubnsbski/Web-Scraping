"""Build an actionable backlog for a daily-bars intake slice."""

from __future__ import annotations

import csv
import json
import shutil
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Any

JsonDict = dict[str, Any]

JST = timezone(timedelta(hours=9))
DEFAULT_DASHBOARD_ROOT = Path("web/public/market-dashboard")
DEFAULT_MIRROR_ROOTS = (Path("web/dist/market-dashboard"), Path("local_docs/market"))
PREFIX = "daily_bars_backfill_batch001_slice001_readiness_backlog"
VALIDATION_JSON = "daily_bars_backfill_batch001_slice001_intake_validation.json"
INPUT_TEMPLATE = "daily_bars_backfill_batch001_slice001_input_template.csv"
INTAKE_HTML = "daily_bars_backfill_batch001_slice001_intake_validation.html"
APPEND_DRY_RUN_HTML = "daily_bars_backfill_batch001_slice001_append_dry_run.html"
WORKFLOW_HTML = "daily_bars_backfill_batch001_workflow.html"
SPRINT_REVIEW_HTML = "data_quality_sprint_review.html"
BACKLOG_COLUMNS = (
    "rank",
    "priority",
    "slice_id",
    "row_number",
    "ticker",
    "name",
    "field",
    "issue",
    "issue_type",
    "field_group",
    "next_action",
    "input_template",
)
FIELD_COLUMNS = (
    "field",
    "field_group",
    "completed_rows",
    "missing_rows",
    "total_rows",
    "completion_rate",
    "blocking_issue_count",
    "status",
    "next_action",
)


@dataclass(frozen=True)
class DailyBarsSliceReadinessBacklogConfig:
    dashboard_root: Path = DEFAULT_DASHBOARD_ROOT
    output_dir: Path | None = None
    validation_path: Path | None = None
    generated_at: str | None = None
    mirror_dirs: tuple[Path, ...] = DEFAULT_MIRROR_ROOTS


def build_daily_bars_slice_readiness_backlog(
    config: DailyBarsSliceReadinessBacklogConfig,
) -> JsonDict:
    """Build CSV/JSON/HTML/Markdown backlog artifacts from local validation output."""
    root = Path(config.dashboard_root)
    output_dir = Path(config.output_dir or root)
    validation_path = Path(config.validation_path or root / VALIDATION_JSON)
    validation = _read_json(validation_path)
    validation_summary = _as_dict(validation.get("summary"))
    validation_rows = [_as_dict(row) for row in validation.get("validation_rows", [])]
    field_completion = [_as_dict(row) for row in validation.get("field_completion", [])]
    generated_at = config.generated_at or _now_jst()

    backlog_rows = _build_backlog_rows(validation_summary, validation_rows)
    field_rows = _build_field_rows(field_completion, backlog_rows)
    blocker_count = len(backlog_rows)
    ticker_count = len({str(row["ticker"]) for row in backlog_rows if row.get("ticker")})
    field_count = len({str(row["field"]) for row in backlog_rows if row.get("field")})
    ready_rows = _as_int(validation_summary.get("ready_rows"))
    template_rows = _as_int(validation_summary.get("template_rows"))
    status = "ready" if blocker_count == 0 else "blocked"

    summary: JsonDict = {
        "generated_at": generated_at,
        "status": status,
        "slice_id": str(validation_summary.get("slice_id") or "daily-bars-batch001-slice001"),
        "batch_id": str(validation_summary.get("batch_id") or "daily-bars-batch001"),
        "ready_rows": ready_rows,
        "template_rows": template_rows,
        "blockers": blocker_count,
        "blocked_ticker_count": ticker_count,
        "blocked_field_count": field_count,
        "field_backlog_count": len(field_rows),
        "append_ready": blocker_count == 0 and ready_rows == template_rows,
        "current_stage": "append_dry_run" if blocker_count == 0 else "data_entry",
        "next_sprint_goal": _next_sprint_goal(blocker_count),
        "write_executed": False,
        "source_data_write_executed": False,
        "external_fetch_executed": False,
        "auto_trading": False,
        "call_real_api": False,
    }
    links = {
        "backlog_html": f"{PREFIX}.html",
        "backlog_json": f"{PREFIX}.json",
        "backlog_csv": f"{PREFIX}.csv",
        "field_summary_csv": f"{PREFIX}_field_summary.csv",
        "input_template": INPUT_TEMPLATE,
        "intake_validation": INTAKE_HTML,
        "append_dry_run": APPEND_DRY_RUN_HTML,
        "batch_workflow": WORKFLOW_HTML,
        "sprint_review": SPRINT_REVIEW_HTML,
    }
    payload: JsonDict = {
        "status": status,
        "title": "Daily Bars Slice 001 Readiness Backlog",
        "generated_at": generated_at,
        "summary": summary,
        "backlog_rows": backlog_rows,
        "field_summary": field_rows,
        "safe_flags": {
            "write_executed": False,
            "source_data_write_executed": False,
            "external_fetch_executed": False,
            "auto_trading": False,
            "call_real_api": False,
            "advisory_output": False,
        },
        "links": links,
        "disclaimer": "Data-quality workflow only. No advice, no trading, no source write.",
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / f"{PREFIX}.json", payload)
    _write_csv(output_dir / f"{PREFIX}.csv", backlog_rows, BACKLOG_COLUMNS)
    _write_csv(output_dir / f"{PREFIX}_field_summary.csv", field_rows, FIELD_COLUMNS)
    _write_text(output_dir / f"{PREFIX}.html", _render_html(payload))
    _write_text(output_dir / f"{PREFIX}.md", _render_md(payload))
    _mirror(output_dir, tuple(Path(path) for path in config.mirror_dirs))
    return payload


def _build_backlog_rows(summary: JsonDict, validation_rows: list[JsonDict]) -> list[JsonDict]:
    slice_id = str(summary.get("slice_id") or "daily-bars-batch001-slice001")
    rows: list[JsonDict] = []
    rank = 1
    for row in validation_rows:
        issues = _split_issues(row.get("issues"))
        for issue in issues:
            field = _field_from_issue(issue)
            rows.append(
                {
                    "rank": rank,
                    "priority": _priority_for_issue(issue),
                    "slice_id": slice_id,
                    "row_number": _as_int(row.get("row_number")),
                    "ticker": str(row.get("ticker") or ""),
                    "name": _clean_display(row.get("name")),
                    "field": field,
                    "issue": issue,
                    "issue_type": _issue_type(issue),
                    "field_group": _field_group(field),
                    "next_action": _next_action_for_issue(field, issue),
                    "input_template": INPUT_TEMPLATE,
                }
            )
            rank += 1
    return rows


def _build_field_rows(
    field_completion: list[JsonDict], backlog_rows: list[JsonDict]
) -> list[JsonDict]:
    issue_counts = Counter(str(row.get("field") or "") for row in backlog_rows)
    rows: list[JsonDict] = []
    for row in field_completion:
        field = str(row.get("field") or "")
        missing_rows = _as_int(row.get("missing_rows"))
        rows.append(
            {
                "field": field,
                "field_group": _field_group(field),
                "completed_rows": _as_int(row.get("completed_rows")),
                "missing_rows": missing_rows,
                "total_rows": _as_int(row.get("total_rows")),
                "completion_rate": _as_float(row.get("completion_rate")),
                "blocking_issue_count": issue_counts[field],
                "status": "ready" if missing_rows == 0 and issue_counts[field] == 0 else "blocked",
                "next_action": _next_action_for_issue(field, f"missing_{field}"),
            }
        )
    return rows


def _split_issues(value: object) -> list[str]:
    return [part.strip() for part in str(value or "").split(";") if part.strip()]


def _field_from_issue(issue: str) -> str:
    for prefix in ("missing_", "invalid_"):
        if issue.startswith(prefix):
            return issue.removeprefix(prefix)
    if issue == "invalid_high_below_price":
        return "high"
    if issue == "invalid_low_above_price":
        return "low"
    return "unknown"


def _issue_type(issue: str) -> str:
    if issue.startswith("missing_"):
        return "missing_required_field"
    if issue.startswith("invalid_"):
        return "invalid_value"
    return "validation_issue"


def _field_group(field: str) -> str:
    if field in {"open", "high", "low", "close", "volume"}:
        return "ohlcv"
    if field in {"source_provider", "source_url"}:
        return "source_evidence"
    if field in {"date", "checked_at"}:
        return "timeliness"
    return "other"


def _priority_for_issue(issue: str) -> str:
    if issue.startswith("missing_"):
        return "P0"
    return "P1"


def _next_action_for_issue(field: str, issue: str) -> str:
    if issue.startswith("missing_"):
        return f"Enter reviewed {field} in Slice 001 input template."
    if field in {"high", "low"}:
        return "Check OHLC consistency against reviewed open/high/low/close values."
    if field in {"date", "checked_at"}:
        return f"Normalize {field} to the required ISO format."
    if field == "source_url":
        return "Use an auditable http(s) source URL for the reviewed row."
    return f"Correct {field} so the intake validation contract passes."


def _next_sprint_goal(blocker_count: int) -> str:
    if blocker_count:
        return (
            "Resolve P0 Slice 001 backlog rows by filling reviewed OHLCV/source "
            "evidence, then rerun intake validation and append dry run."
        )
    return "Review append dry run output before any explicit source-data write."


def _render_html(payload: JsonDict) -> str:
    summary = _as_dict(payload["summary"])
    links = _as_dict(payload["links"])
    cards = [
        ("Backlog items", str(summary["blockers"]), "validation blockers"),
        (
            "Blocked tickers",
            f"{summary['blocked_ticker_count']}/{summary['template_rows']}",
            "Slice 001 rows needing input",
        ),
        (
            "Blocked fields",
            f"{summary['blocked_field_count']}/{summary['field_backlog_count']}",
            "required fields with open issues",
        ),
        ("Writes", "0", "write_executed=false"),
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
    field_rows = "".join(
        "<tr>"
        f"<td><code>{escape(str(row['field']))}</code></td>"
        f"<td>{escape(str(row['field_group']))}</td>"
        f"<td>{escape(str(row['missing_rows']))}</td>"
        f"<td>{escape(str(row['completion_rate']))}%</td>"
        f"<td><span class='pill {escape(str(row['status']))}'>"
        f"{escape(str(row['status']))}</span></td>"
        f"<td>{escape(str(row['next_action']))}</td>"
        "</tr>"
        for row in payload["field_summary"]
    )
    backlog_rows = "".join(
        "<tr>"
        f"<td>{escape(str(row['rank']))}</td>"
        f"<td>{escape(str(row['priority']))}</td>"
        f"<td><code>{escape(str(row['ticker']))}</code></td>"
        f"<td>{escape(str(row['row_number']))}</td>"
        f"<td><code>{escape(str(row['field']))}</code></td>"
        f"<td>{escape(str(row['issue']))}</td>"
        f"<td>{escape(str(row['next_action']))}</td>"
        "</tr>"
        for row in payload["backlog_rows"]
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
        "th{background:#f1f5f9}.pill{font-weight:800}.blocked{color:#b42318}"
        ".ready{color:#067647}"
    )
    return (
        "<!doctype html><html lang='ja'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{escape(str(payload['title']))}</title><style>{css}</style></head>"
        "<body><main class='shell'><p><strong>Daily Bars Data Quality</strong></p>"
        f"<h1>{escape(str(payload['title']))}</h1>"
        "<p>Actionable input backlog generated from local intake validation only. "
        "No external fetch, no source write, no advice, and no trading.</p>"
        f"<section class='grid'>{card_html}</section>"
        f"<section class='card'><h2>Links</h2>{link_html}</section>"
        "<section class='card'><h2>Field Summary</h2><table><thead><tr>"
        "<th>Field</th><th>Group</th><th>Missing</th><th>Completion</th>"
        f"<th>Status</th><th>Next Action</th></tr></thead><tbody>{field_rows}"
        "</tbody></table></section>"
        "<section class='card'><h2>Backlog</h2><table><thead><tr>"
        "<th>Rank</th><th>Priority</th><th>Ticker</th><th>Row</th><th>Field</th>"
        f"<th>Issue</th><th>Next Action</th></tr></thead><tbody>{backlog_rows}"
        "</tbody></table></section></main></body></html>\n"
    )


def _render_md(payload: JsonDict) -> str:
    summary = _as_dict(payload["summary"])
    lines = [
        "# Daily Bars Slice 001 Readiness Backlog",
        "",
        f"- status: {summary['status']}",
        f"- generated_at: {summary['generated_at']}",
        f"- blockers: {summary['blockers']}",
        f"- blocked_ticker_count: {summary['blocked_ticker_count']}",
        f"- blocked_field_count: {summary['blocked_field_count']}",
        f"- ready_rows: {summary['ready_rows']}/{summary['template_rows']}",
        f"- next_sprint_goal: {summary['next_sprint_goal']}",
        "- write_executed: false",
        "- external_fetch_executed: false",
        "- auto_trading: false",
        "",
        "## Field Summary",
    ]
    for row in payload["field_summary"]:
        lines.append(
            f"- {row['field']}: {row['missing_rows']} missing "
            f"({row['completion_rate']}%)"
        )
    return "\n".join(lines) + "\n"


def _read_json(path: Path) -> JsonDict:
    return _as_dict(json.loads(path.read_text(encoding="utf-8-sig")))


def _write_json(path: Path, payload: JsonDict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _write_csv(path: Path, rows: list[JsonDict], fieldnames: tuple[str, ...]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _mirror(output_dir: Path, mirror_dirs: tuple[Path, ...]) -> None:
    names = (
        f"{PREFIX}.json",
        f"{PREFIX}.html",
        f"{PREFIX}.md",
        f"{PREFIX}.csv",
        f"{PREFIX}_field_summary.csv",
    )
    for mirror_dir in mirror_dirs:
        mirror_dir.mkdir(parents=True, exist_ok=True)
        for name in names:
            source = output_dir / name
            if source.exists():
                shutil.copy2(source, mirror_dir / name)


def _now_jst() -> str:
    return datetime.now(tz=JST).isoformat(timespec="seconds")


def _as_dict(value: object) -> JsonDict:
    return value if isinstance(value, dict) else {}


def _as_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_float(value: object) -> float:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return 0.0


def _clean_display(value: object) -> str:
    text = str(value or "").strip()
    return text.replace("\ufffd", "?")
