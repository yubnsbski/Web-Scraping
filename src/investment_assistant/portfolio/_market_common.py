"""Shared helpers for the market-data fetchers (prices / OHLCV / intraday).

Keeps the network boundary and CSV rendering in one place so the per-source
modules differ only in their URLs and parsers.
"""

from __future__ import annotations

from collections.abc import Iterable

from investment_assistant.ingestion.fetcher import SafeFetcher

__all__ = ["default_fetch", "render_csv"]


def default_fetch(url: str) -> str:
    """Fetch a URL's body via the robots-respecting, rate-limited SafeFetcher."""

    return SafeFetcher().fetch_document(url).html


def render_csv(fields: tuple[str, ...], rows: Iterable[dict[str, object]]) -> str:
    """Render row dicts as CSV text with a fixed header; None renders as empty."""

    def cell(value: object) -> str:
        return "" if value is None else str(value)

    lines = [",".join(fields)]
    lines.extend(",".join(cell(row.get(field)) for field in fields) for row in rows)
    return "\n".join(lines) + "\n"
