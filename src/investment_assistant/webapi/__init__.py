"""Local web API and dashboard for the investment assistant.

A dependency-free (standard library) JSON API over the existing CLI functions,
plus an optional static-file server for the built React/Vite frontend in
``web/dist``. It never performs auto-trading and the web UI never triggers real
Gemini API calls.
"""

from investment_assistant.webapi.service import (
    ApiError,
    JsonDict,
)
from investment_assistant.webapi.service import (
    available_routes as _core_available_routes,
)
from investment_assistant.webapi.service import (
    handle_api as _core_handle_api,
)
from investment_assistant.webapi.yahoo_market import (
    available_yahoo_market_routes,
    handle_yahoo_market_api,
)


def handle_api(
    method: str,
    path: str,
    body: JsonDict | None = None,
) -> tuple[int, JsonDict]:
    yahoo_result = handle_yahoo_market_api(method, path, body)
    if yahoo_result is not None:
        return yahoo_result
    return _core_handle_api(method, path, body)


def available_routes() -> list[str]:
    return sorted({*_core_available_routes(), *available_yahoo_market_routes()})


__all__ = ["ApiError", "JsonDict", "available_routes", "handle_api"]
