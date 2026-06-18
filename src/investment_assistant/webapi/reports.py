"""Investment-report JSON API handlers.

The handlers in this module keep report generation, history, markdown, and
audit endpoints separate from the main routing module. Numeric calculations
stay in the investment/portfolio engines; these handlers only translate JSON
payloads into those deterministic calls.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from investment_assistant.financials.evidence import DEFAULT_FINANCIALS_CSV
from investment_assistant.webapi.errors import ApiError

JsonDict = dict[str, Any]
_DEFAULT_REPORT_DOCS_DIR = Path("local_docs") / "reports"


def investment_monthly_report(body: JsonDict) -> JsonDict:
    from investment_assistant.investment import (
        build_investment_monthly_report,
        holdings_from_payload,
    )
    from investment_assistant.investment.report_history import save_investment_report
    from investment_assistant.portfolio.simulator import plan_for_target_dividend

    raw_candidates = body.get("candidates")
    candidates: list[dict[str, object]] = []
    if isinstance(raw_candidates, list):
        candidates = [
            {str(key): value for key, value in item.items()}
            for item in raw_candidates
            if isinstance(item, dict)
        ]
    holdings = holdings_from_payload(body)
    financials_csv = str(body.get("financials_csv") or DEFAULT_FINANCIALS_CSV)
    target_result: JsonDict | None = None
    target_annual_dividend = _as_float(body.get("target_annual_dividend"), 0.0)
    if target_annual_dividend > 0:
        target_result = plan_for_target_dividend(
            target_annual_dividend=target_annual_dividend,
            holdings=_target_planner_holdings(holdings),
            years=_as_int(body.get("years"), 10),
            reinvest=_as_bool(body.get("reinvest"), True),
            growth_rate=_as_float(body.get("growth_rate"), 0.0),
            auto_weight=str(body.get("auto_weight") or "equal"),
            optimization=str(body.get("optimization") or "balanced"),
            dividend_basis=str(body.get("dividend_basis") or "conservative"),
            financials_csv=financials_csv,
        )
    report = build_investment_monthly_report(
        holdings,
        candidates=candidates,
        target_result=target_result,
        financials_csv=financials_csv,
        runtime_mode=str(body.get("runtime_mode") or "development"),
    )
    if _as_bool(body.get("save_history"), True):
        report["history"] = save_investment_report(
            report,
            history_dir=_optional_history_dir(body),
            max_entries=_as_int(body.get("history_limit"), 50),
        )
    return report


def investment_report_history(body: JsonDict) -> JsonDict:
    from investment_assistant.investment.report_history import list_investment_reports

    return list_investment_reports(
        history_dir=_optional_history_dir(body),
        limit=_as_int(body.get("limit"), 20),
    )


def investment_report_history_load(body: JsonDict) -> JsonDict:
    from investment_assistant.investment.report_history import load_investment_report

    report_id = _report_history_id(body)
    entry = load_investment_report(report_id, history_dir=_optional_history_dir(body))
    return _entry_with_report_history(entry)


def investment_report_history_delete(body: JsonDict) -> JsonDict:
    from investment_assistant.investment.report_history import delete_investment_report

    report_id = _report_history_id(body)
    return delete_investment_report(report_id, history_dir=_optional_history_dir(body))


def investment_report_history_verify(body: JsonDict) -> JsonDict:
    from investment_assistant.investment.report_history import verify_investment_report_history

    report_id = _report_history_id(body)
    return verify_investment_report_history(report_id, history_dir=_optional_history_dir(body))


def investment_report_history_compare(body: JsonDict) -> JsonDict:
    from investment_assistant.investment.report_compare import compare_investment_reports
    from investment_assistant.investment.report_history import load_investment_report

    base_id = str(body.get("base_id") or "").strip()
    compare_id = str(body.get("compare_id") or "").strip()
    if not base_id or not compare_id:
        raise ApiError("base_id and compare_id are required")
    history_dir = _optional_history_dir(body)
    return compare_investment_reports(
        load_investment_report(base_id, history_dir=history_dir),
        load_investment_report(compare_id, history_dir=history_dir),
    )


def investment_report_markdown(body: JsonDict) -> JsonDict:
    from investment_assistant.investment.report_markdown import render_investment_report_markdown

    report = _report_from_body_or_history(body)
    return {
        "markdown": render_investment_report_markdown(report),
        "auto_trading": False,
        "call_real_api": False,
    }


def investment_report_markdown_save(body: JsonDict) -> JsonDict:
    from investment_assistant import cli
    from investment_assistant.investment.report_markdown import render_investment_report_markdown
    from investment_assistant.rag.store import DEFAULT_RAG_DB_PATH

    report = _report_from_body_or_history(body)
    markdown = render_investment_report_markdown(report)
    output_dir = _safe_report_docs_dir(body.get("output_dir"))
    output_dir.mkdir(parents=True, exist_ok=True)
    save_path = _unique_path(output_dir / _report_markdown_filename(report, body.get("filename")))
    save_path.write_text(markdown, encoding="utf-8")

    index_after_save = _as_bool(body.get("index_after_save"), True)
    db_path = str(body.get("db_path") or DEFAULT_RAG_DB_PATH)
    indexed = None
    if index_after_save:
        indexed = cli.run_rag_index(
            path=save_path,
            db_path=db_path,
        )
    return {
        "saved_path": str(save_path),
        "chars": len(markdown),
        "index_after_save": index_after_save,
        "db_path": db_path,
        "indexed": indexed,
        "auto_trading": False,
        "call_real_api": False,
    }


def investment_report_markdown_library(body: JsonDict) -> JsonDict:
    output_dir = _safe_report_docs_dir(body.get("output_dir"))
    limit = _as_int(body.get("limit"), 20)
    docs = []
    if output_dir.exists():
        docs = [
            _report_markdown_doc_summary(path)
            for path in output_dir.glob("*.md")
            if path.is_file()
        ]
        docs.sort(key=lambda item: str(item.get("modified_at") or ""), reverse=True)
    safe_limit = max(limit, 0)
    return {
        "output_dir": str(output_dir),
        "docs": docs[:safe_limit],
        "count": len(docs),
        "auto_trading": False,
        "call_real_api": False,
    }


def investment_report_audit(body: JsonDict) -> JsonDict:
    from investment_assistant.investment.report_audit import audit_investment_report

    return audit_investment_report(_report_from_body_or_history(body))


def _report_history_id(body: JsonDict) -> str:
    report_id = str(body.get("id") or body.get("report_id") or "").strip()
    if not report_id:
        raise ApiError("report history id is required")
    return report_id


def _report_from_body_or_history(body: JsonDict) -> JsonDict:
    from investment_assistant.investment.report_history import load_investment_report

    report = body.get("report")
    if isinstance(report, dict):
        return report

    report_id = str(body.get("id") or body.get("report_id") or "").strip()
    if not report_id:
        raise ApiError("report or report history id is required")
    entry = load_investment_report(report_id, history_dir=_optional_history_dir(body))
    loaded_report = _entry_with_report_history(entry).get("report")
    if not isinstance(loaded_report, dict):
        raise ApiError("saved report is invalid")
    return loaded_report


def _entry_with_report_history(entry: JsonDict) -> JsonDict:
    out = dict(entry)
    report = out.get("report")
    if isinstance(report, dict):
        report_out = dict(report)
        report_out["history"] = _entry_history_summary(out)
        out["report"] = report_out
    return out


def _entry_history_summary(entry: JsonDict) -> JsonDict:
    summary = entry.get("summary")
    out = dict(summary) if isinstance(summary, dict) else {}
    for key in (
        "id",
        "saved_at",
        "report_hash",
        "calculated_report_hash",
        "integrity_status",
    ):
        if entry.get(key) is not None:
            out[key] = entry.get(key)
    return out


def _safe_report_docs_dir(raw: object) -> Path:
    value = str(raw or _DEFAULT_REPORT_DOCS_DIR).strip() or str(_DEFAULT_REPORT_DOCS_DIR)
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ApiError("output_dir must be a relative path under local_docs")
    if not path.parts or path.parts[0] != "local_docs":
        raise ApiError("output_dir must be under local_docs")
    return path


def _report_markdown_filename(report: JsonDict, raw: object) -> str:
    if isinstance(raw, str) and raw.strip():
        stem = Path(raw.strip()).stem
    else:
        history = report.get("history")
        report_id = ""
        if isinstance(history, dict):
            report_id = str(history.get("id") or "")
        generated = str(report.get("generated_at") or "")
        stamp = generated[:19].replace(":", "").replace("-", "").replace("T", "-")
        stem = f"investment-report-{report_id or stamp or 'latest'}"
    safe_stem = re.sub(r"[^0-9A-Za-z_.-]+", "-", stem).strip("-_.")
    return f"{safe_stem or 'investment-report'}.md"


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    candidate = path.with_name(f"{path.stem}-{stamp}{path.suffix}")
    counter = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}-{stamp}-{counter}{path.suffix}")
        counter += 1
    return candidate


def _report_markdown_doc_summary(path: Path) -> JsonDict:
    stat = path.stat()
    metadata = _report_markdown_doc_metadata(path)
    return {
        "path": str(path),
        "filename": path.name,
        "title": metadata.get("title") or path.stem,
        "report_id": metadata.get("report_id"),
        "saved_at": metadata.get("saved_at"),
        "integrity_status": metadata.get("integrity_status"),
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
    }


def _report_markdown_doc_metadata(path: Path) -> JsonDict:
    text = path.read_text(encoding="utf-8", errors="replace")[:8000]
    out: JsonDict = {}
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and not out.get("title"):
            out["title"] = stripped[2:].strip()
            continue
        if stripped.startswith("- id:"):
            out["report_id"] = stripped.split(":", 1)[1].strip() or None
            continue
        if stripped.startswith("- saved_at:"):
            out["saved_at"] = stripped.split(":", 1)[1].strip() or None
            continue
        if stripped.startswith("- integrity_status:"):
            out["integrity_status"] = stripped.split(":", 1)[1].strip() or None
    return out


def _target_planner_holdings(holdings: list[Any]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for holding in holdings:
        quantity = _as_float(getattr(holding, "quantity", 0.0), 0.0)
        price = _as_float(
            getattr(holding, "current_price", None),
            _as_float(getattr(holding, "avg_cost", 0.0), 0.0),
        )
        if quantity <= 0 or price <= 0:
            continue
        asset_type = str(getattr(holding, "asset_type", "") or "").lower()
        row: dict[str, object] = {
            "ticker": str(getattr(holding, "ticker_or_fund_code", "") or ""),
            "name": str(getattr(holding, "name", "") or ""),
            "price": price,
            "shares": quantity,
            "lot": 100 if asset_type == "stock" else 1,
        }
        dividend_per_unit = _dividend_per_unit_for_target(holding, quantity)
        if dividend_per_unit is not None:
            row["dividend_per_share"] = dividend_per_unit
        rows.append(row)
    return rows


def _dividend_per_unit_for_target(holding: Any, quantity: float) -> float | None:
    annual_income = _optional_float(getattr(holding, "annual_income", None))
    if annual_income is not None and quantity > 0:
        return max(annual_income / quantity, 0.0)
    distribution_per_unit = _optional_float(getattr(holding, "distribution_per_unit", None))
    if distribution_per_unit is not None:
        return max(distribution_per_unit, 0.0)
    return None


def _optional_history_dir(body: JsonDict) -> str | None:
    raw = body.get("history_dir")
    if raw is None:
        return None
    value = str(raw).strip()
    return value or None


def _as_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.lower().strip()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _as_int(value: object, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: object, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return _as_float(value, 0.0)
