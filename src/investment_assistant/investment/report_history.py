"""Local persistence for generated investment reports.

The MVP is a single-user PWA, so report history is intentionally file-based and
small. The stored payload is the generated report plus a compact summary for
the UI; raw CSV request bodies and provider credentials are not stored here.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

JsonDict = dict[str, Any]

_SAFE_ID = re.compile(r"^[0-9A-Za-z_.-]+$")
_DEFAULT_MAX_ENTRIES = 50


def save_investment_report(
    report: Mapping[str, object],
    *,
    history_dir: str | Path | None = None,
    max_entries: int = _DEFAULT_MAX_ENTRIES,
) -> JsonDict:
    """Persist a generated investment report and return its summary row."""

    folder = _history_dir(history_dir)
    folder.mkdir(parents=True, exist_ok=True)
    saved_at = datetime.now(UTC).isoformat()
    report_id = _new_report_id()
    summary = _summary(report, report_id=report_id, saved_at=saved_at)
    entry: JsonDict = {
        "id": report_id,
        "saved_at": saved_at,
        "summary": summary,
        "report": dict(report),
    }
    _write_json(_entry_path(folder, report_id), entry)
    _prune(folder, max_entries=max_entries)
    return summary


def list_investment_reports(
    *,
    history_dir: str | Path | None = None,
    limit: int = 20,
) -> JsonDict:
    """Return report history summaries, newest first."""

    folder = _history_dir(history_dir)
    summaries = [_entry_summary(entry) for entry in _read_entries(folder)]
    summaries.sort(key=lambda item: str(item.get("saved_at") or ""), reverse=True)
    safe_limit = max(limit, 0)
    return {
        "reports": summaries[:safe_limit],
        "count": len(summaries),
        "history_dir": str(folder),
        "auto_trading": False,
        "call_real_api": False,
    }


def load_investment_report(
    report_id: str,
    *,
    history_dir: str | Path | None = None,
) -> JsonDict:
    """Load one saved report entry by id."""

    safe_id = _safe_report_id(report_id)
    folder = _history_dir(history_dir)
    path = _entry_path(folder, safe_id)
    if not path.exists():
        raise FileNotFoundError(f"report history entry not found: {safe_id}")
    entry = _read_json(path)
    if not isinstance(entry, dict):
        raise ValueError(f"invalid report history entry: {safe_id}")
    return entry


def delete_investment_report(
    report_id: str,
    *,
    history_dir: str | Path | None = None,
) -> JsonDict:
    """Delete one saved report entry by id."""

    safe_id = _safe_report_id(report_id)
    folder = _history_dir(history_dir)
    path = _entry_path(folder, safe_id)
    if not path.exists():
        raise FileNotFoundError(f"report history entry not found: {safe_id}")
    path.unlink()
    return {
        "id": safe_id,
        "deleted": True,
        "auto_trading": False,
        "call_real_api": False,
    }


def _history_dir(history_dir: str | Path | None) -> Path:
    if history_dir is not None:
        return Path(history_dir)
    configured = os.getenv("INVESTMENT_ASSISTANT_REPORT_HISTORY_DIR")
    if configured:
        return Path(configured)
    return Path(tempfile.gettempdir()) / "investment_assistant" / "report_history"


def _new_report_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{stamp}-{uuid4().hex[:8]}"


def _safe_report_id(report_id: str) -> str:
    value = str(report_id).strip()
    if not value or not _SAFE_ID.fullmatch(value):
        raise ValueError("invalid report history id")
    return value


def _entry_path(folder: Path, report_id: str) -> Path:
    return folder / f"{_safe_report_id(report_id)}.json"


def _summary(
    report: Mapping[str, object],
    *,
    report_id: str,
    saved_at: str,
) -> JsonDict:
    kpis = _kpi_index(report.get("kpis"))
    return {
        "id": report_id,
        "saved_at": saved_at,
        "generated_at": report.get("generated_at"),
        "title": report.get("title") or "Investment monthly report",
        "market_value": _kpi_value(kpis, "market_value"),
        "annual_income_estimate": _kpi_value(kpis, "annual_income_estimate"),
        "nisa_remaining": _kpi_value(kpis, "nisa_remaining"),
        "target_annual_dividend": _kpi_value(kpis, "target_annual_dividend"),
        "target_required_budget": _kpi_value(kpis, "target_required_budget"),
        "target_reachable": _kpi_value(kpis, "target_reachable"),
        "candidate_count": report.get("candidate_count"),
        "evidence_count": _sequence_len(report.get("evidence")),
        "publish_audit_status": _publish_audit_value(report, "status", "unknown"),
        "publish_audit_issue_count": _publish_audit_value(report, "issue_count", None),
        "auto_trading": False,
        "call_real_api": False,
    }


def _entry_summary(entry: Mapping[str, object]) -> JsonDict:
    summary = entry.get("summary")
    if isinstance(summary, dict):
        return dict(summary)
    report_id = str(entry.get("id") or "")
    saved_at = str(entry.get("saved_at") or "")
    report = entry.get("report")
    return _summary(
        report if isinstance(report, Mapping) else {},
        report_id=report_id,
        saved_at=saved_at,
    )


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


def _kpi_value(kpis: Mapping[str, Mapping[str, object]], key: str) -> object:
    item = kpis.get(key)
    return item.get("value") if item is not None else None


def _sequence_len(value: object) -> int:
    return len(value) if isinstance(value, list) else 0


def _publish_audit_value(
    report: Mapping[str, object],
    key: str,
    fallback: object,
) -> object:
    audit = report.get("publish_audit")
    if not isinstance(audit, Mapping):
        return fallback
    return audit.get(key, fallback)


def _read_entries(folder: Path) -> list[JsonDict]:
    if not folder.exists():
        return []
    entries: list[JsonDict] = []
    for path in folder.glob("*.json"):
        try:
            value = _read_json(path)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if isinstance(value, dict):
            entries.append(value)
    return entries


def _read_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, value: Mapping[str, object]) -> None:
    temp_path = path.with_suffix(".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    temp_path.replace(path)


def _prune(folder: Path, *, max_entries: int) -> None:
    if max_entries <= 0:
        return
    entries = sorted(folder.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in entries[max_entries:]:
        path.unlink(missing_ok=True)
