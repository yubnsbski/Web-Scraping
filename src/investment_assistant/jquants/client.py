"""Minimal J-Quants API v2 client.

The official v2 docs use an API key issued from the dashboard and pass it in
the ``x-api-key`` header. This client intentionally supports only read-only
market data endpoints used by the local single-user investment tool.
"""

from __future__ import annotations

import json
import os
import re
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

        return self._daily_bars_for_code(
            normalize_equity_code(code),
            date=date,
            from_date=from_date,
            to_date=to_date,
            pagination_key=pagination_key,
        )

    def _daily_bars_for_code(
        self,
        code: str,
        *,
        date: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        pagination_key: str | None = None,
    ) -> JsonDict:
        query = {
            "code": code,
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

    def _daily_bars_with_subscription_fallback(
        self,
        code: str,
        *,
        date: str | None,
        from_date: str | None,
        to_date: str | None,
        lookback_days: int,
    ) -> JsonDict:
        try:
            return self._daily_bars_for_code(
                code,
                date=date,
                from_date=from_date,
                to_date=to_date,
            )
        except JQuantsApiError as exc:
            retry_window = None if date else _subscription_retry_window(str(exc), lookback_days)
            if retry_window is None:
                raise
            retry_from, retry_to = retry_window
            result = self._daily_bars_for_code(
                code,
                from_date=retry_from,
                to_date=retry_to,
            )
            result["subscription_window_used"] = {
                "from": retry_from,
                "to": retry_to,
            }
            return result

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
            errors: list[str] = []
            candidates = candidate_equity_codes(ticker)
            try:
                result: JsonDict | None = None
                for code in candidates:
                    try:
                        result = self._daily_bars_with_subscription_fallback(
                            code,
                            date=date,
                            from_date=None if date else from_date.isoformat(),
                            to_date=None if date else today.isoformat(),
                            lookback_days=lookback_days,
                        )
                        price, row_date = _latest_close(result["rows"])
                        if price is not None:
                            break
                        errors.append(f"{code}: no_close_price_returned")
                    except JQuantsApiError as exc:
                        errors.append(f"{code}: {exc}")
                if result is None:
                    raise JQuantsApiError("; ".join(errors) or "no J-Quants response")
                price, row_date = _latest_close(result["rows"])
                prices[ticker] = price
                if row_date:
                    as_of[ticker] = row_date
                if isinstance(result.get("subscription_window_used"), dict):
                    window = result["subscription_window_used"]
                    notes[ticker] = (
                        f"subscription_window_used:{window.get('from')}~{window.get('to')}"
                    )
                if price is None:
                    notes[ticker] = "; ".join(errors) or "no_close_price_returned"
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

    def fetch_daily_bars(
        self,
        tickers: Iterable[str],
        *,
        date: str | None = None,
        lookback_days: int = 30,
    ) -> JsonDict:
        """Fetch normalized daily OHLCV rows for each ticker."""

        from investment_assistant.portfolio.bar_store import (
            daily_bar_from_jquants_row,
            summarize_daily_bars,
        )

        bar_facts: list[Any] = []
        notes: dict[str, str] = {}
        tried_codes: dict[str, list[str]] = {}
        today = datetime.now(UTC).date()
        from_date = today - timedelta(days=max(lookback_days, 1))
        source = "https://api.jquants.com/v2/equities/bars/daily"
        for raw in tickers:
            ticker = str(raw).strip()
            if not ticker:
                continue
            errors: list[str] = []
            candidates = candidate_equity_codes(ticker)
            tried_codes[ticker] = list(candidates)
            for code in candidates:
                try:
                    result = self._daily_bars_with_subscription_fallback(
                        code,
                        date=date,
                        from_date=None if date else from_date.isoformat(),
                        to_date=None if date else today.isoformat(),
                        lookback_days=lookback_days,
                    )
                except JQuantsApiError as exc:
                    errors.append(f"{code}: {exc}")
                    continue
                rows = result["rows"]
                normalized = [
                    fact
                    for row in rows
                    if (
                        fact := daily_bar_from_jquants_row(
                            row,
                            fallback_ticker=ticker,
                            provider_id="jquants",
                            source_ref=source,
                        )
                    )
                    is not None
                ]
                if normalized:
                    bar_facts.extend(normalized)
                    if isinstance(result.get("subscription_window_used"), dict):
                        window = result["subscription_window_used"]
                        notes[ticker] = (
                            f"subscription_window_used:{window.get('from')}~{window.get('to')}"
                        )
                    break
                errors.append(f"{code}: no_daily_bars_returned")
            if errors and not any(str(fact.ticker) == ticker for fact in bar_facts):
                notes[ticker] = "; ".join(errors)
        return {
            "bars": [fact.to_dict() for fact in bar_facts],
            "summary": summarize_daily_bars(bar_facts),
            "notes": notes,
            "tried_codes": tried_codes,
            "source": source,
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
            raise JQuantsApiError(_http_error_message(exc, path, cleaned)) from exc
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


def candidate_equity_codes(code: str) -> tuple[str, ...]:
    """Return J-Quants code candidates for visible Japanese security codes."""

    raw = str(code or "").strip().upper()
    digits = "".join(ch for ch in raw if ch.isdigit())
    primary = normalize_equity_code(code)
    candidates: list[str] = []
    for candidate in (primary, digits):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    if len(digits) == 5 and digits.endswith("0"):
        visible = digits[:4]
        if visible not in candidates:
            candidates.append(visible)
    if not digits and raw and raw not in candidates:
        candidates.append(raw)
    return tuple(candidates)


def _env_api_key() -> str:
    return os.getenv(API_KEY_ENV_VAR, "").strip() or os.getenv(REFRESH_TOKEN_ENV_VAR, "").strip()


def _compact_date(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text.replace("-", "")


def _subscription_retry_window(message: str, lookback_days: int) -> tuple[str, str] | None:
    match = re.search(r"(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})", message)
    if not match:
        return None
    try:
        covered_to = datetime.fromisoformat(match.group(2)).date()
    except ValueError:
        return None
    covered_from = covered_to - timedelta(days=max(lookback_days, 1))
    return covered_from.isoformat(), covered_to.isoformat()


def _extract_rows(payload: JsonDict) -> list[JsonDict]:
    for key in ("daily_bars", "daily_quotes", "bars", "data", "items", "equities"):
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
            or row.get("AdjC")
            or row.get("C")
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


def _http_error_message(exc: HTTPError, path: str, params: Mapping[str, str]) -> str:
    try:
        raw = exc.read(500)
    except Exception:  # noqa: BLE001 - HTTPError body is best-effort diagnostics only
        raw = b""
    detail = raw.decode("utf-8", errors="replace").strip()
    safe_params = ", ".join(f"{key}={value}" for key, value in params.items() if key != "x-api-key")
    message = f"J-Quants API returned HTTP {exc.code} for {path}"
    if safe_params:
        message = f"{message} ({safe_params})"
    if detail:
        message = f"{message}: {detail[:300]}"
    return message
