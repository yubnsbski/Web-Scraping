"""Local web API and dashboard for the investment assistant.

A dependency-free (standard library) JSON API over the existing CLI functions,
plus an optional static-file server for the built React/Vite frontend in
``web/dist``. It never performs auto-trading and the web UI never triggers real
Gemini API calls.
"""

from investment_assistant.webapi.errors import ApiError
from investment_assistant.webapi.service import available_routes, handle_api

__all__ = ["ApiError", "available_routes", "handle_api"]
