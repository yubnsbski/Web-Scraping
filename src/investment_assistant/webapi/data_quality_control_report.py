"""Build an operations-ready data quality control report."""

from __future__ import annotations

import csv
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

JsonDict = dict[str, Any]

_PREFIX = "data_quality_control_report"
_CONTROL_FLAGS = (
    "source_data_write_executed",
    "write_executed",
    "external_fetch_executed",
    "auto_trading",
    "call_real_api",
)


@dataclass(frozen=True)
class DataQualityControlReportConfig:
    output_dir: Path
    data_quality_profile_path: Path = Path(
        "web/public/market-dashboard/data_quality_profile.json"
    )
    data_gap_dashboard_path: Path = Path(
        "web/public/market-dashboard/data_gap_dashboard.json"
    )
    source_drift_audit_path: Path = Path(
        "web/public/market-dashboard/source_drift_audit.json"
    )
    source_cleansing_preview_path: Path = Path(
        "web/public/market-dashboard/source_cleansing_preview.json"
    )
    daily_bars_readiness_backlog_path: Path = Path(
        "web/public/market-dashboard/"
        "daily_bars_backfill_batch001_slice001_readiness_backlog.json"
    )
    mirror_dirs: tuple[Path, ...] = field(default_factory=tuple)
    generated_at: str | None = None


def build_data_quality_control_report(
    config: DataQualityControlReportConfig,
) -> JsonDict:
    """Summarize current data-quality gates from existing static artifacts."""

    config.output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "data_quality_profile": _read_json(config.data_quality_profile_path),
        "data_gap_dashboard": _read_json(config.data_gap_dashboard_path),
        "source_drift_audit": _read_json(config.source_drift_audit_path),
        "source_cleansing_preview": _read_json(config.source_cleansing_preview_path),
        "daily_bars_readiness_backlog": _read_optional_json(
            config.daily_bars_readiness_backlog_path
        ),
    }
    gates = _build_gates(config, artifacts)
    operational_backlogs = _build_operational_backlogs(artifacts)
    gate_counts = _gate_counts(gates)
    status = _overall_status(gates)
    raw_ingestion_allowed = not _has_gate_status(gates, "raw_source_drift", "needs_attention")
    clean_preview_available = _has_gate_status(gates, "clean_preview_available", "pass")
    downstream_ready = (
        status == "ready"
        and raw_ingestion_allowed
        and _has_gate_status(gates, "downstream_completeness", "pass")
    )
    payload: JsonDict = {
        "schema_version": 1,
        "status": status,
        "title": "Data Quality Control Report",
        "generated_at": config.generated_at
        or datetime.now().astimezone().isoformat(timespec="seconds"),
        "summary": {
            **gate_counts,
            **_operational_backlog_summary(operational_backlogs),
            "raw_source_ingestion_allowed": raw_ingestion_allowed,
            "clean_preview_available": clean_preview_available,
            "safe_data_mode": (
                "clean_preview_only"
                if clean_preview_available and not raw_ingestion_allowed
                else "raw_sources_allowed"
                if raw_ingestion_allowed
                else "blocked"
            ),
            "downstream_ready": downstream_ready,
            "source_data_write_executed": False,
            "external_fetch_executed": False,
            "auto_trading": False,
            "call_real_api": False,
        },
        "gates": gates,
        "operational_backlogs": operational_backlogs,
        "recommended_actions": _recommended_actions(gates, operational_backlogs),
        "artifact_inputs": [
            str(config.data_quality_profile_path),
            str(config.data_gap_dashboard_path),
            str(config.source_drift_audit_path),
            str(config.source_cleansing_preview_path),
            str(config.daily_bars_readiness_backlog_path),
        ],
        "notes": [
            "This report reads existing local artifacts only.",
            "It separates raw-source readiness from clean-preview availability.",
            "The report is non-advisory and never triggers trading, fetching, or source writes.",
        ],
    }
    _write_json(config.output_dir / f"{_PREFIX}.json", payload)
    _write_csv(config.output_dir / f"{_PREFIX}.csv", payload)
    _write_html(config.output_dir / f"{_PREFIX}.html", payload)
    _write_markdown(config.output_dir / f"{_PREFIX}.md", payload)
    _mirror_artifacts(config.output_dir, config.mirror_dirs)
    return payload


