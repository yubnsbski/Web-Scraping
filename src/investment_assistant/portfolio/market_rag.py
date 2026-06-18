"""Turn scraped market data into per-ticker RAG evidence documents.

The RAG index only ingests text (``.md`` / ``.txt``), so the scraped market
CSVs never reach it -- which is why a freshly-built store stays at zero
documents. This module renders one Markdown evidence note per ticker from the
Yahoo fundamentals CSV (optionally enriched with the latest close from the
daily-bars CSV), so the data the user already collected can be indexed and
cited by the non-advisory AI answer flow.

Pure / offline: CSV in, Markdown files out. Indexing is a separate step.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping
from pathlib import Path
from typing import Any

JsonDict = dict[str, Any]

_FIN_TICKER_KEYS = ("ticker", "code")
_BARS_TICKER_KEYS = ("ticker", "code")

# (financials column, label, unit) rendered as evidence bullet lines.
_METRIC_LINES: tuple[tuple[str, str, str], ...] = (
    ("price", "株価", "円"),
    ("per", "PER", "倍"),
    ("pbr", "PBR", "倍"),
    ("dividend_yield_percent", "配当利回り", "%"),
    ("dps", "1株配当", "円"),
    ("eps", "EPS", "円"),
    ("market_cap", "時価総額", "円"),
)


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "cp932", "utf-8"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text.strip().lstrip("﻿"), newline=""))
    return [dict(row) for row in reader]


def _pick(row: Mapping[str, str], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _num_text(value: str) -> str | None:
    text = value.strip()
    if not text or text in {"-", "--", "—"}:
        return None
    return text


def _as_float(value: object) -> float | None:
    text = _num_text(str(value or ""))
    if text is None:
        return None
    try:
        return float(text.replace(",", "").replace("%", "").replace("円", ""))
    except ValueError:
        return None


def _format_yen(value_text: str | None) -> str | None:
    """Render a raw-yen figure as a readable 億円 amount (e.g. 6.3兆 -> 63,000 億円)."""

    amount = _as_float(value_text)
    if amount is None:
        return None
    return f"{amount / 1e8:,.0f} 億円"


def _feature_tags(row: Mapping[str, str]) -> list[str]:
    """Keyword tags that make the note easier to retrieve by intent (e.g. 高配当)."""

    tags: list[str] = []
    yield_pct = _as_float(row.get("dividend_yield_percent"))
    dps = _as_float(row.get("dps"))
    per = _as_float(row.get("per"))
    pbr = _as_float(row.get("pbr"))
    if yield_pct is not None and yield_pct >= 4.0:
        tags.append("高配当")
    if (yield_pct == 0.0 or yield_pct is None) and (dps == 0.0 or dps is None):
        tags.append("無配・低配当")
    if per is not None and 0 < per < 10:
        tags.append("低PER（割安圏）")
    if pbr is not None and 0 < pbr < 1.0:
        tags.append("PBR1倍割れ（資産妙味）")
    return tags


def _latest_closes(daily_bars_csv: str | Path | None) -> dict[str, tuple[str, str]]:
    """Map ticker -> (latest_date, latest_close) from the daily-bars CSV."""

    if daily_bars_csv is None or not Path(daily_bars_csv).is_file():
        return {}
    latest: dict[str, tuple[str, str]] = {}
    for row in _read_csv(daily_bars_csv):
        ticker = _pick(row, _BARS_TICKER_KEYS)
        date = str(row.get("date") or "").strip()
        close = str(row.get("close") or "").strip()
        if not ticker or not date or not close:
            continue
        current = latest.get(ticker)
        if current is None or date > current[0]:
            latest[ticker] = (date, close)
    return latest


def render_market_evidence_markdown(
    row: Mapping[str, str],
    *,
    latest_close: tuple[str, str] | None = None,
) -> str | None:
    """Render one ticker's market evidence note, or ``None`` if it has no code."""

    ticker = _pick(row, _FIN_TICKER_KEYS)
    if not ticker:
        return None
    name = str(row.get("name") or "").strip() or ticker
    as_of = latest_close[0] if latest_close else ""

    lines = [
        "---",
        "doc_type: market_evidence",
        f'ticker: "{ticker}"',
        f'name: "{name}"',
        f'as_of: "{as_of}"',
        "---",
        "",
        f"# {name}（{ticker}） 市場データ",
        "",
    ]
    for column, label, unit in _METRIC_LINES:
        if column == "market_cap":
            readable = _format_yen(str(row.get(column) or ""))
            if readable is not None:
                lines.append(f"- {label}: {readable}")
            continue
        value = _num_text(str(row.get(column) or ""))
        if value is not None:
            lines.append(f"- {label}: {value} {unit}")
    if latest_close is not None:
        lines.append(f"- 直近終値: {latest_close[1]} 円（{latest_close[0]} 時点）")

    tags = _feature_tags(row)
    if tags:
        lines.extend(["", f"特徴: {' / '.join(tags)}"])
    lines.extend(
        [
            "",
            "出典: Yahoo!ファイナンスの機械集計。投資助言ではなく、判断材料の提示です。",
            "",
        ]
    )
    return "\n".join(lines)


def build_market_evidence_docs(
    *,
    financials_csv: str | Path,
    output_dir: str | Path,
    daily_bars_csv: str | Path | None = None,
) -> JsonDict:
    """Write one Markdown evidence note per ticker; return a summary.

    The notes land in ``output_dir`` as ``<ticker>.md`` (stable source per
    ticker, so re-running refreshes rather than duplicates), ready for
    ``rag-index-dir`` to ingest.
    """

    rows = _read_csv(financials_csv)
    closes = _latest_closes(daily_bars_csv)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    written = 0
    seen: set[str] = set()
    for row in rows:
        ticker = _pick(row, _FIN_TICKER_KEYS)
        if not ticker or ticker in seen:
            continue
        markdown = render_market_evidence_markdown(row, latest_close=closes.get(ticker))
        if markdown is None:
            continue
        seen.add(ticker)
        safe = "".join(ch for ch in ticker if ch.isalnum() or ch in {"-", "_"})
        (out / f"{safe or 'ticker'}.md").write_text(markdown, encoding="utf-8")
        written += 1

    return {
        "source": str(financials_csv),
        "output_dir": str(out),
        "documents_written": written,
        "with_daily_close": bool(closes),
        "auto_trading": False,
        "call_real_api": False,
    }
