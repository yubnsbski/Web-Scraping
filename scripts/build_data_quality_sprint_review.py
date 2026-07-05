"""Build repeatable data-quality sprint review artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from investment_assistant.webapi.data_quality_sprint_review import (
    DataQualitySprintReviewConfig,
    build_data_quality_sprint_review,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dashboard-root",
        type=Path,
        default=Path("web/public/market-dashboard"),
        help="Directory containing existing dashboard artifacts.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory where sprint review artifacts are written. Defaults to dashboard root.",
    )
    parser.add_argument(
        "--mirror-dir",
        action="append",
        type=Path,
        default=[],
        help="Optional mirror output directory. Can be repeated.",
    )
    args = parser.parse_args()

    payload = build_data_quality_sprint_review(
        DataQualitySprintReviewConfig(
            dashboard_root=args.dashboard_root,
            output_dir=args.output_dir,
            mirror_dirs=tuple(args.mirror_dir),
        )
    )
    print(json.dumps(payload["summary"], ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
