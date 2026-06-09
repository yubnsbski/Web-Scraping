"""Weekly EDINET ingest scheduler.

Runs every Monday at 06:00 local time and triggers the EDINET ingest endpoint,
which downloads the latest official filings for the registry's targets and
indexes the extracted financial numbers into RAG. The webapi server
(``investment-assistant serve``) must be running.

Timing logic lives in ``investment_assistant.scheduling.next_weekly_run`` so it
can be unit-tested without running this loop.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from investment_assistant.scheduling import next_weekly_run  # noqa: E402

API_BASE = "http://127.0.0.1:8000/api"
API_URL = f"{API_BASE}/edinet/ingest"
PRUNE_URL = f"{API_BASE}/storage/prune"
STATE_PATH = Path(".cache/investment_assistant/edinet_schedule_state.json")
REGISTRY_PATH = "examples/source_registry_nikkei225_edinet.yaml"
SCAN_DAYS = 7
# Retain the most recent N filings per ticker so storage stays bounded; the
# durable dividend history lives in financials.csv and is not pruned.
KEEP_PER_DIR = 8


def _post(url: str, body: dict[str, object]) -> dict[str, object]:
    req = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=300) as res:  # noqa: S310 - fixed localhost endpoint
        result: dict[str, object] = json.loads(res.read().decode("utf-8"))
    return result


def run_once() -> None:
    payload = _post(
        API_URL,
        {
            "registry_path": REGISTRY_PATH,
            "days": SCAN_DAYS,
            "db_path": ".cache/investment_assistant/rag.sqlite",
            "index_after_fetch": True,
        },
    )
    # Auto-delete old data so weekly accumulation cannot grow unbounded.
    payload["storage_prune"] = _post(PRUNE_URL, {"keep_per_dir": KEEP_PER_DIR})

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(
            {"last_run_at": datetime.now().isoformat(), "result": payload},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)


def main() -> None:
    print("edinet scheduler started; weekly Monday 06:00", flush=True)
    while True:
        target = next_weekly_run(datetime.now(), weekday=0, hour=6)
        seconds = max(1, int((target - datetime.now()).total_seconds()))
        print(f"next run at {target.isoformat()}", flush=True)
        time.sleep(seconds)
        try:
            run_once()
        except Exception as exc:  # noqa: BLE001 - keep the loop alive
            print(f"edinet ingest failed: {type(exc).__name__}: {exc}", flush=True)
            time.sleep(60)


if __name__ == "__main__":
    main()
