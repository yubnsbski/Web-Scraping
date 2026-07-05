"""Build repeatable data-quality sprint review artifacts."""

from __future__ import annotations

import csv
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

JsonDict = dict[str, Any]

PREFIX = "data_quality_sprint_review"
ARTIFACT_FILES = (
    f"{PREFIX}.json",
    f"{PREFIX}.html",
    f"{PREFIX}.md",
    f"{PREFIX}_dimensions.csv",
    f"{PREFIX}_process.csv",
)
CONTROL_FLAGS = (
    "write_executed",
    "source_data_write_executed",
    "external_fetch_executed",
    "auto_trading",
    "call_real_api",
)


@dataclass(frozen=True)
class DataQualitySprintReviewConfig:
    dashboard_root: Path = Path("web/public/market-dashboard")
    output_dir: Path | None = None
    data_quality_profile_path: Path | None = None
    batch_workflow_path: Path | None = None
    batch_intake_path: Path | None = None
    batch_append_dry_run_path: Path | None = None
    active_slice_path: Path | None = None
    active_slice_intake_path: Path | None = None
    generated_at: str | None = None
    mirror_dirs: tuple[Path, ...] = ()


def build_data_quality_sprint_review(
    config: DataQualitySprintReviewConfig,
) -> JsonDict:
    """Summarize the current quality sprint from local artifacts only."""

    root = config.dashboard_root
    output_dir = config.output_dir or root
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = config.generated_at or datetime.now().astimezone().isoformat(
        timespec="seconds"
    )

    profile = _read_json(config.data_quality_profile_path or root / "data_quality_profile.json")
    workflow = _read_json(
        config.batch_workflow_path or root / "daily_bars_backfill_batch001_workflow.json"
    )
    intake = _read_json(
        config.batch_intake_path
        or root / "daily_bars_backfill_batch001_intake_validation.json"
    )
    append_dry_run = _read_json(
        config.batch_append_dry_run_path
        or root / "daily_bars_backfill_batch001_append_dry_run.json"
    )
    active_slice = _read_json(
        config.active_slice_path or root / "daily_bars_backfill_batch001_slice001.json"
    )
    active_slice_intake = _read_json(
        config.active_slice_intake_path
        or root / "daily_bars_backfill_batch001_slice001_intake_validation.json"
    )

    profile_summary = _as_dict(profile.get("summary"))
    workflow_summary = _as_dict(workflow.get("summary"))
    intake_summary = _as_dict(intake.get("summary"))
    append_summary = _as_dict(append_dry_run.get("summary"))
    slice_summary = _as_dict(active_slice.get("summary"))
    slice_intake_summary = _as_dict(active_slice_intake.get("summary"))
    daily_bars = _as_dict(_as_dict(profile.get("sources")).get("daily_bars"))

    dimensions = _quality_dimensions(profile)
    process_steps = _process_steps(
        profile=profile,
        workflow=workflow,
        intake_summary=intake_summary,
        append_summary=append_summary,
    )
    domestic_stock_count = _first_int(
        profile_summary.get("jpx_domestic_stock_count"),
        daily_bars.get("reference_count"),
        append_summary.get("domestic_stock_count"),
    )
    daily_bars_ticker_count = _first_int(
        daily_bars.get("ticker_count"),
        append_summary.get("existing_daily_bars_tickers"),
    )
    daily_bars_rows = _first_int(
        daily_bars.get("row_count"),
        append_summary.get("existing_daily_bars_rows"),
    )
    batch_template_rows = _first_int(
        workflow_summary.get("template_rows"),
        intake_summary.get("template_rows"),
        append_summary.get("template_rows"),
    )
    batch_input_ready_rows = _first_int(
        workflow_summary.get("input_ready_rows"),
        intake_summary.get("ready_rows"),
        append_summary.get("intake_ready_rows"),
    )
    batch_append_candidate_rows = _first_int(
        workflow_summary.get("append_candidate_rows"),
        append_summary.get("append_candidate_rows"),
    )
    intake_blockers = _first_int(
        intake_summary.get("blocker_count"),
        intake_summary.get("issue_count"),
        append_summary.get("blocked_rows"),
    )
    active_slice_ready_rows = _first_int(
        workflow_summary.get("active_slice_ready_rows"),
        slice_summary.get("ready_rows"),
        slice_intake_summary.get("ready_rows"),
    )
    active_slice_template_rows = _first_int(
        workflow_summary.get("active_slice_template_rows"),
        slice_summary.get("template_rows"),
        slice_intake_summary.get("template_rows"),
    )
    active_slice_blockers = _first_int(
        workflow_summary.get("active_slice_blockers"),
        slice_summary.get("blockers"),
        slice_intake_summary.get("blocker_count"),
        slice_intake_summary.get("issue_count"),
    )
    guardrails_ok = _guardrails_ok(
        profile, workflow, intake, append_dry_run, active_slice, active_slice_intake
    )
    status = "ready" if guardrails_ok and process_steps else "blocked"
    next_sprint_goal = _next_sprint_goal(
        active_slice_blockers=active_slice_blockers,
        batch_template_rows=batch_template_rows,
        batch_input_ready_rows=batch_input_ready_rows,
        append_ready=bool(append_summary.get("append_ready")),
    )
    summary: JsonDict = {
        "generated_at": generated_at,
        "status": status,
        "quality_status": profile.get("status"),
        "profile_pass_count": _first_int(profile_summary.get("pass_count")),
        "profile_needs_attention_count": _first_int(
            profile_summary.get("needs_attention_count")
        ),
        "dimension_count": _first_int(profile_summary.get("dimension_count"), len(dimensions)),
        "domestic_stock_count": domestic_stock_count,
        "daily_bars_rows": daily_bars_rows,
        "daily_bars_ticker_count": daily_bars_ticker_count,
        "daily_bars_coverage_rate": _coverage_rate(
            daily_bars_ticker_count, domestic_stock_count
        ),
        "latest_daily_bar_date": daily_bars.get("latest_value"),
        "current_batch_stage": workflow_summary.get("current_stage"),
        "batch_input_ready_rows": batch_input_ready_rows,
        "batch_template_rows": batch_template_rows,
        "batch_append_candidate_rows": batch_append_candidate_rows,
        "intake_blockers": intake_blockers,
        "append_ready": bool(append_summary.get("append_ready")),
        "next_sprint_goal": next_sprint_goal,
        "write_executed": False,
        "source_data_write_executed": False,
        "external_fetch_executed": False,
        "auto_trading": False,
        "call_real_api": False,
        "active_slice_id": workflow_summary.get("active_slice_id")
        or slice_summary.get("slice_id"),
        "active_slice_ready_rows": active_slice_ready_rows,
        "active_slice_template_rows": active_slice_template_rows,
        "active_slice_blockers": active_slice_blockers,
    }
    payload: JsonDict = {
        "schema_version": 1,
        "status": status,
        "title": "Data Quality Sprint Review",
        "summary": summary,
        "quality_dimensions": dimensions,
        "process_steps": process_steps,
        "links": _links(workflow, intake, append_dry_run, active_slice, active_slice_intake),
        "notes": [
            "This sprint review reads local artifacts only.",
            "It does not fetch external data, call Gemini, write source data, or trade.",
            "Completeness uses JPX domestic stock issues as the denominator.",
        ],
    }
    _write_json(output_dir / f"{PREFIX}.json", payload)
    _write_dimensions_csv(output_dir / f"{PREFIX}_dimensions.csv", dimensions)
    _write_process_csv(output_dir / f"{PREFIX}_process.csv", process_steps)
    _write_markdown(output_dir / f"{PREFIX}.md", payload)
    _write_html(output_dir / f"{PREFIX}.html", payload)
    _mirror(output_dir, config.mirror_dirs)
    return payload


