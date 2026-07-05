from __future__ import annotations

import argparse
import json
from pathlib import Path

from investment_assistant.webapi.jpx_ticker_map_reconcile import (
    TickerMapReconcileConfig,
    reconcile_ticker_data_map,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile ticker_data_map to a JPX snapshot.")
    parser.add_argument(
        "--ticker-map",
        type=Path,
        default=Path("web/public/market-dashboard/ticker_data_map.csv"),
    )
    parser.add_argument("--official-snapshot", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("web/public/market-dashboard"))
    parser.add_argument("--mirror-dir", action="append", type=Path, default=[])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    payload = reconcile_ticker_data_map(
        TickerMapReconcileConfig(
            ticker_map_path=args.ticker_map,
            official_snapshot_path=args.official_snapshot,
            output_dir=args.output_dir,
            apply=args.apply,
            mirror_dirs=tuple(args.mirror_dir),
        )
    )
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 0 if payload["status"] in {"pass", "fixed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
