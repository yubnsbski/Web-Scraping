from __future__ import annotations

import json

from investment_assistant.webapi.market_dashboard_entry_artifacts import (
    build_market_dashboard_entry_artifacts,
)


def main() -> None:
    result = build_market_dashboard_entry_artifacts()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
