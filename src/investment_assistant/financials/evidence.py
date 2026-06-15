"""Build dividend / financial-trend evidence text for grounding answers.

Turns the mechanical comparison (from EDINET-derived financials) into a compact,
non-advisory evidence block that can be injected into the AI Chat prompt so
answers about a ticker are grounded in the actual dividend-cut history and
operating-cash-flow / equity-ratio trends — not just RAG text.
"""

from __future__ import annotations

import re
from pathlib import Path

from investment_assistant.financials.dividend_quality import normalize_dividend_points
from investment_assistant.financials.loader import compare_financials, load_financials

DEFAULT_FINANCIALS_CSV = "local_docs/edinet/financials.csv"

_TREND_JP: dict[str, str] = {
    "increasing": "増加傾向",
    "declining": "減少傾向",
    "flat": "横ばい",
    "mixed": "増減混在",
    "insufficient": "データ不足",
}

_TICKER_RE = re.compile(r"\d{4}")


def load_comparison(csv_path: str | Path = DEFAULT_FINANCIALS_CSV) -> dict[str, object] | None:
    """Load and compare a financials CSV, or return ``None`` if unavailable."""

    path = Path(csv_path)
    if not path.is_file():
        return None
    try:
        points, _ = normalize_dividend_points(load_financials(path))
        return compare_financials(points)
    except (ValueError, OSError):
        return None


def ticker_from_source(target_source: str | None) -> str | None:
    """Extract the first 4-digit ticker code from a source path/label."""

    if not target_source:
        return None
    match = _TICKER_RE.search(target_source)
    return match.group(0) if match else None


def find_company(comparison: dict[str, object], ticker: str) -> dict[str, object] | None:
    companies = comparison.get("companies")
    if not isinstance(companies, list):
        return None
    for company in companies:
        if isinstance(company, dict) and str(company.get("ticker")) == ticker:
            return company
    return None


def dividend_evidence_text(company: dict[str, object]) -> str:
    """Render a company's dividend / trend record as a grounding block."""

    cuts = company.get("dividend_cut_years")
    cut_years = [str(year) for year in cuts] if isinstance(cuts, list) else []
    series = company.get("dividend_series")
    dividend_path = (
        " → ".join(str(value) for value in series)
        if isinstance(series, list) and series
        else "不明"
    )
    cut_note = f"（減配年: {', '.join(cut_years)}）" if cut_years else "（減配履歴なし）"

    years = company.get("years")
    n_periods = len(years) if isinstance(years, list) else 0

    lines = [
        "【財務根拠（EDINET公式数値・機械集計）】",
        f"対象: {company.get('ticker')} {company.get('name')}",
        f"配当推移: {_trend(company.get('dividend_trend'))}{cut_note}",
        f"1株当たり配当の推移: {dividend_path}",
        f"営業CF推移: {_trend(company.get('operating_cf_trend'))}",
        f"自己資本比率推移: {_trend(company.get('equity_ratio_trend'))}",
        (
            f"最新(FY{company.get('latest_fiscal_year')}): "
            f"営業CF={company.get('latest_operating_cf')} / "
            f"自己資本比率={company.get('latest_equity_ratio')} / "
            f"1株配当={company.get('latest_dividend_per_share')}"
        ),
    ]
    if n_periods <= 1:
        lines.append(
            "※ 現在1期のみ取得。推移は次期取得後に算出（上記「最新」は取得済みの実数値）。"
        )
    lines.append("※ 取得済みEDINETデータの機械的集計であり、投資助言ではありません。")
    return "\n".join(lines)


def build_financial_evidence(
    *,
    ticker: str | None = None,
    target_source: str | None = None,
    csv_path: str | Path = DEFAULT_FINANCIALS_CSV,
) -> str | None:
    """Resolve a ticker and return its evidence block, or ``None`` if unavailable."""

    resolved = (ticker or "").strip() or ticker_from_source(target_source)
    if not resolved:
        return None
    comparison = load_comparison(csv_path)
    if comparison is None:
        return None
    company = find_company(comparison, resolved)
    if company is None:
        return None
    return dividend_evidence_text(company)


def _trend(value: object) -> str:
    return _TREND_JP.get(str(value), str(value))
