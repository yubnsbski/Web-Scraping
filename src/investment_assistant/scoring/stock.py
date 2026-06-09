"""Score & rank stocks from EDINET-derived financials (non-advisory).

Unlike the manual-CSV fund scorer, this turns the financials the system already
collects (``financials.csv`` via EDINET ingest) into a transparent, weighted
"dividend-quality" score per ticker — so the user gets an automatic ranking of
their universe without preparing any input. Components:

- dividend level   (latest 1株配当, higher better; normalized across the set)
- dividend trend   (増配/横ばい/減少 …)
- dividend safety  (penalty for past dividend cuts)
- equity ratio     (自己資本比率, higher better; normalized)
- operating cash flow trend

Named strategy presets re-weight these. Pure data aggregation: no market data,
no LLM, no buy/sell recommendation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from investment_assistant.financials.evidence import DEFAULT_FINANCIALS_CSV, load_comparison
from investment_assistant.scoring.normalizer import normalize_higher_is_better

DISCLAIMER = (
    "これは投資助言ではありません。EDINET由来の公開財務データを機械的に集計・"
    "スコア化したもので、売買推奨ではありません。最終判断はご自身で行ってください。"
)

_TREND_SCORE: dict[str, float] = {
    "increasing": 1.0,
    "flat": 0.6,
    "mixed": 0.4,
    "declining": 0.1,
    "insufficient": 0.5,
}
_TREND_JP: dict[str, str] = {
    "increasing": "増加",
    "flat": "横ばい",
    "mixed": "増減混在",
    "declining": "減少",
    "insufficient": "データ不足",
}


@dataclass(frozen=True)
class StockScoreWeights:
    """Weights for the dividend-quality stock score (need not sum to 1)."""

    dividend_level: float = 0.25
    dividend_trend: float = 0.25
    dividend_safety: float = 0.20
    equity_ratio: float = 0.15
    operating_cf: float = 0.15

    def normalized(self) -> StockScoreWeights:
        total = (
            self.dividend_level
            + self.dividend_trend
            + self.dividend_safety
            + self.equity_ratio
            + self.operating_cf
        )
        if total <= 0:
            msg = "At least one scoring weight must be positive."
            raise ValueError(msg)
        return StockScoreWeights(
            dividend_level=self.dividend_level / total,
            dividend_trend=self.dividend_trend / total,
            dividend_safety=self.dividend_safety / total,
            equity_ratio=self.equity_ratio / total,
            operating_cf=self.operating_cf / total,
        )


# One-click strategy presets (re-weighting of the same transparent components).
STRATEGY_PRESETS: dict[str, StockScoreWeights] = {
    "balanced": StockScoreWeights(),
    "high_yield": StockScoreWeights(
        dividend_level=0.40, dividend_trend=0.20, dividend_safety=0.20,
        equity_ratio=0.10, operating_cf=0.10,
    ),
    "defensive": StockScoreWeights(
        dividend_level=0.20, dividend_trend=0.10, dividend_safety=0.30,
        equity_ratio=0.30, operating_cf=0.10,
    ),
    "growth": StockScoreWeights(
        dividend_level=0.15, dividend_trend=0.35, dividend_safety=0.10,
        equity_ratio=0.10, operating_cf=0.30,
    ),
}
STRATEGY_LABELS: dict[str, str] = {
    "balanced": "バランス",
    "high_yield": "高配当重視",
    "defensive": "安定・ディフェンシブ",
    "growth": "増配・成長",
}


@dataclass(frozen=True)
class StockMetrics:
    """Per-ticker inputs distilled from the financials comparison."""

    ticker: str
    name: str
    dividend_latest: float | None
    dividend_trend: str
    cut_count: int
    equity_ratio: float | None
    operating_cf_trend: str
    periods: int


@dataclass(frozen=True)
class ScoredStock:
    rank: int
    ticker: str
    name: str
    total_score: float
    breakdown: dict[str, float]
    metrics: dict[str, object]
    rationale: list[str] = field(default_factory=list)


def build_stock_metrics(comparison: dict[str, object]) -> list[StockMetrics]:
    """Distil the financials comparison output into per-ticker metrics."""

    companies = comparison.get("companies")
    metrics: list[StockMetrics] = []
    if not isinstance(companies, list):
        return metrics
    for company in companies:
        if not isinstance(company, dict):
            continue
        ticker = str(company.get("ticker") or "").strip()
        if not ticker:
            continue
        cuts = company.get("dividend_cut_years")
        series = company.get("dividend_series")
        metrics.append(
            StockMetrics(
                ticker=ticker,
                name=str(company.get("name") or ""),
                dividend_latest=_as_float(company.get("latest_dividend_per_share")),
                dividend_trend=str(company.get("dividend_trend") or "insufficient"),
                cut_count=len(cuts) if isinstance(cuts, list) else 0,
                equity_ratio=_as_float(company.get("latest_equity_ratio")),
                operating_cf_trend=str(company.get("operating_cf_trend") or "insufficient"),
                periods=len(series) if isinstance(series, list) else 0,
            )
        )
    return metrics


def score_stocks(
    metrics: list[StockMetrics],
    *,
    weights: StockScoreWeights | None = None,
    exclude_dividend_cut: bool = False,
    min_equity_ratio: float | None = None,
    min_periods: int = 1,
) -> list[ScoredStock]:
    """Rank tickers by the weighted dividend-quality score after filtering."""

    chosen = (weights or StockScoreWeights()).normalized()
    pool = [
        metric
        for metric in metrics
        if metric.periods >= min_periods
        and not (exclude_dividend_cut and metric.cut_count > 0)
        and not (
            min_equity_ratio is not None
            and metric.equity_ratio is not None
            and metric.equity_ratio < min_equity_ratio
        )
    ]
    if not pool:
        return []

    dividend_values = [m.dividend_latest for m in pool if m.dividend_latest is not None]
    equity_values = [m.equity_ratio for m in pool if m.equity_ratio is not None]

    scored: list[ScoredStock] = []
    for metric in pool:
        level = (
            normalize_higher_is_better(metric.dividend_latest, dividend_values)
            if metric.dividend_latest is not None and dividend_values
            else 0.0
        )
        trend = _TREND_SCORE.get(metric.dividend_trend, 0.5)
        safety = 1.0 - min(metric.cut_count, 3) / 3
        equity = (
            normalize_higher_is_better(metric.equity_ratio, equity_values)
            if metric.equity_ratio is not None and equity_values
            else 0.5
        )
        cf = _TREND_SCORE.get(metric.operating_cf_trend, 0.5)
        breakdown = {
            "dividend_level": round(level, 4),
            "dividend_trend": round(trend, 4),
            "dividend_safety": round(safety, 4),
            "equity_ratio": round(equity, 4),
            "operating_cf": round(cf, 4),
        }
        total = (
            level * chosen.dividend_level
            + trend * chosen.dividend_trend
            + safety * chosen.dividend_safety
            + equity * chosen.equity_ratio
            + cf * chosen.operating_cf
        )
        scored.append(
            ScoredStock(
                rank=0,
                ticker=metric.ticker,
                name=metric.name,
                total_score=round(total, 4),
                breakdown=breakdown,
                metrics={
                    "dividend_latest": metric.dividend_latest,
                    "dividend_trend": metric.dividend_trend,
                    "cut_count": metric.cut_count,
                    "equity_ratio": metric.equity_ratio,
                    "operating_cf_trend": metric.operating_cf_trend,
                    "periods": metric.periods,
                },
                rationale=_rationale(metric),
            )
        )

    scored.sort(key=lambda s: (-s.total_score, s.ticker))
    return [
        ScoredStock(
            rank=index,
            ticker=s.ticker,
            name=s.name,
            total_score=s.total_score,
            breakdown=s.breakdown,
            metrics=s.metrics,
            rationale=s.rationale,
        )
        for index, s in enumerate(scored, start=1)
    ]


def run_stock_scoring(
    *,
    financials_csv: str | Path = DEFAULT_FINANCIALS_CSV,
    strategy: str = "balanced",
    exclude_dividend_cut: bool = False,
    min_equity_ratio: float | None = None,
    min_periods: int = 1,
    limit: int | None = None,
) -> dict[str, object]:
    """Load financials, score the universe with a strategy preset, and rank."""

    weights = STRATEGY_PRESETS.get(strategy, StockScoreWeights())
    comparison = load_comparison(financials_csv)
    if comparison is None:
        return {
            "strategy": strategy,
            "available": False,
            "results": [],
            "count": 0,
            "hint": "financials.csv が見つかりません。先にEDINET取得を実行してください。",
            "disclaimer": DISCLAIMER,
        }
    metrics = build_stock_metrics(comparison)
    ranked = score_stocks(
        metrics,
        weights=weights,
        exclude_dividend_cut=exclude_dividend_cut,
        min_equity_ratio=min_equity_ratio,
        min_periods=min_periods,
    )
    results = ranked if limit is None else ranked[: max(0, limit)]
    return {
        "strategy": strategy,
        "strategy_label": STRATEGY_LABELS.get(strategy, strategy),
        "available": True,
        "weights": _weights_dict(weights.normalized()),
        "universe": len(metrics),
        "count": len(ranked),
        "results": [_scored_to_dict(stock) for stock in results],
        "disclaimer": DISCLAIMER,
    }


def score_for_ticker(
    *,
    ticker: str,
    financials_csv: str | Path = DEFAULT_FINANCIALS_CSV,
    strategy: str = "balanced",
) -> dict[str, object] | None:
    """Return one ticker's scored row (for Chat / Dashboard), or None."""

    result = run_stock_scoring(financials_csv=financials_csv, strategy=strategy)
    rows = result.get("results", [])
    if not isinstance(rows, list):
        return None
    for row in rows:
        if isinstance(row, dict) and str(row.get("ticker")) == str(ticker).strip():
            return row
    return None


