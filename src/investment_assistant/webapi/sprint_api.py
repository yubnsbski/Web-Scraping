"""Sprint API handlers — fast output track (出力系).

リクエスト時にネットワーク・LLMを一切使わず、
事前キャッシュ済みスコアから瞬時に応答する。

Endpoints:
  POST /api/sprint/rank     — キャッシュからランキング取得（即時）
  POST /api/sprint/status   — キャッシュ収録状況
  POST /api/flick/update    — 差分収集 + スプリントキャッシュ更新（バックグラウンドOK）
  POST /api/flick/status    — 陳腐化チェック（収集はしない）
  POST /api/flick/append    — 新規ticker追加 + 即時収集
"""

from __future__ import annotations

import logging
from typing import Any

from investment_assistant.data.flick_collector import build_flick_collector
from investment_assistant.data.sprint_cache import SprintCache
from investment_assistant.data.store import DEFAULT_DB_PATH, InvestmentDataStore

_log = logging.getLogger("webapi.sprint")

JsonDict = dict[str, Any]


def _get_db_path(body: JsonDict) -> str:
    return str(body.get("db_path") or DEFAULT_DB_PATH)


def _get_store(body: JsonDict) -> InvestmentDataStore:
    return InvestmentDataStore(_get_db_path(body))


def _get_cache(body: JsonDict) -> SprintCache:
    return SprintCache(_get_store(body))


def _get_tickers(body: JsonDict) -> list[str]:
    raw = body.get("tickers", [])
    if isinstance(raw, str):
        raw = [t.strip() for t in raw.split(",") if t.strip()]
    return [str(t).strip() for t in raw if str(t).strip()]


# ── Sprint（出力系）────────────────────────────────────────────────────────────

def sprint_rank(body: JsonDict) -> JsonDict:
    """キャッシュからスコアランキングを即時返却。ネットワーク不要。

    body:
      tickers: list[str]  (省略時: 全キャッシュ)
      top_n: int          (省略時: 全件)
      db_path: str
    """
    cache = _get_cache(body)
    tickers = _get_tickers(body) or None
    top_n_raw = body.get("top_n")
    top_n = int(top_n_raw) if top_n_raw else None

    ranked = cache.get_ranked(tickers=tickers, top_n=top_n)
    stale = cache.is_stale()

    return {
        "ok": True,
        "source": "sprint_cache",
        "count": len(ranked),
        "cache_stale": stale,
        "hint": "データが古い場合は POST /api/flick/update で再取得してください。" if stale else None,
        "ranked": ranked,
    }


def sprint_status(body: JsonDict) -> JsonDict:
    """スプリントキャッシュの収録状況を返す。"""
    cache = _get_cache(body)
    cov = cache.coverage()
    stale = cache.is_stale(float(body.get("max_age_hours", 26)))
    return {
        "ok": True,
        "cached": cov["cached"],
        "newest": cov["newest"],
        "oldest": cov["oldest"],
        "stale": stale,
        "tickers": cov["tickers"],
    }


# ── Flick（入力系）────────────────────────────────────────────────────────────

def flick_update(body: JsonDict) -> JsonDict:
    """陳腐化したtickerを差分収集 → スプリントキャッシュ更新。

    body:
      watchlist: list[str]    (省略時: DB全件)
      max_age_hours: float    (default 24)
      db_path: str
    """
    collector = build_flick_collector(_get_db_path(body))
    watchlist = _get_tickers(body) or body.get("watchlist") or None
    max_age = float(body.get("max_age_hours", 24))

    result = collector.update_stale(
        watchlist=watchlist,
        max_age_hours=max_age,
        refresh_sprint_cache=True,
    )

    return {"ok": True, **result.to_dict()}


def flick_status(body: JsonDict) -> JsonDict:
    """陳腐化チェックのみ（収集はしない）。更新が必要なtickerリストを返す。

    body:
      watchlist: list[str]    (省略時: DB全件)
      max_age_hours: float    (default 24)
      db_path: str
    """
    collector = build_flick_collector(_get_db_path(body))
    watchlist = _get_tickers(body) or body.get("watchlist") or None
    max_age = float(body.get("max_age_hours", 24))

    status = collector.check_staleness(watchlist=watchlist, max_age_hours=max_age)
    return {"ok": True, **status.to_dict()}


def flick_append(body: JsonDict) -> JsonDict:
    """新規tickerを即時収集してDB登録 + スプリントキャッシュ更新。

    body:
      ticker: str    (必須)
      db_path: str
    """
    ticker = str(body.get("ticker", "")).strip()
    if not ticker:
        return {"error": "ticker は必須です"}

    collector = build_flick_collector(_get_db_path(body))
    result = collector.append_ticker(ticker, refresh_sprint_cache=True)
    return {"ok": result["success"], **result}


def flick_score_all(body: JsonDict) -> JsonDict:
    """DBの全tickerを再スコアリングしてキャッシュ更新（重い処理・初回セットアップ用）。

    body:
      tickers: list[str]   (省略時: DB全件)
      db_path: str
    """
    from investment_assistant.data.dividend_scorer import score_stocks
    from investment_assistant.data.sector_comparator import build_score_inputs

    store = _get_store(body)
    tickers = _get_tickers(body) or store.all_tickers()

    if not tickers:
        return {"error": "DBにデータがありません。先に /api/flick/update を実行してください。"}

    inputs = build_score_inputs(tickers, store)
    if not inputs:
        return {"error": "スコア計算できる銘柄がありません。"}

    ranked = score_stocks(inputs)
    cache = SprintCache(store)
    n = cache.upsert_scores(ranked)

    return {
        "ok": True,
        "scored": n,
        "ranked_preview": [
            {"rank": s.rank, "ticker": s.input.ticker, "name": s.input.name,
             "total_score": s.breakdown.total_score}
            for s in ranked[:10]
        ],
    }