def _build_gates(config: DataQualityControlReportConfig, artifacts: JsonDict) -> list[JsonDict]:
    profile = artifacts["data_quality_profile"]
    gap = artifacts["data_gap_dashboard"]
    drift = artifacts["source_drift_audit"]
    preview = artifacts["source_cleansing_preview"]
    readiness_backlog = artifacts.get("daily_bars_readiness_backlog", {})
    profile_summary = profile.get("summary", {})
    gap_summary = gap.get("summary", {})
    drift_summary = drift.get("summary", {})
    preview_summary = preview.get("summary", {})
    reference_counts = [
        int(profile_summary.get("jpx_domestic_stock_count") or 0),
        int(gap_summary.get("universe_count") or 0),
        int(drift_summary.get("reference_count") or 0),
        int(preview_summary.get("reference_count") or 0),
    ]
    source_of_truth_ready = len(set(reference_counts)) == 1 and reference_counts[0] > 0
    drift_count = int(drift_summary.get("source_with_drift_count") or 0)
    dropped_rows = int(preview_summary.get("total_dropped_row_count") or 0)
    missing_tickers = int(preview_summary.get("total_missing_ticker_count") or 0)
    yield_gap = int(gap_summary.get("yield_gap_count") or 0)
    price_gap = int(gap_summary.get("price_gap_count") or 0)
    profile_attention = int(profile_summary.get("needs_attention_count") or 0)
    preview_files_missing = _missing_preview_files(config.output_dir, preview)
    guardrails_ok = _guardrails_ok(profile, gap, drift, preview, readiness_backlog)
    return [
        {
            "gate_id": "source_of_truth",
            "label": "Source of truth alignment",
            "status": "pass" if source_of_truth_ready else "blocked",
            "score": 100.0 if source_of_truth_ready else 0.0,
            "evidence": f"reference_counts={reference_counts}",
            "next_action": "Keep monitoring JPX domestic universe counts."
            if source_of_truth_ready
            else "Reconcile JPX domestic universe counts before using derived artifacts.",
            "artifact": "data_quality_profile.json",
        },
        {
            "gate_id": "raw_source_drift",
            "label": "Raw source drift",
            "status": "pass" if drift_count == 0 else "needs_attention",
            "score": 100.0 if drift_count == 0 else 50.0,
            "evidence": (
                f"sources_with_drift={drift_count}, "
                f"extra={drift_summary.get('total_extra_ticker_count', 0)}, "
                f"missing={drift_summary.get('total_missing_ticker_count', 0)}"
            ),
            "next_action": "Raw sources may feed downstream."
            if drift_count == 0
            else "Use clean preview CSVs until raw extra and missing tickers are resolved.",
            "artifact": "source_drift_audit.json",
        },
        {
            "gate_id": "clean_preview_available",
            "label": "Clean preview availability",
            "status": "pass" if not preview_files_missing else "blocked",
            "score": 100.0 if not preview_files_missing else 0.0,
            "evidence": (
                f"dropped_rows={dropped_rows}, missing_tickers={missing_tickers}, "
                f"missing_preview_files={preview_files_missing}"
            ),
            "next_action": "Review clean preview outputs before downstream ingestion."
            if not preview_files_missing
            else "Regenerate source cleansing preview artifacts.",
            "artifact": "source_cleansing_preview.json",
        },
        {
            "gate_id": "downstream_completeness",
            "label": "Downstream completeness",
            "status": "pass" if yield_gap == 0 and price_gap == 0 else "needs_attention",
            "score": float(gap_summary.get("yield_coverage_pct") or 0.0),
            "evidence": (
                f"price_gap={price_gap}, yield_gap={yield_gap}, "
                f"yield_coverage_pct={gap_summary.get('yield_coverage_pct', 0)}"
            ),
            "next_action": "Continue non-advisory data-entry or reviewed fetch workflow for gaps."
            if yield_gap or price_gap
            else "Keep monitoring completeness.",
            "artifact": "data_gap_dashboard.json",
        },
        {
            "gate_id": "quality_dimensions",
            "label": "Six quality dimensions",
            "status": "pass" if profile_attention == 0 else "needs_attention",
            "score": _profile_score(profile_summary),
            "evidence": (
                f"pass={profile_summary.get('pass_count', 0)}, "
                f"needs_attention={profile_attention}, "
                f"dimensions={profile_summary.get('dimension_count', 0)}"
            ),
            "next_action": "Resolve dimensions marked needs_attention."
            if profile_attention
            else "Keep monitoring quality dimensions.",
            "artifact": "data_quality_profile.json",
        },
        {
            "gate_id": "operational_guardrails",
            "label": "Operational guardrails",
            "status": "pass" if guardrails_ok else "blocked",
            "score": 100.0 if guardrails_ok else 0.0,
            "evidence": "no source write, no external fetch, no real API call, no trading",
            "next_action": "Keep guardrails enabled."
            if guardrails_ok
            else "Stop and inspect guardrail flags before continuing.",
            "artifact": "all_inputs",
        },
    ]


