from __future__ import annotations

import argparse
import json
from pathlib import Path

from investment_assistant.webapi.jpx_count_audit import JpxCountAuditConfig, build_jpx_count_audit


def main() -> int:
    parser = argparse.ArgumentParser(description="Build JPX listed issue count audit artifacts.")
    parser.add_argument("--dashboard-root", type=Path, default=Path("web/public/market-dashboard"))
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--mirror-dir", action="append", type=Path, default=[])
    args = parser.parse_args()

    payload = build_jpx_count_audit(
        JpxCountAuditConfig(
            dashboard_root=args.dashboard_root,
            output_dir=args.output_dir,
            mirror_dirs=tuple(args.mirror_dir),
        )
    )
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
