"""Shared Web API exceptions."""

from __future__ import annotations


class ApiError(Exception):
    """Raised by handlers to return a 4xx with a JSON error body."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
