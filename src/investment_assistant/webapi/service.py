"""Framework-agnostic JSON API over the existing CLI run_* functions.

This module contains no socket or HTTP-server code so it can be unit-tested
in-process without binding a port or hitting the network. ``server.py`` is a
thin stdlib adapter on top of :func:`handle_api`.

Design notes:
* Read-only/offline endpoints (RAG search, answer-context, orchestration with
  the local client, scoring, forecasting on a local CSV, budget) never call
  Gemini or the network and are safe to test.
* The fetch endpoints reach the network (robots.txt + pages) through the same
  guarded SafeFetcher path and are intended for interactive use, not tests.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from investment_assistant import cli
from investment_assistant.llm.factory import DEFAULT_GEMINI_CONFIG_PATH
from investment_assistant.rag.store import DEFAULT_RAG_DB_PATH

JsonDict = dict[str, Any]
Handler = Callable[[JsonDict], JsonDict]


class ApiError(Exception):
    """Raised by handlers to return a 4xx with a JSON error body."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def handle_api(method: str, path: str, body: JsonDict | None = None) -> tuple[int, JsonDict]:
    """Route an API request to a handler and return (status_code, payload)."""

    handler = _ROUTES.get((method.upper(), path.rstrip("/") or "/"))
    if handler is None:
        return 404, {"error": f"no such endpoint: {method} {path}"}
    try:
        return 200, handler(body or {})
    except ApiError as exc:
        return exc.status, {"error": exc.message}
    except (ValueError, KeyError, FileNotFoundError, OSError) as exc:
        return 400, {"error": f"{type(exc).__name__}: {exc}"}


# --- handlers --------------------------------------------------------------


def _health(_: JsonDict) -> JsonDict:
    return {"status": "ok", "service": "investment-assistant", "auto_trading": False}


def _budget(_: JsonDict) -> JsonDict:
    from dataclasses import asdict

    return asdict(cli.build_budget_report(DEFAULT_GEMINI_CONFIG_PATH))


def _rag_search(body: JsonDict) -> JsonDict:
    query = _require_str(body, "query")
    results = cli.run_rag_search(
        query=query,
        db_path=str(body.get("db_path") or DEFAULT_RAG_DB_PATH),
        limit=_as_int(body.get("limit"), 5),
        hybrid=bool(body.get("hybrid", False)),
        alpha=_as_float(body.get("alpha"), 0.5),
    )
    return {"query": query, "results": results}


def _rag_answer_context(body: JsonDict) -> JsonDict:
    return cli.run_rag_answer_context(
        query=_require_str(body, "query"),
        db_path=str(body.get("db_path") or DEFAULT_RAG_DB_PATH),
        limit=_as_int(body.get("limit"), 5),
    )


def _rag_answer(body: JsonDict) -> JsonDict:
    # call_real_api is intentionally never exposed to the web UI.
    return cli.run_rag_answer(
        query=_require_str(body, "query"),
        db_path=str(body.get("db_path") or DEFAULT_RAG_DB_PATH),
        limit=_as_int(body.get("limit"), 5),
        call_real_api=False,
    )


def _orchestrate(body: JsonDict) -> JsonDict:
    return cli.run_orchestrate_answer(
        query=_require_str(body, "query"),
        db_path=str(body.get("db_path") or DEFAULT_RAG_DB_PATH),
        limit=_as_int(body.get("limit"), 5),
        drafts=_as_int(body.get("drafts"), 1),
        include_critique=bool(body.get("critique", True)),
        hybrid=bool(body.get("hybrid", False)),
        alpha=_as_float(body.get("alpha"), 0.5),
        call_real_api=False,
    )


def _rag_index_dir(body: JsonDict) -> JsonDict:
    return cli.run_rag_index_dir(
        path=_require_str(body, "path"),
        db_path=str(body.get("db_path") or DEFAULT_RAG_DB_PATH),
    )


def _scoring_rank(body: JsonDict) -> JsonDict:
    csv_text = body.get("csv_text")
    if csv_text:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".csv", delete=False, encoding="utf-8"
        ) as handle:
            handle.write(str(csv_text))
            path = handle.name
        try:
            return cli.run_scoring_rank(path=path, limit=_as_int(body.get("limit"), 10))
        finally:
            Path(path).unlink(missing_ok=True)
    return cli.run_scoring_rank(
        path=_require_str(body, "path"), limit=_as_int(body.get("limit"), 10)
    )


