from __future__ import annotations

import json

from investment_assistant.webapi.daily_bars_slice_review_gate import (
    DailyBarsSliceReviewGateConfig,
    build_daily_bars_slice_review_gate,
)


def main() -> None:
    payload = build_daily_bars_slice_review_gate(DailyBarsSliceReviewGateConfig())
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