def _quality_dimensions(profile: JsonDict) -> list[JsonDict]:
    dimensions: list[JsonDict] = []
    for dimension in _as_list(profile.get("dimensions")):
        actions = _as_list(dimension.get("recommended_actions"))
        action = str(actions[0]) if actions else "Keep monitoring."
        observations = _as_list(dimension.get("observations"))
        evidence = str(observations[0]) if observations else ""
        dimensions.append(
            {
                "id": str(dimension.get("id") or ""),
                "label": str(dimension.get("label") or dimension.get("id") or ""),
                "status": str(dimension.get("status") or "unknown"),
                "score": _as_float(dimension.get("score")),
                "evidence": evidence,
                "next_action": action,
            }
        )
    return dimensions


def _process_steps(
    *,
    profile: JsonDict,
    workflow: JsonDict,
    intake_summary: JsonDict,
    append_summary: JsonDict,
) -> list[JsonDict]:
    profile_complete = "complete" if profile else "blocked"
    cleansing_status = "complete" if append_summary.get("append_ready") else "active"
    if _first_int(intake_summary.get("blocker_count"), intake_summary.get("issue_count")):
        cleansing_status = "active"
    governance_status = "active" if workflow else "blocked"
    return [
        {
            "step": "1",
            "process": "Profiling / current-state assessment",
            "status": profile_complete,
            "evidence": "data_quality_profile.json and six quality dimensions",
            "link": "data_quality_profile.html",
        },
        {
            "step": "2",
            "process": "Cleansing / standardization",
            "status": cleansing_status,
            "evidence": "Batch 001 templates, intake validation, and append dry run",
            "link": "daily_bars_backfill_batch001_workflow.html",
        },
        {
            "step": "3",
            "process": "Maintenance / governance",
            "status": governance_status,
            "evidence": "Sprint review, no-write gates, and repeatable CSV/JSON outputs",
            "link": "data_quality_sprint_review.html",
        },
    ]


