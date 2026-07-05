"""API handlers for the investment-specialized stock analysis pipeline.

Endpoints:
  POST /api/stocks/collect   — fetch and store latest data for given tickers
  POST /api/stocks/score     — score and rank tickers from DB (no LLM)
  POST /api/stocks/analyze   — score + LLM qualitative analysis
  POST /api/stocks/status    — show DB coverage for given tickers

All handlers follow the (body: JsonDict) -> JsonDict signature.
"""

from __future__ import annotations

import logging
from typing import Any

from investment_assistant.data.dividend_scorer import (
    DividendScoreWeights,
    score_stocks,
)
from investment_assistant.data.models import StockQuote
from investment_assistant.data.pipeline import build_pipeline
from investment_assistant.data.sector_comparator import build_score_inputs
from investment_assistant.data.store import DEFAULT_DB_PATH, InvestmentDataStore

_log = logging.getLogger("webapi.stock_analysis")

JsonDict = dict[str, Any]

# ── helpers ──────────────────────────────────────────────────────────────────

def _get_tickers(body: JsonDict) -> list[str]:
    raw = body.get("tickers", [])
    if isinstance(raw, str):
        raw = [t.strip() for t in raw.split(",") if t.strip()]
    return [str(t).strip() for t in raw if str(t).strip()]


def _get_store(body: JsonDict) -> InvestmentDataStore:
    db_path = str(body.get("db_path") or DEFAULT_DB_PATH)
    return InvestmentDataStore(db_path)


def _get_weights(body: JsonDict) -> DividendScoreWeights | None:
    w = body.get("weights")
    if not isinstance(w, dict):
        return None
    try:
        # デフォルト値は DividendScoreWeights のクラスデフォルト（論文根拠）に合わせる
        weights = DividendScoreWeights(
            stability_weight=float(w.get("stability", 0.25)),
            health_weight=float(w.get("health", 0.20)),
            yield_weight=float(w.get("yield", 0.20)),
            momentum_weight=float(w.get("momentum", 0.15)),
            payout_weight=float(w.get("payout", 0.10)),
            streak_weight=float(w.get("streak", 0.07)),
            sector_rank_weight=float(w.get("sector_rank", 0.03)),
        )
        weights.validate()
        return weights
    except (TypeError, ValueError) as exc:
        _log.warning("invalid weights in request: %s", exc)
        return None


# ── handlers ─────────────────────────────────────────────────────────────────

def stocks_collect(body: JsonDict) -> JsonDict:
    """Fetch latest data from Yahoo Finance Japan and store in SQLite.

    body:
      tickers: list[str] | comma-separated str  (required)
      db_path: str  (optional, defaults to DEFAULT_DB_PATH)
    """
    tickers = _get_tickers(body)
    if not tickers:
        return {"error": "tickers は必須です (例: [\"8306\", \"9432\"])"}

    pipeline = build_pipeline(str(body.get("db_path") or DEFAULT_DB_PATH))
    summary = pipeline.collect_tickers(tickers)

    return {
        "ok": True,
        "total": summary.total,
        "succeeded": summary.succeeded,
        "failed": summary.failed,
        "flags_raised": summary.flags_raised,
        "errors": summary.errors,
    }


def stocks_score(body: JsonDict) -> JsonDict:
    """Score and rank stocks already in the DB.

    body:
      tickers: list[str] | comma-sep str  (required; or omit to score all in DB)
      db_path: str  (optional)
      weights: dict with keys yield/payout/streak/health/sector_rank  (optional)
    """
    store = _get_store(body)
    tickers = _get_tickers(body)
    if not tickers:
        tickers = store.all_tickers()
        if not tickers:
            return {"error": "DBにデータがありません。先に /api/stocks/collect を実行してください。"}

    weights = _get_weights(body)
    inputs = build_score_inputs(tickers, store)

    if not inputs:
        return {
            "error": "スコア計算できる銘柄がありません。先に /api/stocks/collect でデータ取得してください。",
            "tickers_requested": tickers,
        }

    ranked = score_stocks(inputs, weights=weights)
    return {
        "ok": True,
        "count": len(ranked),
        "weights_used": (weights or DividendScoreWeights()).yield_weight and _weights_dict(weights),
        "ranked": [s.to_dict() for s in ranked],
    }


