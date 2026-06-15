"""Market universe helpers for non-advisory stock selection.

This module deliberately separates *security selection metadata* from market
prices or index weights. JPX market segment data and Nikkei 225 membership are
used only to help the user narrow a comparison universe; they are not trading
signals.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from investment_assistant.edinet.registry import build_edinet_targets_from_registry
from investment_assistant.financials import compare_financials, load_financials
from investment_assistant.financials.dividend_quality import normalize_dividend_points
from investment_assistant.financials.evidence import DEFAULT_FINANCIALS_CSV

DEFAULT_NIKKEI225_REGISTRY = "examples/source_registry_nikkei225_edinet.yaml"
DEFAULT_JPX_LISTED_ISSUES_PATH = "local_docs/jpx/listed_issues.csv"
JPX_LISTED_ISSUES_PAGE_URL = "https://www.jpx.co.jp/markets/statistics-equities/misc/01.html"
JPX_LISTED_ISSUES_FILE_URL = (
    "https://www.jpx.co.jp/markets/statistics-equities/misc/"
    "tvdivq0000001vg2-att/data_j.xls"
)
JPX_DATA_PORTAL_URL = "https://clientportal.jpx.co.jp/"
NIKKEI225_COMPONENTS_URL = "https://indexes.nikkei.co.jp/en/nkave/index/component?idx=nk225"

_CODE_RE = re.compile(r"^[0-9A-Za-z]{4}")

_CODE_COLUMNS = ("コード", "code", "local code", "銘柄コード", "security code")
_NAME_COLUMNS = ("銘柄名", "name", "issue name", "company name", "銘柄")
_MARKET_COLUMNS = ("市場・商品区分", "market segment", "market", "市場区分")
_SECTOR_COLUMNS = ("33業種区分", "sector", "33 sector", "業種")
_DATE_COLUMNS = ("日付", "date", "as_of", "基準日")


@dataclass(frozen=True)
class ListedIssue:
    code: str
    name: str
    market_segment: str
    sector: str = ""
    as_of: str = ""
    source_ref: str = ""

    @property
    def is_prime(self) -> bool:
        return is_prime_segment(self.market_segment)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        raw_segment = self.market_segment
        display_segment = display_market_segment(raw_segment)
        payload["market_segment_raw"] = raw_segment
        payload["market_segment"] = display_segment
        payload["market_segment_label"] = display_segment
        payload["is_prime"] = self.is_prime
        return payload


def source_manifest() -> dict[str, object]:
    """Return official source references and licensing cautions."""

    return {
        "jpx_listed_issues": {
            "label": "JPX 東証上場銘柄一覧",
            "page_url": JPX_LISTED_ISSUES_PAGE_URL,
            "file_url": JPX_LISTED_ISSUES_FILE_URL,
            "data_portal_url": JPX_DATA_PORTAL_URL,
            "usage": (
                "市場区分による銘柄選択補助のみ。"
                "価格・指数ウェイト・再配布用途には使いません。"
            ),
        },
        "nikkei225_components": {
            "label": "Nikkei 225 Components",
            "page_url": NIKKEI225_COMPONENTS_URL,
            "usage": "日経225構成銘柄フラグの表示のみ。指数データやウェイトの再配布は扱いません。",
        },
        "non_advisory_boundary": (
            "市場区分と指数構成フラグは比較対象を絞るための表示です。"
            "買付・売却・保有継続を推奨しません。"
        ),
        "auto_trading": False,
        "call_real_api": False,
    }


def jpx_listed_issue_template() -> dict[str, object]:
    csv_text = (
        "日付,コード,銘柄名,市場・商品区分,33業種区分\n"
        "2026-05-31,7203,トヨタ自動車,プライム（国内株式）,輸送用機器\n"
        "2026-05-31,8306,三菱ＵＦＪフィナンシャル・グループ,プライム（国内株式）,銀行業\n"
        "2026-05-31,9999,サンプルスタンダード,スタンダード（国内株式）,サービス業\n"
    )
    return {
        "kind": "jpx_listed_issues",
        "csv_text": csv_text,
        "required_columns": ["コード", "銘柄名", "市場・商品区分"],
        "optional_columns": ["日付", "33業種区分"],
        "sources": source_manifest(),
        "auto_trading": False,
        "call_real_api": False,
    }


def parse_jpx_listed_issues_text(text: str, *, source_ref: str = "") -> list[ListedIssue]:
    """Parse JPX listed issue data exported as CSV/TSV.

    The official JPX monthly file is distributed as legacy ``.xls``. To keep the
    app dependency-free, this parser accepts the same table after it has been
    exported or copied as CSV/TSV.
    """

    normalized = text.strip()
    if not normalized:
        raise ValueError("JPX listed issue data is empty.")
    delimiter = _detect_delimiter(normalized)
    reader = csv.DictReader(io.StringIO(normalized), delimiter=delimiter)
    headers = [str(name or "").strip() for name in (reader.fieldnames or [])]
    code_col = _find_header(headers, _CODE_COLUMNS)
    name_col = _find_header(headers, _NAME_COLUMNS)
    market_col = _find_header(headers, _MARKET_COLUMNS)
    sector_col = _find_header(headers, _SECTOR_COLUMNS)
    date_col = _find_header(headers, _DATE_COLUMNS)
    missing = [
        label
        for label, column in (
            ("コード", code_col),
            ("銘柄名", name_col),
            ("市場・商品区分", market_col),
        )
        if column is None
    ]
    if missing:
        raise ValueError(f"JPX listed issue data is missing columns: {', '.join(missing)}")

    issues: list[ListedIssue] = []
    for row in reader:
        code = normalize_security_code(row.get(code_col or ""))
        if not code:
            continue
        issues.append(
            ListedIssue(
                code=code,
                name=str(row.get(name_col or "") or "").strip(),
                market_segment=str(row.get(market_col or "") or "").strip(),
                sector=str(row.get(sector_col or "") or "").strip() if sector_col else "",
                as_of=str(row.get(date_col or "") or "").strip() if date_col else "",
                source_ref=source_ref,
            )
        )
    if not issues:
        raise ValueError("JPX listed issue data has no usable rows.")
    return issues


def load_jpx_listed_issues(path: str | Path = DEFAULT_JPX_LISTED_ISSUES_PATH) -> list[ListedIssue]:
    csv_path = Path(path)
    if not csv_path.is_file():
        return []
    return parse_jpx_listed_issues_text(
        csv_path.read_text(encoding="utf-8"),
        source_ref=str(csv_path),
    )


def write_jpx_listed_issues(issues: list[ListedIssue], path: str | Path) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["日付", "コード", "銘柄名", "市場・商品区分", "33業種区分"],
        )
        writer.writeheader()
        for issue in issues:
            writer.writerow(
                {
                    "日付": issue.as_of,
                    "コード": issue.code,
                    "銘柄名": issue.name,
                    "市場・商品区分": issue.market_segment,
                    "33業種区分": issue.sector,
                }
            )
    return str(target)


def build_market_universe(
    *,
    financials_csv: str | Path = DEFAULT_FINANCIALS_CSV,
    jpx_listed_path: str | Path = DEFAULT_JPX_LISTED_ISSUES_PATH,
    nikkei225_registry: str | Path = DEFAULT_NIKKEI225_REGISTRY,
    query: str = "",
    scope: str = "prime",
    limit: int = 50,
) -> dict[str, object]:
    listed = {issue.code: issue for issue in load_jpx_listed_issues(jpx_listed_path)}
    nikkei = nikkei225_index(nikkei225_registry)
    financials = _financials_index(financials_csv)

    codes = set(financials) | set(listed) | set(nikkei)
    rows = [_universe_row(code, financials, listed, nikkei) for code in codes]
    scoped = [_row for _row in rows if _in_scope(_row, scope)]
    searched = [_row for _row in scoped if _matches_query(_row, query)]
    searched.sort(key=_universe_sort_key)
    clipped = searched[: max(limit, 1)]
    prime_available = bool(listed)
    return {
        "available": True,
        "scope": scope,
        "query": query,
        "count": len(clipped),
        "total_count": len(searched),
        "securities": clipped,
        "universe": clipped,
        "jpx_listed_available": prime_available,
        "jpx_listed_count": len(listed),
        "nikkei225_count": len(nikkei),
        "financials_available": bool(financials),
        "financials_count": len(financials),
        "sources": source_manifest(),
        "hint": _scope_hint(scope, prime_available),
        "auto_trading": False,
        "call_real_api": False,
    }


def nikkei225_index(
    registry_path: str | Path = DEFAULT_NIKKEI225_REGISTRY,
) -> dict[str, dict[str, object]]:
    try:
        targets = build_edinet_targets_from_registry(registry_path)
    except (OSError, ValueError):
        return {}
    return {
        target.ticker: {
            "ticker": target.ticker,
            "name": target.company or target.name,
            "source_ref": str(registry_path),
        }
        for target in targets
    }


def normalize_security_code(value: object) -> str:
    text = str(value or "").strip()
    if text.endswith(".0"):
        text = text[:-2]
    match = _CODE_RE.match(text)
    return match.group(0).upper() if match else ""


def is_prime_segment(value: object) -> bool:
    text = str(value or "").strip().lower()
    return "プライム" in text or "prime" in text


def display_market_segment(value: object) -> str:
    """Return a user-facing market segment label without mutating source data."""

    text = str(value or "").strip()
    if not text:
        return "未取込"
    return text.replace("内国株式", "国内株式")


def _detect_delimiter(text: str) -> str:
    first = text.splitlines()[0] if text.splitlines() else ""
    if "\t" in first:
        return "\t"
    try:
        return csv.Sniffer().sniff(text[:2048], delimiters=",\t;").delimiter
    except csv.Error:
        return ","


def _find_header(headers: list[str], aliases: tuple[str, ...]) -> str | None:
    lowered = {header.lower().strip(): header for header in headers}
    for alias in aliases:
        hit = lowered.get(alias.lower())
        if hit is not None:
            return hit
    for header in headers:
        normalized = header.lower().strip()
        if any(alias.lower() in normalized for alias in aliases):
            return header
    return None


def _financials_index(path: str | Path) -> dict[str, dict[str, object]]:
    csv_path = Path(path)
    if not csv_path.is_file():
        return {}
    try:
        points, _ = normalize_dividend_points(load_financials(csv_path))
        comparison = compare_financials(points)
    except (OSError, ValueError):
        return {}
    companies = comparison.get("companies")
    if not isinstance(companies, list):
        return {}
    out: dict[str, dict[str, object]] = {}
    for company in companies:
        if not isinstance(company, dict):
            continue
        code = normalize_security_code(company.get("ticker"))
        if code:
            out[code] = company
    return out


def _universe_row(
    code: str,
    financials: dict[str, dict[str, object]],
    listed: dict[str, ListedIssue],
    nikkei: dict[str, dict[str, object]],
) -> dict[str, object]:
    financial = financials.get(code, {})
    listed_issue = listed.get(code)
    nikkei_issue = nikkei.get(code, {})
    name = (
        str(financial.get("name") or "").strip()
        or (listed_issue.name if listed_issue else "")
        or str(nikkei_issue.get("name") or "").strip()
    )
    market_segment = listed_issue.market_segment if listed_issue else ""
    display_segment = display_market_segment(market_segment)
    return {
        "ticker": code,
        "code": code,
        "name": name,
        "market_segment": display_segment,
        "market_segment_raw": market_segment,
        "market_segment_label": display_segment,
        "sector": listed_issue.sector if listed_issue else "",
        "is_prime": listed_issue.is_prime if listed_issue else False,
        "is_nikkei225": code in nikkei,
        "has_financials": code in financials,
        "latest_fiscal_year": financial.get("latest_fiscal_year"),
        "latest_equity_ratio": financial.get("latest_equity_ratio"),
        "latest_dividend_per_share": financial.get("latest_dividend_per_share"),
        "dividend_cut_years": financial.get("dividend_cut_years"),
        "operating_cf_trend": financial.get("operating_cf_trend"),
        "source_ref": financial.get("source_ref") or "",
        "jpx_source_ref": listed_issue.source_ref if listed_issue else "",
        "nikkei225_source_ref": nikkei_issue.get("source_ref") or "",
    }


def _in_scope(row: dict[str, object], scope: str) -> bool:
    normalized = scope.strip().lower()
    if normalized in {"prime", "tse_prime", "tosho_prime"}:
        return bool(row.get("is_prime"))
    if normalized in {"nikkei225", "nikkei_225", "n225"}:
        return bool(row.get("is_nikkei225"))
    if normalized in {"domestic", "domestic_stock", "domestic_stocks", "japan_stocks"}:
        segment = " ".join(
            str(row.get(key) or "")
            for key in ("market_segment", "market_segment_raw", "market_segment_label")
        ).lower()
        return "国内株式" in segment or "内国株式" in segment or "domestic stock" in segment
    if normalized in {"financials", "edinet", "financials_available"}:
        return bool(row.get("has_financials"))
    return True


def _matches_query(row: dict[str, object], query: str) -> bool:
    needle = query.strip().lower()
    if not needle:
        return True
    haystack = " ".join(
        str(row.get(key) or "")
        for key in ("ticker", "name", "market_segment", "market_segment_raw", "sector")
    ).lower()
    return needle in haystack


def _universe_sort_key(row: dict[str, object]) -> tuple[int, int, str]:
    return (
        0 if row.get("is_prime") else 1,
        0 if row.get("is_nikkei225") else 1,
        str(row.get("ticker") or ""),
    )


def _scope_hint(scope: str, jpx_available: bool) -> str:
    if scope.strip().lower() in {"prime", "tse_prime", "tosho_prime"} and not jpx_available:
        return (
            "東証プライムを選ぶにはJPX上場銘柄一覧データの取込が必要です。"
            "Dataタブで公式JPXファイルを取得し、CSV/TSVとして保存してください。"
        )
    return "市場区分と日経225フラグは比較対象の絞り込み用です。投資助言ではありません。"
