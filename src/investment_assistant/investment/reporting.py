"""Deterministic investment monthly report rendering."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from investment_assistant.financials.evidence import DEFAULT_FINANCIALS_CSV
from investment_assistant.investment.analysis import analyze_portfolio
from investment_assistant.investment.models import DISCLAIMER, InvestmentHolding


def build_investment_monthly_report(
    holdings: Sequence[InvestmentHolding],
    *,
    candidates: Sequence[dict[str, object]] = (),
    financials_csv: str | Path = DEFAULT_FINANCIALS_CSV,
) -> dict[str, object]:
    """Build a non-advisory monthly report from computed facts."""

    analysis = analyze_portfolio(holdings, financials_csv=financials_csv)
    summary = analysis["summary"]
    if not isinstance(summary, dict):
        raise ValueError("portfolio analysis did not return a summary")
    evidence = list(_evidence_rows(analysis.get("evidence")))
    for item in candidates[:10]:
        evidence.append(
            {
                "claim_key": f"candidate.{item.get('code')}",
                "source_type": "candidate_screen",
                "source_ref": item.get("asset_type"),
                "metric_key": "matched_conditions",
                "note": "条件一致の比較候補であり、推奨ではありません。",
            }
        )
    kpis = [
        _kpi("market_value", "評価額", summary.get("market_value"), "holding.*.market_value"),
        _kpi("unrealized_pnl", "評価損益", summary.get("unrealized_pnl"), "holding.*.market_value"),
        _kpi(
            "annual_income_estimate",
            "配当/分配金見込み",
            summary.get("annual_income_estimate"),
            "holding.*.dividend",
        ),
        _kpi("nisa_remaining", "NISA残枠", _nisa_remaining(summary), "nisa.cost_basis"),
    ]
    return {
        "title": "投資月次レポート",
        "generated_at": datetime.now(UTC).isoformat(),
        "kpis": kpis,
        "sections": [
            {
                "key": "holdings",
                "title": "保有状況",
                "body": (
                    f"保有 {summary.get('holdings_count')} 件、評価額 "
                    f"{summary.get('market_value')} 円、"
                    f"評価損益 {summary.get('unrealized_pnl')} 円。"
                ),
            },
            {
                "key": "concentration",
                "title": "集中リスク",
                "body": (
                    f"最大保有は {_largest(summary)}。Top3比率 "
                    f"{_top3(summary)}%。"
                ),
            },
            {
                "key": "income",
                "title": "配当/分配金見込み",
                "body": (
                    f"年間見込み {summary.get('annual_income_estimate')} 円、"
                    f"評価額利回り {summary.get('income_yield_pct')}%。"
                ),
            },
            {
                "key": "nisa",
                "title": "NISA枠",
                "body": (
                    f"総枠残 {_nisa_remaining(summary)} 円、"
                    f"成長投資枠残 {_nisa_growth_remaining(summary)} 円。"
                ),
            },
            {
                "key": "candidates",
                "title": "候補抽出結果",
                "body": (
                    f"条件一致候補 {len(candidates)} 件。"
                    "これは推奨ではなく比較対象の提示です。"
                ),
            },
        ],
        "portfolio": analysis,
        "candidate_count": len(candidates),
        "evidence": evidence,
        "disclaimer": DISCLAIMER,
        "auto_trading": False,
        "call_real_api": False,
    }


def _kpi(key: str, label: str, value: object, evidence_key: str) -> dict[str, object]:
    return {
        "metric_key": key,
        "label": label,
        "value": value,
        "evidence_keys": [evidence_key],
        "formula": _formula(key),
    }


def _formula(key: str) -> str:
    formulas = {
        "market_value": "数量 × 現在価格（未入力時は取得単価）",
        "unrealized_pnl": "評価額 - 取得額",
        "annual_income_estimate": "ユーザー入力分配金、またはEDINET最新1株配当 × 数量",
        "nisa_remaining": "18,000,000円 - NISA口座の取得額合計",
    }
    return formulas.get(key, "機械集計")


def _evidence_rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _nisa_remaining(summary: dict[str, object]) -> object:
    nisa = summary.get("nisa")
    return nisa.get("remaining_lifetime") if isinstance(nisa, dict) else None


def _nisa_growth_remaining(summary: dict[str, object]) -> object:
    nisa = summary.get("nisa")
    return nisa.get("growth_remaining") if isinstance(nisa, dict) else None


def _largest(summary: dict[str, object]) -> str:
    largest = summary.get("largest_position")
    if not isinstance(largest, dict):
        return "不明"
    return f"{largest.get('code')} {largest.get('name')}（{largest.get('share_pct')}%）"


def _top3(summary: dict[str, object]) -> object:
    concentration = summary.get("concentration")
    return concentration.get("top3_share_pct") if isinstance(concentration, dict) else None
