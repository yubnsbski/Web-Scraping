"""Yahoo Finance Japan scraper for Japanese stock data.

Collects: price, DPS, EPS, PER, PBR, sector, market cap.
No API key required. Rate-limited to be polite.

Page type: Server-side rendered HTML (SSR).
Parse strategy:
  1. Strip HTML tags → plain text (similar to browser's innerText)
  2. The text contains patterns like:
       "配当利回り（会社予想）用語1.92%(15:30)"
       "1株配当（会社予想）用語150.00円(2027/03)"
       "最低購入代金用語781,400(15:30)"
       "単元株数用語100株"
       "前日終値用語7,743(06/30)"
       "前日比+71(+0.92%)"
  3. Price = 最低購入代金 ÷ 単元株数
"""

from __future__ import annotations

import logging
import re
import time
import urllib.request
from datetime import date, datetime
from html.parser import HTMLParser
from typing import Optional

from investment_assistant.data.models import StockQuote

_log = logging.getLogger("collectors.yahoo_jp")

_BASE = "https://finance.yahoo.co.jp/quote/{ticker}.T"
_TIMEOUT = 15
_MIN_INTERVAL = 1.5  # seconds between requests
_last_request: float = 0.0

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate",
}


def fetch_quote(ticker: str) -> Optional[StockQuote]:
    """Scrape current quote for a Tokyo Stock Exchange ticker (e.g. '8306')."""
    global _last_request
    elapsed = time.monotonic() - _last_request
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_request = time.monotonic()

    url = _BASE.format(ticker=ticker)
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise RuntimeError(f"fetch_quote({ticker}): HTTP error: {exc}") from exc

    return _parse_quote(ticker, html)


# ── HTML → plain text ─────────────────────────────────────────────────────────

