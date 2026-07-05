"""Build Daily Bars Batch 001 Slice 001 quality-gate artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from investment_assistant.webapi.daily_bars_quality import SliceBuildConfig, build_daily_bars_slice


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dashboard-root", type=Path, default=Path("web/public/market-dashboard"))
    parser.add_argument("--batch-manifest", type=Path, default=None)
    parser.add_argument("--slice-size", type=int, default=5)
    parser.add_argument("--slice-id", default="daily-bars-batch001-slice001")
    parser.add_argument("--batch-id", default="daily-bars-batch001")
    parser.add_argument("--mirror-dir", action="append", type=Path, default=[])
    args = parser.parse_args()

    dashboard_root = args.dashboard_root
    manifest = args.batch_manifest or dashboard_root / "daily_bars_backfill_batch001_manifest.csv"
    payload = build_daily_bars_slice(
        SliceBuildConfig(
            batch_manifest_path=manifest,
            output_dir=dashboard_root,
            slice_id=args.slice_id,
            batch_id=args.batch_id,
            slice_size=args.slice_size,
            mirror_dirs=tuple(args.mirror_dir),
        )
    )
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
