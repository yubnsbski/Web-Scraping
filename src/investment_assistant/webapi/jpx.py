"""JPX NeuroFinance pipeline API handlers.

Endpoints:
  GET/POST /api/jpx/status   — data freshness & file inventory
  POST     /api/jpx/results  — return jpx_ml_v3_results.json as JSON
  POST     /api/jpx/run      — trigger ML pipeline (v2 → v3 → viz) as background job

Security notes:
  - All file paths are resolved from __file__ (never from user input).
  - subprocess uses an explicit args list (no shell=True).
  - Server already binds to 127.0.0.1; no auth needed for single-user localhost.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from investment_assistant.webapi.jobs import JOBS

JsonDict = dict[str, Any]

# ── Hardcoded paths (no user input touches these) ───────────────────────────

# jpx.py lives at:  <repo>/src/investment_assistant/webapi/jpx.py
#   parents[0] = webapi/
#   parents[1] = investment_assistant/
#   parents[2] = src/
#   parents[3] = <repo root>  ← Web-Scraping/
_WS = Path(__file__).resolve().parents[3]

_DASHBOARD_HTML = _WS / "JPX_NeuroFinance_Dashboard.html"
_DATA_JSON      = _WS / "jpx_data.json"
_ML_RESULTS     = _WS / "jpx_ml_results.json"
_V2_RESULTS     = _WS / "jpx_ml_v2_results.json"
_V3_RESULTS     = _WS / "jpx_ml_v3_results.json"
_CACHE          = _WS / "extra_features_cache_v290.json"

# Pipeline scripts executed in order by jpx_run()
_PIPELINE: list[Path] = [
    _WS / "jpx_ml_v2.py",
    _WS / "jpx_ml_v3.py",
    _WS / "jpx_viz_gen.py",
]

_PIPELINE_TIMEOUT_SECS = 1800  # 30 min total


# ── helpers ──────────────────────────────────────────────────────────────────

def _file_info(path: Path) -> JsonDict:
    """Return size and modification time for a file, or exists=False."""
    if not path.exists():
        return {"exists": False, "path": path.name}
    stat = path.stat()
    return {
        "exists": True,
        "path": path.name,
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }


def _stock_count(path: Path) -> int | None:
    """Return number of stocks in a jpx JSON file, or None on error."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        stocks = data.get("stocks") or data.get("ranked") or []
        return len(stocks)
    except Exception:
        return None


# ── handlers ─────────────────────────────────────────────────────────────────

def jpx_status(_: JsonDict) -> JsonDict:
    """Return freshness status for all JPX data files."""
    return {
        "ok": True,
        "n_stocks": _stock_count(_DATA_JSON),
        "files": {
            "jpx_data":   _file_info(_DATA_JSON),
            "ml_results": _file_info(_ML_RESULTS),
            "v2_results": _file_info(_V2_RESULTS),
            "v3_results": _file_info(_V3_RESULTS),
            "cache":      _file_info(_CACHE),
            "dashboard":  _file_info(_DASHBOARD_HTML),
        },
        "pipeline_scripts_present": all(p.exists() for p in _PIPELINE),
        "dashboard_ready": _DASHBOARD_HTML.exists(),
        "ws_path": str(_WS),
    }


def jpx_results(_: JsonDict) -> JsonDict:
    """Return jpx_ml_v3_results.json as JSON."""
    if not _V3_RESULTS.exists():
        return {
            "error": "jpx_ml_v3_results.json が存在しません。",
            "hint": "POST /api/jpx/run でパイプラインを実行してください。",
        }
    try:
        data = json.loads(_V3_RESULTS.read_text(encoding="utf-8"))
        return {"ok": True, "data": data}
    except Exception as exc:
        return {"ok": False, "error": f"JSON読み込みエラー: {type(exc).__name__}: {exc}"}


def jpx_run(_: JsonDict) -> JsonDict:
    """Start ML pipeline (jpx_ml_v2 → jpx_ml_v3 → jpx_viz_gen) as a background job.

    Prerequisite: jpx_ml_results.json must already exist
    (produced by jpx_ml_analysis.py, which requires jpx_data.json from jpx_collect_v2.py).
    """
    if not _ML_RESULTS.exists():
        return {
            "error": "jpx_ml_results.json が存在しません。",
            "hint": "先に jpx_ml_analysis.py を実行してください。",
            "ok": False,
        }

    missing = [p.name for p in _PIPELINE if not p.exists()]
    if missing:
        return {
            "error": f"パイプラインスクリプトが見つかりません: {missing}",
            "ok": False,
        }

    python = sys.executable  # venv Python — never shell=True

    def _run() -> JsonDict:
        steps: list[JsonDict] = []
        for script in _PIPELINE:
            # Explicit args list prevents shell injection
            proc = subprocess.run(
                [python, str(script)],
                capture_output=True,
                text=True,
                timeout=_PIPELINE_TIMEOUT_SECS,
            )
            step: JsonDict = {
                "script": script.name,
                "returncode": proc.returncode,
                "ok": proc.returncode == 0,
            }
            if proc.returncode != 0:
                step["stderr_tail"] = proc.stderr[-500:] if proc.stderr else ""
                steps.append(step)
                return {"ok": False, "failed_at": script.name, "steps": steps}
            steps.append(step)
        return {
            "ok": True,
            "steps": steps,
            "dashboard": str(_DASHBOARD_HTML),
        }

    job_id = JOBS.start("jpx-pipeline", _run)
    return {
        "job_id": job_id,
        "status": "running",
        "kind": "jpx-pipeline",
        "poll": f"POST /api/jobs/status  {{\"job_id\": \"{job_id}\"}}",
    }
