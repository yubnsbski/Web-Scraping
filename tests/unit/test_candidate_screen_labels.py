"""Truthfulness of fund candidate `matched_conditions` labels.

The screen keeps funds with an unknown (None) diversification score rather than
dropping them, but it must not then claim they satisfy the diversification
threshold. New / conflict-light file: complements test_investment_mvp.py, which
only exercises funds whose score is known.
"""

from __future__ import annotations

from investment_assistant.investment.candidates import screen_candidates, screen_from_values
from investment_assistant.investment.models import FundProfile


def _fund(code: str, *, score: float | None) -> FundProfile:
    return FundProfile(
        fund_code=code,
        name=code,
        asset_class="global_equity",
        expense_ratio=0.1,
        distribution_policy="reinvest",
        nisa_eligible=True,
        provider_id="user_csv",
        diversification_score=score,
    )


def _screen():
    return screen_from_values(
        asset_types=["fund"],
        exclude_dividend_cut=False,
        min_equity_ratio=None,
        max_expense_ratio=None,
        nisa_eligible_only=False,
        min_diversification_score=0.8,
        sort_by="score",
        limit=None,
    )


def _conditions(result: dict, code: str) -> list[str]:
    for item in result["results"]:
        if item["code"] == code:
            return list(item["matched_conditions"])
    raise AssertionError(f"{code} not in results")


def test_unknown_diversification_fund_kept_but_not_labeled_as_matching() -> None:
    result = screen_candidates(screen=_screen(), funds=[_fund("F_NONE", score=None)])
    # Lenient-on-missing-data: the fund is not dropped...
    assert {item["code"] for item in result["results"]} == {"F_NONE"}
    # ...but it must not claim a threshold it was never checked against.
    assert not any("分散度" in c for c in _conditions(result, "F_NONE"))


def test_known_passing_fund_is_labeled_as_matching() -> None:
    result = screen_candidates(screen=_screen(), funds=[_fund("F_PASS", score=0.95)])
    assert "分散度 0.8 以上" in _conditions(result, "F_PASS")


def test_known_failing_fund_is_dropped() -> None:
    result = screen_candidates(screen=_screen(), funds=[_fund("F_FAIL", score=0.4)])
    assert result["results"] == []
