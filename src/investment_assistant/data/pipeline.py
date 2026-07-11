"""High-quality investment data pipeline.

Entry point for collecting, validating, and storing investment data.
Designed to run on-demand or on a schedule.

Usage:
    from investment_assistant.data.pipeline import DataPipeline
    from investment_assistant.data.store import InvestmentDataStore

    store = InvestmentDataStore()
    pipeline = DataPipeline(store)
    results = pipeline.collect_tickers(["8306", "2914", "9432"])
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Sequence

from investment_assistant.data.collectors.yahoo_jp import fetch_quote
from investment_assistant.data.models import CollectionResult, DataQualityFlag
from investment_assistant.data.store import InvestmentDataStore
from investment_assistant.data.validator import validate_quote

_log = logging.getLogger("data.pipeline")


@dataclass
class PipelineConfig:
    max_errors: int = 5           # stop after this many consecutive errors
    save_flags: bool = True       # persist quality flags to DB


@dataclass
class PipelineSummary:
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    flags_raised: int = 0
    errors: list[str] = field(default_factory=list)


class DataPipeline:
    """Orchestrates data collection, validation, and storage for a ticker list."""

    def __init__(
        self,
        store: InvestmentDataStore,
        config: PipelineConfig | None = None,
    ) -> None:
        self._store = store
        self._cfg = config or PipelineConfig()

    def collect_tickers(self, tickers: Sequence[str]) -> PipelineSummary:
        summary = PipelineSummary(total=len(tickers))
        consecutive_errors = 0

        for ticker in tickers:
            if consecutive_errors >= self._cfg.max_errors:
                _log.warning("too many consecutive errors; aborting pipeline run")
                break
            result = self._collect_one(ticker)
            if result.success:
                consecutive_errors = 0
                summary.succeeded += 1
                summary.flags_raised += len(result.flags)
            else:
                consecutive_errors += 1
                summary.failed += 1
                if result.error:
                    summary.errors.append(f"{ticker}: {result.error}")
                    _log.warning("collect_one failed: %s – %s", ticker, result.error)

        return summary

    def collect_single(self, ticker: str) -> CollectionResult:
        return self._collect_one(ticker)

    # ── internals ────────────────────────────────────────────────────────────

    def _collect_one(self, ticker: str) -> CollectionResult:
        try:
            quote = fetch_quote(ticker)
        except Exception as exc:
            return CollectionResult(ticker=ticker, success=False, error=str(exc))

        if quote is None:
            return CollectionResult(
                ticker=ticker, success=False,
                error="fetch returned no data (price parse failed)",
            )

        flags: list[DataQualityFlag] = validate_quote(quote)

        try:
            self._store.upsert_quote(quote)
        except Exception as exc:
            return CollectionResult(ticker=ticker, success=False, error=f"DB write error: {exc}")

        if flags and self._cfg.save_flags:
            try:
                self._store.save_flags(flags)
            except Exception as exc:
                _log.warning("failed to save flags for %s: %s", ticker, exc)

        return CollectionResult(
            ticker=ticker,
            success=True,
            quote=quote,
            flags=flags,
        )


def build_pipeline(db_path: str | None = None) -> DataPipeline:
    """Convenience factory used by API endpoints."""
    from investment_assistant.data.store import DEFAULT_DB_PATH
    store = InvestmentDataStore(db_path or DEFAULT_DB_PATH)
    return DataPipeline(store)
