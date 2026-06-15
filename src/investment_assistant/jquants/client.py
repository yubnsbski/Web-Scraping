"""Minimal J-Quants API v2 client.

The official v2 docs use an API key issued from the dashboard and pass it in
the ``x-api-key`` header. This client intentionally supports only read-only
market data endpoints used by the local single-user investment tool.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

JsonDict = dict[str, Any]
FetchJson = Callable[[str, Mapping[str, str], Mapping[str, str]], JsonDict]

DEFAULT_BASE_URL = "https://api.jquants.com/v2"
BASE_URL_ENV_VAR = "JQUANTS_API_BASE_URL"
API_KEY_ENV_VAR = "JQUANTS_API_KEY"
REFRESH_TOKEN_ENV_VAR = "JQUANTS_REFRESH_TOKEN"
USER_AGENT = "investment-assistant/0.1 (+jquants-local-single-user)"


class JQuantsApiError(RuntimeError):
    """Raised when J-Quants configuration or API access fails."""


class JQuantsClient:
    """Small API-key based J-Quants v2 client."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        fetch_json: FetchJson | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.api_key = (api_key or _env_api_key()).strip()
        self.base_url = (base_url or os.getenv(BASE_URL_ENV_VAR) or DEFAULT_BASE_URL).rstrip("/")
        self.fetch_json = fetch_json
        self.timeout_seconds = timeout_seconds

    def daily_bars(
        self,
        code: str,
        *,
        date: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        pagination_key: str | None = None,
    ) -> JsonDict:
        """Fetch stock OHLC rows from ``/v2/equities/bars/daily``."""

        query = {
            "code": normalize_equity_code(code),
            "date": _compact_date(date),
            "from": _compact_date(from_date),
            "to": _compact_date(to_date),
            "pagination_key": pagination_key,
        }
        payload = self._request_json("/equities/bars/daily", query)
        return {
            "rows": _extract_rows(payload),
            "pagination_key": payload.get("pagination_key"),
            "source_endpoint": "/v2/equities/bars/daily",
            "raw": payload,
        }

    def fetch_latest_prices(
        self,
        tickers: Iterable[str],
        *,
        date: str | None = None,
        lookback_days: int = 14,
    ) -> JsonDict:
        """Fetch latest available close price for each ticker."""

        prices: dict[str, float | None] = {}
        notes: dict[str, str] = {}
        as_of: dict[str, str] = {}
        today = datetime.now(UTC).date()
        from_date = today - timedelta(days=max(lookback_days, 1))
        for raw in tickers:
            ticker = str(raw).strip()
            if not ticker or ticker in prices:
                continue
            try:
                result = self.daily_bars(
                    ticker,
                    date=date,
                    from_date=None if date else from_date.isoformat(),
                    to_date=None if date else today.isoformat(),
                )
                price, row_date = _latest_close(result["rows"])
                prices[ticker] = price
                if row_date:
                    as_of[ticker] = row_date
                if price is None:
                    notes[ticker] = "no_close_price_returned"
            except JQuantsApiError as exc:
                prices[ticker] = None
                notes[ticker] = str(exc)
        return {
            "prices": prices,
            "notes": notes,
            "as_of": as_of,
            "source": "https://api.jquants.com/v2/equities/bars/daily",
            "provider_id": "jquants",
            "auto_trading": False,
            "call_real_api": True,
        }

    def _request_json(self, path: str, params: Mapping[str, str | None]) -> JsonDict:
        if not self.api_key:
            raise JQuantsApiError(
                f"{API_KEY_ENV_VAR} is not configured. Set it from the Data tab or .env."
            )
        cleaned = {key: value for key, value in params.items() if value}
        headers = {
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            "x-api-key": self.api_key,
        }
        if self.fetch_json is not None:
            return self.fetch_json(path, cleaned, headers)
        url = f"{self.base_url}{path}"
        if cleaned:
            url = f"{url}?{urlencode(cleaned)}"
        request = Request(url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
        except HTTPError as exc:
            raise JQuantsApiError(f"J-Quants API returned HTTP {exc.code}") from exc
        except URLError as exc:
            raise JQuantsApiError(f"J-Quants API connection failed: {exc.reason}") from exc
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise JQuantsApiError("J-Quants API returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise JQuantsApiError("J-Quants API returned unexpected payload")
        return parsed


def normalize_equity_code(code: str) -> str:
    """Normalize a visible 4-digit Japanese ticker to J-Quants' 5-digit code."""

    raw = str(code or "").strip().upper()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == 4:
        return f"{digits}0"
    return digits or raw


def _env_api_key() -> str:
    return os.getenv(API_KEY_ENV_VAR, "").strip() or os.getenv(REFRESH_TOKEN_ENV_VAR, "").strip()


def _compact_date(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text.replace("-", "")


def _extract_rows(payload: JsonDict) -> list[JsonDict]:
    for key in ("daily_quotes", "bars", "data", "items", "equities"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _latest_close(rows: Iterable[JsonDict]) -> tuple[float | None, str | None]:
    candidates: list[tuple[str, float]] = []
    for row in rows:
        date = str(row.get("Date") or row.get("date") or "")
        value = _positive_float(
            row.get("Close")
            or row.get("close")
            or row.get("AdjustmentClose")
            or row.get("adjustment_close")
        )
        if value is not None:
            candidates.append((date, value))
    if not candidates:
        return None, None
    row_date, price = sorted(candidates, key=lambda item: item[0])[-1]
    return price, row_date or None


def _positive_float(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
