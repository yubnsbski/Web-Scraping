"""Source registry policy for safe investment data intake.

This module does not crawl the open web.
It converts explicitly approved registry entries into fetch-job sources.
"""

from __future__ import annotations

from pathlib import Path

from investment_assistant.config.loader import load_yaml

ALLOWED_SOURCE_TYPES: frozenset[str] = frozenset(
    {
        "issuer_ir",
        "public_api",
        "manual",
    }
)

BLOCKED_SOURCE_TYPES: frozenset[str] = frozenset(
    {
        "broker_public",
        "broker_login",
        "market_data_realtime",
        "order_api",
    }
)

FETCH_JOB_METHODS: frozenset[str] = frozenset({"html"})


def build_fetch_job_from_registry(path: str | Path) -> dict[str, object]:
    """Build a fetch-job payload from an explicit source registry.

    Only allowed html sources are included in fetch-job output.
    API/manual sources are kept visible as excluded entries because they need
    a dedicated connector or manual import flow.
    """

    registry_path = Path(path)
    config = load_yaml(registry_path)
    raw_sources = config.get("sources")

    if not isinstance(raw_sources, list) or not raw_sources:
        msg = f"source registry must define a non-empty sources list: {registry_path}"
        raise ValueError(msg)

    fetch_sources: list[dict[str, object]] = []
    excluded: list[dict[str, object]] = []

    for index, raw_source in enumerate(raw_sources, start=1):
        if not isinstance(raw_source, dict):
            raise ValueError(f"source #{index} must be a mapping")

        normalized = _normalize_registry_source(raw_source, index=index)
        decision = _source_decision(normalized)

        if decision["include"]:
            fetch_sources.append(_to_fetch_job_source(normalized))
        else:
            excluded.append(
                {
                    "name": normalized["name"],
                    "source_type": normalized["source_type"],
                    "method": normalized["method"],
                    "reason": decision["reason"],
                }
            )

    return {
        "registry_path": str(registry_path),
        "sources_count": len(raw_sources),
        "fetch_job": {"sources": fetch_sources},
        "fetch_sources_count": len(fetch_sources),
        "excluded_count": len(excluded),
        "excluded": excluded,
        "policy": {
            "allowed_source_types": sorted(ALLOWED_SOURCE_TYPES),
            "blocked_source_types": sorted(BLOCKED_SOURCE_TYPES),
            "fetch_job_methods": sorted(FETCH_JOB_METHODS),
            "broker_sources_default_blocked": True,
            "auto_trading": False,
        },
    }


def fetch_job_to_yaml(fetch_job: dict[str, object]) -> str:
    raw_sources = fetch_job.get("sources")
    if not isinstance(raw_sources, list):
        raise ValueError("fetch_job must contain sources list")

    lines = ["sources:"]
    for source in raw_sources:
        if not isinstance(source, dict):
            raise ValueError("fetch_job source must be a mapping")
        items = list(source.items())
        if not items:
            raise ValueError("fetch_job source must not be empty")

        first_key, first_value = items[0]
        lines.append(f"  - {first_key}: {_yaml_scalar(first_value)}")
        for key, value in items[1:]:
            lines.append(f"    {key}: {_yaml_scalar(value)}")

    return "\n".join(lines) + "\n"


def _normalize_registry_source(raw_source: dict[str, object], *, index: int) -> dict[str, object]:
    required = ("name", "source_type", "method")
    missing = [key for key in required if key not in raw_source]
    if missing:
        raise ValueError(f"source #{index} missing required keys: {', '.join(missing)}")

    name = str(raw_source["name"]).strip()
    source_type = str(raw_source["source_type"]).strip()
    method = str(raw_source["method"]).strip()

    if not name:
        raise ValueError(f"source #{index}: name must not be empty")
    if not source_type:
        raise ValueError(f"source #{index}: source_type must not be empty")
    if not method:
        raise ValueError(f"source #{index}: method must not be empty")

    normalized = dict(raw_source)
    normalized["name"] = name
    normalized["source_type"] = source_type
    normalized["method"] = method
    normalized["allowed"] = _bool_or_default(raw_source.get("allowed"), True)
    return normalized


def _source_decision(source: dict[str, object]) -> dict[str, object]:
    source_type = str(source["source_type"])
    method = str(source["method"])
    allowed = bool(source["allowed"])

    if source_type in BLOCKED_SOURCE_TYPES:
        return {
            "include": False,
            "reason": _reason(source, f"blocked source_type: {source_type}"),
        }

    if source_type not in ALLOWED_SOURCE_TYPES:
        return {
            "include": False,
            "reason": _reason(source, f"unknown source_type: {source_type}"),
        }

    if not allowed:
        return {
            "include": False,
            "reason": _reason(source, "allowed=false"),
        }

    if method not in FETCH_JOB_METHODS:
        return {
            "include": False,
            "reason": _reason(source, f"method={method} is not fetch-job compatible"),
        }

    for key in ("url", "output_path"):
        if not str(source.get(key) or "").strip():
            return {
                "include": False,
                "reason": _reason(source, f"missing fetch-job field: {key}"),
            }

    return {"include": True, "reason": "included"}


def _to_fetch_job_source(source: dict[str, object]) -> dict[str, object]:
    fetch_source: dict[str, object] = {
        "name": str(source["name"]),
        "url": str(source["url"]).strip(),
        "output_path": str(source["output_path"]).strip(),
        "extract_text": _bool_or_default(source.get("extract_text"), True),
        "include_metadata": _bool_or_default(source.get("include_metadata"), True),
        "preview_chars": _int_or_default(source.get("preview_chars"), 800),
    }

    query_hint = str(source.get("query_hint") or "").strip()
    if query_hint:
        fetch_source["query_hint"] = query_hint

    return fetch_source


def _reason(source: dict[str, object], fallback: str) -> str:
    reason = str(source.get("reason") or "").strip()
    return reason or fallback


def _bool_or_default(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _int_or_default(value: object, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _yaml_scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    text = str(value).replace('"', '\\"')
    return f'"{text}"'