def _read_json(path: Path) -> JsonDict:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_optional_json(path: Path) -> JsonDict:
    if not path.is_file():
        return {}
    return _read_json(path)


def _build_operational_backlogs(artifacts: JsonDict) -> list[JsonDict]:
    backlog = artifacts.get("daily_bars_readiness_backlog", {})
    if not backlog:
        return []
    summary = backlog.get("summary", {})
    blockers = int(summary.get("blockers") or 0)
    append_ready = bool(summary.get("append_ready"))
    status = "pass" if blockers == 0 and append_ready else "needs_attention"
    return [
        {
            "backlog_id": "daily_bars_slice001_readiness",
            "label": "Daily bars Slice 001 readiness",
            "status": status,
            "blockers": blockers,
            "blocked_ticker_count": int(summary.get("blocked_ticker_count") or 0),
            "blocked_field_count": int(summary.get("blocked_field_count") or 0),
            "ready_rows": int(summary.get("ready_rows") or 0),
            "template_rows": int(summary.get("template_rows") or 0),
            "append_ready": append_ready,
            "next_action": str(summary.get("next_sprint_goal") or ""),
            "artifact": "daily_bars_backfill_batch001_slice001_readiness_backlog.json",
            "link": "daily_bars_backfill_batch001_slice001_readiness_backlog.html",
        }
    ]


def _operational_backlog_summary(backlogs: list[JsonDict]) -> JsonDict:
    blockers = sum(int(backlog.get("blockers") or 0) for backlog in backlogs)
    blocked_tickers = sum(
        int(backlog.get("blocked_ticker_count") or 0) for backlog in backlogs
    )
    blocked_fields = sum(
        int(backlog.get("blocked_field_count") or 0) for backlog in backlogs
    )
    return {
        "operational_backlog_count": len(backlogs),
        "operational_backlog_blockers": blockers,
        "operational_backlog_blocked_ticker_count": blocked_tickers,
        "operational_backlog_blocked_field_count": blocked_fields,
        "operational_backlog_ready": bool(backlogs) and blockers == 0,
    }


def _missing_preview_files(output_dir: Path, preview: JsonDict) -> list[str]:
    missing: list[str] = []
    for source in preview.get("sources", []):
        filename = str(source.get("preview_filename") or "").strip()
        if filename and not (output_dir / filename).exists():
            missing.append(filename)
    return missing


