"""Select EDINET targets from the approved source registry.

Reuses the same safety boundary as the HTML path: only ``allowed=true`` entries
are eligible, and only ``source_type: public_api`` entries that name the EDINET
provider are turned into EDINET targets. Broker / login / realtime entries can
never reach this connector.
"""

from __future__ import annotations

from pathlib import Path

from investment_assistant.config.loader import load_yaml
from investment_assistant.edinet.models import (
    FINANCIAL_DOC_TYPES,
    securities_code,
)

EDINET_PROVIDERS: frozenset[str] = frozenset({"edinet", "edinet_api", "edinet-fsa"})
EDINET_SOURCE_TYPE = "public_api"


class EdinetTarget:
    """A resolved EDINET acquisition target derived from a registry entry."""

    def __init__(
        self,
        *,
        name: str,
        ticker: str,
        company: str | None,
        doc_types: tuple[str, ...],
        max_periods: int = 1,
    ) -> None:
        self.name = name
        self.ticker = ticker
        self.company = company
        self.doc_types = doc_types
        self.max_periods = max_periods
        self.sec_code = securities_code(ticker)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, EdinetTarget):
            return NotImplemented
        return (
            self.name == other.name
            and self.ticker == other.ticker
            and self.company == other.company
            and self.doc_types == other.doc_types
            and self.max_periods == other.max_periods
        )

    def __repr__(self) -> str:
        return (
            f"EdinetTarget(name={self.name!r}, ticker={self.ticker!r}, "
            f"company={self.company!r}, doc_types={self.doc_types!r}, "
            f"max_periods={self.max_periods!r})"
        )


def build_edinet_targets_from_registry(path: str | Path) -> list[EdinetTarget]:
    """Read a source registry and return the eligible EDINET targets."""

    config = load_yaml(Path(path))
    raw_sources = config.get("sources")
    if not isinstance(raw_sources, list):
        return []

    targets: list[EdinetTarget] = []
    for raw_source in raw_sources:
        if not isinstance(raw_source, dict):
            continue
        target = _maybe_target(raw_source)
        if target is not None:
            targets.append(target)
    return targets


def _maybe_target(source: dict[str, object]) -> EdinetTarget | None:
    if str(source.get("source_type") or "").strip() != EDINET_SOURCE_TYPE:
        return None
    if not _is_allowed(source.get("allowed")):
        return None
    provider = str(source.get("provider") or "").strip().lower()
    if provider and provider not in EDINET_PROVIDERS:
        return None

    ticker = str(source.get("ticker") or "").strip()
    if not ticker:
        return None

    raw_doc_types = source.get("doc_types")
    if raw_doc_types is None:
        raw_doc_types = source.get("doc_type_codes")

    doc_types = _doc_types_from_value(raw_doc_types)
    if not doc_types:
        doc_types = tuple(sorted(FINANCIAL_DOC_TYPES))

    company = str(source.get("company") or "").strip() or None
    max_periods = _positive_int(source.get("max_periods"), default=1)
    return EdinetTarget(
        name=str(source.get("name") or ticker).strip(),
        ticker=ticker,
        company=company,
        doc_types=doc_types,
        max_periods=max_periods,
    )


def _doc_types_from_value(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(
            str(item).strip().strip('"').strip("'")
            for item in value
            if str(item).strip().strip('"').strip("'")
        )

    if isinstance(value, str):
        cleaned = (
            value.strip()
            .removeprefix("[")
            .removesuffix("]")
            .replace(",", " ")
        )
        return tuple(
            part.strip().strip('"').strip("'")
            for part in cleaned.split()
            if part.strip().strip('"').strip("'")
        )

    return ()


def _positive_int(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str):
        try:
            parsed = int(value.strip())
        except ValueError:
            return default
        return parsed if parsed > 0 else default
    return default


def _is_allowed(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    # Default-allow only when the key is absent; an explicit non-bool is rejected.
    return value is None