def _rationale(metric: StockMetrics) -> list[str]:
    notes: list[str] = []
    if metric.dividend_latest is not None:
        notes.append(
            f"1株配当 {metric.dividend_latest:g}円・{_TREND_JP.get(metric.dividend_trend, '不明')}"
        )
    notes.append("減配なし" if metric.cut_count == 0 else f"減配 {metric.cut_count}回")
    if metric.equity_ratio is not None:
        notes.append(f"自己資本比率 {metric.equity_ratio:g}%")
    notes.append(f"営業CF {_TREND_JP.get(metric.operating_cf_trend, '不明')}")
    if metric.periods < 2:
        notes.append("※ 1期のみ（トレンド未確定）")
    return notes


def _scored_to_dict(stock: ScoredStock) -> dict[str, object]:
    return {
        "rank": stock.rank,
        "ticker": stock.ticker,
        "name": stock.name,
        "total_score": stock.total_score,
        "breakdown": stock.breakdown,
        "metrics": stock.metrics,
        "rationale": stock.rationale,
    }


def _weights_dict(weights: StockScoreWeights) -> dict[str, float]:
    return {
        "dividend_level": round(weights.dividend_level, 4),
        "dividend_trend": round(weights.dividend_trend, 4),
        "dividend_safety": round(weights.dividend_safety, 4),
        "equity_ratio": round(weights.equity_ratio, 4),
        "operating_cf": round(weights.operating_cf, 4),
    }


def _as_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None
