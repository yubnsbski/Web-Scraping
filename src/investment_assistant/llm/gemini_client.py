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
        response = client.models.generate_content(model=model, contents=prompt)
        text = getattr(response, "text", None)
        if not isinstance(text, str) or not text.strip():
            msg = "Gemini API response did not include non-empty text"
            raise RuntimeError(msg)
        return text
