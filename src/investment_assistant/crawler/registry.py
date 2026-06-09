"""Select crawl-enabled targets from the approved source registry.

Same safety boundary as the rest of the registry: only ``allowed=true`` entries
with ``source_type: issuer_ir`` and ``method: crawl`` become crawl targets, and
each carries the domain/prefix locks the crawler enforces. Broker / login /
realtime entries can never become a crawl start point.
"""

from __future__ import annotations

from pathlib import Path

from investment_assistant.config.loader import load_yaml

CRAWL_SOURCE_TYPE = "issuer_ir"
CRAWL_METHOD = "crawl"


def build_crawl_targets_from_registry(path: str | Path) -> list[dict[str, object]]:
    """Return the eligible crawl-target source mappings from a registry."""

    config = load_yaml(Path(path))
    raw_sources = config.get("sources")
    if not isinstance(raw_sources, list):
        return []

    targets: list[dict[str, object]] = []
    for raw_source in raw_sources:
        if not isinstance(raw_source, dict):
            continue
        if not _is_crawl_target(raw_source):
            continue
        targets.append(raw_source)
    return targets


def _is_crawl_target(source: dict[str, object]) -> bool:
    if str(source.get("source_type") or "").strip() != CRAWL_SOURCE_TYPE:
        return False
    if str(source.get("method") or "").strip() != CRAWL_METHOD:
        return False
    if not _is_allowed(source.get("allowed")):
        return False
    return bool(str(source.get("url") or "").strip())


def _is_allowed(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return value is None