def _forecast_evaluate(body: JsonDict) -> JsonDict:
    return cli.run_forecast_evaluate(
        path=str(body.get("path") or _SAMPLE_SP500),
        value_column=str(body.get("value_column") or "SP500"),
        horizon=_as_int(body.get("horizon"), 1),
        step=_as_int(body.get("step"), 1),
        tail=None if body.get("tail") is None else _as_int(body.get("tail"), 0),
        include_ml=bool(body.get("include_ml", False)),
        ensemble_method=str(body.get("ensemble_method") or "weighted"),
        space=str(body.get("space") or "returns"),
        ma_windows=_as_int_tuple(body.get("ma_windows")),
    )


def _forecast_predict(body: JsonDict) -> JsonDict:
    return cli.run_forecast_predict(
        path=str(body.get("path") or _SAMPLE_SP500),
        value_column=str(body.get("value_column") or "SP500"),
        horizon=_as_int(body.get("horizon"), 1),
        include_ml=bool(body.get("include_ml", False)),
        space=str(body.get("space") or "returns"),
    )


def _cache_maintenance(body: JsonDict) -> JsonDict:
    max_rows = body.get("max_rows")
    return cli.run_cache_maintenance(
        config_path=DEFAULT_GEMINI_CONFIG_PATH,
        max_rows=None if max_rows is None else _as_int(max_rows, 0),
    )


def _fetch_job(body: JsonDict, *, dry_run: bool) -> JsonDict:
    """Run a fetch-job from inline sources or a server-side path (network)."""

    path = body.get("path")
    if path:
        return cli.run_fetch_job(path=str(path), dry_run=dry_run)
    sources = body.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ApiError("provide 'path' or a non-empty 'sources' list")
    yaml_text = _sources_to_yaml(sources)
    with tempfile.NamedTemporaryFile(
        "w", suffix=".yaml", delete=False, encoding="utf-8"
    ) as handle:
        handle.write(yaml_text)
        temp_path = handle.name
    try:
        return cli.run_fetch_job(path=temp_path, dry_run=dry_run)
    finally:
        Path(temp_path).unlink(missing_ok=True)


# --- helpers ---------------------------------------------------------------

_SAMPLE_SP500 = str(
    Path(__file__).resolve().parents[3] / "examples" / "sp500_monthly_sample.csv"
)


def _require_str(body: JsonDict, key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ApiError(f"missing required string field: {key}")
    return value


def _as_int(value: object, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: object, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int_tuple(value: object) -> tuple[int, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(_as_int(item, 0) for item in value if _as_int(item, 0) > 0)


def _sources_to_yaml(sources: list[Any]) -> str:
    """Serialize inline fetch-job sources into the loader's YAML subset."""

    lines = ["sources:"]
    for source in sources:
        if not isinstance(source, dict):
            raise ApiError("each source must be an object")
        items = list(source.items())
        if not items:
            raise ApiError("source objects must not be empty")
        first_key, first_value = items[0]
        lines.append(f"  - {first_key}: {_yaml_scalar(first_value)}")
        for key, value in items[1:]:
            lines.append(f"    {key}: {_yaml_scalar(value)}")
    return "\n".join(lines) + "\n"


def _yaml_scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    text = str(value).replace('"', '\\"')
    return f'"{text}"'


_ROUTES: dict[tuple[str, str], Handler] = {
    ("GET", "/api/health"): _health,
    ("GET", "/api/budget"): _budget,
    ("POST", "/api/rag/search"): _rag_search,
    ("POST", "/api/rag/answer-context"): _rag_answer_context,
    ("POST", "/api/rag/answer"): _rag_answer,
    ("POST", "/api/orchestrate"): _orchestrate,
    ("POST", "/api/rag/index-dir"): _rag_index_dir,
    ("POST", "/api/scoring/rank"): _scoring_rank,
    ("POST", "/api/forecast/evaluate"): _forecast_evaluate,
    ("POST", "/api/forecast/predict"): _forecast_predict,
    ("POST", "/api/cache/maintenance"): _cache_maintenance,
    ("POST", "/api/fetch-job/dry-run"): lambda body: _fetch_job(body, dry_run=True),
    ("POST", "/api/fetch-job/run"): lambda body: _fetch_job(body, dry_run=False),
}


def available_routes() -> list[str]:
    """Return a sorted list of "METHOD /path" route descriptors."""

    return sorted(f"{method} {path}" for method, path in _ROUTES)
