"""Data models for local, non-advisory investment scoring."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InvestmentCandidate:
    """One locally supplied investment candidate.

    Values are expected to come from user-controlled CSV input. This model does
    not fetch market data, call an LLM, place orders, or make definitive buy/sell
    recommendations.
    """

    name: str
    expense_ratio: float
    annual_return: float
    volatility: float
    diversification_score: float


@dataclass(frozen=True)
class ScoreWeights:
    """Weights used by the transparent scoring formula."""

    expense_ratio: float = 0.30
    annual_return: float = 0.30
    volatility: float = 0.25
    diversification_score: float = 0.15

    def normalized(self) -> ScoreWeights:
        """Return weights scaled to sum to 1.0."""

        total = (
            self.expense_ratio
            + self.annual_return
            + self.volatility
            + self.diversification_score
        )
        if total <= 0:
            msg = "At least one scoring weight must be positive."
            raise ValueError(msg)
        return ScoreWeights(
            expense_ratio=self.expense_ratio / total,
            annual_return=self.annual_return / total,
            volatility=self.volatility / total,
            diversification_score=self.diversification_score / total,
        )


@dataclass(frozen=True)
class ScoreBreakdown:
    """Normalized metric components and weighted final score."""

    expense_ratio_score: float
    annual_return_score: float
    volatility_score: float
    diversification_score: float
    total_score: float


@dataclass(frozen=True)
class ScoredInvestment:
    """A candidate with transparent score details and explanatory notes."""

    rank: int
    candidate: InvestmentCandidate
    breakdown: ScoreBreakdown
    rationale: list[str]
