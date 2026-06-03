"""Non-advisory report wrappers for investment scoring results."""

from __future__ import annotations

from pathlib import Path

from investment_assistant.scoring.models import ScoreWeights
from investment_assistant.scoring.scorer import rank_candidates_from_csv

DISCLAIMER = (
    "このスコアはユーザー提供データに基づく機械的な比較であり、投資助言、売買推奨、"
    "将来リターンの保証ではありません。過去実績や入力値には不確実性があり、"
    "最終的な投資判断はユーザー本人が行います。自動売買は行いません。"
)


def build_scoring_report(
    *,
    path: str | Path,
    limit: int = 10,
    weights: ScoreWeights | None = None,
) -> dict[str, object]:
    """Build a JSON-friendly scoring report with compliance guardrails."""

    report = rank_candidates_from_csv(path, limit=limit, weights=weights)
    report["methodology"] = {
        "summary": "経費率・リターン・リスク・分散度を0〜1に正規化し、重み付き平均で比較します。",
        "expense_ratio": "低いほど高評価",
        "annual_return": "高いほど高評価",
        "volatility": "低いほど高評価",
        "diversification_score": "高いほど高評価",
    }
    report["disclaimer"] = DISCLAIMER
    report["call_real_api"] = False
    report["auto_trading"] = False
    return report
