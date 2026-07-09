"""Thin Gemini client abstraction.

The production API integration is intentionally isolated here. Tests should use
fake clients instead of calling Gemini. The real Gemini client uses the official
``google-genai`` SDK lazily so normal unit tests and local smoke checks do not
require network access or an API key.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
from dataclasses import dataclass
from typing import Protocol


class TextGenerationClient(Protocol):
    """Protocol implemented by concrete or fake text generation clients."""

    def generate(self, prompt: str, *, model: str) -> str:
        """Generate text for ``prompt`` with ``model``."""


class GeminiApiError(RuntimeError):
    """Raised when a Gemini API call fails, with a classified ``reason``.

    ``reason`` is read by ``LlmService`` (via ``getattr(exc, "reason", None)``)
    to decide cooldown / retry behavior: ``"rate_limit"`` (HTTP 429, enters
    cooldown), ``"server_error"`` (HTTP 5xx, transient and worth retrying --
    the failed request consumed no quota), ``"empty_response"`` (Gemini
    returned HTTP 200 with no usable text -- quota already spent, so never
    retried), or ``None`` for anything else.
    """

    def __init__(self, message: str, *, reason: str | None = None) -> None:
        super().__init__(message)
        self.reason = reason


def _classify_gemini_error(exc: Exception) -> str | None:
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if code is None:
        return None
    # SDK/transport layers sometimes report the status as a string ("429");
    # coerce before classifying so those are not silently unclassified.
    try:
        code_int = int(str(code))
    except (TypeError, ValueError):
        return None
    if code_int == 429:
        return "rate_limit"
    if 500 <= code_int < 600:
        return "server_error"
    return None


@dataclass
class GeminiClient:
    """Real Gemini API client using the optional official Google GenAI SDK."""

    api_key: str | None = None

    def generate(self, prompt: str, *, model: str) -> str:
        """Generate text using Gemini through ``google-genai``.

        This method is intentionally reached only through ``LlmService`` so cache,
        budget checks, usage recording, and fallback behavior always apply before
        any real API request is attempted.
        """

        key = self.api_key or os.getenv("GEMINI_API_KEY")
        if not key:
            msg = "GEMINI_API_KEY is not configured"
            raise RuntimeError(msg)
        if importlib.util.find_spec("google.genai") is None:
            msg = "Install the optional Gemini SDK with: pip install -e '.[gemini]'"
            raise RuntimeError(msg)

        genai = importlib.import_module("google.genai")
        client = genai.Client(api_key=key)
        try:
            response = client.models.generate_content(model=model, contents=prompt)
        except Exception as exc:  # noqa: BLE001 - reclassified as GeminiApiError below
            reason = _classify_gemini_error(exc)
            raise GeminiApiError(str(exc), reason=reason) from exc

        text = getattr(response, "text", None)
        if not isinstance(text, str) or not text.strip():
            msg = "Gemini API response did not include non-empty text"
            raise GeminiApiError(msg, reason="empty_response")
        return text
