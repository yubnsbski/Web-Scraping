"""EDINET workflow helpers for the local dashboard."""

from __future__ import annotations

import os
from typing import Any

from investment_assistant.edinet.client import API_KEY_ENV_VAR
from investment_assistant.edinet.registry import build_edinet_targets_from_registry
from investment_assistant.ingestion.fetcher import reject_path_traversal

JsonDict = dict[str, Any]

_DEFAULT_REGISTRY_PATH = "examples/source_registry_nikkei225_edinet.yaml"
_DEFAULT_OUTPUT_DIR = "local_docs/edinet"
_DEFAULT_DB_PATH = ".cache/investment_assistant/rag.sqlite"


def edinet_status(body: JsonDict) -> JsonDict:
    """Return a dry-run plan for EDINET ingest without touching the network."""

    registry_path = str(body.get("registry_path") or _DEFAULT_REGISTRY_PATH)
    output_dir = str(body.get("output_dir") or _DEFAULT_OUTPUT_DIR)
    db_path = str(body.get("db_path") or _DEFAULT_DB_PATH)
    days = _as_int(body.get("days"), 7)
    years = _as_int(body.get("years"), 0)
    max_periods = _as_int(body.get("max_periods"), 0)
    index_after_fetch = _as_bool(body.get("index_after_fetch"), True)

    registry = reject_path_traversal(registry_path)
    output = reject_path_traversal(output_dir)
    db = reject_path_traversal(db_path)
    api_key_configured = bool(os.getenv(API_KEY_ENV_VAR, "").strip())

    registry_error: str | None = None
    targets: list[JsonDict] = []
    try:
        parsed_targets = build_edinet_targets_from_registry(registry)
        targets = [
            {
                "ticker": target.ticker,
                "company": target.company,
                "doc_types": list(target.doc_types),
                "max_periods": target.max_periods,
            }
            for target in parsed_targets
        ]
    except (OSError, ValueError, TypeError) as exc:
        registry_error = f"{type(exc).__name__}: {exc}"

    warnings: list[str] = []
    if not api_key_configured:
        warnings.append("EDINET_API_KEY がバックエンド環境変数に設定されていません。")
    if registry_error:
        warnings.append("EDINET registry を読み取れません。")
    if not targets and not registry_error:
        warnings.append("EDINET registry に取得対象がありません。")
    if days <= 0:
        warnings.append("遡る日数は1以上にしてください。")

    can_start = api_key_configured and not registry_error and bool(targets) and days > 0
    payload: JsonDict = {
        "registry_path": str(registry),
        "output_dir": str(output),
        "db_path": str(db),
        "days": max(1, days),
        "index_after_fetch": index_after_fetch,
    }
    if years > 0:
        payload["years"] = years
    if max_periods > 0:
        payload["max_periods"] = max_periods

    return {
        "status": "ready" if can_start else "needs_setup",
        "api_key_configured": api_key_configured,
        "api_key_env_var": API_KEY_ENV_VAR,
        "registry_path": str(registry),
        "registry_exists": registry.exists(),
        "registry_error": registry_error,
        "target_count": len(targets),
        "sample_targets": targets[:8],
        "output_dir": str(output),
        "financials_csv": str(output / "financials.csv"),
        "db_path": str(db),
        "days": max(1, days),
        "years": years,
        "max_periods": max_periods,
        "index_after_fetch": index_after_fetch,
        "can_start": can_start,
        "warnings": warnings,
        "start_endpoint": "/api/edinet/ingest-async",
        "poll_endpoint": "/api/jobs/status",
        "start_payload": payload,
        "auto_trading": False,
        "call_real_api": False,
    }


def _as_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
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
