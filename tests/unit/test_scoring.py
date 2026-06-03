from __future__ import annotations

import pytest

from investment_assistant.scoring.models import InvestmentCandidate, ScoreWeights
from investment_assistant.scoring.report import build_scoring_report
from investment_assistant.scoring.scorer import load_candidates_csv, score_candidates


def test_load_candidates_csv_requires_expected_columns(tmp_path):
    csv_path = tmp_path / "funds.csv"
    csv_path.write_text("name,expense_ratio\nA,0.1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Missing required CSV columns"):
        load_candidates_csv(csv_path)


def test_score_candidates_ranks_with_transparent_breakdown():
    candidates = [
        InvestmentCandidate(
            name="低コスト全世界株式",
            expense_ratio=0.12,
            annual_return=0.065,
            volatility=0.18,
            diversification_score=0.95,
        ),
        InvestmentCandidate(
            name="高コストテーマ型",
            expense_ratio=1.20,
            annual_return=0.080,
            volatility=0.35,
            diversification_score=0.45,
        ),
        InvestmentCandidate(
            name="債券バランス型",
            expense_ratio=0.35,
            annual_return=0.030,
            volatility=0.08,
            diversification_score=0.80,
        ),
    ]

    ranked = score_candidates(candidates)

    assert ranked[0].candidate.name == "低コスト全世界株式"
    assert ranked[0].rank == 1
    assert ranked[0].breakdown.total_score > ranked[1].breakdown.total_score
    assert ranked[0].breakdown.expense_ratio_score == 1.0
    assert "低いほど高評価" in ranked[0].rationale[0]


def test_score_weights_are_normalized():
    weights = ScoreWeights(
        expense_ratio=3,
        annual_return=3,
        volatility=2.5,
        diversification_score=1.5,
    ).normalized()

    assert weights.expense_ratio == 0.3
    assert weights.annual_return == 0.3
    assert weights.volatility == 0.25
    assert weights.diversification_score == 0.15


def test_build_scoring_report_includes_guardrails(tmp_path):
    csv_path = tmp_path / "funds.csv"
    csv_path.write_text(
        "name,expense_ratio,annual_return,volatility,diversification_score\n"
        "低コスト全世界株式,0.12,0.065,0.18,0.95\n"
        "高コストテーマ型,1.20,0.080,0.35,0.45\n",
        encoding="utf-8",
    )

    report = build_scoring_report(path=csv_path, limit=1)

    assert report["call_real_api"] is False
    assert report["auto_trading"] is False
    assert len(report["results"]) == 1
    assert "投資助言" in str(report["disclaimer"])
    assert "最終的な投資判断" in str(report["disclaimer"])
