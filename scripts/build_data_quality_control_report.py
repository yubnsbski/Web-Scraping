"""Build an integrated data quality control report for the market dashboard."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from investment_assistant.webapi.data_quality_control_report import (
    DataQualityControlReportConfig,
    build_data_quality_control_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("web/public/market-dashboard"),
        help="Directory where static dashboard artifacts are written.",
    )
    parser.add_argument(
        "--mirror-dir",
        action="append",
        type=Path,
        default=[],
        help="Optional mirror output directory. Can be repeated.",
    )
    parser.add_argument(
        "--data-quality-profile",
        type=Path,
        default=Path("web/public/market-dashboard/data_quality_profile.json"),
    )
    parser.add_argument(
        "--data-gap-dashboard",
        type=Path,
        default=Path("web/public/market-dashboard/data_gap_dashboard.json"),
    )
    parser.add_argument(
        "--source-drift-audit",
        type=Path,
        default=Path("web/public/market-dashboard/source_drift_audit.json"),
    )
    parser.add_argument(
        "--source-cleansing-preview",
        type=Path,
        default=Path("web/public/market-dashboard/source_cleansing_preview.json"),
    )
    parser.add_argument(
        "--daily-bars-readiness-backlog",
        type=Path,
        default=Path(
            "web/public/market-dashboard/"
            "daily_bars_backfill_batch001_slice001_readiness_backlog.json"
        ),
    )
    args = parser.parse_args()

    payload = build_data_quality_control_report(
        DataQualityControlReportConfig(
            output_dir=args.output_dir,
            data_quality_profile_path=args.data_quality_profile,
            data_gap_dashboard_path=args.data_gap_dashboard,
            source_drift_audit_path=args.source_drift_audit,
            source_cleansing_preview_path=args.source_cleansing_preview,
            daily_bars_readiness_backlog_path=args.daily_bars_readiness_backlog,
            mirror_dirs=tuple(args.mirror_dir),
        )
    )
    print(json.dumps(payload["summary"], ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
