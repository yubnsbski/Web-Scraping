"""Markdown rendering for deterministic investment reports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

JsonDict = dict[str, Any]


def render_investment_report_markdown(report: Mapping[str, object]) -> str:
    """Render a generated investment report as review-friendly Markdown."""

    lines = [
        f"# {_text(report.get('title'), 'Investment monthly report')}",
        "",
        f"- generated_at: {_text(report.get('generated_at'), '-')}",
        f"- auto_trading: {_bool_text(report.get('auto_trading'))}",
        f"- call_real_api: {_bool_text(report.get('call_real_api'))}",
        "",
        "## KPIs",
        "",
        "| metric_key | label | value | formula | evidence_keys |",
        "| --- | --- | ---: | --- | --- |",
    ]
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


def _items(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


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
