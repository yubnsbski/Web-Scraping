from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen

API_URL = "http://127.0.0.1:8000/api/fetch-job/auto"
STATE_PATH = Path(".cache/investment_assistant/auto_scrape_state.json")

SOURCES = [
    {
        "name": "9432_NTT_ir",
        "url": "https://group.ntt/jp/ir/",
        "output_path": "local_docs/nikkei225/9432/ir.txt",
        "query_hint": "9432 NTT 配当 方針 DOE 配当性向 IR",
        "extract_text": True,
        "include_metadata": True,
        "preview_chars": 500,
    },
    {
        "name": "7203_toyota_ir",
        "url": "https://global.toyota/jp/ir/",
        "output_path": "local_docs/nikkei225/7203/ir.txt",
        "query_hint": "7203 トヨタ 配当 方針 株主還元 IR",
        "extract_text": True,
        "include_metadata": True,
        "preview_chars": 500,
    },
]

def next_6am(now: datetime) -> datetime:
    target = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target

def run_once() -> None:
    body = json.dumps(
        {
            "sources": SOURCES,
            "db_path": ".cache/investment_assistant/rag.sqlite",
            "index_path": "local_docs",
            "index_after_fetch": True,
        }
    ).encode("utf-8")

    req = Request(
        API_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=120) as res:
        payload = json.loads(res.read().decode("utf-8"))

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(
            {
                "last_run_at": datetime.now().isoformat(),
                "result": payload,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)

def main() -> None:
    print("auto scrape scheduler started; daily 06:00", flush=True)
    while True:
        target = next_6am(datetime.now())
        seconds = max(1, int((target - datetime.now()).total_seconds()))
        print(f"next run at {target.isoformat()}", flush=True)
        time.sleep(seconds)
        try:
            run_once()
        except Exception as exc:
            print(f"auto scrape failed: {type(exc).__name__}: {exc}", flush=True)
            time.sleep(60)

if __name__ == "__main__":
    main()
