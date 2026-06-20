"""Deterministic detail view for one stock or fund.

The detail payload is designed for comparison and evidence review. It does not
rank, recommend, or produce order instructions.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from investment_assistant.financials.evidence import DEFAULT_FINANCIALS_CSV, load_comparison
from investment_assistant.investment.analysis import analyze_portfolio
from investment_assistant.investment.models import DISCLAIMER, FundProfile, InvestmentHolding


def build_investment_detail(
    *,
    code: str,
    asset_type: str | None = None,
    holdings: Sequence[InvestmentHolding] = (),
    funds: Sequence[FundProfile] = (),
    financials_csv: str | Path = DEFAULT_FINANCIALS_CSV,
    market_financials_csv: str | Path | None = None,
) -> dict[str, object]:
    """Build a non-advisory detail view for a single code."""

    normalized_code = code.strip()
    if not normalized_code:
        raise ValueError("code is required")

    requested_type = _asset_type(asset_type)
    generated_at = datetime.now(UTC).isoformat()
    comparison = load_comparison(financials_csv)
    company = _find_company(comparison, normalized_code)
    fund = _find_fund(funds, normalized_code)
    market_row = _market_financials_row(market_financials_csv, normalized_code)
    matching_holdings = [
        holding
        for holding in holdings
        if holding.ticker_or_fund_code == normalized_code
        and (requested_type is None or holding.asset_type == requested_type)
    ]
    inferred_type = _infer_asset_type(requested_type, matching_holdings, company, fund)
    if inferred_type == "unknown" and market_row is not None:
        inferred_type = "stock"
    evidence: list[dict[str, object]] = []
    metrics: list[dict[str, object]] = []

    holding_summary: dict[str, object] | None = None
    holding_rows: list[dict[str, object]] = []
    if matching_holdings:
        analysis = analyze_portfolio(holdings, financials_csv=financials_csv)
        all_rows = analysis.get("holdings")
        if isinstance(all_rows, list):
            holding_rows = [
                row
                for row in all_rows
                if isinstance(row, dict)
                and str(row.get("ticker_or_fund_code") or "") == normalized_code
            ]
        holding_summary = _holding_summary(holding_rows)
        evidence.extend(_matching_evidence(analysis.get("evidence"), normalized_code))
        if holding_summary is not None:
            metrics.extend(
                [
                    _metric(
                        "holding.market_value",
                        "保有評価額",
                        holding_summary.get("market_value"),
                        "対象コードの保有数量 × 現在価格（未入力時は取得単価）",
                        _claim_keys(evidence, ".market_value"),
                        generated_at,
                    ),
                    _metric(
                        "holding.unrealized_pnl",
                        "評価損益",
                        holding_summary.get("unrealized_pnl"),
                        "対象コードの保有評価額 - 取得額",
                        _claim_keys(evidence, ".market_value")
                        + _claim_keys(evidence, ".cost_basis"),
                        generated_at,
                    ),
                    _metric(
                        "holding.annual_income_estimate",
                        "配当/分配金見込み",
                        holding_summary.get("annual_income_estimate"),
                        "ユーザー入力分配金、またはEDINET最新1株配当 × 数量",
                        _claim_keys(evidence, ".annual_income")
                        or _claim_keys(evidence, ".dividend"),
                        generated_at,
                    ),
                ]
            )

    if company is not None:
        claim_key = f"financials.{normalized_code}.summary"
        evidence.append(
            {
                "claim_key": claim_key,
                "source_type": "edinet_financials",
                "source_ref": str(financials_csv),
                "metric_key": "financial_statement_summary",
                "formula": "latest fiscal-year row and historical series from financials CSV",
                "last_updated": generated_at,
                "note": "EDINET由来CSVを機械集計した比較材料です。投資助言ではありません。",
            }
        )
        metrics.extend(_financial_metrics(company, claim_key, generated_at))

    if fund is not None:
        claim_key = f"fund.{normalized_code}.profile"
        evidence.append(
            {
                "claim_key": claim_key,
                "source_type": "fund_profile",
                "source_ref": fund.provider_id,
                "metric_key": "fund_profile_fields",
                "formula": "fund profile CSV/provider fields as provided",
                "last_updated": generated_at,
                "note": "投信プロファイルの条件確認用データです。推奨ではありません。",
            }
        )
        metrics.extend(_fund_metrics(fund, claim_key, generated_at))

    if market_row is not None:
        claim_key = f"market.{normalized_code}.yahoo"
        evidence.append(
            {
                "claim_key": claim_key,
                "source_type": "yahoo_market_financials",
                "source_ref": str(market_financials_csv),
                "metric_key": "market_quote",
                "formula": "latest scraped Yahoo quote row (price, dividend, yield, PER, PBR)",
                "last_updated": generated_at,
                "note": "Yahoo由来の市場データを機械集計した比較材料です。投資助言ではありません。",
            }
        )
        metrics.extend(_market_metrics(market_row, claim_key, generated_at))

    available = bool(
        matching_holdings or company is not None or fund is not None or market_row is not None
    )
    return {
        "available": available,
        "generated_at": generated_at,
        "asset_type": inferred_type,
        "code": normalized_code,
        "name": _display_name(normalized_code, matching_holdings, company, fund, market_row),
        "holding_summary": holding_summary,
        "holdings": holding_rows,
        "financials": company,
        "market_financials": market_row,
        "fund_profile": fund.to_dict() if fund is not None else None,
        "metrics": _dedupe_metrics(metrics),
        "sections": _sections(
            code=normalized_code,
            asset_type=inferred_type,
            holding_summary=holding_summary,
            company=company,
            fund=fund,
            market_row=market_row,
        ),
        "evidence": evidence,
        "non_advisory_boundary": (
            "この詳細は保有状況、財務、投信プロファイルを確認する比較材料です。"
            "買付・売却・保有継続を推奨せず、最終判断はユーザーが行います。"
        ),
        "disclaimer": DISCLAIMER,
        "auto_trading": False,
        "call_real_api": False,
    }


def _asset_type(value: str | None) -> str | None:
    text = str(value or "").strip().lower()
    if not text or text == "auto":
        return None
    aliases = {"jp_stock": "stock", "japan_stock": "stock", "mutual_fund": "fund"}
    return aliases.get(text, text)


def _find_company(
    comparison: dict[str, object] | None, code: str
) -> dict[str, object] | None:
    if comparison is None:
        return None
    companies = comparison.get("companies")
    if not isinstance(companies, list):
        return None
    for company in companies:
        if isinstance(company, dict) and str(company.get("ticker") or "") == code:
            return company
    return None


def _find_fund(funds: Sequence[FundProfile], code: str) -> FundProfile | None:
    for fund in funds:
        if fund.fund_code == code:
            return fund
    return None


def _infer_asset_type(
    requested_type: str | None,
    holdings: Sequence[InvestmentHolding],
    company: dict[str, object] | None,
    fund: FundProfile | None,
) -> str:
    if requested_type is not None:
        return requested_type
    if holdings:
        return holdings[0].asset_type
    if fund is not None:
        return "fund"
    if company is not None:
        return "stock"
    return "unknown"


def _display_name(
    code: str,
    holdings: Sequence[InvestmentHolding],
    company: dict[str, object] | None,
    fund: FundProfile | None,
    market_row: dict[str, object] | None = None,
) -> str:
    if holdings:
        return holdings[0].name
    if fund is not None:
        return fund.name
    if company is not None:
        return str(company.get("name") or code)
    if market_row is not None:
        name = str(market_row.get("name") or "").strip()
        if name:
            return name
    return code


def _market_financials_row(
    path: str | Path | None, code: str
) -> dict[str, object] | None:
    """Return the scraped Yahoo quote row for ``code`` (or ``None``)."""

    if path is None or not Path(path).is_file():
        return None
    import csv
    import io

    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "cp932", "utf-8"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
    wanted = _bare_code(code)
    reader = csv.DictReader(io.StringIO(text.strip().lstrip("﻿"), newline=""))
    for row in reader:
        ticker = str(row.get("ticker") or row.get("code") or "")
        if _bare_code(ticker) == wanted:
            return {str(key): value for key, value in row.items()}
    return None


def _bare_code(value: str) -> str:
    text = value.strip().upper()
    return text[:-2] if text.endswith(".T") else text


def _market_metrics(
    row: dict[str, object], claim_key: str, generated_at: str
) -> list[dict[str, object]]:
    specs = (
        ("market.price", "株価（Yahoo）", "price", "Yahooの現在株価"),
        ("market.dps", "1株配当（Yahoo）", "dps", "Yahooの1株配当（年額）"),
        (
            "market.dividend_yield_percent",
            "配当利回り%（Yahoo）",
            "dividend_yield_percent",
            "Yahooの配当利回り（％）",
        ),
        ("market.per", "PER（Yahoo）", "per", "Yahooのトレーリング PER"),
        ("market.pbr", "PBR（Yahoo）", "pbr", "Yahooの PBR"),
    )
    metrics: list[dict[str, object]] = []
    for key, label, field, formula in specs:
        value = _number(row.get(field))
        if value is None:
            continue
        metrics.append(_metric(key, label, value, formula, [claim_key], generated_at))
    return metrics


def _holding_summary(rows: Sequence[dict[str, object]]) -> dict[str, object] | None:
    if not rows:
        return None
    market_value = sum(_number(row.get("market_value")) or 0.0 for row in rows)
    cost_basis = sum(_number(row.get("cost_basis")) or 0.0 for row in rows)
    annual_income = sum(
        _number(row.get("annual_income_estimate")) or 0.0 for row in rows
    )
    return {
        "lots": len(rows),
        "market_value": round(market_value, 2),
        "cost_basis": round(cost_basis, 2),
        "unrealized_pnl": round(market_value - cost_basis, 2),
        "unrealized_pnl_pct": round((market_value - cost_basis) / cost_basis * 100.0, 2)
        if cost_basis
        else 0.0,
        "annual_income_estimate": round(annual_income, 2),
        "income_yield_pct": round(annual_income / market_value * 100.0, 2)
        if market_value
        else 0.0,
    }


def _matching_evidence(value: object, code: str) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    prefix = f"holding.{code}."
    return [
        item
        for item in value
        if isinstance(item, dict) and str(item.get("claim_key") or "").startswith(prefix)
    ]


def _financial_metrics(
    company: dict[str, object], claim_key: str, generated_at: str
) -> list[dict[str, object]]:
    cut_years = company.get("dividend_cut_years")
    cut_value: object = cut_years if isinstance(cut_years, list) else []
    return [
        _metric(
            "financials.latest_equity_ratio",
            "自己資本比率",
            company.get("latest_equity_ratio"),
            "最新年度の自己資本比率",
            [claim_key],
            generated_at,
        ),
        _metric(
            "financials.latest_dividend_per_share",
            "1株配当",
            company.get("latest_dividend_per_share"),
            "最新年度の1株配当",
            [claim_key],
            generated_at,
        ),
        _metric(
            "financials.dividend_cut_years",
            "減配年度",
            cut_value,
            "年度順の1株配当が前年を下回った年度",
            [claim_key],
            generated_at,
        ),
        _metric(
            "financials.operating_cf_trend",
            "営業CF傾向",
            company.get("operating_cf_trend"),
            "年度順の営業CF系列から機械分類",
            [claim_key],
            generated_at,
        ),
    ]


def _fund_metrics(
    fund: FundProfile, claim_key: str, generated_at: str
) -> list[dict[str, object]]:
    return [
        _metric(
            "fund.expense_ratio",
            "信託報酬",
            fund.expense_ratio,
            "投信プロファイルの信託報酬",
            [claim_key],
            generated_at,
        ),
        _metric(
            "fund.nisa_eligible",
            "NISA対象",
            fund.nisa_eligible,
            "投信プロファイルのNISA対象フラグ",
            [claim_key],
            generated_at,
        ),
        _metric(
            "fund.asset_class",
            "資産クラス",
            fund.asset_class,
            "投信プロファイルの資産クラス",
            [claim_key],
            generated_at,
        ),
        _metric(
            "fund.diversification_score",
            "分散度",
            fund.diversification_score,
            "投信プロファイルの分散度スコア",
            [claim_key],
            generated_at,
        ),
    ]


def _metric(
    key: str,
    label: str,
    value: object,
    formula: str,
    evidence_keys: Sequence[str],
    last_updated: str,
) -> dict[str, object]:
    return {
        "metric_key": key,
        "label": label,
        "value": value,
        "formula": formula,
        "evidence_keys": list(dict.fromkeys(evidence_keys)),
        "last_updated": last_updated,
        "disclaimer": DISCLAIMER,
    }


def _claim_keys(evidence: Sequence[dict[str, object]], suffix: str) -> list[str]:
    return [
        str(item.get("claim_key"))
        for item in evidence
        if str(item.get("claim_key") or "").endswith(suffix)
    ]


def _dedupe_metrics(metrics: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    seen: set[str] = set()
    for metric in metrics:
        key = str(metric.get("metric_key") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(dict(metric))
    return out


def _sections(
    *,
    code: str,
    asset_type: str,
    holding_summary: dict[str, object] | None,
    company: dict[str, object] | None,
    fund: FundProfile | None,
    market_row: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    sections: list[dict[str, object]] = [
        {
            "key": "boundary",
            "title": "非助言の境界",
            "body": (
                f"{code} の詳細を比較材料として表示します。"
                "買付・売却・保有継続の判断は代行しません。"
            ),
        }
    ]
    if holding_summary is not None:
        sections.append(
            {
                "key": "holding",
                "title": "保有状況",
                "body": (
                    f"評価額 {holding_summary.get('market_value')} 円、"
                    f"評価損益 {holding_summary.get('unrealized_pnl')} 円、"
                    f"配当/分配金見込み {holding_summary.get('annual_income_estimate')} 円。"
                ),
            }
        )
    if asset_type == "stock" and company is not None:
        sections.append(
            {
                "key": "financials",
                "title": "財務・配当",
                "body": (
                    f"最新年度は FY{company.get('latest_fiscal_year')}。"
                    f"自己資本比率 {company.get('latest_equity_ratio')}%、"
                    f"1株配当 {company.get('latest_dividend_per_share')}。"
                ),
            }
        )
    if asset_type == "fund" and fund is not None:
        sections.append(
            {
                "key": "fund",
                "title": "投信プロファイル",
                "body": (
                    f"資産クラス {fund.asset_class}、信託報酬 {fund.expense_ratio}%、"
                    f"NISA対象 {fund.nisa_eligible}。"
                ),
            }
        )
    if market_row is not None:
        price = _number(market_row.get("price"))
        dps = _number(market_row.get("dps"))
        yield_pct = _number(market_row.get("dividend_yield_percent"))
        sections.append(
            {
                "key": "market",
                "title": "市場データ（Yahoo）",
                "body": (
                    f"株価 {price} 円、1株配当 {dps} 円、"
                    f"配当利回り {yield_pct}%。取得済みYahooデータの機械集計です。"
                ),
            }
        )
    return sections


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None
