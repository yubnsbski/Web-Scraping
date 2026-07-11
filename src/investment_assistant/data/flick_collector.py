"""Flick Collector — incremental, stale-aware data ingestion (入力系).

Philosophy:
  データ取得はリクエスト時ではなくバックグラウンドで常時実行。
  「陳腐化したものだけ更新」することでネットワークI/Oをリクエストパスから切り離す。

Flow:
  FlickCollector.update_stale()
    → DBで最終取得日時確認
    → 陳腐化ticker（max_age_hours超過）のみYahoo JPから差分取得
    → バリデーション → DB保存
    → スコアを即時再計算 → SprintCache更新

Scheduling:
  - API: POST /api/flick/update   (手動トリガー)
  - API: POST /api/flick/status   (陳腐化状況確認)
  - Scheduled: 毎日15:30 (東証終値後) に自動実行 (scheduleスキルで登録)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Sequence

from investment_assistant.data.pipeline import DataPipeline, build_pipeline
from investment_assistant.data.store import DEFAULT_DB_PATH, InvestmentDataStore

_log = logging.getLogger("data.flick")


@dataclass
class FlickStatus:
    """陳腐化チェック結果。"""
    total_in_db: int = 0
    stale: list[str] = field(default_factory=list)
    fresh: list[str] = field(default_factory=list)
    never_fetched: list[str] = field(default_factory=list)

    @property
    def stale_count(self) -> int:
        return len(self.stale)

    @property
    def needs_update(self) -> bool:
        return bool(self.stale or self.never_fetched)

    def to_dict(self) -> dict:
        return {
            "total_in_db": self.total_in_db,
            "stale_count": self.stale_count,
            "fresh_count": len(self.fresh),
            "never_fetched_count": len(self.never_fetched),
            "stale": self.stale,
            "never_fetched": self.never_fetched,
            "needs_update": self.needs_update,
        }


@dataclass
class FlickResult:
    """フリック更新の実行結果。"""
    tickers_checked: list[str] = field(default_factory=list)
    tickers_updated: list[str] = field(default_factory=list)
    tickers_skipped: list[str] = field(default_factory=list)
    tickers_failed: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    sprint_cache_refreshed: bool = False
    elapsed_s: float = 0.0

    def to_dict(self) -> dict:
        return {
            "tickers_checked": len(self.tickers_checked),
            "tickers_updated": len(self.tickers_updated),
            "tickers_skipped": len(self.tickers_skipped),
            "tickers_failed": len(self.tickers_failed),
            "errors": self.errors[:5],  # cap to avoid huge response
            "sprint_cache_refreshed": self.sprint_cache_refreshed,
            "elapsed_s": round(self.elapsed_s, 2),
        }


class FlickCollector:
    """差分収集エンジン — 陳腐化したデータのみYahoo JPから再取得する。"""

    def __init__(
        self,
        store: InvestmentDataStore | None = None,
        pipeline: DataPipeline | None = None,
        db_path: str | None = None,
    ) -> None:
        _db = db_path or str(DEFAULT_DB_PATH)
        self._store = store or InvestmentDataStore(_db)
        self._pipeline = pipeline or build_pipeline(_db)

    # ── public API ────────────────────────────────────────────────────────────

    def check_staleness(
        self,
        watchlist: Sequence[str] | None = None,
        max_age_hours: float = 24.0,
    ) -> FlickStatus:
        """DBまたはwatchlistのtickerを陳腐化チェック。更新は行わない。"""
        tickers = list(watchlist) if watchlist else self._store.all_tickers()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        status = FlickStatus(total_in_db=len(self._store.all_tickers()))

        for ticker in tickers:
            quote = self._store.latest_quote(ticker)
            if quote is None:
                status.never_fetched.append(ticker)
            else:
                fetched_at_raw = quote.get("fetched_at", "")
                fetched_dt = _parse_dt(fetched_at_raw)
                if fetched_dt is None or fetched_dt < cutoff:
                    status.stale.append(ticker)
                else:
                    status.fresh.append(ticker)

        return status

    def update_stale(
        self,
        watchlist: Sequence[str] | None = None,
        max_age_hours: float = 24.0,
        refresh_sprint_cache: bool = True,
    ) -> FlickResult:
        """陳腐化したtickerのみ差分更新。フリッシュは完全スキップ。"""
        import time
        t0 = time.monotonic()

        status = self.check_staleness(watchlist, max_age_hours)
        to_update = status.stale + status.never_fetched

        result = FlickResult(
            tickers_checked=list(status.stale) + list(status.fresh) + list(status.never_fetched),
            tickers_skipped=list(status.fresh),
        )

        if to_update:
            summary = self._pipeline.collect_tickers(to_update)
            result.tickers_updated = [t for t in to_update if t not in summary.errors]
            result.tickers_failed = [e.split(":")[0].strip() for e in summary.errors]
            result.errors = summary.errors
            _log.info(
                "flick: updated %d/%d tickers (skipped %d fresh)",
                summary.succeeded, len(to_update), len(status.fresh),
            )
        else:
            _log.info("flick: all %d tickers are fresh, nothing to update", len(status.fresh))

        if refresh_sprint_cache and result.tickers_updated:
            try:
                _refresh_sprint_cache(self._store, result.tickers_updated)
                result.sprint_cache_refreshed = True
            except Exception as exc:
                _log.warning("sprint cache refresh failed: %s", exc)

        result.elapsed_s = time.monotonic() - t0
        return result

    def append_ticker(
        self,
        ticker: str,
        refresh_sprint_cache: bool = True,
    ) -> dict:
        """新規tickerを即時取得してDB登録。スコアキャッシュも即更新。"""
        cr = self._pipeline.collect_single(ticker)
        if cr.success and refresh_sprint_cache:
            try:
                _refresh_sprint_cache(self._store, [ticker])
            except Exception as exc:
                _log.warning("sprint cache refresh after append failed: %s", exc)
        return {
            "ticker": ticker,
            "success": cr.success,
            "error": cr.error,
            "flags": len(cr.flags),
            "sprint_cache_refreshed": cr.success and refresh_sprint_cache,
        }


# ── helpers ───────────────────────────────────────────────────────────────────

def _parse_dt(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        # SQLite stores UTC without timezone; attach UTC
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _refresh_sprint_cache(store: InvestmentDataStore, tickers: list[str]) -> None:
    """更新されたtickerのスコアをスプリントキャッシュに書き込む。"""
    from investment_assistant.data.sector_comparator import build_score_inputs
    from investment_assistant.data.dividend_scorer import score_stocks
    from investment_assistant.data.sprint_cache import SprintCache

    cache = SprintCache(store)
    inputs = build_score_inputs(tickers, store)
    if not inputs:
        return
    ranked = score_stocks(inputs)
    cache.upsert_scores(ranked)
    _log.info("sprint cache updated for %d tickers", len(ranked))


def build_flick_collector(db_path: str | None = None) -> FlickCollector:
    """Convenience factory for API handlers."""
    return FlickCollector(db_path=db_path)