class _TextExtractor(HTMLParser):
    """Extracts visible text from HTML, similar to browser's element.innerText."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip = False
        self._skip_tags = {"script", "style", "noscript", "head"}

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag.lower() in self._skip_tags:
            self._skip = True
        # Block elements → newline separator
        if tag.lower() in ("div", "p", "tr", "li", "br", "h1", "h2", "h3", "td", "th", "dt", "dd"):
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._skip_tags:
            self._skip = False

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._parts.append(data)

    def handle_entityref(self, name: str) -> None:
        _ENTITIES = {"amp": "&", "lt": "<", "gt": ">", "nbsp": " ", "quot": '"'}
        self._parts.append(_ENTITIES.get(name, ""))

    def handle_charref(self, name: str) -> None:
        try:
            ch = chr(int(name[1:], 16) if name.startswith("x") else int(name))
            self._parts.append(ch)
        except (ValueError, OverflowError):
            pass

    def get_text(self) -> str:
        return "".join(self._parts)


def _html_to_text(html: str) -> str:
    """Convert HTML to plain text (preserving line structure)."""
    extractor = _TextExtractor()
    try:
        extractor.feed(html)
    except Exception:
        # Fallback: basic tag stripping
        html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<[^>]+>", " ", html)
        return html
    return extractor.get_text()


# ── parse ─────────────────────────────────────────────────────────────────────

def _parse_quote(ticker: str, html: str) -> Optional[StockQuote]:
    """Parse Yahoo Finance Japan HTML into StockQuote."""
    # Collapse all whitespace (incl. newlines) to single spaces so patterns like
    # "最低購入代金\n用語\n324,700" become "最低購入代金 用語 324,700" and match.
    text = re.sub(r"\s+", " ", _html_to_text(html))

    def find_num(pattern: str, default: float = 0.0) -> float:
        m = re.search(pattern, text)
        if not m:
            return default
        try:
            return float(m.group(1).replace(",", "").replace("円", "").strip())
        except (ValueError, IndexError):
            return default

    def find_str(pattern: str, default: str = "") -> str:
        m = re.search(pattern, text)
        return m.group(1).strip() if m else default

    # ── Company name ─────────────────────────────────────────────────────────
    m_title = re.search(r"<title>([^<\|]+)", html)
    name = m_title.group(1).strip() if m_title else ticker
    name = re.sub(r"\s*[-–—|]\s*Yahoo.*", "", name).strip()
    name = re.sub(r"【\d+】.*", "", name).strip() or ticker

    # ── Price ─────────────────────────────────────────────────────────────────
    # Method 1: 最低購入代金 ÷ 単元株数
    min_buy = find_num(r"最低購入代金[^\d\n]*([\d,]+)")
    lot_size = find_num(r"単元株数[^\d\n]*([\d,]+)\s*株") or 100.0
    price = min_buy / lot_size if min_buy > 0 else 0.0

    # Method 2: 前日終値 + 前日比
    if price <= 0:
        prev_close = find_num(r"前日終値[^\d\n]*([\d,]+(?:\.\d+)?)")
        diff_m = re.search(r"前日比\s*([+-][\d,]+(?:\.\d+)?)", text)
        diff = float(diff_m.group(1).replace(",", "")) if diff_m else 0.0
        if prev_close > 0:
            price = prev_close + diff

    if price <= 0:
        _log.warning("%s: could not parse price", ticker)
        return None

    # ── DPS (1株配当) ─────────────────────────────────────────────────────────
    dps = find_num(r"1株配当[^円\n\d]*[\(（][^\)）]+[\)）][^\d\n]*([\d,]+(?:\.\d+)?)\s*円")
    if dps <= 0:
        dps = find_num(r"1株配当[^\d\n]*([\d,]+(?:\.\d+)?)\s*円")

    # ── Yield% (配当利回り) ───────────────────────────────────────────────────
    yield_pct = find_num(r"配当利回り[^%\n\d]*[\(（][^\)）]+[\)）][^\d\n]*([\d.]+)\s*%")
    if yield_pct <= 0:
        yield_pct = find_num(r"配当利回り[^\d\n]*([\d.]+)\s*%")

    # Back-calculate DPS from yield% if DPS still missing
    if dps <= 0 and yield_pct > 0 and price > 0:
        dps = round(price * yield_pct / 100, 1)

    # ── EPS ──────────────────────────────────────────────────────────────────
    eps = find_num(r"EPS[^（\d\n]*[\(（][^\)）]+[\)）][^\d\n\-]*([-\d,]+(?:\.\d+)?)")
    if eps <= 0:
        eps = find_num(r"EPS[^\d\n\-]*([-\d,]+(?:\.\d+)?)")

    # ── PER ──────────────────────────────────────────────────────────────────
    per = find_num(r"PER[^（\d\n]*[\(（][^\)）]+[\)）][^\d\n]*([\d,]+(?:\.\d+)?)\s*倍")
    if per <= 0:
        per = find_num(r"PER[^\d\n]*([\d.]+)\s*倍")

    # ── PBR ──────────────────────────────────────────────────────────────────
    pbr = find_num(r"PBR[^（\d\n]*[\(（][^\)）]+[\)）][^\d\n]*([\d.]+)\s*倍")
    if pbr <= 0:
        pbr = find_num(r"PBR[^\d\n]*([\d.]+)\s*倍")

    # ── Market cap ───────────────────────────────────────────────────────────
    cap_m_str = find_str(r"時価総額[^\d\n]*([\d,]+(?:兆|億|百万)?円?)")
    market_cap_m = _parse_market_cap(cap_m_str)

    # ── Sector ───────────────────────────────────────────────────────────────
    sector = find_str(r"(\S{2,6}業)") or ""
    # Fix false positives
    if sector in ("連結業", "業績"):
        sector = ""

    _log.debug(
        "%s: price=%.1f dps=%.1f yield=%.2f%% per=%.1f pbr=%.2f sector=%s",
        ticker, price, dps, yield_pct, per, pbr, sector,
    )

    return StockQuote(
        ticker=ticker,
        name=name,
        price=price,
        price_date=date.today(),
        dps_ttm=dps,
        eps_ttm=eps,
        per=per,
        pbr=pbr,
        market_cap_m=market_cap_m,
        sector=sector,
        source="yahoo_jp",
        fetched_at=datetime.utcnow(),
    )


# ── market cap parser ─────────────────────────────────────────────────────────

def _parse_market_cap(raw: str) -> float:
    """Convert '1.2兆円', '3,456億円', '12,345百万円' → million JPY."""
    if not raw:
        return 0.0
    raw = raw.replace(",", "")
    m = re.search(r"([\d\.]+)(兆|億|百万)?", raw)
    if not m:
        return 0.0
    val = float(m.group(1))
    unit = m.group(2) or ""
    if unit == "兆":
        return val * 1_000_000
    if unit == "億":
        return val * 100
    if unit == "百万":
        return val
    return val
