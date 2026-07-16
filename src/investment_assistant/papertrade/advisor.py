"""Trade advisor context: the bridge between the virtual book and the AI advisor.

仮想取引 × AIアドバイザーの合わせ技 (Sprint V3). This module computes a
**deterministic, offline** advice context from one virtual account's book and
the loaded daily bars, in two parts:

1. **Position signals** (:class:`PositionSignal`): per held position, the
   mechanical facts an advisor needs to discuss 売り時 and 注文方法 — price vs
   20-day moving average, trailing momentum/volatility, and the active
   preset's stop-loss / take-profit price lines rounded to a valid 呼値 tick
   (so a 指値/逆指値 level quoted in the advice is actually placeable).
2. **Timing review** (:class:`TimingStats`): the feedback-loop half. Every
   past fill is scored against the price ``TIMING_HORIZON_BARS`` trading days
   *after* it — a buy was well-timed if the price went on to rise, a sell was
   well-timed if the price went on to fall. Aggregated win rates and average
   forward moves ("売った後に平均+2.1%上がっている = 早売り傾向") are fed
   back into the advice prompt so the AI's guidance reflects the account's
   *measured* virtual results, not generic textbook rules.

The LLM never decides anything here. This module only *describes* the book;
the guarded LLM (or the deterministic local template,
:func:`render_local_advice`) turns the description into Japanese guidance.
Advice is 情報提供 only — never 断定的な売買推奨 (AGENTS.md), and every
payload built from it carries ``PAPERTRADE_DISCLAIMER``. No per-ticker
weighting knob is introduced: the only strategy inputs remain the named
autopilot presets, and the advice discusses positions the book already holds.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from investment_assistant.papertrade.autopilot import PRESETS, AutopilotPreset
from investment_assistant.papertrade.mechanics import round_to_tick
from investment_assistant.papertrade.universe import SectorInfo
from investment_assistant.papertrade.virtual import (
    AccountId,
    BarsMap,
    TradeRecord,
    build_portfolio,
)

TIMING_HORIZON_BARS = 5
_MA_WINDOW = 20
_VOL_WINDOW = 20
_MOMENTUM_WINDOW = 60


@dataclass(frozen=True)
class PositionSignal:
    """Deterministic per-position facts for one held ticker."""

    ticker: str
    name: str
    sector: str
    shares: int
    avg_cost: float
    price: float | None
    unrealized_pnl_pct: float | None
    ma20_gap_pct: float | None
    momentum_60d_pct: float | None
    volatility_20d_pct: float | None
    stop_loss_price: float
    take_profit_price: float


@dataclass(frozen=True)
class TimingStats:
    """How well this account's past fills were timed, measured after the fact.

    A buy counts as well-timed when the close ``TIMING_HORIZON_BARS`` trading
    days later is above the fill price; a sell counts as well-timed when that
    later close is below the fill price (the position would have lost value if
    kept). Fills too recent to have a full horizon of later bars are skipped,
    not guessed.
    """

    horizon_bars: int
    buys_evaluated: int
    buy_timing_win_rate_pct: float | None
    avg_move_after_buy_pct: float | None
    sells_evaluated: int
    sell_timing_win_rate_pct: float | None
    avg_move_after_sell_pct: float | None


@dataclass(frozen=True)
class AdviceContext:
    """Everything the advice prompt (or local template) is built from."""

    account: AccountId
    as_of: str | None
    preset: AutopilotPreset
    cash: float
    equity: float
    cash_ratio_pct: float
    total_return_pct: float
    trade_count: int
    positions: tuple[PositionSignal, ...]
    timing: TimingStats


# --- signals ---------------------------------------------------------------


def _sorted_closes(bars: BarsMap, ticker: str) -> list[tuple[str, float]]:
    ticker_bars = bars.get(ticker)
    if not ticker_bars:
        return []
    return sorted(((bar.date, bar.close) for bar in ticker_bars), key=lambda item: item[0])


def _ma_gap_pct(closes: Sequence[float]) -> float | None:
    if len(closes) < _MA_WINDOW:
        return None
    window = closes[-_MA_WINDOW:]
    ma = sum(window) / len(window)
    if ma <= 0:
        return None
    return (closes[-1] / ma - 1.0) * 100.0


def _momentum_pct(closes: Sequence[float]) -> float | None:
    window = closes[-_MOMENTUM_WINDOW:]
    if len(window) < 2 or window[0] <= 0:
        return None
    return (window[-1] / window[0] - 1.0) * 100.0


def _volatility_pct(closes: Sequence[float]) -> float | None:
    window = closes[-_VOL_WINDOW:]
    returns = [
        curr / prev - 1.0 for prev, curr in zip(window, window[1:], strict=False) if prev > 0
    ]
    if len(returns) < 2:
        return None
    return statistics.pstdev(returns) * 100.0


def build_position_signals(
    bars: BarsMap,
    sectors: Mapping[str, SectorInfo],
    preset: AutopilotPreset,
    *,
    ticker: str,
    name: str,
    shares: int,
    avg_cost: float,
    price: float | None,
    unrealized_pnl_pct: float | None,
) -> PositionSignal:
    closes = [close for _, close in _sorted_closes(bars, ticker)]
    info = sectors.get(ticker)
    return PositionSignal(
        ticker=ticker,
        name=name or (info.name if info else ""),
        sector=info.sector33 if info else "",
        shares=shares,
        avg_cost=avg_cost,
        price=price,
        unrealized_pnl_pct=unrealized_pnl_pct,
        ma20_gap_pct=_ma_gap_pct(closes),
        momentum_60d_pct=_momentum_pct(closes),
        volatility_20d_pct=_volatility_pct(closes),
        # Sell-side lines: both are prices at which the *held* position would
        # be closed, so both round down to a placeable sell tick.
        stop_loss_price=round_to_tick(avg_cost * (1.0 + preset.stop_loss_pct), side="sell"),
        take_profit_price=round_to_tick(avg_cost * (1.0 + preset.take_profit_pct), side="sell"),
    )


# --- timing review (the feedback loop) --------------------------------------


def _close_after(
    history: Sequence[tuple[str, float]], trade_date: str, horizon: int
) -> float | None:
    """The close ``horizon`` trading bars after ``trade_date``, or ``None``.

    ``None`` (not enough later bars yet) means the fill is too recent to
    judge — it is excluded from the stats rather than scored optimistically.
    """

    later = [close for bar_date, close in history if bar_date > trade_date]
    if len(later) < horizon:
        return None
    return later[horizon - 1]


def build_timing_stats(
    trades: Sequence[TradeRecord],
    bars: BarsMap,
    *,
    horizon: int = TIMING_HORIZON_BARS,
) -> TimingStats:
    buy_moves: list[float] = []
    sell_moves: list[float] = []
    history_cache: dict[str, list[tuple[str, float]]] = {}
    for trade in trades:
        if trade.price <= 0:
            continue
        history = history_cache.setdefault(trade.ticker, _sorted_closes(bars, trade.ticker))
        later_close = _close_after(history, trade.trade_date, horizon)
        if later_close is None:
            continue
        move_pct = (later_close / trade.price - 1.0) * 100.0
        if trade.side == "buy":
            buy_moves.append(move_pct)
        else:
            sell_moves.append(move_pct)

    def _win_rate(moves: Sequence[float], *, wins_when_positive: bool) -> float | None:
        if not moves:
            return None
        wins = sum(1 for m in moves if (m > 0) == wins_when_positive)
        return wins / len(moves) * 100.0

    def _avg(moves: Sequence[float]) -> float | None:
        return sum(moves) / len(moves) if moves else None

    return TimingStats(
        horizon_bars=horizon,
        buys_evaluated=len(buy_moves),
        buy_timing_win_rate_pct=_win_rate(buy_moves, wins_when_positive=True),
        avg_move_after_buy_pct=_avg(buy_moves),
        sells_evaluated=len(sell_moves),
        sell_timing_win_rate_pct=_win_rate(sell_moves, wins_when_positive=False),
        avg_move_after_sell_pct=_avg(sell_moves),
    )


# --- context ---------------------------------------------------------------


def build_advice_context(
    trades: Sequence[TradeRecord],
    bars: BarsMap,
    sectors: Mapping[str, SectorInfo],
    *,
    store_path: str | Path,
    account: AccountId,
    preset_name: str,
) -> AdviceContext:
    """Assemble the full deterministic advice context for one account."""

    preset = PRESETS.get(preset_name, PRESETS["balanced"])
    snapshot = build_portfolio(store_path, bars=bars, account=account)
    positions = tuple(
        build_position_signals(
            bars,
            sectors,
            preset,
            ticker=position.ticker,
            name="",
            shares=position.shares,
            avg_cost=position.avg_cost,
            price=position.price,
            unrealized_pnl_pct=position.unrealized_pnl_pct,
        )
        for position in snapshot.positions
    )
    cash_ratio = (snapshot.cash / snapshot.equity * 100.0) if snapshot.equity else 100.0
    return AdviceContext(
        account=account,
        as_of=snapshot.as_of,
        preset=preset,
        cash=snapshot.cash,
        equity=snapshot.equity,
        cash_ratio_pct=cash_ratio,
        total_return_pct=snapshot.total_return_pct,
        trade_count=snapshot.trade_count,
        positions=positions,
        timing=build_timing_stats(trades, bars),
    )


# --- prompt / local rendering ------------------------------------------------


def _fmt_pct(value: float | None) -> str:
    return f"{value:+.2f}%" if value is not None else "不明"


def _fmt_rate(value: float | None) -> str:
    return f"{value:.0f}%" if value is not None else "評価対象なし"


def _fmt_yen(value: float | None) -> str:
    return f"{value:,.0f}円" if value is not None else "不明"


def _position_lines(ctx: AdviceContext) -> list[str]:
    lines: list[str] = []
    for pos in ctx.positions:
        lines.append(
            f"- {pos.ticker} {pos.name}（{pos.sector}）: {pos.shares}株 "
            f"取得単価{_fmt_yen(pos.avg_cost)} 現在値{_fmt_yen(pos.price)} "
            f"損益率{_fmt_pct(pos.unrealized_pnl_pct)} "
            f"20日線乖離{_fmt_pct(pos.ma20_gap_pct)} "
            f"60日騰落{_fmt_pct(pos.momentum_60d_pct)} "
            f"日次ボラ{_fmt_pct(pos.volatility_20d_pct)} "
            f"損切りライン{_fmt_yen(pos.stop_loss_price)} "
            f"利確ライン{_fmt_yen(pos.take_profit_price)}"
        )
    return lines


def _timing_lines(timing: TimingStats) -> list[str]:
    return [
        f"- 買いタイミング勝率（{timing.horizon_bars}営業日後に上昇していた割合）: "
        f"{_fmt_rate(timing.buy_timing_win_rate_pct)}（評価{timing.buys_evaluated}件、"
        f"買い後平均騰落 {_fmt_pct(timing.avg_move_after_buy_pct)}）",
        f"- 売りタイミング勝率（{timing.horizon_bars}営業日後に下落していた割合）: "
        f"{_fmt_rate(timing.sell_timing_win_rate_pct)}（評価{timing.sells_evaluated}件、"
        f"売り後平均騰落 {_fmt_pct(timing.avg_move_after_sell_pct)}）",
    ]


def build_advice_prompt(ctx: AdviceContext) -> str:
    """The Japanese prompt sent to the guarded LLM. Facts only, no history."""

    account_label = "ユーザー" if ctx.account == "user" else "AI自動運用"
    sections = [
        "あなたは投資学習用シミュレーション（仮想取引）のアドバイザーです。"
        "以下は実際の資金を伴わない仮想取引口座の事実データです。"
        "断定的な売買推奨は禁止です。「〜という考え方があります」等の情報提供の形で、"
        "根拠と不確実性を必ず添えて日本語で助言してください。",
        f"[口座] 種別: {account_label} / 基準日: {ctx.as_of or '不明'} / "
        f"戦略プリセット: {ctx.preset.name} / 総資産: {_fmt_yen(ctx.equity)} / "
        f"現金比率: {ctx.cash_ratio_pct:.1f}% / 累計損益率: {_fmt_pct(ctx.total_return_pct)} / "
        f"累計取引数: {ctx.trade_count}",
    ]
    if ctx.positions:
        sections.append("[保有銘柄とシグナル]\n" + "\n".join(_position_lines(ctx)))
    else:
        sections.append("[保有銘柄] なし（全額現金）")
    sections.append("[過去の売買タイミング実績]\n" + "\n".join(_timing_lines(ctx.timing)))
    sections.append(
        "次の4点を、上のデータを根拠として引用しながら簡潔に述べてください。\n"
        "1. 各保有銘柄の売り時の考え方（損切りライン・利確ライン・20日線乖離を使って）\n"
        "2. 新規買いのタイミングの考え方（現金比率とボラティリティを踏まえて）\n"
        "3. 注文方法の使い分け（成行・指値・逆指値。指値/逆指値は上記のライン価格を例に）\n"
        "4. 過去のタイミング実績から読み取れる傾向（早売り・高値掴み等）と改善の方向性\n"
        "全体で600字以内。最後に、これは仮想取引に基づく情報提供であり投資助言ではない旨を1文添えてください。"
    )
    return "\n\n".join(sections)


def render_local_advice(ctx: AdviceContext) -> str:
    """Deterministic Japanese advice used when the LLM is off or unavailable.

    Rule-based rendering of the same facts the prompt carries, so the feature
    degrades gracefully to a useful (if drier) answer at zero LLM cost.
    """

    lines: list[str] = []
    if not ctx.positions:
        lines.append(
            "現在は全額現金です。新規買いは1回で使い切らず、現金比率を段階的に下げる"
            "分割エントリー（例: 3回に分けて指値）でタイミングの偏りを抑える考え方があります。"
        )
    for pos in ctx.positions:
        parts = [f"{pos.ticker} {pos.name}".strip() + ":"]
        if pos.unrealized_pnl_pct is not None and pos.unrealized_pnl_pct <= -5.0:
            parts.append(
                f"含み損{_fmt_pct(pos.unrealized_pnl_pct)}。損切りライン"
                f"{_fmt_yen(pos.stop_loss_price)}に逆指値を置き、下振れを機械的に"
                "限定する考え方があります。"
            )
        elif pos.unrealized_pnl_pct is not None and pos.unrealized_pnl_pct >= 10.0:
            parts.append(
                f"含み益{_fmt_pct(pos.unrealized_pnl_pct)}。利確ライン"
                f"{_fmt_yen(pos.take_profit_price)}付近の指値売りで利益を確定するか、"
                "逆指値を取得単価より上に引き上げて利益を守る考え方があります。"
            )
        else:
            parts.append(
                f"損切りライン{_fmt_yen(pos.stop_loss_price)}・利確ライン"
                f"{_fmt_yen(pos.take_profit_price)}を目安に、逆指値と指値を"
                "組み合わせて出口を事前に決めておく考え方があります。"
            )
        if pos.ma20_gap_pct is not None:
            if pos.ma20_gap_pct >= 5.0:
                parts.append(
                    f"20日線から{_fmt_pct(pos.ma20_gap_pct)}上方乖離しており、"
                    "短期的な過熱に注意が必要です。"
                )
            elif pos.ma20_gap_pct <= -5.0:
                parts.append(
                    f"20日線から{_fmt_pct(pos.ma20_gap_pct)}下方乖離しており、"
                    "下落トレンド入りの可能性に注意が必要です。"
                )
        lines.append(" ".join(parts))

    timing = ctx.timing
    if timing.sells_evaluated > 0 and (timing.avg_move_after_sell_pct or 0.0) > 1.0:
        lines.append(
            f"過去の売りの後、{timing.horizon_bars}営業日で平均"
            f"{_fmt_pct(timing.avg_move_after_sell_pct)}上昇しています（早売り傾向）。"
            "利確を指値でやや上に置く、または分割売りにする改善余地があります。"
        )
    if timing.buys_evaluated > 0 and (timing.avg_move_after_buy_pct or 0.0) < -1.0:
        lines.append(
            f"過去の買いの後、{timing.horizon_bars}営業日で平均"
            f"{_fmt_pct(timing.avg_move_after_buy_pct)}下落しています（高値掴み傾向）。"
            "成行での飛び付き買いを避け、20日線近辺への押し目を指値で待つ改善余地があります。"
        )
    if timing.buys_evaluated == 0 and timing.sells_evaluated == 0:
        lines.append(
            "タイミング実績を評価できる取引がまだありません。取引を重ねると、"
            "売買それぞれの成否傾向がここに反映されます。"
        )
    if ctx.cash_ratio_pct < 10.0:
        lines.append(
            f"現金比率が{ctx.cash_ratio_pct:.1f}%と低く、下落時の買い余力がありません。"
            "一部利確で現金比率を回復させる考え方があります。"
        )
    lines.append("これは仮想取引データに基づく情報提供であり、投資助言ではありません。")
    return "\n".join(lines)
