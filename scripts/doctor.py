#!/usr/bin/env python3
"""Local setup diagnostics for the repository."""

from __future__ import annotations

import platform
import sys
from pathlib import Path


def main() -> int:
    """Print local setup diagnostics and return non-zero for blocking issues."""

    script_path = Path(__file__).resolve()
    repo_root = script_path.parents[1]
    pyproject = repo_root / "pyproject.toml"
    print(f"Python executable: {sys.executable}")
    print(f"Python version: {platform.python_version()}")
    print(f"Current directory: {Path.cwd()}")
    print(f"Detected repository root: {repo_root}")
    print(f"pyproject.toml exists: {pyproject.exists()}")

    major_minor = tuple(int(part) for part in platform.python_version_tuple()[:2])
    if major_minor < (3, 11):
        print("ERROR: Python 3.11+ is required. Use python3.11 or install Python 3.11+.")
        return 1
    if not pyproject.exists():
        print("ERROR: pyproject.toml was not found next to this script's repository root.")
        return 1

    print("\nRecommended setup commands:")
    print(f"cd {repo_root}")
    print("python3 -m venv .venv")
    print("source .venv/bin/activate")
    print("python -m pip install --upgrade pip")
    print("python -m pip install -e '.[dev]'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
