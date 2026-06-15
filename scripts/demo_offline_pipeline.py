"""Thin wrapper around :func:`investment_assistant.demo.run_offline_demo`.

Kept for convenience (``python scripts/demo_offline_pipeline.py``); the demo
itself now lives in the package and is also exposed as ``investment-assistant
demo``.
"""

from __future__ import annotations

from investment_assistant.demo import run_offline_demo

if __name__ == "__main__":
    raise SystemExit(run_offline_demo())