def stocks_analyze(body: JsonDict) -> JsonDict:
    """Score stocks + generate LLM qualitative analysis for each.

    body:
      tickers: list[str] | comma-sep str  (required)
      db_path: str  (optional)
      weights: dict  (optional)
      use_llm: bool  (default True)
      perspective: str  (default "高配当・長期保有")
    """
    store = _get_store(body)
    tickers = _get_tickers(body)
    if not tickers:
        return {"error": "tickers は必須です"}

    weights = _get_weights(body)
    inputs = build_score_inputs(tickers, store)

    if not inputs:
        return {
            "error": "スコア計算できる銘柄がありません。先に /api/stocks/collect でデータ取得してください。",
            "tickers_requested": tickers,
        }

    ranked = score_stocks(inputs, weights=weights)
    results = [s.to_dict() for s in ranked]

    use_llm = bool(body.get("use_llm", True))
    perspective = str(body.get("perspective", "高配当・長期保有"))

    if use_llm:
        try:
            llm_comments = _run_llm_analysis(ranked, perspective, store)
            for r in results:
                ticker = r["ticker"]
                r["llm_comment"] = llm_comments.get(ticker, "")
        except Exception as exc:
            _log.warning("LLM analysis failed (non-fatal): %s", exc)
            for r in results:
                r["llm_comment"] = ""
            results[0]["llm_error"] = str(exc) if results else None

    return {
        "ok": True,
        "count": len(results),
        "perspective": perspective,
        "ranked": results,
    }


def stocks_status(body: JsonDict) -> JsonDict:
    """Show DB data coverage for the given tickers.

    body:
      tickers: list[str] | comma-sep str  (optional; omit → show all)
      db_path: str  (optional)
    """
    store = _get_store(body)
    tickers = _get_tickers(body) or store.all_tickers()

    rows = []
    for ticker in tickers:
        quote = store.latest_quote(ticker)  # returns dict or None
        div_hist = store.dividend_history(ticker)
        fin_hist = store.financial_history(ticker)
        flags = store.recent_flags(ticker)
        rows.append({
            "ticker": ticker,
            "name": quote["name"] if quote else None,
            "price": float(quote["price"]) if quote else None,
            "price_date": str(quote.get("price_date", "")) if quote else None,
            "dps_ttm": float(quote["dps_ttm"]) if quote else None,
            "div_history_years": len(div_hist),
            "financial_years": len(fin_hist),
            "quality_flags": len(flags),
            "has_data": quote is not None,
        })

    return {
        "ok": True,
        "count": len(rows),
        "stocks": rows,
    }


# ── LLM integration ──────────────────────────────────────────────────────────

def _run_llm_analysis(
    ranked: list,  # list[DividendScoredStock]
    perspective: str,
    store: InvestmentDataStore,
) -> dict[str, str]:
    """Generate a short Japanese qualitative comment for each scored stock.

    Uses the existing Gemini service (free-tier, budget-guarded).
    Returns {ticker: comment}.
    """
    from investment_assistant.llm.factory import (
        DEFAULT_GEMINI_CONFIG_PATH,
        build_llm_service,
    )
    from investment_assistant.llm.service import LlmService

    try:
        svc: LlmService = build_llm_service(DEFAULT_GEMINI_CONFIG_PATH)
    except Exception as exc:
        raise RuntimeError(f"LLMサービス初期化失敗: {exc}") from exc

    comments: dict[str, str] = {}
    for stock in ranked:
        ticker = stock.input.ticker
        prompt = _build_stock_prompt(stock, perspective, store)
        try:
            resp = svc.generate(prompt=prompt, task_type="rag_answer")
            comments[ticker] = resp.text.strip()
        except Exception as exc:
            _log.warning("LLM skipped for %s: %s", ticker, exc)
            comments[ticker] = ""

    return comments


