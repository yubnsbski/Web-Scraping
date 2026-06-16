"""Run the local dashboard API: ``python -m investment_assistant.webapi``."""

from __future__ import annotations

import argparse

from investment_assistant.webapi.local_env import load_local_env_files
from investment_assistant.webapi.server import serve


def main() -> int:
    parser = argparse.ArgumentParser(prog="investment-assistant-webapi")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    load_local_env_files()
    serve(host=str(args.host), port=int(args.port))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
