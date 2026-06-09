#!/usr/bin/env python3
"""Run a no-network smoke check through the guarded LLM service."""

from __future__ import annotations

from investment_assistant.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["smoke"]))
