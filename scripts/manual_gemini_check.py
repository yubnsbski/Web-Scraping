#!/usr/bin/env python3
"""Manually call the real Gemini API through cache and budget controls."""

from __future__ import annotations

import sys

from investment_assistant.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["gemini-live", *sys.argv[1:]]))
