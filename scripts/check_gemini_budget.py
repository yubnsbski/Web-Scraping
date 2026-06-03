#!/usr/bin/env python3
"""Print current Gemini budget usage without calling Gemini."""

from __future__ import annotations

from investment_assistant.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["budget", "--json"]))
