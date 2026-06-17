"""Markdown rendering for deterministic investment reports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

JsonDict = dict[str, Any]


def render_investment_report_markdown(report: Mapping[str, object]) -> str:
    """Render a generated investment report as review-friendly Markdown."""

    publish_audit = _mapping(report.get("publish_audit"))
    lines = _front_matter_lines(report)
    lines.extend(
        [
            f"# {_text(report.get('title'), 'Investment monthly report')}",
            "",
            f"- generated_at: {_text(report.get('generated_at'), '-')}",
            f"- auto_trading: {_bool_text(report.get('auto_trading'))}",
            f"- call_real_api: {_bool_text(report.get('call_real_api'))}",
            "",
        ]
    )
    _extend_saved_report(lines, report)
    lines.extend(
        [
            "## Publish Audit",
            "",
            f"- status: {_text(publish_audit.get('status') if publish_audit else None, 'unknown')}",
            "- issue_count: "
            + _text(publish_audit.get("issue_count") if publish_audit else None, "-"),
            "",
            "## KPIs",
            "",
            "| metric_key | label | value | formula | evidence_keys |",
            "| --- | --- | ---: | --- | --- |",
        ]
    )
    for kpi in _items(report.get("kpis")):
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(kpi.get("metric_key")),
                    _cell(kpi.get("label")),
                    _cell(kpi.get("value")),
                    _cell(kpi.get("formula")),
                    _cell(_join(kpi.get("evidence_keys"))),
                ]
            )
            + " |"
        )

    lines.extend(["", "## Sections", ""])
    for section in _items(report.get("sections")):
        lines.extend(
            [
                f"### {_text(section.get('title'), _text(section.get('key'), 'Section'))}",
                "",
                _text(section.get("body"), "-"),
                "",
            ]
        )

    lines.extend(
        [
            "## Evidence",
            "",
            "| claim_key | source_type | source_ref | metric_key | formula | last_updated |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in _items(report.get("evidence")):
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(row.get("claim_key")),
                    _cell(row.get("source_type")),
                    _cell(row.get("source_ref")),
                    _cell(row.get("metric_key")),
                    _cell(row.get("formula")),
                    _cell(row.get("last_updated")),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Disclaimer",
            "",
            _text(report.get("disclaimer"), "-"),
            "",
        ]
    )
    return "\n".join(lines)


def _front_matter_lines(report: Mapping[str, object]) -> list[str]:
    history = _mapping(report.get("history"))
    values: dict[str, object] = {
        "doc_type": "investment_report",
        "title": _text(report.get("title"), "Investment monthly report"),
        "generated_at": _text(report.get("generated_at"), "-"),
        "auto_trading": _bool_text(report.get("auto_trading")),
        "call_real_api": _bool_text(report.get("call_real_api")),
    }
    if history is not None:
        values.update(
            {
                "report_id": _text(history.get("id"), "-"),
                "saved_at": _text(history.get("saved_at"), "-"),
                "integrity_status": _text(history.get("integrity_status"), "unknown"),
                "report_hash": _text(history.get("report_hash"), "-"),
            }
        )
    lines = ["---"]
    for key, value in values.items():
        if str(value).lower() in {"true", "false"}:
            lines.append(f"{key}: {str(value).lower()}")
        else:
            lines.append(f'{key}: "{_front_matter_value(value)}"')
    lines.extend(["---", ""])
    return lines


def _front_matter_value(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _extend_saved_report(lines: list[str], report: Mapping[str, object]) -> None:
    history = _mapping(report.get("history"))
    if history is None:
        return
    lines.extend(
        [
            "## Saved Report",
            "",
            f"- id: {_text(history.get('id'), '-')}",
            f"- saved_at: {_text(history.get('saved_at'), '-')}",
            f"- integrity_status: {_text(history.get('integrity_status'), 'unknown')}",
            f"- report_hash: {_text(history.get('report_hash'), '-')}",
            f"- calculated_report_hash: {_text(history.get('calculated_report_hash'), '-')}",
            "",
        ]
    )


def _items(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _join(value: object) -> str:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return ", ".join(str(item) for item in value)
    return _text(value, "")


def _cell(value: object) -> str:
    return _text(value, "").replace("|", "\\|").replace("\n", "<br>")


def _text(value: object, fallback: str) -> str:
    if value is None:
        return fallback
    text = str(value)
    return text if text else fallback


def _bool_text(value: object) -> str:
    return "true" if value is True else "false"
