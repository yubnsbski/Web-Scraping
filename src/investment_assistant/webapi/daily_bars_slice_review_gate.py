"""Validate the Daily Bars Slice 001 review queue before any copy step."""

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
PREFIX = "daily_bars_backfill_batch001_slice001_review_gate"
REVIEW_QUEUE = "daily_bars_backfill_batch001_slice001_local_evidence_review_queue.csv"
LOCAL_EVIDENCE_HTML = "daily_bars_backfill_batch001_slice001_local_evidence.html"
INPUT_TEMPLATE = "daily_bars_backfill_batch001_slice001_input_template.csv"
REQUIRED_FIELDS = (
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
ISSUE_COLUMNS = (
    "rank",
    "priority",
    "row_number",
    "ticker",
    "field",
    "issue",
    "issue_type",
    "next_action",
)
FIELD_COLUMNS = (
    "field",
    "completed_rows",
    "missing_rows",
    "issue_count",
    "status",
    "next_action",
)
VALIDATION_COLUMNS = (
    "row_number",
    "ticker",
    "status",
    "field_issue_count",
    "copy_approval_issue_count",
    "issues",
)


@dataclass(frozen=True)
class DailyBarsSliceReviewGateConfig:
    dashboard_root: Path = DEFAULT_DASHBOARD_ROOT
    output_dir: Path | None = None
    review_queue_path: Path | None = None
    generated_at: str | None = None
    mirror_dirs: tuple[Path, ...] = DEFAULT_MIRROR_ROOTS


def build_daily_bars_slice_review_gate(config: DailyBarsSliceReviewGateConfig) -> JsonDict:
    """Build a local-only validation gate for the reviewed Slice 001 queue."""
    root = Path(config.dashboard_root)
    output_dir = Path(config.output_dir or root)
    review_queue_path = Path(config.review_queue_path or root / REVIEW_QUEUE)
    generated_at = config.generated_at or _now_jst()
    rows = _read_csv(review_queue_path)

    validation_rows, issue_rows = _validate_rows(rows)
    field_summary = _field_summary(rows, issue_rows)
    field_blockers = sum(
        1
        for issue in issue_rows
        if str(issue.get("issue_type")) in {"missing_required_field", "invalid_value"}
    )
    copy_approval_blockers = sum(
        1 for issue in issue_rows if str(issue.get("issue_type")) == "copy_approval"
    )
    blockers = len(issue_rows)
    ready_rows = sum(1 for row in validation_rows if row["status"] == "ready")
    status = "ready" if rows and blockers == 0 else "blocked"
    summary: JsonDict = {
        "generated_at": generated_at,
        "status": status,
        "review_queue_rows": len(rows),
        "ready_rows": ready_rows,
        "blocked_rows": len(rows) - ready_rows,
        "blockers": blockers,
        "field_blockers": field_blockers,
        "copy_approval_blockers": copy_approval_blockers,
        "copy_ready_rows": ready_rows,
        "copy_to_input_template_ready": bool(rows) and blockers == 0,
        "source_url_missing_rows": _missing_count(rows, "source_url"),
        "checked_at_missing_rows": _missing_count(rows, "checked_at"),
        "input_template_write_executed": False,
        "source_data_write_executed": False,
        "write_executed": False,
        "external_fetch_executed": False,
        "auto_trading": False,
        "call_real_api": False,
        "next_sprint_goal": _next_sprint_goal(field_blockers, copy_approval_blockers),
    }
    links = {
        "review_gate_html": f"{PREFIX}.html",
        "review_gate_json": f"{PREFIX}.json",
        "review_gate_csv": f"{PREFIX}.csv",
        "field_summary_csv": f"{PREFIX}_field_summary.csv",
        "local_evidence": LOCAL_EVIDENCE_HTML,
        "review_queue": REVIEW_QUEUE,
        "input_template": INPUT_TEMPLATE,
    }
    payload: JsonDict = {
        "status": status,
        "title": "Daily Bars Slice 001 Review Gate",
        "generated_at": generated_at,
        "summary": summary,
        "validation_rows": validation_rows,
        "issue_rows": issue_rows,
        "field_summary": field_summary,
        "safe_flags": {
            "input_template_write_executed": False,
            "source_data_write_executed": False,
            "write_executed": False,
            "external_fetch_executed": False,
            "auto_trading": False,
            "call_real_api": False,
            "advisory_output": False,
        },
        "links": links,
        "disclaimer": "Validation only. No copy, no source write, no advice, no trading.",
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / f"{PREFIX}.json", payload)
    _write_csv(output_dir / f"{PREFIX}.csv", issue_rows, ISSUE_COLUMNS)
    _write_csv(output_dir / f"{PREFIX}_validation.csv", validation_rows, VALIDATION_COLUMNS)
    _write_csv(output_dir / f"{PREFIX}_field_summary.csv", field_summary, FIELD_COLUMNS)
    _write_text(output_dir / f"{PREFIX}.html", _render_html(payload))
    _write_text(output_dir / f"{PREFIX}.md", _render_md(payload))
    _mirror(output_dir, tuple(Path(path) for path in config.mirror_dirs))
    return payload


def _validate_rows(rows: list[JsonDict]) -> tuple[list[JsonDict], list[JsonDict]]:
    validation_rows: list[JsonDict] = []
    issue_rows: list[JsonDict] = []
    rank = 1
    for row_number, row in enumerate(rows, start=2):
        issues = _row_issues(row)
        for field, issue, issue_type in issues:
            issue_rows.append(
                {
                    "rank": rank,
                    "priority": "P0" if issue_type != "copy_approval" else "P1",
                    "row_number": row_number,
                    "ticker": _clean(row.get("ticker")),
                    "field": field,
                    "issue": issue,
                    "issue_type": issue_type,
                    "next_action": _next_action(field, issue_type),
                }
            )
            rank += 1
        field_issue_count = sum(1 for _, _, issue_type in issues if issue_type != "copy_approval")
        copy_issue_count = sum(1 for _, _, issue_type in issues if issue_type == "copy_approval")
        validation_rows.append(
            {
                "row_number": row_number,
                "ticker": _clean(row.get("ticker")),
                "status": "ready" if not issues else "blocked",
                "field_issue_count": field_issue_count,
                "copy_approval_issue_count": copy_issue_count,
                "issues": ";".join(issue for _, issue, _ in issues),
            }
        )
    return validation_rows, issue_rows


def _row_issues(row: JsonDict) -> list[tuple[str, str, str]]:
    issues: list[tuple[str, str, str]] = []
    for field in REQUIRED_FIELDS:
        if not _clean(row.get(field)):
            issues.append((field, f"missing_{field}", "missing_required_field"))
    if _clean(row.get("date")) and not _is_date(_clean(row.get("date"))):
        issues.append(("date", "invalid_date", "invalid_value"))
    if _clean(row.get("checked_at")) and not _is_datetime(_clean(row.get("checked_at"))):
        issues.append(("checked_at", "invalid_checked_at", "invalid_value"))
    if _clean(row.get("source_url")) and not _clean(row.get("source_url")).startswith(
        ("http://", "https://")
    ):
        issues.append(("source_url", "invalid_source_url", "invalid_value"))

    numeric: dict[str, float] = {}
    for field in ("open", "high", "low", "close"):
        value = _clean(row.get(field))
        if not value:
            continue
        parsed = _number(value)
        if parsed is None or parsed <= 0:
            issues.append((field, f"invalid_{field}", "invalid_value"))
        else:
            numeric[field] = parsed
    volume = _clean(row.get("volume"))
    if volume:
        parsed_volume = _number(volume)
        if parsed_volume is None or parsed_volume < 0 or not parsed_volume.is_integer():
            issues.append(("volume", "invalid_volume", "invalid_value"))
    if set(numeric) == {"open", "high", "low", "close"}:
        if numeric["high"] < max(numeric.values()):
            issues.append(("high", "invalid_high_below_price", "invalid_value"))
        if numeric["low"] > min(numeric.values()):
            issues.append(("low", "invalid_low_above_price", "invalid_value"))
    if not _as_bool(row.get("can_copy_to_input_template")):
        issues.append(
            (
                "can_copy_to_input_template",
                "copy_not_approved",
                "copy_approval",
            )
        )
    return issues


def _field_summary(rows: list[JsonDict], issues: list[JsonDict]) -> list[JsonDict]:
    issue_counts = Counter(str(row.get("field") or "") for row in issues)
    total = len(rows)
    fields = (*REQUIRED_FIELDS, "can_copy_to_input_template")
    output: list[JsonDict] = []
    for field in fields:
        completed = sum(1 for row in rows if _clean(row.get(field)))
        missing = total - completed
        output.append(
            {
                "field": field,
                "completed_rows": completed,
                "missing_rows": missing,
                "issue_count": issue_counts[field],
                "status": "ready" if issue_counts[field] == 0 else "blocked",
                "next_action": _next_action(
                    field,
                    "copy_approval" if field == "can_copy_to_input_template" else "field",
                ),
            }
        )
    return output


def _next_action(field: str, issue_type: str) -> str:
    if field == "source_url":
        return "Add an audited http(s) source_url for the reviewed OHLCV row."
    if field == "checked_at":
        return "Add the ISO timestamp when the source evidence was reviewed."
    if issue_type == "copy_approval":
        return "Set can_copy_to_input_template=true only after source evidence is reviewed."
    if field in {"high", "low"}:
        return "Check OHLC consistency against the reviewed candidate row."
    return f"Correct or review {field} before copying to the input template."


def _next_sprint_goal(field_blockers: int, copy_approval_blockers: int) -> str:
    if field_blockers:
        return "Fill audited source_url and checked_at values in the review queue."
    if copy_approval_blockers:
        return "Mark reviewed rows as copy-approved, then rerun the review gate."
    return "Copy reviewed rows into the Slice 001 input template and rerun intake validation."


def _missing_count(rows: list[JsonDict], field: str) -> int:
    return sum(1 for row in rows if not _clean(row.get(field)))


def _read_csv(path: Path) -> list[JsonDict]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


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
        f"{PREFIX}_validation.csv",
        f"{PREFIX}_field_summary.csv",
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
        ("Ready rows", f"{summary['ready_rows']}/{summary['review_queue_rows']}", "copy-ready"),
        ("Field blockers", str(summary["field_blockers"]), "required field issues"),
        ("Copy approvals", str(summary["copy_approval_blockers"]), "approval flags"),
        ("Writes", "0", "validation only"),
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
    issue_rows = "".join(
        "<tr>"
        f"<td>{escape(str(row['rank']))}</td>"
        f"<td>{escape(str(row['priority']))}</td>"
        f"<td><code>{escape(str(row['ticker']))}</code></td>"
        f"<td><code>{escape(str(row['field']))}</code></td>"
        f"<td>{escape(str(row['issue']))}</td>"
        f"<td>{escape(str(row['next_action']))}</td>"
        "</tr>"
        for row in payload["issue_rows"]
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
        "th{background:#f1f5f9}"
    )
    return (
        "<!doctype html><html lang='ja'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{escape(str(payload['title']))}</title><style>{css}</style></head>"
        "<body><main class='shell'><p><strong>Daily Bars Backfill</strong></p>"
        f"<h1>{escape(str(payload['title']))}</h1>"
        "<p>Review queue validation. No copy, no source write, no advice, no trading.</p>"
        f"<section class='grid'>{card_html}</section><nav>{link_html}</nav>"
        "<section class='card'><h2>Open issues</h2><table><thead><tr>"
        "<th>#</th><th>Priority</th><th>Ticker</th><th>Field</th>"
        "<th>Issue</th><th>Next action</th></tr></thead>"
        f"<tbody>{issue_rows}</tbody></table></section>"
        f"<p>Generated {escape(str(payload['generated_at']))}</p>"
        "</main></body></html>"
    )


def _render_md(payload: JsonDict) -> str:
    summary = _as_dict(payload["summary"])
    lines = [
        "# Daily Bars Slice 001 Review Gate",
        "",
        f"Generated: {payload['generated_at']}",
        "",
        f"- Status: {summary['status']}",
        f"- Ready rows: {summary['ready_rows']}/{summary['review_queue_rows']}",
        f"- Field blockers: {summary['field_blockers']}",
        f"- Copy approval blockers: {summary['copy_approval_blockers']}",
        f"- Source URL missing rows: {summary['source_url_missing_rows']}",
        f"- checked_at missing rows: {summary['checked_at_missing_rows']}",
        "",
        "| Ticker | Field | Issue | Next action |",
        "|---|---|---|---|",
    ]
    for row in payload["issue_rows"]:
        lines.append(
            f"| {row['ticker']} | {row['field']} | {row['issue']} | "
            f"{row['next_action']} |"
        )
    return "\n".join(lines) + "\n"


def _clean(value: object) -> str:
    return str(value or "").strip()


def _number(value: object) -> float | None:
    try:
        return float(_clean(value))
    except ValueError:
        return None


def _is_date(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _is_datetime(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return _clean(value).lower() in {"1", "true", "yes", "y", "approved"}


def _as_dict(value: object) -> JsonDict:
    return value if isinstance(value, dict) else {}


def _now_jst() -> str:
    return datetime.now(JST).isoformat(timespec="seconds")
