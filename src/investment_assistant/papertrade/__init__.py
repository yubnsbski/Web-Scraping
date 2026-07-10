"""Paper-trading (virtual trading) simulation package.

**Simulation only. No real orders are ever placed.** This package exists to
let an AI's virtual buy/sell decisions be scored against realistic Japanese
equity market mechanics (tick rounding, price-limit bands, T+2 settlement,
simplified capital-gains tax) so that a learning loop across cycles can be
evaluated statistically. It never calls a broker API, never touches
real money, and never executes a real order -- this is a hard compliance
boundary carried over from ``AGENTS.md`` ("自動売買機能は実装しない" /
"実注文や自動売買を追加する場合は、別途法務レビューを必須にする").

See ``docs/papertrade-design.md`` (Japanese) for the full design: the
walk-forward cycle loop, the A/B/C experiment design used to separate
"the AI got better" from "the AI got lucky", and the deterministic-core /
policy-only-LLM split that keeps this offline-testable and within the
Gemini free-tier budget.

Sprint P1 (this sprint) ships only the simulation foundation -- trading
calendar, universe selection, market mechanics (tick/limit/slippage/
commission/tax), the cash+position account, and SQLite persistence. No
engine, strategy, or LLM policy adjustment exists yet (Sprint P2/P3).
"""

from __future__ import annotations

PAPERTRADE_DISCLAIMER = (
    "これは仮想売買シミュレーションであり、投資助言ではありません。"
    "実際の注文は行われません。最終的な投資判断はユーザー本人が行ってください。"
)

__all__ = ["PAPERTRADE_DISCLAIMER"]
