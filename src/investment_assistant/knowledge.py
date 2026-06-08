"""Knowledge-base snapshots and diffs ("context analysis").

The assistant's answer context comes from the RAG corpus and the EDINET-derived
``financials.csv``. As the weekly ingest accumulates filings, that knowledge
evolves. This module captures a compact snapshot of the current knowledge and
diffs it against the previously saved one, so the UI can visualize *what the
system learned / what changed* since you last looked:

- new / removed RAG sources and chunk-count growth,
- per-ticker financial changes: dividend moves, new periods, newly detected
  dividend cuts, and trend flips.

No network I/O. Snapshots persist as a small JSON file.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from investment_assistant.financials.evidence import DEFAULT_FINANCIALS_CSV, load_comparison
from investment_assistant.rag.store import DEFAULT_RAG_DB_PATH, RagStore

DEFAULT_SNAPSHOT_PATH = ".cache/investment_assistant/knowledge_snapshot.json"

_TRACKED_FIELDS: tuple[tuple[str, str], ...] = (
    ("dividend_trend", "配当トレンド"),
    ("operating_cf_trend", "営業CFトレンド"),
    ("equity_ratio_trend", "自己資本比率トレンド"),
)


def snapshot_knowledge(
    *,
    db_path: str | Path = DEFAULT_RAG_DB_PATH,
    financials_csv: str | Path = DEFAULT_FINANCIALS_CSV,
) -> dict[str, object]:
    """Capture a compact snapshot of the current knowledge base."""

    per_source: Counter[str] = Counter()
    total_chunks = 0
    if Path(db_path).exists():
        for chunk in RagStore(db_path).list_chunks():
            per_source[chunk.source] += 1
            total_chunks += 1

    financials: dict[str, dict[str, object]] = {}
    comparison = load_comparison(financials_csv)
    if comparison is not None:
        companies = comparison.get("companies")
        if isinstance(companies, list):
            for company in companies:
                if not isinstance(company, dict):
                    continue
                ticker = str(company.get("ticker") or "").strip()
                if not ticker:
                    continue
                series = company.get("dividend_series")
                financials[ticker] = {
                    "name": company.get("name"),
                    "latest_fiscal_year": company.get("latest_fiscal_year"),
                    "dividend_per_share": company.get("latest_dividend_per_share"),
                    "dividend_series": series if isinstance(series, list) else [],
                    "dividend_cut_years": company.get("dividend_cut_years") or [],
                    "dividend_trend": company.get("dividend_trend"),
                    "operating_cf_trend": company.get("operating_cf_trend"),
                    "equity_ratio_trend": company.get("equity_ratio_trend"),
                    "periods": len(series) if isinstance(series, list) else 0,
                }

    return {
        "captured_at": datetime.now(UTC).isoformat(),
        "rag": {
            "sources": len(per_source),
            "chunks": total_chunks,
            "per_source": dict(per_source),
        },
        "financials": financials,
    }


def diff_snapshots(
    previous: dict[str, object] | None, current: dict[str, object]
) -> dict[str, object]:
    """Diff two snapshots into a UI-friendly summary of what changed."""

    prev = previous or {}
    prev_rag = _as_dict(prev.get("rag"))
    curr_rag = _as_dict(current.get("rag"))
    prev_sources = set(_as_dict(prev_rag.get("per_source")))
    curr_sources = set(_as_dict(curr_rag.get("per_source")))

    rag_diff = {
        "chunks_delta": _as_int(curr_rag.get("chunks")) - _as_int(prev_rag.get("chunks")),
        "sources_delta": _as_int(curr_rag.get("sources")) - _as_int(prev_rag.get("sources")),
        "new_sources": sorted(curr_sources - prev_sources),
        "removed_sources": sorted(prev_sources - curr_sources),
    }

    prev_fin = _as_dict(prev.get("financials"))
    curr_fin = _as_dict(current.get("financials"))
    financial_changes: list[dict[str, object]] = []
    for ticker, company in curr_fin.items():
        company = _as_dict(company)
        before = prev_fin.get(ticker)
        if before is None:
            financial_changes.append(
                {
                    "ticker": ticker,
                    "name": company.get("name"),
                    "kind": "new",
                    "changes": [{"field": "新規追跡", "to": company.get("dividend_per_share")}],
                }
            )
            continue
        before = _as_dict(before)
        changes: list[dict[str, object]] = []
        if company.get("dividend_per_share") != before.get("dividend_per_share"):
            changes.append(
                {
                    "field": "1株配当",
                    "from": before.get("dividend_per_share"),
                    "to": company.get("dividend_per_share"),
                }
            )
        if _as_int(company.get("periods")) > _as_int(before.get("periods")):
            changes.append(
                {"field": "期数", "from": before.get("periods"), "to": company.get("periods")}
            )
        new_cuts = [
            year
            for year in _as_list(company.get("dividend_cut_years"))
            if year not in _as_list(before.get("dividend_cut_years"))
        ]
        if new_cuts:
            changes.append({"field": "新規減配年", "to": new_cuts})
        for field, label in _TRACKED_FIELDS:
            if company.get(field) != before.get(field):
                changes.append(
                    {"field": label, "from": before.get(field), "to": company.get(field)}
                )
        if changes:
            financial_changes.append(
                {
                    "ticker": ticker,
                    "name": company.get("name"),
                    "kind": "changed",
                    "changes": changes,
                }
            )

    has_changes = bool(
        rag_diff["new_sources"]
        or rag_diff["removed_sources"]
        or rag_diff["chunks_delta"]
        or financial_changes
    )
    return {"rag": rag_diff, "financial_changes": financial_changes, "has_changes": has_changes}


def load_last_snapshot(path: str | Path) -> dict[str, object] | None:
    snapshot_path = Path(path)
    if not snapshot_path.is_file():
        return None
    try:
        data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def save_snapshot(path: str | Path, snapshot: dict[str, object]) -> None:
    snapshot_path = Path(path)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def run_knowledge_diff(
    *,
    db_path: str | Path = DEFAULT_RAG_DB_PATH,
    financials_csv: str | Path = DEFAULT_FINANCIALS_CSV,
    snapshot_path: str | Path = DEFAULT_SNAPSHOT_PATH,
    save: bool = True,
) -> dict[str, object]:
    """Snapshot the knowledge base and diff it against the last saved snapshot.

    Saves the new snapshot (unless ``save`` is false) so the next call reports
    only what changed since this one — a running "what did I learn" view.
    """

    previous = load_last_snapshot(snapshot_path)
    current = snapshot_knowledge(db_path=db_path, financials_csv=financials_csv)
    diff = diff_snapshots(previous, current)
    if save:
        save_snapshot(snapshot_path, current)
    return {
        "captured_at": current["captured_at"],
        "previous_at": (previous or {}).get("captured_at"),
        "snapshot": current,
        "diff": diff,
    }


def _as_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _as_int(value: object) -> int:
    return value if isinstance(value, int) else 0
