"""Build a domestic-stock ticker universe from the JPX listed-issues file.

The market-data backend currently treats the ``domestic``/``all``/``prime``
universe scopes as "every ticker in the financials CSV", which is only the
small EDINET fundamentals sample -- so a "全株式（国内株式）" request quietly
collapses to a few dozen names. The real universe is JPX's public
"東証上場銘柄一覧" (``data_j.xls``; export to CSV), which lists every listed
issue with a 市場・商品区分 (segment) column.

This module parses that file (no network, no contract) into bare Tokyo
codes -- the OHLCV/financials runners append the ``.T`` suffix themselves --
filtered to domestic common stock, optionally by market segment.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

JsonDict = dict[str, Any]

# Header aliases tolerate both the Japanese data_j export and the English one.
_CODE_KEYS = ("コード", "code", "Code", "Local Code", "local_code", "ticker")
_SEGMENT_KEYS = ("市場・商品区分", "Section/Products", "section", "market_segment", "segment")
_NAME_KEYS = ("銘柄名", "Name", "name")

# A domestic common-stock segment always carries this marker in the JPX file
# (プライム（内国株式）/ スタンダード（内国株式）/ グロース（内国株式）),
# which excludes ETF・ETN, REIT, 出資証券, PRO Market and 外国株式.
_DOMESTIC_MARKER = "内国株式"

# Scope -> additional segment substring required (beyond the domestic marker).
_SCOPE_SEGMENT_FILTER: dict[str, str | None] = {
    "domestic": None,
    "all": None,
    "stock": None,
    "domestic_stocks": None,
    "prime": "プライム",
    "tse_prime": "プライム",
    "東証プライム": "プライム",
    "standard": "スタンダード",
    "growth": "グロース",
}

UNIVERSE_COLUMNS = ("ticker", "name", "segment")


def _decode_bytes(raw: bytes) -> str:
    """Decode a JPX file, which is typically CP932 (Shift_JIS), tolerating BOM/UTF-8."""

    for encoding in ("utf-8-sig", "cp932", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    # Last resort: never raise on a stray byte; replace it so parsing can proceed.
    return raw.decode("cp932", errors="replace")


def _pick(row: Mapping[str, str], keys: Sequence[str]) -> str:
    for key in keys:
        if key in row and str(row[key]).strip():
            return str(row[key]).strip()
    return ""


def _normalize_code(value: str) -> str:
    """Keep JPX codes verbatim (4-digit and the newer alphanumeric like ``130A``).

    Strips a stray ``.T`` suffix or surrounding whitespace if a pre-suffixed file
    is supplied, so the runner's own ``.T`` is never doubled.
    """

    code = value.strip().upper()
    if code.endswith(".T"):
        code = code[:-2]
    return code


def parse_jpx_rows(text: str) -> list[dict[str, str]]:
    """Parse JPX listed-issues CSV text into ``{code, name, segment}`` rows."""

    body = text.strip().lstrip("﻿")
    # newline="" lets csv handle CRLF / lone-CR endings (Excel exports) itself;
    # without it a stray CR raises "new-line character seen in unquoted field".
    reader = csv.DictReader(io.StringIO(body, newline=""))
    rows: list[dict[str, str]] = []
    for raw in reader:
        code = _normalize_code(_pick(raw, _CODE_KEYS))
        if not code:
            continue
        rows.append(
            {
                "code": code,
                "name": _pick(raw, _NAME_KEYS),
                "segment": _pick(raw, _SEGMENT_KEYS),
            }
        )
    return rows


def _scope_marker(scope: str) -> str | None:
    key = scope.strip().lower()
    if key in _SCOPE_SEGMENT_FILTER:
        return _SCOPE_SEGMENT_FILTER[key]
    # Unknown scopes fall back to the whole domestic universe rather than empty.
    return None


def domestic_rows(
    rows: Iterable[Mapping[str, str]], *, scope: str = "domestic"
) -> list[dict[str, str]]:
    """Filter parsed rows to domestic common stock, optionally by market segment."""

    marker = _scope_marker(scope)
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        segment = str(row.get("segment") or "")
        if _DOMESTIC_MARKER not in segment:
            continue
        if marker is not None and marker not in segment:
            continue
        code = _normalize_code(str(row.get("code") or ""))
        if not code or code in seen:
            continue
        seen.add(code)
        out.append({"code": code, "name": str(row.get("name") or ""), "segment": segment})
    return out


def domestic_tickers(text: str, *, scope: str = "domestic") -> list[str]:
    """Bare Tokyo codes for the requested domestic scope (``.T`` added downstream)."""

    return [row["code"] for row in domestic_rows(parse_jpx_rows(text), scope=scope)]


def build_domestic_universe_csv(
    jpx_path: str | Path,
    *,
    output_path: str | Path,
    scope: str = "domestic",
) -> JsonDict:
    """Read a JPX listed-issues file and write a deduplicated universe CSV.

    Returns a summary (counts + paths) and never raises on a non-domestic-only
    file; it simply reports how many domestic rows were retained.
    """

    raw = Path(jpx_path).read_bytes()
    rows = domestic_rows(parse_jpx_rows(_decode_bytes(raw)), scope=scope)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(UNIVERSE_COLUMNS), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({"ticker": row["code"], "name": row["name"], "segment": row["segment"]})
    out.write_text(buffer.getvalue(), encoding="utf-8-sig")
    return {
        "source": str(jpx_path),
        "output_path": str(out),
        "scope": scope,
        "ticker_count": len(rows),
        "auto_trading": False,
        "call_real_api": False,
    }


def load_domestic_universe_tickers(
    path: str | Path, *, scope: str = "domestic"
) -> list[str]:
    """Read tickers back from a built universe CSV, filtered by scope."""

    raw = Path(path).read_bytes()
    reader = csv.DictReader(io.StringIO(_decode_bytes(raw).strip().lstrip("﻿"), newline=""))
    marker = _scope_marker(scope)
    out: list[str] = []
    seen: set[str] = set()
    for row in reader:
        code = _normalize_code(str(row.get("ticker") or row.get("code") or ""))
        if not code or code in seen:
            continue
        if marker is not None and marker not in str(row.get("segment") or ""):
            continue
        seen.add(code)
        out.append(code)
    return out
