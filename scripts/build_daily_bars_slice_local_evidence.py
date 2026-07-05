from __future__ import annotations

import json

from investment_assistant.webapi.daily_bars_slice_local_evidence import (
    DailyBarsSliceLocalEvidenceConfig,
    build_daily_bars_slice_local_evidence,
)


def main() -> None:
    payload = build_daily_bars_slice_local_evidence(DailyBarsSliceLocalEvidenceConfig())
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
