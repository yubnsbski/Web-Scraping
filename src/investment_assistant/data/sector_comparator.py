"""Build DividendScoreInput objects from the SQLite store for sector-aware ranking.

Usage:
    from investment_assistant.data.sector_comparator import build_score_inputs
    from investment_assistant.data.store import InvestmentDataStore

    store = InvestmentDataStore()
    inputs = build_score_inputs(["8306", "8316", "8411"], store)
"""

from __future__ import annotations

import logging

from investment_assistant.data.consecutive_tracker import consecutive_raises
from investment_assistant.data.dividend_scorer import DividendScoreInput
from investment_assistant.data.store import InvestmentDataStore

_log = logging.getLogger("data.sector_comparator")


def build_score_inputs(
    tickers: list[str],
    store: InvestmentDataStore,
    *,
    default_equity_ratio: float = 0.30,
    default_debt_equity: float = 1.0,
) -> list[DividendScoreInput]:
    """Build DividendScoreInput for each ticker from the store.

    Missing financial data falls back to conservative defaults
    (equity_ratio=30%, debt_equity=1.0x) so scoring still works.
    The sector_yield_rank placeholder is 0.5 — overridden by score_stocks().
    """
    inputs: list[DividendScoreInput] = []
    for ticker in tickers:
        try:
            inp = _build_one(ticker, store, default_equity_ratio, default_debt_equity)
            if inp is not None:
                inputs.append(inp)
        except Exception as exc:
            _log.warning("build_score_inputs: skipping %s — %s", ticker, exc)
    return inputs


def _build_one(
    ticker: str,
    store: InvestmentDataStore,
    default_equity_ratio: float,
    default_debt_equity: float,
) -> DividendScoreInput | None:
    quote = store.latest_quote(ticker)
    if quote is None:
        _log.debug("no quote for %s — skipping", ticker)
        return None

    div_hist = store.dividend_history(ticker)
    fin_hist = store.financial_history(ticker)

    # Store returns dicts; access fields via key lookup
    price = float(quote["price"])
    dps = float(quote["dps_ttm"])
    eps = float(quote.get("eps_ttm", 0) or 0)
    name = str(quote.get("name", ticker))

    # Payout ratio: DPS/EPS when EPS positive
    payout_ratio = (dps / eps) if eps > 0 else 0.50

    # Financial health: use most recent financial_summary dict if available
    equity_ratio = default_equity_ratio
    debt_equity = default_debt_equity
    if fin_hist:
        latest_fin = sorted(fin_hist, key=lambda f: f["fiscal_year"], reverse=True)[0]
        eq = latest_fin.get("equity_ratio")
        if eq is not None and float(eq) > 0:
            equity_ratio = float(eq)
        eq_m = latest_fin.get("equity_m") or 0
        debt_m = latest_fin.get("interest_bearing_debt_m") or 0
        if float(eq_m) > 0:
            debt_equity = float(debt_m) / float(eq_m)

    streak = consecutive_raises(div_hist)

    # Build DPS history list (oldest→newest) for neurofinance stability/momentum scoring
    dps_history: list[float] = []
    if div_hist:
        def _fy(d: dict) -> int:
            return int(d["fiscal_year"]) if isinstance(d, dict) else int(d.fiscal_year)
        def _dps_val(d: dict) -> float:
            return float(d["dps"]) if isinstance(d, dict) else float(d.dps)
        sorted_div = sorted(div_hist, key=_fy)
        dps_history = [_dps_val(d) for d in sorted_div if _dps_val(d) >= 0]

    return DividendScoreInput(
        ticker=ticker,
        name=name,
        price=price,
        dps=dps,
        payout_ratio=payout_ratio,
        equity_ratio=equity_ratio,
        debt_equity=debt_equity,
        consecutive_raises=streak,
        sector_yield_rank=0.5,  # placeholder; overridden by score_stocks()
        dps_history=dps_history,  # [NEURO] for stability/momentum scoring
    )


def get_sector_peers(ticker: str, store: InvestmentDataStore) -> list[str]:
    """Return tickers in the same sector as the given ticker (excludes self)."""
    quote = store.latest_quote(ticker)
    if quote is None or not quote.get("sector"):
        return []
    peers = store.sector_peers(quote["sector"])
    # sector_peers returns list[dict]; extract tickers
    peer_tickers = [p["ticker"] if isinstance(p, dict) else p for p in peers]
    return [t for t in peer_tickers if t != ticker]
