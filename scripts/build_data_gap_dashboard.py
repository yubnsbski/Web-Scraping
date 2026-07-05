from __future__ import annotations

import argparse
import json
from pathlib import Path

from investment_assistant.webapi.data_gap_dashboard import (
    DataGapDashboardConfig,
    build_data_gap_dashboard,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build data gap dashboard artifacts.")
    parser.add_argument(
        "--ticker-map",
        type=Path,
        default=Path("web/public/market-dashboard/ticker_data_map.csv"),
    )
    parser.add_argument("--output-dir", type=Path, default=Path("web/public/market-dashboard"))
    parser.add_argument("--mirror-dir", action="append", type=Path, default=[])
    args = parser.parse_args()

    payload = build_data_gap_dashboard(
        DataGapDashboardConfig(
            ticker_map_path=args.ticker_map,
            output_dir=args.output_dir,
            mirror_dirs=tuple(args.mirror_dir),
        )
    )
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