def _links(
    workflow: JsonDict,
    intake: JsonDict,
    append_dry_run: JsonDict,
    active_slice: JsonDict,
    active_slice_intake: JsonDict,
) -> JsonDict:
    workflow_links = _as_dict(workflow.get("links"))
    active_slice_links = _as_dict(active_slice.get("links"))
    return {
        "data_quality_profile": "data_quality_profile.html",
        "data_quality_exceptions": "data_quality_exceptions.html",
        "batch001_workflow": "daily_bars_backfill_batch001_workflow.html",
        "batch001_intake_validation": intake.get(
            "workflow_link", "daily_bars_backfill_batch001_intake_validation.html"
        ),
        "batch001_append_dry_run": workflow_links.get(
            "append_dry_run", "daily_bars_backfill_batch001_append_dry_run.html"
        ),
        "batch001_slice001": workflow_links.get(
            "batch001_slice001", "daily_bars_backfill_batch001_slice001.html"
        ),
        "batch001_slice001_intake_validation": active_slice_links.get(
            "intake_validation",
            "daily_bars_backfill_batch001_slice001_intake_validation.html",
        ),
        "batch001_slice001_append_dry_run": active_slice_links.get(
            "append_dry_run",
            "daily_bars_backfill_batch001_slice001_append_dry_run.html",
        ),
        "batch001_slice001_readiness_backlog": (
            "daily_bars_backfill_batch001_slice001_readiness_backlog.html"
            if active_slice_intake
            else None
        ),
        "batch001_slice001_local_evidence": (
            "daily_bars_backfill_batch001_slice001_local_evidence.html"
            if active_slice_intake
            else None
        ),
        "batch001_slice001_review_gate": (
            "daily_bars_backfill_batch001_slice001_review_gate.html"
            if active_slice_intake
            else None
        ),
        "batch001_append_json": "daily_bars_backfill_batch001_append_dry_run.json"
        if append_dry_run
        else None,
        "batch001_slice001_json": "daily_bars_backfill_batch001_slice001.json"
        if active_slice_intake
        else None,
    }


def _next_sprint_goal(
    *,
    active_slice_blockers: int,
    batch_template_rows: int,
    batch_input_ready_rows: int,
    append_ready: bool,
) -> str:
    if active_slice_blockers:
        return (
            "Complete reviewed OHLCV/source evidence for Slice 001, then rerun "
            "intake validation and append dry run before any write."
        )
    if batch_input_ready_rows < batch_template_rows:
        return (
            "Scale the reviewed input pattern from Slice 001 to the remaining "
            "Batch 001 rows, then rerun batch validation."
        )
    if append_ready:
        return "Review the append preview with a human before any explicit write step."
    return "Rerun the no-write append dry run and inspect blockers."


