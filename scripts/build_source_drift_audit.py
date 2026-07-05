"""Build static raw-source drift audit artifacts for the market dashboard."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from investment_assistant.webapi.source_drift_audit import (
    SourceDriftAuditConfig,
    build_source_drift_audit,
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
        "--reference-universe",
        type=Path,
        default=Path("local_docs/market/domestic_universe.csv"),
    )
    parser.add_argument(
        "--cleaned-map",
        type=Path,
        default=Path("web/public/market-dashboard/ticker_data_map.csv"),
    )
    parser.add_argument(
        "--current-prices",
        type=Path,
        default=Path("local_docs/market/current_prices.csv"),
    )
    parser.add_argument(
        "--market-financials",
        type=Path,
        default=Path("local_docs/market/yahoo_financials.csv"),
    )
    args = parser.parse_args()

    payload = build_source_drift_audit(
        SourceDriftAuditConfig(
            output_dir=args.output_dir,
            reference_universe_path=args.reference_universe,
            cleaned_map_path=args.cleaned_map,
            current_prices_path=args.current_prices,
            market_financials_path=args.market_financials,
            mirror_dirs=tuple(args.mirror_dir),
        )
    )
    print(json.dumps(payload["summary"], ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