def _guardrails_ok(*payloads: JsonDict) -> bool:
    for payload in payloads:
        summary = payload.get("summary", {})
        for flag in _CONTROL_FLAGS:
            if payload.get(flag) is True or summary.get(flag) is True:
                return False
    return True


def _profile_score(summary: JsonDict) -> float:
    dimension_count = int(summary.get("dimension_count") or 0)
    pass_count = int(summary.get("pass_count") or 0)
    return round(pass_count / dimension_count * 100.0, 2) if dimension_count else 0.0


def _gate_counts(gates: list[JsonDict]) -> JsonDict:
    return {
        "gate_count": len(gates),
        "pass_count": sum(1 for gate in gates if gate["status"] == "pass"),
        "needs_attention_count": sum(
            1 for gate in gates if gate["status"] == "needs_attention"
        ),
        "blocked_count": sum(1 for gate in gates if gate["status"] == "blocked"),
    }


def _overall_status(gates: list[JsonDict]) -> str:
    if any(gate["status"] == "blocked" for gate in gates):
        return "blocked"
    if any(gate["status"] == "needs_attention" for gate in gates):
        return "needs_attention"
    return "ready"


def _has_gate_status(gates: list[JsonDict], gate_id: str, status: str) -> bool:
    return any(gate["gate_id"] == gate_id and gate["status"] == status for gate in gates)


def _recommended_actions(
    gates: list[JsonDict], operational_backlogs: list[JsonDict]
) -> list[str]:
    actions = [
        str(gate["next_action"])
        for gate in gates
        if gate["status"] in {"blocked", "needs_attention"}
    ]
    actions.extend(
        str(backlog["next_action"])
        for backlog in operational_backlogs
        if backlog["status"] in {"blocked", "needs_attention"} and backlog.get("next_action")
    )
    return actions