def _guardrails_ok(*payloads: JsonDict) -> bool:
    for payload in payloads:
        summary = _as_dict(payload.get("summary"))
        for flag in CONTROL_FLAGS:
            if payload.get(flag) is True or summary.get(flag) is True:
                return False
    return True


def _read_json(path: Path) -> JsonDict:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: JsonDict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _write_dimensions_csv(path: Path, rows: list[JsonDict]) -> None:
    _write_csv(path, rows, ("id", "label", "status", "score", "evidence", "next_action"))


def _write_process_csv(path: Path, rows: list[JsonDict]) -> None:
    _write_csv(path, rows, ("step", "process", "status", "evidence", "link"))


def _write_csv(path: Path, rows: list[JsonDict], fieldnames: tuple[str, ...]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_markdown(path: Path, payload: JsonDict) -> None:
    summary = payload["summary"]
    lines = [
        "# Data Quality Sprint Review",
        "",
        f"- status: {payload['status']}",
        f"- generated_at: {summary['generated_at']}",
        f"- domestic_stock_count: {summary['domestic_stock_count']}",
        f"- daily_bars_coverage_rate: {summary['daily_bars_coverage_rate']}",
        f"- batch_stage: {summary['current_batch_stage']}",
        f"- batch_ready_rows: {summary['batch_input_ready_rows']}/{summary['batch_template_rows']}",
        (
            f"- active_slice_ready_rows: {summary['active_slice_ready_rows']}/"
            f"{summary['active_slice_template_rows']}"
        ),
        f"- active_slice_blockers: {summary['active_slice_blockers']}",
        f"- next_sprint_goal: {summary['next_sprint_goal']}",
        "",
        "## Quality Dimensions",
    ]
    for dimension in payload["quality_dimensions"]:
        lines.append(
            f"- {dimension['id']}: {dimension['status']} "
            f"({dimension['score']}) -> {dimension['next_action']}"
        )
    lines.extend(["", "## Process Steps"])
    for step in payload["process_steps"]:
        lines.append(
            f"- {step['step']}. {step['process']}: {step['status']} -> {step['link']}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_html(path: Path, payload: JsonDict) -> None:
    summary = payload["summary"]
    cards = [
        (
            "Daily-bars coverage",
            f"{summary['daily_bars_ticker_count']}/{summary['domestic_stock_count']}",
            f"{summary['daily_bars_coverage_rate']}% / latest {summary['latest_daily_bar_date']}",
        ),
        (
            "Batch stage",
            str(summary["current_batch_stage"]),
            (
                f"{summary['batch_input_ready_rows']}/"
                f"{summary['batch_template_rows']} input rows ready"
            ),
        ),
        (
            "Append candidates",
            f"{summary['batch_append_candidate_rows']}/{summary['batch_template_rows']}",
            "write_executed=false",
        ),
        (
            "Quality dimensions",
            f"{summary['profile_pass_count']}/{summary['dimension_count']}",
            "pass / total",
        ),
    ]
    card_html = "".join(
        "<article class='card'>"
        f"<h2>{escape(title)}</h2><div class='metric'>{escape(metric)}</div>"
        f"<p class='muted'>{escape(detail)}</p></article>"
        for title, metric, detail in cards
    )
    dimension_rows = "".join(
        "<tr>"
        f"<td><code>{escape(str(row['id']))}</code></td>"
        f"<td>{escape(str(row['label']))}</td>"
        f"<td><span class='pill {escape(str(row['status']))}'>"
        f"{escape(str(row['status']))}</span></td>"
        f"<td>{escape(str(row['score']))}</td>"
        f"<td>{escape(str(row['next_action']))}</td>"
        "</tr>"
        for row in payload["quality_dimensions"]
    )
    process_rows = "".join(
        "<tr>"
        f"<td>{escape(str(row['step']))}</td>"
        f"<td>{escape(str(row['process']))}</td>"
        f"<td><span class='pill {escape(str(row['status']))}'>"
        f"{escape(str(row['status']))}</span></td>"
        f"<td>{escape(str(row['evidence']))}</td>"
        f"<td><a class='btn' href='{escape(str(row['link']))}'>Open</a></td>"
        "</tr>"
        for row in payload["process_steps"]
    )
    links = _as_dict(payload.get("links"))
    link_html = "".join(
        f"<a class='btn' href='{escape(str(link))}'>{escape(str(label))}</a>"
        for label, link in links.items()
        if link
    )
    css = (
        ":root{color-scheme:light;font-family:Inter,'Segoe UI',sans-serif;"
        "color:#172033;background:#f6f8fb}*{box-sizing:border-box}body{margin:0}"
        ".shell{max-width:1180px;margin:auto;padding:32px 22px}.eyebrow{font-weight:800;"
        "color:#2563eb}h1{font-size:34px;margin:6px 0 10px}.lead{color:#475569;"
        "line-height:1.7}.grid{display:grid;grid-template-columns:repeat(auto-fit,"
        "minmax(220px,1fr));gap:14px}.card{background:white;border:1px solid #dbe3ee;"
        "border-radius:8px;padding:18px;box-shadow:0 10px 24px rgba(15,23,42,.06)}"
        ".metric{font-size:28px;font-weight:850}.btn{display:inline-flex;margin:18px 8px "
        "18px 0;padding:10px 13px;border-radius:8px;border:1px solid #cbd5e1;background:white;"
        "text-decoration:none;color:#0f172a;font-weight:800}.pill{display:inline-flex;"
        "border-radius:999px;padding:6px 10px;font-weight:800;font-size:13px}.pass,.complete{"
        "background:#ecfdf5;border:1px solid #a7f3d0;color:#047857}.active{background:#eff6ff;"
        "border:1px solid #bfdbfe;color:#1d4ed8}.needs_attention,.blocked{background:#fffbeb;"
        "border:1px solid #fde68a;color:#b45309}table{width:100%;border-collapse:collapse;"
        "background:white;border:1px solid #dbe3ee;margin-top:14px}th,td{border-bottom:1px "
        "solid #e5eaf2;text-align:left;padding:10px;vertical-align:top}th{background:#f1f5f9}"
        ".muted{color:#64748b}@media(max-width:720px){.shell{padding:22px 14px}h1{font-size:27px}}"
    )
    html = (
        "<!doctype html><html lang='ja'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{escape(str(payload['title']))}</title><style>{css}</style></head>"
        "<body><main class='shell'><p class='eyebrow'>Data Quality Sprint</p>"
        "<h1>Data Quality Sprint Review</h1>"
        "<p class='lead'>A repeatable review of the current data-quality sprint: "
        "profile, cleanse, govern, then review again. This is not investment advice "
        "and it does not fetch data, call Gemini, write source data, or trade.</p>"
        f"<section class='grid'>{card_html}</section>"
        "<section class='card'><h2>Next sprint focus</h2>"
        f"<p class='lead'>{escape(str(summary['next_sprint_goal']))}</p>{link_html}</section>"
        "<section class='card'><h2>Six-dimension review</h2><table><thead><tr>"
        "<th>ID</th><th>Dimension</th><th>Status</th><th>Score</th><th>Next action</th>"
        f"</tr></thead><tbody>{dimension_rows}</tbody></table></section>"
        "<section class='card'><h2>Process review</h2><table><thead><tr>"
        "<th>Step</th><th>Process</th><th>Status</th><th>Evidence</th><th>Link</th>"
        f"</tr></thead><tbody>{process_rows}</tbody></table></section>"
        "</main></body></html>"
    )
    path.write_text(html, encoding="utf-8")


def _mirror(output_dir: Path, mirror_dirs: tuple[Path, ...]) -> None:
    for mirror_dir in mirror_dirs:
        mirror_dir.mkdir(parents=True, exist_ok=True)
        for filename in ARTIFACT_FILES:
            shutil.copy2(output_dir / filename, mirror_dir / filename)


def _as_dict(value: Any) -> JsonDict:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _first_int(*values: Any) -> int:
    for value in values:
        if value is None:
            continue
        if isinstance(value, bool):
            return int(value)
        try:
            return int(str(value))
        except ValueError:
            continue
    return 0


def _as_float(value: Any) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return 0.0


def _coverage_rate(count: int, total: int) -> float:
    return round(count / total * 100.0, 2) if total else 0.0
