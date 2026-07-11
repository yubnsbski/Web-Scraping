"""Deterministic autonomous AI virtual-trading strategy -- Sprint V2.

**Virtual only (Phase 2).** Every order this module decides to place still
flows through :class:`~investment_assistant.papertrade.virtual.VirtualBroker`
under the ``"ai"`` book -- exactly the same validate -> price -> execute ->
record path a human's order takes through the web UI. Nothing here ever
calls a real brokerage API, holds real money, or places a real order. A
**Phase-3 real-broker adapter** that would give this strategy a real
execution target is deliberately **not implemented anywhere** in this
codebase: ``AGENTS.md`` prohibits real orders / auto-trading outright
("自動売買機能は実装しない"), and adding one would first require a
separate, explicit legal review ("実注文や自動売買を追加する場合は、
別途法務レビューを必須にする").

**No LLM.** Every decision this module makes -- which tickers are eligible,
how they are ranked, when a position is sold -- is a fixed, offline,
deterministic computation over already-loaded daily bars. This keeps the
autopilot free (no Gemini budget consumed for a background process that can
run every time the web UI is opened) and reproducible (the same trade log
replays to the same decisions given the same bar data).

**No per-ticker weighting knobs (owner requirement).** The only per-name
signal this module ever looks at is the coarse 33業種 sector via
:func:`~investment_assistant.papertrade.universe.is_defensive`, used solely
for defensive/cyclical bucketing and the ``max_per_sector`` cap. There is no
way to configure this strategy to prefer or avoid an individual ticker --
only a small, named set of :class:`AutopilotPreset` instances (differing by
target position count, sector cap, defensive-only flag, ranking rule, and
stop-loss/take-profit thresholds) and a single sector-level rule
(``max_per_sector``) are exposed. The ranking itself (:func:`_rank`) is a
fixed mechanical rule -- trailing-window momentum or trailing-window
volatility -- not an adjustable per-ticker weight a caller could tune to
favor one stock over another.

Two entry points:

- :func:`run_cycle` makes one decision at a single bar date ``D``: sell any
  held position that no longer qualifies as a candidate or has hit its
  preset's stop-loss/take-profit, then buy down the ranked candidate list
  (respecting ``target_positions`` and ``max_per_sector``) until the target
  position count is reached. All fills happen at ``D``'s close via
  ``VirtualBroker.submit_order(..., trade_date=D)``.
- :func:`catch_up` is the lazy-tick driver the webapi layer calls on every
  ``/api/vtrade/ai/*`` read: it runs one :func:`run_cycle` per bar date
  strictly newer than the persisted ``autopilot:last_run_date`` (capped, to
  bound the work done inside one request), so the AI's book advances simply
  by the web UI being opened, with no background scheduler needed. On its
  very first activation (no ``last_run_date`` yet persisted) it deliberately
  runs *only* the latest known bar date -- the AI starts trading "now",
  never backfilling a multi-year history of hypothetical trades. Both
  ``autopilot:auto`` (on/off) and ``autopilot:preset`` are read from the
  store's existing meta helpers (:meth:`VirtualTradingStore.autopilot_auto`,
  :meth:`VirtualTradingStore.autopilot_preset`, etc.) -- those already exist
  on the store from the P1/V1 sprint, so this module adds no new persistence
  surface of its own.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from investment_assistant.papertrade.account import Side
from investment_assistant.papertrade.mechanics import round_lot
from investment_assistant.papertrade.universe import Bar, SectorInfo, is_defensive
from investment_assistant.papertrade.virtual import (
    BarsMap,
    OrderFill,
    OrderRequest,
    VirtualBroker,
    VirtualTradingStore,
)

Ranking = Literal["momentum", "low_vol"]

_MIN_HISTORY_BARS = 30
_LOOKBACK_BARS = 60
_LIQUIDITY_WINDOW = 20
_MIN_MEDIAN_TURNOVER_YEN = 50_000_000.0
DEFAULT_CATCH_UP_CAP = 40


@dataclass(frozen=True)
class AutopilotPreset:
    """One named, fixed strategy configuration -- no per-ticker parameters.

    ``stop_loss_pct``/``take_profit_pct`` are signed fractions applied to
    ``(price - avg_cost) / avg_cost`` (e.g. ``-0.08`` means "sell once the
    position is down 8% from its average cost").
    """

    name: str
    target_positions: int
    max_per_sector: int
    defensive_only: bool
    ranking: Ranking
    stop_loss_pct: float
    take_profit_pct: float


BALANCED = AutopilotPreset(
    name="balanced",
    target_positions=8,
    max_per_sector=2,
    defensive_only=False,
    ranking="momentum",
    stop_loss_pct=-0.08,
    take_profit_pct=0.15,
)

DEFENSIVE = AutopilotPreset(
    name="defensive",
    target_positions=6,
    max_per_sector=2,
    defensive_only=True,
    ranking="low_vol",
    stop_loss_pct=-0.08,
    take_profit_pct=0.15,
)

MOMENTUM = AutopilotPreset(
    name="momentum",
    target_positions=8,
    max_per_sector=2,
    defensive_only=False,
    ranking="momentum",
    stop_loss_pct=-0.10,
    take_profit_pct=0.20,
)

PRESETS: dict[str, AutopilotPreset] = {
    preset.name: preset for preset in (BALANCED, DEFENSIVE, MOMENTUM)
}


@dataclass(frozen=True)
class AutopilotRejection:
    """A candidate order the broker declined (e.g. insufficient cash, no price)."""

    ticker: str
    side: Side
    reason: str


@dataclass(frozen=True)
class AutopilotCycleSummary:
    """Outcome of one :func:`run_cycle` call."""

    date: str
    buys: tuple[OrderFill, ...]
    sells: tuple[OrderFill, ...]
    rejected: tuple[AutopilotRejection, ...]

    @property
    def buy_count(self) -> int:
        return len(self.buys)

    @property
    def sell_count(self) -> int:
        return len(self.sells)


@dataclass(frozen=True)
class _Candidate:
    ticker: str
    sector: str
    name: str
    close: float
    score: float


def _sorted_history(ticker_bars: Sequence[Bar], as_of: str) -> list[Bar]:
    """``ticker_bars`` with ``date <= as_of``, sorted ascending by date.

    Defensively re-sorts rather than trusting caller ordering, mirroring
    :mod:`investment_assistant.papertrade.virtual`'s own paranoia (see its
    ``_price_history`` helper).
    """

    return sorted((bar for bar in ticker_bars if bar.date <= as_of), key=lambda bar: bar.date)


def _score(history: Sequence[Bar], ranking: Ranking) -> float | None:
    """A single ranking score over the trailing window, or ``None`` if undecidable.

    Momentum: total return over the trailing window (higher is better).
    Low-vol: population stddev of daily close-to-close returns over the
    trailing window (lower is better). Both use whatever history is
    available up to :data:`_LOOKBACK_BARS`, so a candidate that only barely
    clears :data:`_MIN_HISTORY_BARS` still gets a (noisier) score rather than
    being silently dropped from ranking.
    """

    window = history[-_LOOKBACK_BARS:]
    if len(window) < 2:
        return None
    if ranking == "momentum":
        start = window[0].close
        end = window[-1].close
        if start <= 0:
            return None
        return end / start - 1.0

    closes = [bar.close for bar in window]
    returns = [
        curr / prev - 1.0 for prev, curr in zip(closes, closes[1:], strict=False) if prev > 0
    ]
    if len(returns) < 2:
        return None
    return statistics.pstdev(returns)


def _candidates(
    bars: BarsMap,
    sectors: Mapping[str, SectorInfo],
    preset: AutopilotPreset,
    date: str,
) -> list[_Candidate]:
    """Eligible, ranked candidates for a cycle at ``date`` (best first).

    A ticker qualifies when: it has a bar exactly on ``date``; it has at
    least :data:`_MIN_HISTORY_BARS` bars up to and including ``date``; its
    JPX sector is known (and, if ``preset.defensive_only``, defensive); and
    its median close*volume turnover over the trailing
    :data:`_LIQUIDITY_WINDOW` bars is at least :data:`_MIN_MEDIAN_TURNOVER_YEN`.
    """

    out: list[_Candidate] = []
    for ticker, ticker_bars in bars.items():
        history = _sorted_history(ticker_bars, date)
        if not history or history[-1].date != date:
            continue
        if len(history) < _MIN_HISTORY_BARS:
            continue
        info = sectors.get(ticker)
        if info is None or not info.sector33:
            continue
        if preset.defensive_only and not is_defensive(info.sector33):
            continue
        window = history[-_LIQUIDITY_WINDOW:]
        turnovers = [bar.close * bar.volume for bar in window]
        if not turnovers or statistics.median(turnovers) < _MIN_MEDIAN_TURNOVER_YEN:
            continue
        score = _score(history, preset.ranking)
        if score is None:
            continue
        out.append(
            _Candidate(
                ticker=ticker,
                sector=info.sector33,
                name=info.name,
                close=history[-1].close,
                score=score,
            )
        )

    if preset.ranking == "momentum":
        out.sort(key=lambda c: (-c.score, c.ticker))
    else:
        out.sort(key=lambda c: (c.score, c.ticker))
    return out


def _bar_on(ticker_bars: Sequence[Bar] | None, date: str) -> Bar | None:
    if not ticker_bars:
        return None
    for bar in ticker_bars:
        if bar.date == date:
            return bar
    return None


def run_cycle(
    store: VirtualTradingStore,
    bars: BarsMap,
    sectors: Mapping[str, SectorInfo],
    preset: AutopilotPreset,
    date: str,
) -> AutopilotCycleSummary:
    """Run one deterministic decision cycle for the ``"ai"`` book at bar date ``date``.

    Sells (stop-loss / take-profit / no-longer-a-candidate) are decided and
    submitted first, then buys are decided against the post-sell book, so a
    ticker sold this cycle can never immediately be re-bought in the same
    cycle even if it still ranks well.
    """

    broker = VirtualBroker(store.path, bars=bars)
    candidates = _candidates(bars, sectors, preset, date)
    candidate_by_ticker = {c.ticker: c for c in candidates}

    sells: list[OrderFill] = []
    rejected: list[AutopilotRejection] = []
    sold_tickers: set[str] = set()

    held = broker.account_as_of("ai", date).positions
    for ticker in sorted(held):
        position = held[ticker]
        candidate = candidate_by_ticker.get(ticker)
        should_sell = candidate is None
        if not should_sell:
            bar = _bar_on(bars.get(ticker), date)
            if bar is not None and position.avg_cost > 0:
                pct = (bar.close - position.avg_cost) / position.avg_cost
                if pct <= preset.stop_loss_pct or pct >= preset.take_profit_pct:
                    should_sell = True
        if not should_sell:
            continue

        info = sectors.get(ticker)
        request = OrderRequest(
            ticker=ticker,
            side="sell",
            shares=position.shares,
            account="ai",
            name=info.name if info else "",
            trade_date=date,
        )
        report = broker.submit_order(request)
        if report.ok and report.fill is not None:
            sells.append(report.fill)
            sold_tickers.add(ticker)
        else:
            rejected.append(
                AutopilotRejection(ticker=ticker, side="sell", reason=report.reason or "unknown")
            )

    buys: list[OrderFill] = []
    post_sell = broker.account_as_of("ai", date)
    equity = broker.equity_as_of("ai", date)
    slot_notional = equity / preset.target_positions if preset.target_positions else 0.0

    held_tickers = set(post_sell.positions)
    position_count = len(held_tickers)
    sector_counts: dict[str, int] = {}
    for ticker in held_tickers:
        info = sectors.get(ticker)
        if info is not None:
            sector_counts[info.sector33] = sector_counts.get(info.sector33, 0) + 1

    for candidate in candidates:
        if position_count >= preset.target_positions:
            break
        # A ticker sold this cycle (stop-loss/take-profit) must not be
        # immediately re-bought at the same close -- that would round-trip
        # the position for nothing but a tick spread and a prepaid tax bill,
        # and would turn a stop-loss into a no-op under low_vol ranking.
        if candidate.ticker in held_tickers or candidate.ticker in sold_tickers:
            continue
        if sector_counts.get(candidate.sector, 0) >= preset.max_per_sector:
            continue
        if candidate.close <= 0:
            continue
        shares = round_lot(slot_notional / candidate.close)
        if shares <= 0:
            continue

        request = OrderRequest(
            ticker=candidate.ticker,
            side="buy",
            shares=shares,
            account="ai",
            name=candidate.name,
            trade_date=date,
        )
        report = broker.submit_order(request)
        if report.ok and report.fill is not None:
            buys.append(report.fill)
            held_tickers.add(candidate.ticker)
            position_count += 1
            sector_counts[candidate.sector] = sector_counts.get(candidate.sector, 0) + 1
        else:
            rejected.append(
                AutopilotRejection(
                    ticker=candidate.ticker, side="buy", reason=report.reason or "unknown"
                )
            )

    return AutopilotCycleSummary(
        date=date, buys=tuple(buys), sells=tuple(sells), rejected=tuple(rejected)
    )


def _all_bar_dates(bars: BarsMap) -> list[str]:
    dates: set[str] = set()
    for ticker_bars in bars.values():
        for bar in ticker_bars:
            dates.add(bar.date)
    return sorted(dates)


def catch_up(
    store: VirtualTradingStore,
    bars: BarsMap,
    sectors: Mapping[str, SectorInfo],
    *,
    cap: int = DEFAULT_CATCH_UP_CAP,
    force: bool = False,
) -> list[AutopilotCycleSummary]:
    """Run every missed cycle since ``autopilot:last_run_date`` (lazy tick).

    The AI account's autopilot always runs (``autopilot_auto()`` is always
    ``True`` -- there is no off switch); ``force`` only exists so
    ``/api/vtrade/autopilot/run`` reads the same way regardless of future
    changes to that invariant.

    On first-ever activation (no ``last_run_date`` persisted yet), only the
    single latest known bar date is run -- no historical backfill.
    """

    if not force and not store.autopilot_auto():
        return []

    all_dates = _all_bar_dates(bars)
    if not all_dates:
        return []

    last_run = store.autopilot_last_run_date()
    pending = (
        all_dates[-1:] if last_run is None else [d for d in all_dates if d > last_run][:cap]
    )

    if not pending:
        return []

    preset = PRESETS.get(store.autopilot_preset(), BALANCED)
    summaries: list[AutopilotCycleSummary] = []
    for cycle_date in pending:
        summaries.append(run_cycle(store, bars, sectors, preset, cycle_date))
        store.set_autopilot_last_run_date(cycle_date)
    return summaries
