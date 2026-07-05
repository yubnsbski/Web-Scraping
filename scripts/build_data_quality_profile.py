"""Build static Data Quality Profile artifacts for the market dashboard."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from investment_assistant.webapi.data_quality_profile_artifacts import (
    DataQualityProfileArtifactConfig,
    build_data_quality_profile_artifacts,
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
    parser.add_argument("--jpx-listed-issues-path")
    parser.add_argument("--company-master-path")
    parser.add_argument("--domestic-universe-path")
    parser.add_argument("--current-prices-path")
    parser.add_argument("--market-financials-path")
    parser.add_argument("--daily-bars-path")
    args = parser.parse_args()

    request_body = {
        key: value
        for key, value in {
            "jpx_listed_issues_path": args.jpx_listed_issues_path,
            "company_master_path": args.company_master_path,
            "domestic_universe_path": args.domestic_universe_path,
            "current_prices_path": args.current_prices_path,
            "market_financials_path": args.market_financials_path,
            "daily_bars_path": args.daily_bars_path,
        }.items()
        if value
    }
    payload = build_data_quality_profile_artifacts(
        DataQualityProfileArtifactConfig(
            output_dir=args.output_dir,
            mirror_dirs=tuple(args.mirror_dir),
            request_body=request_body,
        )
    )
    print(json.dumps(payload["summary"], ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
