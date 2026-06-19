"""Deterministic investment monthly report rendering."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from investment_assistant.financials.evidence import DEFAULT_FINANCIALS_CSV
from investment_assistant.investment.analysis import analyze_portfolio
from investment_assistant.investment.models import DISCLAIMER, InvestmentHolding
from investment_assistant.investment.report_audit import audit_investment_report


def build_investment_monthly_report(
    holdings: Sequence[InvestmentHolding],
    *,
    candidates: Sequence[dict[str, object]] = (),
    target_result: Mapping[str, object] | None = None,
    financials_csv: str | Path = DEFAULT_FINANCIALS_CSV,
    market_financials_csv: str | Path | None = None,
    runtime_mode: str = "development",
) -> dict[str, object]:
    """Build a non-advisory monthly report from computed facts."""

    analysis = analyze_portfolio(
        holdings,
        financials_csv=financials_csv,
        market_financials_csv=market_financials_csv,
        runtime_mode=runtime_mode,
    )
    summary = analysis["summary"]
    if not isinstance(summary, dict):
        raise ValueError("portfolio analysis did not return a summary")
    generated_at = datetime.now(UTC).isoformat()
    evidence = list(_evidence_rows(analysis.get("evidence")))
    evidence.append(
        {
            "claim_key": "portfolio.concentration.current",
            "source_type": "computed_portfolio",
            "source_ref": "holdings.market_value",
            "metric_key": "concentration",
            "formula": "market value weights -> top weight, HHI, inverse HHI",
            "last_updated": generated_at,
            "note": "保有評価額の構成比から機械的に集中度を計算します。",
        }
    )
    for item in candidates[:10]:
        evidence.append(
            {
                "claim_key": f"candidate.{item.get('code')}",
                "source_type": "candidate_screen",
                "source_ref": item.get("asset_type"),
                "metric_key": "matched_conditions",
                "formula": "candidate matched the configured deterministic screen conditions",
                "last_updated": generated_at,
                "note": "条件一致の比較候補であり、推奨ではありません。",
            }
        )
    target = _mapping(target_result.get("target")) if target_result is not None else None
    target_summary = _mapping(target_result.get("summary")) if target_result is not None else None
    target_concentration = (
        _mapping(target_summary.get("concentration")) if target_summary is not None else None
    )
    if target is not None:
        evidence.extend(_target_evidence_rows(target, target_concentration, generated_at))
    kpis = [
        _kpi(
            "market_value",
            "評価額",
            summary.get("market_value"),
            _claim_keys(evidence, suffix=".market_value"),
            generated_at,
            value_format="yen",
        ),
        _kpi(
            "unrealized_pnl",
            "評価損益",
            summary.get("unrealized_pnl"),
            [
                *_claim_keys(evidence, suffix=".market_value"),
                *_claim_keys(evidence, suffix=".cost_basis"),
            ],
            generated_at,
            value_format="yen",
        ),
        _kpi(
            "annual_income_estimate",
            "配当/分配金見込み",
            summary.get("annual_income_estimate"),
            _claim_keys(evidence, suffix=".annual_income")
            or _claim_keys(evidence, suffix=".dividend"),
            generated_at,
            value_format="yen",
        ),
        _kpi(
            "nisa_remaining",
            "NISA残枠",
            _nisa_remaining(summary),
            _claim_keys(evidence, prefix="portfolio.nisa"),
            generated_at,
            value_format="yen",
        ),
        _kpi(
            "concentration_top_weight",
            "最大銘柄比率",
            _current_top_weight_pct(summary),
            ["portfolio.concentration.current"],
            generated_at,
            value_format="percent",
        ),
        _kpi(
            "concentration_hhi",
            "HHI",
            _current_hhi(summary),
            ["portfolio.concentration.current"],
            generated_at,
            value_format="number",
        ),
        _kpi(
            "concentration_effective_names",
            "実効銘柄数",
            _current_effective_names(summary),
            ["portfolio.concentration.current"],
            generated_at,
            value_format="number",
        ),
    ]
    if target is not None:
        kpis.extend(
            [
                _kpi(
                    "target_annual_dividend",
                    "目標年間配当",
                    target.get("target_annual_dividend"),
                    ["portfolio.target.input"],
                    generated_at,
                    value_format="yen",
                ),
                _kpi(
                    "target_achieved_annual_dividend",
                    "達成見込み配当",
                    target.get("achieved_annual_dividend"),
                    ["portfolio.target.achieved"],
                    generated_at,
                    value_format="yen",
                ),
                _kpi(
                    "target_required_budget",
                    "必要予算",
                    target.get("required_budget"),
                    ["portfolio.target.required_budget"],
                    generated_at,
                    value_format="yen",
                ),
                _kpi(
                    "target_reachable",
                    "到達可否",
                    "到達可能" if target.get("reachable") is True else "要条件見直し",
                    ["portfolio.target.reachable"],
                    generated_at,
                    value_format="text",
                ),
                _kpi(
                    "target_concentration_top_weight",
                    "逆算後 最大銘柄比率",
                    _target_top_weight_pct(target_concentration),
                    ["portfolio.target.concentration"],
                    generated_at,
                    value_format="percent",
                ),
                _kpi(
                    "target_concentration_hhi",
                    "逆算後 HHI",
                    _target_hhi(target_concentration),
                    ["portfolio.target.concentration"],
                    generated_at,
                    value_format="number",
                ),
                _kpi(
                    "target_effective_names",
                    "逆算後 実効銘柄数",
                    _target_effective_names(target_concentration),
                    ["portfolio.target.concentration"],
                    generated_at,
                    value_format="number",
                ),
            ]
        )
    sections = [
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
                f"{_top3(summary)}%、HHI {_current_hhi(summary)}、"
                f"実効銘柄数 {_current_effective_names(summary)}。"
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
    ]
    data_quality = _mapping(summary.get("data_quality"))
    data_alert_count = data_quality.get("alert_count") if data_quality is not None else 0
    if (
        data_quality is not None
        and isinstance(data_alert_count, int | float)
        and data_alert_count > 0
    ):
        sections.append(
            {
                "key": "data_quality",
                "title": "Data quality",
                "body": (
                    f"Status {data_quality.get('status')}; "
                    f"alerts {data_alert_count}; "
                    f"provider blocks {data_quality.get('provider_blocked_count')}; "
                    f"missing price {data_quality.get('missing_price_count')}; "
                    f"stale price {data_quality.get('stale_price_count')}; "
                    f"stale financials {data_quality.get('stale_financials_count')}. "
                    "These are data review prompts, not trading recommendations."
                ),
            }
        )
    income_quality = _mapping(summary.get("income_quality"))
    income_alert_count = income_quality.get("alert_count") if income_quality is not None else 0
    if (
        income_quality is not None
        and isinstance(income_alert_count, int | float)
        and income_alert_count > 0
    ):
        sections.append(
            {
                "key": "income_quality",
                "title": "Income quality",
                "body": (
                    f"Status {income_quality.get('status')}; "
                    f"alerts {income_alert_count}; "
                    f"missing income {income_quality.get('missing_income_count')}; "
                    f"high yield {income_quality.get('high_yield_count')}; "
                    f"negative input {income_quality.get('negative_input_count')}. "
                    "These are data review prompts, not trading recommendations."
                ),
            }
        )
    if target is not None:
        reachability = "到達可能" if target.get("reachable") is True else "要条件見直し"
        sections.append(
            {
                "key": "target",
                "title": "目標配当からの逆算",
                "body": (
                    f"目標 {target.get('target_annual_dividend')} 円に対し、"
                    f"達成見込み {target.get('achieved_annual_dividend')} 円、"
                    f"必要予算 {target.get('required_budget')} 円。"
                    f"到達可否は {reachability}。"
                ),
            }
        )
    sections.append(
        {
            "key": "candidates",
            "title": "候補抽出結果",
            "body": (
                f"条件一致候補 {len(candidates)} 件。"
                "これは推奨ではなく比較対象の提示です。"
            ),
        }
    )
    report: dict[str, object] = {
        "title": "投資月次レポート",
        "generated_at": generated_at,
        "kpis": kpis,
        "sections": sections,
        "portfolio": analysis,
        "target": target_result,
        "candidate_count": len(candidates),
        "evidence": evidence,
        "disclaimer": DISCLAIMER,
        "auto_trading": False,
        "call_real_api": False,
    }
    report["publish_audit"] = audit_investment_report(report)
    return report


def _kpi(
    key: str,
    label: str,
    value: object,
    evidence_keys: Sequence[str],
    last_updated: str,
    value_format: str = "number",
) -> dict[str, object]:
    return {
        "metric_key": key,
        "label": label,
        "value": value,
        "value_format": value_format,
        "evidence_keys": list(dict.fromkeys(evidence_keys)),
        "formula": _formula(key),
        "last_updated": last_updated,
        "disclaimer": DISCLAIMER,
    }


def _formula(key: str) -> str:
    formulas = {
        "market_value": "数量 × 現在価格（未入力時は取得単価）",
        "unrealized_pnl": "評価額 - 取得額",
        "annual_income_estimate": "ユーザー入力分配金、またはEDINET最新1株配当 × 数量",
        "nisa_remaining": "18,000,000円 - NISA口座の取得額合計",
        "concentration_top_weight": "最大保有銘柄の評価額 ÷ ポートフォリオ評価額",
        "concentration_hhi": "各保有比率の2乗和",
        "concentration_effective_names": "1 ÷ HHI",
        "target_annual_dividend": "ユーザー入力の目標年間配当",
        "target_achieved_annual_dividend": "逆算後の株数 × 保守的な1株配当の合計",
        "target_required_budget": "逆算後の株数 × 価格の合計",
        "target_reachable": "達成見込み配当 >= 目標年間配当",
        "target_concentration_top_weight": "逆算後の最大投資額 ÷ 逆算後の必要予算",
        "target_concentration_hhi": "逆算後の投資額構成比の2乗和",
        "target_effective_names": "逆算後の 1 ÷ HHI",
    }
    return formulas.get(key, "機械集計")


def _target_evidence_rows(
    target: Mapping[str, object],
    concentration: Mapping[str, object] | None,
    generated_at: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = [
        {
            "claim_key": "portfolio.target.input",
            "source_type": "user_input",
            "source_ref": "target_annual_dividend",
            "metric_key": "target_annual_dividend",
            "formula": "user-entered target annual dividend",
            "last_updated": generated_at,
            "note": "目標値はユーザー入力であり、達成を保証しません。",
        },
        {
            "claim_key": "portfolio.target.achieved",
            "source_type": "deterministic_target_planner",
            "source_ref": "plan_for_target_dividend",
            "metric_key": "achieved_annual_dividend",
            "formula": "sum(planned shares * conservative dividend per share)",
            "last_updated": generated_at,
            "note": "配当は安全側の機械試算です。",
        },
        {
            "claim_key": "portfolio.target.required_budget",
            "source_type": "deterministic_target_planner",
            "source_ref": "plan_for_target_dividend",
            "metric_key": "required_budget",
            "formula": "sum(planned shares * price)",
            "last_updated": generated_at,
            "note": "必要予算は売買推奨ではなく、条件一致時の試算です。",
        },
        {
            "claim_key": "portfolio.target.reachable",
            "source_type": "deterministic_target_planner",
            "source_ref": "plan_for_target_dividend",
            "metric_key": "reachable",
            "formula": "achieved_annual_dividend >= target_annual_dividend",
            "last_updated": generated_at,
            "note": f"reachable={target.get('reachable')}",
        },
    ]
    if concentration is not None:
        rows.append(
            {
                "claim_key": "portfolio.target.concentration",
                "source_type": "deterministic_target_planner",
                "source_ref": "plan_for_target_dividend.summary.concentration",
                "metric_key": "target_concentration",
                "formula": "planned invested weights -> top weight, HHI, inverse HHI",
                "last_updated": generated_at,
                "note": "逆算結果の投資額構成比から機械的に集中度を計算します。",
            }
        )
    return rows


def _evidence_rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _claim_keys(
    evidence: Sequence[dict[str, object]],
    *,
    prefix: str | None = None,
    suffix: str | None = None,
) -> list[str]:
    keys: list[str] = []
    for row in evidence:
        key = row.get("claim_key")
        if not isinstance(key, str):
            continue
        if prefix is not None and not key.startswith(prefix):
            continue
        if suffix is not None and not key.endswith(suffix):
            continue
        keys.append(key)
    return keys


def _nisa_remaining(summary: dict[str, object]) -> object:
    nisa = summary.get("nisa")
    return nisa.get("remaining_lifetime") if isinstance(nisa, dict) else None


def _nisa_growth_remaining(summary: dict[str, object]) -> object:
    nisa = summary.get("nisa")
    return nisa.get("growth_remaining") if isinstance(nisa, dict) else None


def _mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _current_concentration(summary: dict[str, object]) -> Mapping[str, object] | None:
    return _mapping(summary.get("concentration"))


def _current_hhi(summary: dict[str, object]) -> object:
    concentration = _current_concentration(summary)
    return concentration.get("hhi") if concentration is not None else None


def _current_effective_names(summary: dict[str, object]) -> object:
    concentration = _current_concentration(summary)
    return concentration.get("effective_names") if concentration is not None else None


def _current_top_weight_pct(summary: dict[str, object]) -> object:
    concentration = _current_concentration(summary)
    if concentration is None:
        return None
    weight = concentration.get("top_weight")
    return round(float(weight) * 100.0, 2) if isinstance(weight, int | float) else None


def _target_hhi(concentration: Mapping[str, object] | None) -> object:
    return concentration.get("hhi") if concentration is not None else None


def _target_effective_names(concentration: Mapping[str, object] | None) -> object:
    return concentration.get("effective_names") if concentration is not None else None


def _target_top_weight_pct(concentration: Mapping[str, object] | None) -> object:
    if concentration is None:
        return None
    weight = concentration.get("top_weight")
    return round(float(weight) * 100.0, 2) if isinstance(weight, int | float) else None


def _largest(summary: dict[str, object]) -> str:
    largest = summary.get("largest_position")
    if not isinstance(largest, dict):
        return "不明"
    return f"{largest.get('code')} {largest.get('name')}（{largest.get('share_pct')}%）"


def _top3(summary: dict[str, object]) -> object:
    concentration = summary.get("concentration")
    return concentration.get("top3_share_pct") if isinstance(concentration, dict) else None