def _write_json(path: Path, payload: JsonDict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _write_csv(path: Path, payload: JsonDict) -> None:
    fieldnames = [
        "gate_id",
        "label",
        "status",
        "score",
        "evidence",
        "next_action",
        "artifact",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(payload["gates"])


def _write_html(path: Path, payload: JsonDict) -> None:
    summary = payload["summary"]
    cards = [
        ("Status", payload["status"]),
        ("Safe mode", summary["safe_data_mode"]),
        ("Passed gates", f"{summary['pass_count']}/{summary['gate_count']}"),
        ("Attention", summary["needs_attention_count"]),
        ("Backlog blockers", summary["operational_backlog_blockers"]),
    ]
    card_html = "".join(
        "<article class='card'>"
        f"<h2>{escape(str(label))}</h2><div class='metric'>{escape(str(value))}</div>"
        "</article>"
        for label, value in cards
    )
    gate_rows = "".join(
        "<tr>"
        f"<td><code>{escape(str(gate['gate_id']))}</code></td>"
        f"<td>{escape(str(gate['status']))}</td>"
        f"<td>{escape(str(gate['score']))}</td>"
        f"<td>{escape(str(gate['evidence']))}</td>"
        f"<td>{escape(str(gate['next_action']))}</td>"
        f"<td><code>{escape(str(gate['artifact']))}</code></td>"
        "</tr>"
        for gate in payload["gates"]
    )
    backlog_rows = "".join(
        "<tr>"
        f"<td><code>{escape(str(backlog['backlog_id']))}</code></td>"
        f"<td>{escape(str(backlog['status']))}</td>"
        f"<td>{escape(str(backlog['blockers']))}</td>"
        f"<td>{escape(str(backlog['blocked_ticker_count']))}</td>"
        f"<td>{escape(str(backlog['blocked_field_count']))}</td>"
        f"<td>{escape(str(backlog['next_action']))}</td>"
        f"<td><a href='{escape(str(backlog['link']))}'>Open</a></td>"
        "</tr>"
        for backlog in payload.get("operational_backlogs", [])
    )
    backlog_section = (
        "<section class='card'><h2>Operational Backlogs</h2><table><thead><tr>"
        "<th>Backlog</th><th>Status</th><th>Blockers</th><th>Tickers</th>"
        "<th>Fields</th><th>Next action</th><th>Link</th></tr></thead>"
        f"<tbody>{backlog_rows}</tbody></table></section>"
        if backlog_rows
        else ""
    )
    css = (
        ":root{color-scheme:light;font-family:Inter,'Segoe UI',sans-serif;"
        "color:#172033;background:#f6f8fb}body{margin:0}.shell{max-width:1180px;"
        "margin:auto;padding:32px 22px}.grid{display:grid;grid-template-columns:"
        "repeat(auto-fit,minmax(220px,1fr));gap:14px}.card{background:white;"
        "border:1px solid #dbe3ee;border-radius:8px;padding:18px;margin:14px 0}"
        ".metric{font-size:26px;font-weight:850;overflow-wrap:anywhere}"
        "table{width:100%;border-collapse:collapse}th,td{border-bottom:1px solid #e5eaf2;"
        "text-align:left;padding:9px;vertical-align:top}th{background:#f1f5f9}"
        ".notice{font-weight:700;color:#44546a}"
    )
    html = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{escape(str(payload['title']))}</title><style>{css}</style></head>"
        "<body><main class='shell'>"
        f"<h1>{escape(str(payload['title']))}</h1>"
        "<p class='notice'>Local quality gates for market data integration. "
        "No source writes, no external fetches, no API calls, no trading.</p>"
        f"<section class='grid'>{card_html}</section>"
        "<section class='card'><h2>Gates</h2><table><thead><tr>"
        "<th>Gate</th><th>Status</th><th>Score</th><th>Evidence</th>"
        f"<th>Next action</th><th>Artifact</th></tr></thead><tbody>{gate_rows}</tbody></table>"
        f"</section>{backlog_section}</main></body></html>"
    )
    path.write_text(html, encoding="utf-8")


def _write_markdown(path: Path, payload: JsonDict) -> None:
    summary = payload["summary"]
    lines = [
        "# Data Quality Control Report",
        "",
        f"- status: {payload['status']}",
        f"- generated_at: {payload['generated_at']}",
        f"- gate_count: {summary['gate_count']}",
        f"- pass_count: {summary['pass_count']}",
        f"- needs_attention_count: {summary['needs_attention_count']}",
        f"- blocked_count: {summary['blocked_count']}",
        f"- safe_data_mode: {summary['safe_data_mode']}",
        f"- raw_source_ingestion_allowed: {str(summary['raw_source_ingestion_allowed']).lower()}",
        f"- clean_preview_available: {str(summary['clean_preview_available']).lower()}",
        f"- operational_backlog_count: {summary['operational_backlog_count']}",
        f"- operational_backlog_blockers: {summary['operational_backlog_blockers']}",
        "",
        "## Gates",
    ]
    for gate in payload["gates"]:
        lines.append(
            "- "
            f"{gate['gate_id']}: {gate['status']} "
            f"({gate['evidence']}) -> {gate['next_action']}"
        )
    if payload.get("operational_backlogs"):
        lines.extend(["", "## Operational Backlogs"])
        for backlog in payload["operational_backlogs"]:
            lines.append(
                "- "
                f"{backlog['backlog_id']}: {backlog['status']} "
                f"({backlog['blockers']} blockers) -> {backlog['next_action']}"
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _mirror_artifacts(output_dir: Path, mirror_dirs: tuple[Path, ...]) -> None:
    filenames = (
        f"{_PREFIX}.json",
        f"{_PREFIX}.csv",
        f"{_PREFIX}.html",
        f"{_PREFIX}.md",
    )
    for mirror_dir in mirror_dirs:
        mirror_dir.mkdir(parents=True, exist_ok=True)
        for filename in filenames:
            shutil.copy2(output_dir / filename, mirror_dir / filename)
