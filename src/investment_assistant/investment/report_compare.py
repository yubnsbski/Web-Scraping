"""Deterministic comparison for saved investment reports."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

JsonDict = dict[str, Any]

_DEFAULT_METRICS = (
    "market_value",
    "unrealized_pnl",
    "annual_income_estimate",
    "nisa_remaining",
    "concentration_top_weight",
    "concentration_hhi",
    "concentration_effective_names",
    "target_required_budget",
    "target_reachable",
)


def compare_investment_reports(
    base_entry: Mapping[str, object],
    compare_entry: Mapping[str, object],
    *,
    metric_keys: tuple[str, ...] = _DEFAULT_METRICS,
) -> JsonDict:
    """Compare two saved report entries without forecasting or advice."""

    base_report = _report(base_entry)
    compare_report = _report(compare_entry)
    base_kpis = _kpi_index(base_report.get("kpis"))
    compare_kpis = _kpi_index(compare_report.get("kpis"))
    rows = [
        _metric_delta(key, base_kpis.get(key), compare_kpis.get(key))
        for key in metric_keys
        if key in base_kpis or key in compare_kpis
    ]
    return {
        "base": _entry_ref(base_entry),
        "compare": _entry_ref(compare_entry),
        "metrics": rows,
        "evidence": _evidence_delta(base_report, compare_report),
        "auto_trading": False,
        "call_real_api": False,
        "disclaimer": compare_report.get("disclaimer") or base_report.get("disclaimer"),
    }


def _report(entry: Mapping[str, object]) -> Mapping[str, object]:
    value = entry.get("report")
    return value if isinstance(value, Mapping) else {}


def _entry_ref(entry: Mapping[str, object]) -> JsonDict:
    summary = entry.get("summary")
    summary_map = summary if isinstance(summary, Mapping) else {}
    return {
        "id": entry.get("id") or summary_map.get("id"),
        "saved_at": entry.get("saved_at") or summary_map.get("saved_at"),
        "generated_at": summary_map.get("generated_at"),
        "title": summary_map.get("title"),
    }


def _kpi_index(value: object) -> dict[str, Mapping[str, object]]:
    if not isinstance(value, list):
        return {}
    out: dict[str, Mapping[str, object]] = {}
    for item in value:
        if isinstance(item, Mapping):
            key = item.get("metric_key")
            if isinstance(key, str):
                out[key] = item
    return out


def _metric_delta(
    key: str,
    base: Mapping[str, object] | None,
    compare: Mapping[str, object] | None,
) -> JsonDict:
    base_value = base.get("value") if base is not None else None
    compare_value = compare.get("value") if compare is not None else None
    base_number = _number(base_value)
    compare_number = _number(compare_value)
    delta = (
        round(compare_number - base_number, 6)
        if base_number is not None and compare_number is not None
        else None
    )
    delta_pct = None
    if delta is not None and base_number is not None and base_number != 0.0:
        delta_pct = round(delta / abs(base_number) * 100.0, 4)
    return {
        "metric_key": key,
        "label": _label(base, compare, key),
        "base_value": base_value,
        "compare_value": compare_value,
        "delta": delta,
        "delta_pct": delta_pct,
        "value_format": _value_format(base, compare),
        "changed": base_value != compare_value,
        "evidence_keys": _merged_evidence_keys(base, compare),
        "formula": "compare_value - base_value",
    }


def _label(
    base: Mapping[str, object] | None,
    compare: Mapping[str, object] | None,
    fallback: str,
) -> object:
    if compare is not None and compare.get("label"):
        return compare.get("label")
    if base is not None and base.get("label"):
        return base.get("label")
    return fallback


def _value_format(
    base: Mapping[str, object] | None,
    compare: Mapping[str, object] | None,
) -> object:
    if compare is not None and compare.get("value_format"):
        return compare.get("value_format")
    if base is not None and base.get("value_format"):
        return base.get("value_format")
    return "number"


def _merged_evidence_keys(
    base: Mapping[str, object] | None,
    compare: Mapping[str, object] | None,
) -> list[str]:
    out: list[str] = []
    for item in (base, compare):
        if item is None:
            continue
        keys = item.get("evidence_keys")
        if isinstance(keys, list):
            out.extend(str(key) for key in keys)
    return list(dict.fromkeys(out))


def _evidence_delta(
    base_report: Mapping[str, object],
    compare_report: Mapping[str, object],
) -> JsonDict:
    base_keys = _evidence_keys(base_report.get("evidence"))
    compare_keys = _evidence_keys(compare_report.get("evidence"))
    return {
        "base_count": len(base_keys),
        "compare_count": len(compare_keys),
        "added": sorted(compare_keys - base_keys),
        "removed": sorted(base_keys - compare_keys),
    }


def _evidence_keys(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    keys: set[str] = set()
    for item in value:
        if isinstance(item, Mapping):
            key = item.get("claim_key")
            if isinstance(key, str):
                keys.add(key)
    return keys


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None
