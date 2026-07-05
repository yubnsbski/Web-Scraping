from __future__ import annotations

import argparse
import json
from pathlib import Path

from investment_assistant.webapi.daily_bars_slice_readiness_backlog import (
    DEFAULT_DASHBOARD_ROOT,
    DEFAULT_MIRROR_ROOTS,
    DailyBarsSliceReadinessBacklogConfig,
    build_daily_bars_slice_readiness_backlog,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build Daily Bars Slice 001 readiness backlog artifacts."
    )
    parser.add_argument("--dashboard-root", type=Path, default=DEFAULT_DASHBOARD_ROOT)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--validation-path", type=Path, default=None)
    parser.add_argument(
        "--mirror-dir",
        action="append",
        type=Path,
        default=None,
        help="Optional mirror directory. Repeat to sync multiple mirrors.",
    )
    args = parser.parse_args()
    mirror_dirs = tuple(args.mirror_dir) if args.mirror_dir else DEFAULT_MIRROR_ROOTS
    payload = build_daily_bars_slice_readiness_backlog(
        DailyBarsSliceReadinessBacklogConfig(
            dashboard_root=args.dashboard_root,
            output_dir=args.output_dir,
            validation_path=args.validation_path,
            mirror_dirs=mirror_dirs,
        )
    )
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
