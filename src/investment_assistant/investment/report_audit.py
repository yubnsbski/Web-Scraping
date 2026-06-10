"""Publish-readiness checks for deterministic investment reports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def audit_investment_report(report: Mapping[str, object]) -> dict[str, object]:
    """Return deterministic, non-blocking issues for report publication."""

    issues: list[dict[str, object]] = []
    _require_non_empty(report, "disclaimer", "report.disclaimer", issues)
    if report.get("auto_trading") is not False:
        _issue(
            issues,
            code="auto_trading_not_false",
            path="report.auto_trading",
            message="Report must explicitly disable auto trading.",
        )
    if report.get("call_real_api") is not False:
        _issue(
            issues,
            code="call_real_api_not_false",
            path="report.call_real_api",
            message="Report must explicitly avoid real API calls during rendering.",
        )

    evidence = _items(report.get("evidence"))
    evidence_keys = {
        str(row.get("claim_key"))
        for row in evidence
        if _non_empty_text(row.get("claim_key"))
    }
    if not evidence:
        _issue(
            issues,
            code="report_missing_evidence",
            path="report.evidence",
            message="Report must include evidence rows.",
        )

    for index, row in enumerate(evidence):
        path = f"report.evidence[{index}]"
        for field in (
            "claim_key",
            "source_type",
            "source_ref",
            "metric_key",
            "formula",
            "last_updated",
        ):
            _require_non_empty(row, field, f"{path}.{field}", issues)

    kpis = _items(report.get("kpis"))
    if not kpis:
        _issue(
            issues,
            code="report_missing_kpis",
            path="report.kpis",
            message="Report must include KPI rows.",
        )

    for index, kpi in enumerate(kpis):
        path = f"report.kpis[{index}]"
        for field in ("metric_key", "formula", "last_updated", "disclaimer"):
            _require_non_empty(kpi, field, f"{path}.{field}", issues)
        evidence_refs = _string_sequence(kpi.get("evidence_keys"))
        if not evidence_refs:
            _issue(
                issues,
                code="kpi_missing_evidence_keys",
                path=f"{path}.evidence_keys",
                message="Every KPI must link to at least one evidence row.",
            )
            continue
        for claim_key in evidence_refs:
            if claim_key not in evidence_keys:
                _issue(
                    issues,
                    code="kpi_evidence_key_not_found",
                    path=f"{path}.evidence_keys",
                    message=f"KPI references missing evidence claim '{claim_key}'.",
                    claim_key=claim_key,
                )

    sections = _items(report.get("sections"))
    if not sections:
        _issue(
            issues,
            code="report_missing_sections",
            path="report.sections",
            message="Report must include narrative sections.",
        )
    for index, section in enumerate(sections):
        path = f"report.sections[{index}]"
        for field in ("key", "title", "body"):
            _require_non_empty(section, field, f"{path}.{field}", issues)

    return {
        "status": "ok" if not issues else "error",
        "issue_count": len(issues),
        "issues": issues,
        "auto_trading": False,
        "call_real_api": False,
    }


def _items(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _require_non_empty(
    row: Mapping[str, object],
    field: str,
    path: str,
    issues: list[dict[str, object]],
) -> None:
    if _non_empty_text(row.get(field)):
        return
    _issue(
        issues,
        code=f"{field}_missing",
        path=path,
        message=f"Required field '{field}' is missing.",
    )


def _non_empty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_sequence(value: object) -> list[str]:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return [str(item) for item in value if str(item).strip()]
    return []


def _issue(
    issues: list[dict[str, object]],
    *,
    code: str,
    path: str,
    message: str,
    **extra: object,
) -> None:
    row: dict[str, object] = {
        "level": "error",
        "code": code,
        "path": path,
        "message": message,
    }
    row.update(extra)
    issues.append(row)
