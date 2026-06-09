"""Vercel Python serverless entrypoint for the local JSON API handler."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from investment_assistant.webapi.server import _Handler  # noqa: E402


class handler(_Handler):
    """Vercel requires an explicit top-level handler symbol."""


__all__ = ["handler"]