def _build_stock_prompt(stock, perspective: str, store: InvestmentDataStore) -> str:
    inp = stock.input
    bd = stock.breakdown
    div_hist = store.dividend_history(inp.ticker)
    hist_str = ""
    if div_hist:
        # store returns list[dict]; keys: fiscal_year, dps
        def _fy(d): return d["fiscal_year"] if isinstance(d, dict) else d.fiscal_year
        def _dps(d): return float(d["dps"] if isinstance(d, dict) else d.dps)
        sorted_h = sorted(div_hist, key=_fy)[-5:]
        hist_str = " → ".join(f"FY{_fy(d)}:{_dps(d):.0f}円" for d in sorted_h)

    # Neuro-derived metrics
    cagr_str = f"{inp.dps_cagr_3y:+.1%}" if hasattr(inp, "dps_cagr_3y") else "不明"
    cv_str = f"{inp.dps_cv:.2f}" if hasattr(inp, "dps_cv") else "不明"
    cut_str = "あり⚠" if (hasattr(inp, "has_dividend_cut") and inp.has_dividend_cut) else "なし"

    return f"""あなたは日本株の高配当投資アナリストです。
ニューロファイナンスの観点（報酬/安定性/モメンタム/リスク認知）を踏まえ、
「{perspective}」の視点で以下の銘柄を100〜150字で簡潔に評価してください。

銘柄: {inp.name} ({inp.ticker})
配当利回り: {inp.dividend_yield:.2%}
配当安定性(CV): {cv_str}（低い=安定）
配当モメンタム(3年CAGR): {cagr_str}
減配履歴: {cut_str}
配当性向: {inp.payout_ratio:.1%}
連続増配: {inp.consecutive_raises}年
自己資本比率: {inp.equity_ratio:.1%} / 有利子負債倍率: {inp.debt_equity:.2f}x
ニューロスコア: 総合{bd.total_score:.3f} (ランク #{stock.rank})
配当履歴(直近5年): {hist_str or "データなし"}

評価:"""


def stocks_import(body: JsonDict) -> JsonDict:
    """Pre-fetched データをDBに直接インポート（Chrome経由で取得済みデータの保存用）。

    body:
      stocks: list of {
        ticker: str,       (必須)
        name: str,         (省略時 ticker を使用)
        price: float,      (必須)
        dps: float,        (省略時 0)
        yield_pct: float,  (dpsが0のとき利回り%からback-calculate)
        eps: float,        (省略時 0)
        per: float,        (省略時 0)
        pbr: float,        (省略時 0)
        sector: str,       (省略時 "")
        market_cap_m: float, (省略時 0)
      }
      score_after: bool  (default True — インポート後にスプリントキャッシュを更新)
      db_path: str
    """
    from datetime import date, datetime

    raw_stocks = body.get("stocks", [])
    if not isinstance(raw_stocks, list) or not raw_stocks:
        return {"error": "stocks は必須です (list of {ticker, price, dps, ...})"}

    store = _get_store(body)
    saved, skipped = [], []

    for item in raw_stocks:
        if not isinstance(item, dict):
            skipped.append(str(item))
            continue

        ticker = str(item.get("ticker", "")).strip()
        price = float(item.get("price", 0) or 0)
        if not ticker or price <= 0:
            skipped.append(ticker or str(item))
            continue

        dps = float(item.get("dps", 0) or 0)
        yield_pct = float(item.get("yield_pct", 0) or 0)
        if dps <= 0 and yield_pct > 0:
            dps = round(price * yield_pct / 100, 1)

        name = str(item.get("name", "") or ticker)
        q = StockQuote(
            ticker=ticker,
            name=name,
            price=price,
            price_date=date.today(),
            dps_ttm=dps,
            eps_ttm=float(item.get("eps", 0) or 0),
            per=float(item.get("per", 0) or 0),
            pbr=float(item.get("pbr", 0) or 0),
            market_cap_m=float(item.get("market_cap_m", 0) or 0),
            sector=str(item.get("sector", "") or ""),
            source="manual_import",
            fetched_at=datetime.utcnow(),
        )
        try:
            store.upsert_quote(q)
            saved.append(ticker)
        except Exception as exc:
            _log.warning("import failed for %s: %s", ticker, exc)
            skipped.append(ticker)

    # スプリントキャッシュを再構築
    sprint_updated = 0
    if body.get("score_after", True) and saved:
        try:
            from investment_assistant.data.sprint_cache import SprintCache
            inputs = build_score_inputs(saved, store)
            if inputs:
                ranked = score_stocks(inputs)
                cache = SprintCache(store)
                sprint_updated = cache.upsert_scores(ranked)
        except Exception as exc:
            _log.warning("sprint cache update after import failed: %s", exc)

    return {
        "ok": True,
        "saved": saved,
        "skipped": skipped,
        "sprint_cache_updated": sprint_updated,
    }


def _weights_dict(weights: DividendScoreWeights | None) -> dict:
    w = weights or DividendScoreWeights()
    return {
        "yield":       w.yield_weight,
        "stability":   w.stability_weight,
        "momentum":    w.momentum_weight,
        "health":      w.health_weight,
        "payout":      w.payout_weight,
        "streak":      w.streak_weight,
        "sector_rank": w.sector_rank_weight,
    }
