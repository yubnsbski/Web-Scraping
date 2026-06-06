"""Structured, secret-free logging for the investment assistant.

Logging is intentionally lightweight (standard library only) and defensive:

* Configuration is idempotent and reads ``LOG_LEVEL`` from the environment.
* :func:`redact` truncates free text (prompts, fetched content) so secrets and
  personal information are not written to logs in full; only a short, length-
  annotated preview is emitted.
* API keys and full prompts/responses are never logged by callers in this
  project -- log identifiers, sizes, sources, and decisions instead.
"""

from __future__ import annotations

import logging
import os

_CONFIGURED = False
_DEFAULT_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging(level: str | None = None, *, force: bool = False) -> None:
    """Configure root logging once, honoring ``LOG_LEVEL`` unless overridden."""

    global _CONFIGURED
    if _CONFIGURED and not force:
        return
    resolved = (level or os.getenv("LOG_LEVEL") or "INFO").upper()
    logging.basicConfig(level=getattr(logging, resolved, logging.INFO), format=_DEFAULT_FORMAT)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger under the ``investment_assistant`` root."""

    if not name.startswith("investment_assistant"):
        name = f"investment_assistant.{name}"
    return logging.getLogger(name)


def redact(text: str | None, *, max_chars: int = 80) -> str:
    """Return a short, length-annotated preview safe to log.

    Never emit full prompts, responses, or fetched content: this collapses
    whitespace, truncates, and appends the original length so logs stay useful
    without leaking secrets or personal information.
    """

    if not text:
        return "<empty>"
    collapsed = " ".join(text.split())
    length = len(collapsed)
    if length <= max_chars:
        return f"{collapsed!r}(len={length})"
    return f"{collapsed[:max_chars]!r}…(len={length})"
