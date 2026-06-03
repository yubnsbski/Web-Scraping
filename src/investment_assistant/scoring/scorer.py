"""CSV loading and transparent local investment scoring."""

from __future__ import annotations

import csv
from dataclasses import asdict
from pathlib import Path

from investment_assistant.scoring.models import (
    InvestmentCandidate,
    ScoreBreakdown,
    ScoredInvestment,
    ScoreWeights,
)
from investment_assistant.scoring.normalizer import (
    normalize_higher_is_better,
    normalize_lower_is_better,
)

_REQUIRED_COLUMNS = frozenset(
    {"name", "expense_ratio", "annual_return", "volatility", "diversification_score"}
)


def load_candidates_csv(path: str | Path) -> list[InvestmentCandidate]:
    """Load investment candidates from a UTF-8 CSV file without network or LLM calls."""

    csv_path = Path(path)
    with csv_path.open(newline="", encoding="utf-8") as file_obj:
        reader = csv.DictReader(file_obj)
        fieldnames = set(reader.fieldnames or [])
        missing = sorted(_REQUIRED_COLUMNS - fieldnames)
        if missing:
            msg = f"Missing required CSV columns: {', '.join(missing)}"
            raise ValueError(msg)
        candidates = [
            _row_to_candidate(row, row_number=index + 2)
            for index, row in enumerate(reader)
        ]

    if not candidates:
        msg = "CSV must contain at least one investment candidate."
        raise ValueError(msg)
    return candidates


def score_candidates(
    candidates: list[InvestmentCandidate],
    *,
    weights: ScoreWeights | None = None,
) -> list[ScoredInvestment]:
    """Rank candidates using transparent normalized metrics.

    Lower expense ratio and volatility are better. Higher annual return and
    diversification score are better. This is a ranking aid, not investment
    advice or a trading signal.
    """

    if not candidates:
        msg = "At least one candidate is required for scoring."
        raise ValueError(msg)

    chosen_weights = (weights or ScoreWeights()).normalized()
    expense_values = [candidate.expense_ratio for candidate in candidates]
    return_values = [candidate.annual_return for candidate in candidates]
    volatility_values = [candidate.volatility for candidate in candidates]
    diversification_values = [candidate.diversification_score for candidate in candidates]

    scored: list[tuple[InvestmentCandidate, ScoreBreakdown, list[str]]] = []
    for candidate in candidates:
        expense_score = normalize_lower_is_better(candidate.expense_ratio, expense_values)
        return_score = normalize_higher_is_better(candidate.annual_return, return_values)
        volatility_score = normalize_lower_is_better(candidate.volatility, volatility_values)
        diversification_score = normalize_higher_is_better(
            candidate.diversification_score,
            diversification_values,
        )
        total = round(
            expense_score * chosen_weights.expense_ratio
            + return_score * chosen_weights.annual_return
            + volatility_score * chosen_weights.volatility
            + diversification_score * chosen_weights.diversification_score,
            6,
        )
        breakdown = ScoreBreakdown(
            expense_ratio_score=expense_score,
            annual_return_score=return_score,
            volatility_score=volatility_score,
            diversification_score=diversification_score,
            total_score=total,
        )
        scored.append((candidate, breakdown, _build_rationale(candidate, breakdown)))

    ranked = sorted(scored, key=lambda item: (-item[1].total_score, item[0].name))
    return [
        ScoredInvestment(
            rank=index + 1,
            candidate=candidate,
            breakdown=breakdown,
            rationale=rationale,
        )
        for index, (candidate, breakdown, rationale) in enumerate(ranked)
    ]


def rank_candidates_from_csv(
    path: str | Path,
    *,
    limit: int = 10,
    weights: ScoreWeights | None = None,
) -> dict[str, object]:
    """Load, score, and format local CSV candidates for CLI output."""

    if limit <= 0:
        msg = "limit must be greater than zero."
        raise ValueError(msg)

    candidates = load_candidates_csv(path)
    ranked = score_candidates(candidates, weights=weights)
    return {
        "source": str(path),
        "limit": limit,
        "count": len(candidates),
        "weights": asdict((weights or ScoreWeights()).normalized()),
        "results": [_scored_to_dict(item) for item in ranked[:limit]],
    }


def _row_to_candidate(row: dict[str, str], *, row_number: int) -> InvestmentCandidate:
    name = row["name"].strip()
    if not name:
        msg = f"Row {row_number}: name is required."
        raise ValueError(msg)
    return InvestmentCandidate(
        name=name,
        expense_ratio=_parse_float(
            row["expense_ratio"],
            row_number=row_number,
            column="expense_ratio",
        ),
        annual_return=_parse_float(
            row["annual_return"],
            row_number=row_number,
            column="annual_return",
        ),
        volatility=_parse_float(row["volatility"], row_number=row_number, column="volatility"),
        diversification_score=_parse_float(
            row["diversification_score"],
            row_number=row_number,
            column="diversification_score",
        ),
    )


def _parse_float(value: str, *, row_number: int, column: str) -> float:
    stripped = value.strip()
    if not stripped:
        msg = f"Row {row_number}: {column} is required."
        raise ValueError(msg)
    try:
        return float(stripped)
    except ValueError as exc:
        msg = f"Row {row_number}: {column} must be numeric."
        raise ValueError(msg) from exc


def _build_rationale(candidate: InvestmentCandidate, breakdown: ScoreBreakdown) -> list[str]:
    expense_note = (
        f"経費率 {candidate.expense_ratio:g} は低いほど高評価です。"
        f"正規化スコア: {breakdown.expense_ratio_score:g}。"
    )
    return_note = (
        f"年率リターン {candidate.annual_return:g} は高いほど高評価です。"
        f"正規化スコア: {breakdown.annual_return_score:g}。"
    )
    volatility_note = (
        f"ボラティリティ {candidate.volatility:g} は低いほど高評価です。"
        f"正規化スコア: {breakdown.volatility_score:g}。"
    )
    diversification_note = (
        f"分散度 {candidate.diversification_score:g} は高いほど高評価です。"
        f"正規化スコア: {breakdown.diversification_score:g}。"
    )
    return [expense_note, return_note, volatility_note, diversification_note]


def _scored_to_dict(item: ScoredInvestment) -> dict[str, object]:
    return {
        "rank": item.rank,
        "name": item.candidate.name,
        "metrics": asdict(item.candidate),
        "score": asdict(item.breakdown),
        "rationale": item.rationale,
    }
