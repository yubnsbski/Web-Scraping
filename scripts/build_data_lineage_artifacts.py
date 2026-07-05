from __future__ import annotations

import json

from investment_assistant.webapi.data_lineage_artifacts import (
    build_data_lineage_artifacts,
)


def main() -> None:
    result = build_data_lineage_artifacts()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
