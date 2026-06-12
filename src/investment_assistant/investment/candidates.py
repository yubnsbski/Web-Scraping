"""Condition-based candidate screening for the investment-only MVP."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from investment_assistant.financials.evidence import DEFAULT_FINANCIALS_CSV, load_comparison
from investment_assistant.investment.edinet import build_edinet_summary
from investment_assistant.investment.models import DISCLAIMER, CandidateScreen, FundProfile
from investment_assistant.investment.provider_policy import provider_policy
from investment_assistant.scoring.stock import run_stock_scoring

FUND_SCORE_WEIGHTS: dict[str, float] = {
    "expense_ratio": 0.35,
    "nisa_eligible": 0.25,
    "diversification": 0.30,
    "distribution_policy": 0.10,
}

_FUND_ASSET_CLASS_DIVERSIFICATION_HINTS: dict[str, float] = {
    "global_equity": 0.90,
    "balanced": 0.85,
    "bond": 0.75,
    "domestic_equity": 0.65,
    "theme": 0.35,
    "unknown": 0.50,
}

_FUND_DISTRIBUTION_POLICY_SCORES: dict[str, float] = {
    "reinvest": 1.0,
    "accumulating": 1.0,
    "no_distribution": 1.0,
    "distribution": 0.70,
    "monthly_distribution": 0.45,
    "unknown": 0.50,
}


def screen_candidates(
    *,
    screen: CandidateScreen,
    funds: Sequence[FundProfile] = (),
    financials_csv: str | Path = DEFAULT_FINANCIALS_CSV,
    runtime_mode: str = "development",
) -> dict[str, object]:
    """Return condition matches only; never a buy/sell recommendation."""

    items: list[dict[str, object]] = []
    blocked_providers: list[dict[str, object]] = []
    asset_types = set(screen.asset_types)
    generated_at = datetime.now(UTC).isoformat()
    financials_source_ref = str(financials_csv)
    companies = _company_index(financials_csv)
    fund_scoring_model = _fund_scoring_model()

    if "stock" in asset_types:
        stock_result = run_stock_scoring(
            financials_csv=financials_csv,
            strategy="balanced",
            exclude_dividend_cut=screen.exclude_dividend_cut,
            min_equity_ratio=screen.min_equity_ratio,
            min_periods=1,
            limit=None,
        )
        for row in _rows(stock_result.get("results")):
            code = str(row.get("ticker") or "")
            items.append(
                _stock_candidate(
                    row,
                    screen,
                    financials_source_ref=financials_source_ref,
                    generated_at=generated_at,
                    company=companies.get(code),
                )
            )

    if "fund" in asset_types:
        for fund in funds:
            policy = provider_policy(fund.provider_id, runtime_mode=runtime_mode)
            if not policy.production_allowed:
                blocked_providers.append(policy.to_dict())
                continue
            score_details = _fund_score_details(fund)
            if (
                screen.max_expense_ratio is not None
                and fund.expense_ratio > screen.max_expense_ratio
            ):
                continue
            if screen.nisa_eligible_only and not fund.nisa_eligible:
                continue
            if (
                screen.min_diversification_score is not None
                and _float(score_details.get("diversification_score"))
                < screen.min_diversification_score
            ):
                continue
            items.append(
                _fund_candidate(
                    fund,
                    screen,
                    policy.to_dict(),
                    score_details=score_details,
                    generated_at=generated_at,
                )
            )

    items = _sort(items, screen.sort_by)
    if screen.limit is not None:
        items = items[: max(screen.limit, 0)]
    return {
        "available": True,
        "generated_at": generated_at,
        "financials_source_ref": financials_source_ref,
        "screen": {
            "asset_types": list(screen.asset_types),
            "exclude_dividend_cut": screen.exclude_dividend_cut,
            "min_equity_ratio": screen.min_equity_ratio,
            "max_expense_ratio": screen.max_expense_ratio,
            "nisa_eligible_only": screen.nisa_eligible_only,
            "min_diversification_score": screen.min_diversification_score,
            "sort_by": screen.sort_by,
            "limit": screen.limit,
        },
        "results": items,
        "count": len(items),
        "blocked_providers": blocked_providers,
        "fund_scoring_model": fund_scoring_model,
        "non_advisory_boundary": (
            "条件に一致した比較対象の提示のみです。買付・売却・保有継続を推奨しません。"
        ),
        "disclaimer": DISCLAIMER,
        "auto_trading": False,
        "call_real_api": False,
    }


def screen_from_values(
    *,
    asset_types: Sequence[str],
    exclude_dividend_cut: bool,
    min_equity_ratio: float | None,
    max_expense_ratio: float | None,
    nisa_eligible_only: bool,
    min_diversification_score: float | None,
    sort_by: str,
    limit: int | None,
) -> CandidateScreen:
    normalized = tuple(_asset_type(item) for item in asset_types if _asset_type(item))
    return CandidateScreen(
        asset_types=normalized or ("stock", "fund"),
        exclude_dividend_cut=exclude_dividend_cut,
        min_equity_ratio=min_equity_ratio,
        max_expense_ratio=max_expense_ratio,
        nisa_eligible_only=nisa_eligible_only,
        min_diversification_score=min_diversification_score,
        sort_by=sort_by or "score",
        limit=limit,
    )


def _stock_candidate(
    row: dict[str, object],
    screen: CandidateScreen,
    *,
    financials_source_ref: str,
    generated_at: str,
    company: dict[str, object] | None,
) -> dict[str, object]:
    metrics = row.get("metrics")
    metric_map = metrics if isinstance(metrics, dict) else {}
    conditions = ["EDINET財務データあり"]
    if screen.exclude_dividend_cut:
        conditions.append("減配履歴なし")
    if screen.min_equity_ratio is not None:
        conditions.append(f"自己資本比率 {screen.min_equity_ratio:g}% 以上")
    evidence = [
        {
            "claim_key": f"candidate.{row.get('ticker')}.edinet_financials",
            "source_type": "edinet_financials",
            "metric_key": "dividend/equity/operating_cf",
            "source_ref": financials_source_ref,
            "formula": "EDINET由来財務データを決定論ルールで集計",
            "last_updated": generated_at,
        }
    ]
    return {
        "asset_type": "stock",
        "code": row.get("ticker"),
        "name": row.get("name"),
        "score": row.get("total_score"),
        "matched_conditions": conditions,
        "metrics": metric_map,
        "edinet_summary": build_edinet_summary(
            company,
            financials_csv=financials_source_ref,
            generated_at=generated_at,
        )
        if company is not None
        else None,
        "evidence": evidence,
    }


def _fund_candidate(
    fund: FundProfile,
    screen: CandidateScreen,
    policy: dict[str, object],
    *,
    score_details: dict[str, object],
    generated_at: str,
) -> dict[str, object]:
    conditions = ["投信プロファイル入力あり"]
    if screen.max_expense_ratio is not None:
        conditions.append(f"信託報酬 {screen.max_expense_ratio:g}% 以下")
    if screen.nisa_eligible_only:
        conditions.append("NISA対象")
    if screen.min_diversification_score is not None:
        conditions.append(f"分散度 {screen.min_diversification_score:g} 以上")
    return {
        "asset_type": "fund",
        "code": fund.fund_code,
        "name": fund.name,
        "score": score_details["score"],
        "matched_conditions": conditions,
        "metrics": {
            "asset_class": fund.asset_class,
            "expense_ratio": fund.expense_ratio,
            "distribution_policy": fund.distribution_policy,
            "nisa_eligible": fund.nisa_eligible,
            "diversification_score": score_details["diversification_score"],
            "diversification_source": score_details["diversification_source"],
            "calculated_score": score_details["score"],
            "score_model": score_details["model_version"],
        },
        "scoring_model": _fund_scoring_model(),
        "score_breakdown": score_details["breakdown"],
        "provider_policy": policy,
        "evidence": [
            {
                "claim_key": f"candidate.{fund.fund_code}.fund_profile_score",
                "source_type": "fund_profile",
                "metric_key": "expense_ratio/nisa_eligible/diversification_score",
                "source_ref": fund.provider_id,
                "formula": score_details["formula"],
                "last_updated": generated_at,
            }
        ],
    }


def _fund_scoring_model() -> dict[str, object]:
    return {
        "model_version": "fund_weighted_v1",
        "formula": "sum(weight * normalized_score)",
        "weights": [
            {
                "key": "expense_ratio",
                "label": "低コスト性",
                "weight": FUND_SCORE_WEIGHTS["expense_ratio"],
            },
            {
                "key": "nisa_eligible",
                "label": "NISA適合",
                "weight": FUND_SCORE_WEIGHTS["nisa_eligible"],
            },
            {
                "key": "diversification",
                "label": "分散度",
                "weight": FUND_SCORE_WEIGHTS["diversification"],
            },
            {
                "key": "distribution_policy",
                "label": "分配方針",
                "weight": FUND_SCORE_WEIGHTS["distribution_policy"],
            },
        ],
        "note": (
            "投信スコアは条件比較のための機械集計です。"
            "売買推奨や将来リターン予測ではありません。"
        ),
    }


def _fund_score_details(fund: FundProfile) -> dict[str, object]:
    diversification, diversification_source = _fund_diversification_score(fund)
    normalized_scores = {
        "expense_ratio": _expense_ratio_score(fund.expense_ratio),
        "nisa_eligible": 1.0 if fund.nisa_eligible else 0.0,
        "diversification": diversification,
        "distribution_policy": _distribution_policy_score(fund.distribution_policy),
    }
    raw_values = {
        "expense_ratio": f"{fund.expense_ratio:g}%",
        "nisa_eligible": "対象" if fund.nisa_eligible else "対象外",
        "diversification": f"{diversification:g} ({diversification_source})",
        "distribution_policy": fund.distribution_policy,
    }
    formulas = {
        "expense_ratio": "max(0, 1 - 信託報酬(%) / 1.0)",
        "nisa_eligible": "NISA対象なら1、対象外なら0",
        "diversification": "入力値。未入力時は資産クラスの保守的な目安値",
        "distribution_policy": "再投資/無分配を1、分配型を0.7、毎月分配を0.45で正規化",
    }
    labels = {
        "expense_ratio": "低コスト性",
        "nisa_eligible": "NISA適合",
        "diversification": "分散度",
        "distribution_policy": "分配方針",
    }
    breakdown: list[dict[str, object]] = []
    total = 0.0
    for key, weight in FUND_SCORE_WEIGHTS.items():
        normalized_score = normalized_scores[key]
        contribution = weight * normalized_score
        total += contribution
        breakdown.append(
            {
                "key": key,
                "label": labels[key],
                "weight": weight,
                "raw_value": raw_values[key],
                "normalized_score": round(normalized_score, 6),
                "contribution": round(contribution, 6),
                "formula": formulas[key],
            }
        )
    return {
        "model_version": "fund_weighted_v1",
        "formula": "sum(weight * normalized_score)",
        "score": round(total, 6),
        "diversification_score": diversification,
        "diversification_source": diversification_source,
        "breakdown": breakdown,
    }


def _fund_diversification_score(fund: FundProfile) -> tuple[float, str]:
    if fund.diversification_score is not None:
        return _clamp01(fund.diversification_score), "user_input"
    asset_class = fund.asset_class.strip().lower() or "unknown"
    return (
        _FUND_ASSET_CLASS_DIVERSIFICATION_HINTS.get(asset_class, 0.50),
        f"asset_class:{asset_class}",
    )


def _expense_ratio_score(expense_ratio: float) -> float:
    return _clamp01(1.0 - max(expense_ratio, 0.0) / 1.0)


def _distribution_policy_score(policy: str) -> float:
    normalized = policy.strip().lower() or "unknown"
    return _FUND_DISTRIBUTION_POLICY_SCORES.get(normalized, 0.50)


def _clamp01(value: float) -> float:
    return min(1.0, max(0.0, value))


def _rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _company_index(financials_csv: str | Path) -> dict[str, dict[str, object]]:
    comparison = load_comparison(financials_csv)
    if comparison is None:
        return {}
    companies = comparison.get("companies")
    if not isinstance(companies, list):
        return {}
    out: dict[str, dict[str, object]] = {}
    for company in companies:
        if not isinstance(company, dict):
            continue
        ticker = str(company.get("ticker") or "").strip()
        if ticker:
            out[ticker] = company
    return out


def _sort(items: list[dict[str, object]], sort_by: str) -> list[dict[str, object]]:
    if sort_by == "expense_ratio":
        return sorted(items, key=lambda item: _expense_key(item))
    if sort_by == "name":
        return sorted(items, key=lambda item: str(item.get("name") or ""))
    return sorted(items, key=lambda item: (-_score(item), str(item.get("code") or "")))


def _score(item: dict[str, object]) -> float:
    value = item.get("score")
    return _float(value)


def _float(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def _expense_key(item: dict[str, object]) -> tuple[float, str]:
    metrics = item.get("metrics")
    if isinstance(metrics, dict):
        value = metrics.get("expense_ratio")
        if isinstance(value, int | float) and not isinstance(value, bool):
            return float(value), str(item.get("code") or "")
    return 999.0, str(item.get("code") or "")


def _asset_type(value: object) -> str:
    text = str(value or "").strip().lower()
    aliases = {"jp_stock": "stock", "japan_stock": "stock", "mutual_fund": "fund", "投信": "fund"}
    return aliases.get(text, text)
