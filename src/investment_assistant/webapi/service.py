"""Framework-agnostic JSON API over the existing CLI run_* functions."""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from difflib import get_close_matches
from pathlib import Path
from typing import Any

from investment_assistant import cli
from investment_assistant.financials import (
    compare_financials,
    load_financials,
)
from investment_assistant.financials.evidence import (
    DEFAULT_FINANCIALS_CSV,
    build_financial_evidence,
)
from investment_assistant.llm.factory import DEFAULT_GEMINI_CONFIG_PATH
from investment_assistant.rag.store import DEFAULT_RAG_DB_PATH
from investment_assistant.webapi import chat as chat_api
from investment_assistant.webapi import data_status as data_status_api
from investment_assistant.webapi import edinet as edinet_api
from investment_assistant.webapi import investments as investment_api
from investment_assistant.webapi import jpx as jpx_api
from investment_assistant.webapi import market as market_api
from investment_assistant.webapi import portfolio as portfolio_api
from investment_assistant.webapi import reports as report_api
from investment_assistant.webapi import sprint_api
from investment_assistant.webapi import stock_analysis as stock_analysis_api
from investment_assistant.webapi.errors import ApiError
from investment_assistant.webapi.jobs import JOBS

JsonDict = dict[str, Any]
Handler = Callable[[JsonDict], JsonDict]
_REAL_API_ENV = "INVESTMENT_ASSISTANT_WEB_REAL_API"
_REAL_API_RUNTIME_ENABLED = False
_DEFAULT_DAILY_BARS_CSV = "local_docs/market/daily_bars.csv"


def handle_api(method: str, path: str, body: JsonDict | None = None) -> tuple[int, JsonDict]:
    handler = _ROUTES.get((method.upper(), path.rstrip("/") or "/"))
    if handler is None:
        return 404, _unknown_endpoint(method=method, path=path)
    try:
        return 200, handler(body or {})
    except ApiError as exc:
        return exc.status, {"error": exc.message}
    except (ValueError, KeyError, FileNotFoundError, OSError) as exc:
        return 400, {"error": f"{type(exc).__name__}: {exc}"}


# --- handlers --------------------------------------------------------------


def _health(_: JsonDict) -> JsonDict:
    return {
        "status": "ok",
        "service": "investment-assistant",
        "route_count": len(_ROUTES),
        "auto_trading": False,
        "call_real_api": False,
    }


def _system_diagnostics(body: JsonDict) -> JsonDict:
    routes = available_routes()
    payload: JsonDict = {
        "status": "ok",
        "service": "investment-assistant",
        "generated_at": datetime.now(UTC).isoformat(),
        "frontend": _frontend_asset_summary(),
        "market_dashboard": _market_dashboard_status({}),
        "routes": routes,
        "route_count": len(routes),
        "route_groups": _route_groups(routes),
        "critical_routes": _critical_route_status(),
        "auto_trading": False,
        "call_real_api": False,
    }
    if _as_bool(body.get("include_data_status"), False):
        try:
            payload["data_status"] = data_status_api.data_status({})
        except Exception as exc:  # pragma: no cover - defensive diagnostics
            payload["data_status_error"] = f"{type(exc).__name__}: {exc}"
    return payload


def _frontend_asset_summary() -> JsonDict:
    dist = Path(__file__).resolve().parents[3] / "web" / "dist"
    index = dist / "index.html"
    assets: list[str] = []
    if index.exists():
        html = index.read_text(encoding="utf-8", errors="replace")
        assets = sorted(set(re.findall(r'["\'](/assets/[^"\']+)["\']', html)))
    return {
        "dist_path": str(dist),
        "dist_exists": dist.exists(),
        "index_exists": index.exists(),
        "assets": assets,
    }


def _market_dashboard_root() -> Path:
    return Path(__file__).resolve().parents[3] / "web" / "dist" / "market-dashboard"


def _read_dashboard_json(root: Path, filename: str, warnings: list[str]) -> JsonDict:
    import json

    path = root / filename
    if not path.is_file():
        warnings.append(f"missing {filename}")
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        warnings.append(f"invalid {filename}: {exc}")
        return {}
    if not isinstance(payload, dict):
        warnings.append(f"invalid {filename}: root is not object")
        return {}
    return payload


def _read_optional_dashboard_json(root: Path, filename: str, warnings: list[str]) -> JsonDict:
    if not (root / filename).is_file():
        return {}
    return _read_dashboard_json(root, filename, warnings)


def _status_is_ok(value: Any) -> bool:
    return str(value or "").lower() in {"ok", "pass", "ready", "success"}


def _dashboard_list_count(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _html_content_status(root: Path, filenames: list[str], warnings: list[str]) -> JsonDict:
    markers = ("\u7e5d", "\ufffd")
    html_status: JsonDict = {}
    for filename in sorted(set(filenames)):
        path = root / filename
        exists = path.is_file()
        marker_hits: list[str] = []
        if exists:
            text = path.read_text(encoding="utf-8", errors="replace")
            marker_hits = [marker for marker in markers if marker in text]
            if marker_hits:
                warnings.append(f"html content mojibake: {filename}")
        html_status[filename] = {
            "exists": exists,
            "mojibake": bool(marker_hits),
            "content_ok": exists and not marker_hits,
        }
    return html_status


def _entry_link_status(root: Path, cards: list[Any], warnings: list[str]) -> JsonDict:
    link_status: JsonDict = {}
    for index, card in enumerate(cards, start=1):
        if not isinstance(card, dict):
            continue
        raw_link = card.get("link")
        if not isinstance(raw_link, str) or not raw_link:
            continue
        if raw_link.startswith(("/", "http://", "https://", "#")):
            link_status[raw_link] = {"kind": "external_or_absolute", "exists": True}
            continue
        target = root / raw_link
        exists = target.is_file()
        link_status[raw_link] = {"kind": "local_file", "exists": exists}
        if not exists:
            title = card.get("title") or f"card {index}"
            warnings.append(f"entry link missing: {title} -> {raw_link}")
    return link_status


def _entry_html_has_link(root: Path, link: str) -> bool:
    path = root / "market_dashboard_entry.html"
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    return f'href="{link}"' in text or f"href='{link}'" in text or link in text


def _market_dashboard_status(_: JsonDict) -> JsonDict:
    root = _market_dashboard_root()
    warnings: list[str] = []
    entry = _read_dashboard_json(root, "market_dashboard_entry.json", warnings)
    health = _read_dashboard_json(root, "market_dashboard_health_check.json", warnings)
    api_contract = _read_dashboard_json(
        root, "frontend_backend_api_contract_audit.json", warnings
    )
    workflow = _read_dashboard_json(root, "yield_refetch_workflow_status.json", warnings)
    control_report = _read_optional_dashboard_json(
        root, "data_quality_control_report.json", warnings
    )
    lineage = _read_optional_dashboard_json(root, "lineage.json", warnings)
    readiness_backlog = _read_optional_dashboard_json(
        root,
        "daily_bars_backfill_batch001_slice001_readiness_backlog.json",
        warnings,
    )
    local_evidence = _read_optional_dashboard_json(
        root,
        "daily_bars_backfill_batch001_slice001_local_evidence.json",
        warnings,
    )
    review_gate = _read_optional_dashboard_json(
        root,
        "daily_bars_backfill_batch001_slice001_review_gate.json",
        warnings,
    )

    cards = entry.get("cards") if isinstance(entry.get("cards"), list) else []
    readiness_backlog_link = (
        "daily_bars_backfill_batch001_slice001_readiness_backlog.html"
    )
    local_evidence_link = "daily_bars_backfill_batch001_slice001_local_evidence.html"
    review_gate_link = "daily_bars_backfill_batch001_slice001_review_gate.html"
    control_report_visible = any(
        isinstance(card, dict)
        and card.get("link") == "data_quality_control_report.html"
        for card in cards
    )
    lineage_visible = _entry_html_has_link(root, "lineage.html") or any(
        isinstance(card, dict) and card.get("link") == "lineage.html" for card in cards
    )
    readiness_backlog_visible = _entry_html_has_link(
        root, readiness_backlog_link
    ) or any(
        isinstance(card, dict) and card.get("link") == readiness_backlog_link
        for card in cards
    )
    local_evidence_visible = _entry_html_has_link(root, local_evidence_link) or any(
        isinstance(card, dict) and card.get("link") == local_evidence_link
        for card in cards
    )
    review_gate_visible = _entry_html_has_link(root, review_gate_link) or any(
        isinstance(card, dict) and card.get("link") == review_gate_link
        for card in cards
    )
    health_summary = health.get("summary") if isinstance(health.get("summary"), dict) else {}
    expected_entry_cards = health_summary.get("entry_cards")
    if isinstance(expected_entry_cards, int) and expected_entry_cards != len(cards):
        warnings.append(
            f"entry card count mismatch: entry={len(cards)} health={expected_entry_cards}"
        )
    key_files = [
        "index.html",
        "market_dashboard_entry.html",
        "market_dashboard_entry.json",
        "market_dashboard_health_check.html",
        "market_dashboard_health_check.json",
        "frontend_backend_api_contract_audit.html",
        "frontend_backend_api_contract_audit.json",
        "yield_refetch_workflow_status.html",
        "yield_refetch_workflow_status.json",
    ]
    if control_report or (root / "data_quality_control_report.html").is_file():
        key_files.extend(
            [
                "data_quality_control_report.html",
                "data_quality_control_report.json",
            ]
        )
    if lineage or (root / "lineage.html").is_file():
        key_files.extend(["lineage.html", "lineage.json"])
    if readiness_backlog or (root / readiness_backlog_link).is_file():
        key_files.extend(
            [
                readiness_backlog_link,
                "daily_bars_backfill_batch001_slice001_readiness_backlog.json",
                "daily_bars_backfill_batch001_slice001_readiness_backlog.csv",
                "daily_bars_backfill_batch001_slice001_readiness_backlog_field_summary.csv",
            ]
        )
    if local_evidence or (root / local_evidence_link).is_file():
        key_files.extend(
            [
                local_evidence_link,
                "daily_bars_backfill_batch001_slice001_local_evidence.json",
                "daily_bars_backfill_batch001_slice001_local_evidence.csv",
                "daily_bars_backfill_batch001_slice001_local_evidence_field_matrix.csv",
                "daily_bars_backfill_batch001_slice001_local_evidence_review_queue.csv",
            ]
        )
    if review_gate or (root / review_gate_link).is_file():
        key_files.extend(
            [
                review_gate_link,
                "daily_bars_backfill_batch001_slice001_review_gate.json",
                "daily_bars_backfill_batch001_slice001_review_gate.csv",
                "daily_bars_backfill_batch001_slice001_review_gate_validation.csv",
                "daily_bars_backfill_batch001_slice001_review_gate_field_summary.csv",
            ]
        )
    static_files = {filename: (root / filename).is_file() for filename in key_files}
    entry_link_status = _entry_link_status(root, cards, warnings)
    html_files = [filename for filename in key_files if filename.endswith(".html")]
    for link, link_status in entry_link_status.items():
        if link_status.get("kind") == "local_file" and link.lower().endswith(".html"):
            html_files.append(link)
    html_content_status = _html_content_status(root, html_files, warnings)
    required_ok = all(
        [
            _status_is_ok(entry.get("status")),
            _status_is_ok(health.get("status")),
            _status_is_ok(api_contract.get("status")),
            static_files["index.html"],
            static_files["market_dashboard_entry.html"],
        ]
    )
    status = "pass" if required_ok and not warnings else "needs_attention"
    workflow_steps = workflow.get("steps")
    return {
        "status": status,
        "generated_at": datetime.now(UTC).isoformat(),
        "dashboard_root": str(root),
        "entry_url": "/market-dashboard/",
        "entry": {
            "status": entry.get("status"),
            "title": entry.get("title"),
            "updated_at": entry.get("updated_at"),
            "card_count": len(cards),
            "cards": cards[:20],
            "data_status_visible": bool(entry.get("data_status_visible")),
            "data_quality_control_visible": control_report_visible,
            "lineage_visible": lineage_visible,
            "readiness_backlog_visible": readiness_backlog_visible,
            "local_evidence_visible": local_evidence_visible,
            "review_gate_visible": review_gate_visible,
            "data_api": entry.get("data_api"),
        },
        "health": {
            "status": health.get("status"),
            "summary": health_summary,
        },
        "api_contract": {
            "status": api_contract.get("status"),
            "summary": api_contract.get("summary", {}),
        },
        "workflow": {
            "status": workflow.get("status"),
            "current_coverage_pct": workflow.get("current_coverage_pct"),
            "step_count": _dashboard_list_count(workflow_steps),
        },
        "control_report": {
            "status": control_report.get("status"),
            "summary": control_report.get("summary", {}),
            "visible_from_entry": control_report_visible,
            "link": "data_quality_control_report.html"
            if control_report_visible
            else None,
        },
        "lineage": {
            "status": lineage.get("status"),
            "summary": lineage.get("summary", {}),
            "visible_from_entry": lineage_visible,
            "link": "lineage.html" if lineage_visible else None,
        },
        "readiness_backlog": {
            "status": readiness_backlog.get("status"),
            "summary": readiness_backlog.get("summary", {}),
            "visible_from_entry": readiness_backlog_visible,
            "link": readiness_backlog_link if readiness_backlog_visible else None,
        },
        "local_evidence": {
            "status": local_evidence.get("status"),
            "summary": local_evidence.get("summary", {}),
            "visible_from_entry": local_evidence_visible,
            "link": local_evidence_link if local_evidence_visible else None,
        },
        "review_gate": {
            "status": review_gate.get("status"),
            "summary": review_gate.get("summary", {}),
            "visible_from_entry": review_gate_visible,
            "link": review_gate_link if review_gate_visible else None,
        },
        "static_files": static_files,
        "entry_link_status": entry_link_status,
        "html_content_status": html_content_status,
        "warnings": warnings,
        "write_to_current_yields": False,
        "external_fetch_executed": False,
        "auto_trading": False,
        "call_real_api": False,
    }

def _critical_route_status() -> JsonDict:
    route_set = set(available_routes())
    critical = [
        "GET /api/data/status",
        "POST /api/data/status",
        "GET /api/data/quality",
        "POST /api/data/quality",
        "GET /api/market-dashboard/status",
        "POST /api/market-dashboard/status",
        "POST /api/market/refresh",
        "POST /api/market/rag/build",
        "POST /api/market/financials",
        "POST /api/market/bars",
        "POST /api/market/forecast/screen",
        "POST /api/financials/preview",
        "POST /api/edinet/status",
        "POST /api/rag/search",
        "POST /api/orchestrate",
    ]
    return {route: route in route_set for route in critical}


def _route_groups(routes: list[str]) -> JsonDict:
    groups: dict[str, list[str]] = {}
    for route in routes:
        _, raw_path = route.split(" ", 1)
        parts = [part for part in raw_path.split("/") if part]
        key = parts[1] if len(parts) > 1 and parts[0] == "api" else "other"
        groups.setdefault(key, []).append(route)
    return {key: sorted(value) for key, value in sorted(groups.items())}


def _unknown_endpoint(method: str, path: str) -> JsonDict:
    normalized = f"{method.upper()} {path.rstrip('/') or '/'}"
    routes = available_routes()
    closest = get_close_matches(normalized, routes, n=8, cutoff=0.45)
    if not closest:
        path_only = path.rstrip("/") or "/"
        closest = [route for route in routes if path_only in route][:8]
    return {
        "error": f"no such endpoint: {method} {path}",
        "kind": "endpoint_not_found",
        "requested": {"method": method.upper(), "path": path},
        "hint": (
            "フロント側のコードが古い、またはバックエンド側のルートが古い可能性があります。"
            "/api/system/diagnostics で利用可能なAPIと市場ダッシュボード状態を確認してください。"
        ),        "closest_routes": closest,
        "available_routes": routes,
        "route_count": len(routes),
        "auto_trading": False,
        "call_real_api": False,
    }


def _budget(_: JsonDict) -> JsonDict:
    from dataclasses import asdict

    return asdict(cli.build_budget_report(DEFAULT_GEMINI_CONFIG_PATH))


def _runtime_real_api_status(_: JsonDict) -> JsonDict:
    env_allowed = _as_bool(os.getenv(_REAL_API_ENV), False)
    runtime_enabled = bool(_REAL_API_RUNTIME_ENABLED)
    has_key = bool(os.getenv("GEMINI_API_KEY"))
    return {
        "enabled": env_allowed or runtime_enabled,
        "usable": (env_allowed or runtime_enabled) and has_key,
        "env_allowed": env_allowed,
        "runtime_enabled": runtime_enabled,
        "api_key_configured": has_key,
    }


def _runtime_real_api_set(body: JsonDict) -> JsonDict:
    global _REAL_API_RUNTIME_ENABLED

    requested = _as_bool(body.get("enabled"), False)
    request_has_key = _apply_request_api_key(body)
    has_key = bool(os.getenv("GEMINI_API_KEY"))

    if requested and not has_key:
        _REAL_API_RUNTIME_ENABLED = False
        return {
            "enabled": False,
            "usable": False,
            "api_key_configured": False,
            "request_api_key_applied": request_has_key,
            "error": "GEMINI_API_KEY is not configured on backend",
        }

    _REAL_API_RUNTIME_ENABLED = requested
    return {
        "enabled": _REAL_API_RUNTIME_ENABLED,
        "usable": _REAL_API_RUNTIME_ENABLED and has_key,
        "api_key_configured": has_key,
        "request_api_key_applied": request_has_key,
    }


def _rag_stats(body: JsonDict) -> JsonDict:
    raw_keywords = body.get("keywords")
    if isinstance(raw_keywords, list):
        keywords = tuple(str(item).strip() for item in raw_keywords if str(item).strip())
    else:
        keywords = cli.DEFAULT_RAG_STATS_KEYWORDS
    return cli.run_rag_stats(
        db_path=str(body.get("db_path") or DEFAULT_RAG_DB_PATH),
        keywords=keywords,
    )


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
    call_real_api, real_api_note = _real_api_decision(body)
    result = cli.run_rag_answer(
        query=_require_str(body, "query"),
        db_path=str(body.get("db_path") or DEFAULT_RAG_DB_PATH),
        limit=_as_int(body.get("limit"), 5),
        call_real_api=call_real_api,
    )
    if real_api_note:
        result["real_api_note"] = real_api_note
    return result


def _chat_simulate(body: JsonDict) -> JsonDict:
    """Chat-triggered portfolio simulation with optional Yahoo Finance DPS overrides.

    Accepts:
      query                  : str  – natural-language question (for context only)
      holdings               : list – [{ticker, name, price, dividend_per_share?, ...}]
      budget                 : float – total budget in JPY (use when splitting by weight)
      target_annual_dividend : float – target gross annual dividend (triggers reverse mode)
      dividend_overrides     : dict  – {ticker: dps_float} appended to each holding
      auto_weight            : str   – equal|safety|amount|shares (default equal)
      optimization           : str   – none|cash_min|dividend_max|balanced
      dividend_basis         : str   – conservative|latest
      net_target             : bool  – interpret target as after-tax
    """
    import re
    from investment_assistant.portfolio.simulator import (
        plan_for_target_dividend,
        simulate_portfolio,
    )

    query = _require_str(body, "query")
    raw = body.get("holdings")
    holdings: list[JsonDict] = [h for h in raw if isinstance(h, dict)] if isinstance(raw, list) else []

    # Apply per-ticker dividend overrides (e.g. from Yahoo Finance)
    overrides: dict[str, float] = {}
    raw_ov = body.get("dividend_overrides")
    if isinstance(raw_ov, dict):
        for k, v in raw_ov.items():
            f = _as_float(v, -1.0)
            if f >= 0:
                overrides[str(k)] = f
    if overrides:
        holdings = [
            {**h, "dividend_per_share": overrides[str(h.get("ticker", ""))]}
            if str(h.get("ticker", "")) in overrides
            else h
            for h in holdings
        ]

    common: JsonDict = {
        "years": _as_int(body.get("years"), 10),
        "reinvest": _as_bool(body.get("reinvest"), True),
        "growth_rate": _as_float(body.get("growth_rate"), 0.0),
        "auto_weight": str(body.get("auto_weight") or "equal"),
        "optimization": str(body.get("optimization") or "none"),
        "dividend_basis": str(body.get("dividend_basis") or "latest"),
        "financials_csv": str(body.get("financials_csv") or DEFAULT_FINANCIALS_CSV),
    }

    target = _as_float(body.get("target_annual_dividend"), 0.0)
    budget = _as_float(body.get("budget"), 0.0)

    if not holdings:
        return {"error": "holdings が空です。銘柄リストを渡してください。", "available": False}

    if target > 0:
        result = plan_for_target_dividend(
            target_annual_dividend=target,
            holdings=holdings,
            net_target=_as_bool(body.get("net_target"), False),
            **common,
        )
    elif budget > 0:
        result = simulate_portfolio(budget=budget, holdings=holdings, **common)
    else:
        return {"error": "budget または target_annual_dividend を指定してください。", "available": False}

    # Build markdown answer for the chat panel
    result["answer"] = _sim_to_markdown(query, result, target=target)
    result["text"] = result["answer"]
    return result


def _sim_to_markdown(query: str, result: dict, *, target: float = 0.0) -> str:
    """Format simulator output as Japanese markdown for the chat response."""
    if not result.get("available"):
        hint = result.get("hint", "シミュレーション結果が取得できませんでした。")
        return f"**シミュレーション失敗**: {hint}"

    summary = result.get("summary", {})
    allocs = result.get("allocations", [])
    invested = int(summary.get("invested") or 0)
    budget_val = int(summary.get("budget") or 0)
    annual = int(summary.get("annual_dividend") or 0)
    annual_net = int(summary.get("annual_dividend_net") or 0)
    yield_pct = float(summary.get("portfolio_yield") or 0) * 100
    basis = summary.get("dividend_basis", "latest")
    basis_label = "保守的試算（ボリンジャー下限）" if basis == "conservative" else "直近配当額"

    lines = [
        f"## ポートフォリオシミュレーション",
        f"",
        f"**投資総額**: {invested:,}円（予算 {budget_val:,}円）",
        f"**年間配当（税引前）**: {annual:,}円（{basis_label}）",
        f"**年間配当（税引後概算）**: {annual_net:,}円",
        f"**ポートフォリオ利回り**: {yield_pct:.2f}%",
        f"",
        f"| 銘柄 | 株数 | 投資額 | 年間配当 | 利回り | 安全スコア |",
        f"|------|------|--------|---------|--------|-----------|",
    ]
    for a in allocs:
        name = a.get("name", "")
        ticker = a.get("ticker", "")
        shares = int(a.get("shares") or 0)
        inv = int(a.get("invested") or 0)
        div = int(a.get("annual_dividend") or 0)
        yld = float(a.get("yield") or 0) * 100
        safety = float(a.get("safety") or 0)
        lines.append(f"| {name}({ticker}) | {shares:,}株 | {inv:,}円 | {div:,}円 | {yld:.2f}% | {safety:.2f} |")

    if "target" in result:
        t = result["target"]
        tgt = int(t.get("target_annual_dividend") or 0)
        achieved = int(t.get("achieved_annual_dividend") or 0)
        req_budget = int(t.get("required_budget") or 0)
        reachable = bool(t.get("reachable"))
        status = "✅ 達成" if reachable else "❌ 未達（銘柄追加または目標引き下げを検討）"
        lines.extend([
            f"",
            f"**目標配当**: {tgt:,}円 → **{status}**",
            f"**達成配当**: {achieved:,}円 / 必要予算: {req_budget:,}円",
        ])
    elif target > 0:
        status = "✅ 達成" if annual >= target else f"❌ 未達（{annual:,}円 / 目標{int(target):,}円）"
        lines.extend(["", f"**目標配当 {int(target):,}円に対して**: {status}"])

    conc = summary.get("concentration", {})
    hhi = float(conc.get("hhi") or 0)
    eff = float(conc.get("effective_names") or 0)
    lines.extend([
        f"",
        f"**集中度(HHI)**: {hhi:.3f}　**実効銘柄数**: {eff:.1f}",
        f"",
        f"> {result.get('disclaimer', '')}",
    ])
    return "\n".join(lines)


_SIMULATIONS_PATH = Path(__file__).resolve().parents[3] / "local_docs" / "simulations" / "saved.json"


def _save_simulation(body: JsonDict) -> JsonDict:
    """保存: シミュレーション結果をJSONファイルに追記する。

    Request:  { "name": str, "query": str, "result": {...} }
    Response: { "saved": true, "id": str, "name": str, "total": int }
    """
    import json

    name = str(body.get("name") or "").strip()
    if not name:
        name = f"simulation-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
    result = body.get("result")
    if not isinstance(result, dict):
        raise ApiError("result is required and must be an object")

    _SIMULATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)

    existing: list[JsonDict] = []
    if _SIMULATIONS_PATH.exists():
        try:
            raw = json.loads(_SIMULATIONS_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                existing = raw
        except Exception:
            existing = []

    record: JsonDict = {
        "id": datetime.now(UTC).strftime("%Y%m%d%H%M%S%f"),
        "name": name,
        "saved_at": datetime.now(UTC).isoformat(),
        "query": str(body.get("query") or ""),
        "result": result,
    }
    existing.append(record)
    _SIMULATIONS_PATH.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"saved": True, "id": record["id"], "name": name, "total": len(existing)}


def _list_simulations(_: JsonDict) -> JsonDict:
    """保存済みシミュレーション一覧を返す（新しい順）。"""
    import json

    if not _SIMULATIONS_PATH.exists():
        return {"simulations": [], "total": 0}
    try:
        raw = json.loads(_SIMULATIONS_PATH.read_text(encoding="utf-8"))
        sims: list[JsonDict] = list(reversed(raw)) if isinstance(raw, list) else []
    except Exception as exc:
        return {"simulations": [], "total": 0, "error": f"{type(exc).__name__}: {exc}"}
    return {"simulations": sims, "total": len(sims)}


def _delete_simulation(body: JsonDict) -> JsonDict:
    """指定IDのシミュレーションを削除する。

    Request:  { "id": str }
    Response: { "deleted": true, "id": str, "total": int }
    """
    import json

    sim_id = _require_str(body, "id")
    if not _SIMULATIONS_PATH.exists():
        raise ApiError(f"simulation not found: {sim_id}")
    try:
        raw = json.loads(_SIMULATIONS_PATH.read_text(encoding="utf-8"))
        existing: list[JsonDict] = raw if isinstance(raw, list) else []
    except Exception as exc:
        raise ApiError(f"failed to read simulations: {exc}") from exc

    before = len(existing)
    existing = [s for s in existing if str(s.get("id", "")) != sim_id]
    if len(existing) == before:
        raise ApiError(f"simulation not found: {sim_id}")

    _SIMULATIONS_PATH.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"deleted": True, "id": sim_id, "total": len(existing)}


def _compute_plans(body: JsonDict) -> JsonDict:
    """複数プランの配当ポートフォリオを一括計算する。

    Request:
      plans: [{ id: str, label: str, stocks: [{ticker, name, price, dps}] }]
      target_annual_dividend: float  (いずれか必須)
      budget: float
    Response:
      plans: { id: { label, allocations, summary } }
      plan_comparison: [{ plan, label, invested, annual_dividend, yield }]
    """
    from investment_assistant.financials.evidence import DEFAULT_FINANCIALS_CSV
    from investment_assistant.portfolio.simulator import (
        plan_for_target_dividend,
        simulate_portfolio,
    )

    raw_plans = body.get("plans")
    if not isinstance(raw_plans, list) or not raw_plans:
        raise ApiError("plans は必須です（例: [{id:'A', label:'...', stocks:[...]}]）")

    target = _as_float(body.get("target_annual_dividend"), 0.0)
    budget = _as_float(body.get("budget"), 0.0)
    if target <= 0 and budget <= 0:
        raise ApiError("target_annual_dividend または budget を指定してください")

    common: JsonDict = {
        "years": _as_int(body.get("years"), 10),
        "reinvest": _as_bool(body.get("reinvest"), True),
        "growth_rate": 0.0,
        "auto_weight": "equal",
        "optimization": "none",
        "dividend_basis": "latest",
        "financials_csv": DEFAULT_FINANCIALS_CSV,
    }

    out_plans: JsonDict = {}
    comparison: list[JsonDict] = []

    for p in raw_plans:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("id") or "").strip()
        label = str(p.get("label") or pid)
        stocks = p.get("stocks")
        if not isinstance(stocks, list) or not stocks:
            out_plans[pid] = {"label": label, "available": False, "error": "銘柄が空です"}
            continue

        holdings: list[JsonDict] = []
        for s in stocks:
            if not isinstance(s, dict):
                continue
            ticker = str(s.get("ticker") or "").strip()
            name = str(s.get("name") or ticker)
            price = _as_float(s.get("price"), 0.0)
            dps = _as_float(s.get("dps"), 0.0)
            if not ticker or price <= 0 or dps <= 0:
                continue
            holdings.append({
                "ticker": ticker,
                "name": name,
                "price": price,
                "dividend_per_share": dps,
            })

        if not holdings:
            out_plans[pid] = {"label": label, "available": False, "error": "有効な銘柄がありません（価格・DPSが必須）"}
            continue

        try:
            if target > 0:
                result = plan_for_target_dividend(
                    target_annual_dividend=target, holdings=holdings, **common
                )
            else:
                result = simulate_portfolio(budget=budget, holdings=holdings, **common)

            summary = result.get("summary", {})
            out_plans[pid] = {
                "label": label,
                "allocations": result.get("allocations", []),
                "summary": summary,
                "available": bool(result.get("available", False)),
            }
            comparison.append({
                "plan": pid,
                "label": label,
                "invested": summary.get("invested", 0),
                "annual_dividend": summary.get("annual_dividend", 0),
                "yield": summary.get("portfolio_yield", 0),
            })
        except Exception as exc:
            out_plans[pid] = {"label": label, "available": False, "error": f"{type(exc).__name__}: {exc}"}

    return {
        "plans": out_plans,
        "plan_comparison": comparison,
        "available": bool(out_plans),
    }


def _yahoo_dps(body: JsonDict) -> JsonDict:
    """Yahoo Finance 非公式APIから1株配当(DPS)をバッチ取得する。

    Request:  { "tickers": ["7267", "2914", ...] }
    Response: { "dps": {"7267": 70.0, ...}, "sources": {...}, "notes": {...} }
    """
    from investment_assistant.portfolio.yahoo_financials import fetch_yahoo_financials

    raw = body.get("tickers")
    tickers: list[str] = (
        [str(t).strip() for t in raw if str(t).strip()] if isinstance(raw, list) else []
    )
    if not tickers:
        return {"error": "tickers is required", "dps": {}}

    result = fetch_yahoo_financials(tickers)
    financials: dict[str, dict[str, object]] = result.get("financials", {})  # type: ignore[assignment]

    dps_map: dict[str, float] = {}
    for ticker, metrics in financials.items():
        if isinstance(metrics, dict):
            v = metrics.get("dps")
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
                dps_map[ticker] = float(v)

    return {
        "dps": dps_map,
        "sources": result.get("sources", {}),
        "notes": result.get("notes", {}),
        "matched": len(dps_map),
        "total": len(tickers),
    }


def _resolve_stock_score(
    body: JsonDict, target_source: str, financials_csv: str
) -> dict[str, object] | None:
    from investment_assistant.financials.evidence import ticker_from_source
    from investment_assistant.scoring.stock import STRATEGY_LABELS, score_for_ticker

    ticker = str(body.get("ticker") or "").strip() or ticker_from_source(target_source or None)
    if not ticker:
        return None
    strategy = str(body.get("strategy") or "balanced")
    row = score_for_ticker(ticker=ticker, financials_csv=financials_csv, strategy=strategy)
    if row is not None:
        row["strategy_label"] = STRATEGY_LABELS.get(strategy, strategy)
    return row


def _resolve_stock_forecast(body: JsonDict, target_source: str) -> dict[str, object] | None:
    from investment_assistant.financials.evidence import ticker_from_source
    from investment_assistant.portfolio.market_forecast import forecast_ticker

    ticker = str(body.get("ticker") or "").strip() or ticker_from_source(target_source or None)
    if not ticker:
        return None
    daily_bars_csv = str(body.get("daily_bars_csv") or _DEFAULT_DAILY_BARS_CSV)
    try:
        return forecast_ticker(
            daily_bars_csv=daily_bars_csv,
            ticker=ticker,
            horizon=5,
            include_ml=False,
            evaluate=True,
        )
    except (ValueError, FileNotFoundError, OSError):
        return None


def _orchestrate(body: JsonDict) -> JsonDict:
    call_real_api, real_api_note = _real_api_decision(body)
    real_api_requested = _as_bool(body.get("call_real_api"), False)
    query = _require_str(body, "query")
    target_source_value = body.get("target_source")

    if target_source_value is not None and not isinstance(target_source_value, str):
        raise ApiError("target_source must be a string")

    target_source = (
        target_source_value.strip()
        if isinstance(target_source_value, str)
        else ""
    )

    source_constraint = (
        "\n\n【対象資料制約】"
        + f"\n対象資料: {target_source}"
        + "\n上記sourceのローカル文書だけを根拠にしてください。"
        + "\n他sourceの情報は混ぜず、不足する場合は不明・要追加取得と明記してください。"
        if target_source
        else ""
    )

    financials_csv = str(body.get("financials_csv") or DEFAULT_FINANCIALS_CSV)
    financial_evidence = build_financial_evidence(
        ticker=str(body.get("ticker") or "").strip() or None,
        target_source=target_source or None,
        csv_path=financials_csv,
    )
    # Inject the dividend-quality score for the resolved ticker (Chat <- Score).
    stock_score = _resolve_stock_score(body, target_source, financials_csv)
    # Inject a statistical price forecast for the resolved ticker (Chat <- Forecast).
    stock_forecast = _resolve_stock_forecast(body, target_source)
    evidence_text = financial_evidence or ""
    if stock_score is not None and evidence_text:
        evidence_text += (
            f"\n配当品質スコア: {stock_score['total_score']} / 1.0"
            f"（戦略: {stock_score.get('strategy_label', 'バランス')}）"
        )
    if stock_forecast is not None:
        forecast_values = stock_forecast.get("forecast")
        last_close = stock_forecast.get("last_close")
        if (
            isinstance(forecast_values, list)
            and forecast_values
            and isinstance(last_close, int | float)
        ):
            fc_close = float(forecast_values[-1])
            er = (fc_close / float(last_close) - 1.0) * 100.0
            evidence_text += (
                f"\n株価予測(統計推定・非助言): 期待リターン {er:+.2f}%"
                f"（{stock_forecast.get('horizon')}営業日、"
                f"直近終値 {float(last_close):.0f}円→予測 {fc_close:.0f}円）。"
                "売買判断ではありません。"
            )
    evidence_block = (
        "\n\n"
        + evidence_text
        + "\n上記の減配履歴・財務トレンド・スコア・予測を根拠として明示的に反映してください。"
        if evidence_text
        else ""
    )

    # The draft -> critique -> synthesis process and role rules live in the
    # orchestrator's prompts now, so the query only carries genuine grounding
    # (the question + source constraint + financial evidence). Retrieval uses the
    # raw question so injected evidence/constraints don't skew the RAG search.
    generation_query = query + source_constraint + evidence_block

    result = cli.run_orchestrate_answer(
        query=generation_query,
        search_query=query,
        db_path=str(body.get("db_path") or DEFAULT_RAG_DB_PATH),
        limit=_as_int(body.get("limit"), 16),
        drafts=3,
        include_critique=bool(body.get("critique", True)),
        hybrid=bool(body.get("hybrid", True)),
        alpha=_as_float(body.get("alpha"), 0.5),
        call_real_api=call_real_api,
        source_filter=target_source or None,
    )

    result["target_source"] = target_source or None
    result["financial_evidence"] = financial_evidence
    result["stock_score"] = stock_score
    result["stock_forecast"] = stock_forecast

    result["orchestration"] = {
        "drafter": "AI 1/2/3",
        "critic": "Reviewer",
        "synthesizer": "Synthesizer",
        "drafts": 3,
        "call_real_api": call_real_api,
        "real_api_requested": real_api_requested,
        "api_key_supplied": bool(_request_api_key(body)),
    }

    if real_api_note:
        result["real_api_note"] = real_api_note

    return _finalize_answer(
        result,
        real_api_requested=real_api_requested,
        query=query,
    )


def _rag_index_dir(body: JsonDict) -> JsonDict:
    return cli.run_rag_index_dir(
        path=_require_str(body, "path"),
        db_path=str(body.get("db_path") or DEFAULT_RAG_DB_PATH),
    )


def _manual_doc_save(body: JsonDict) -> JsonDict:
    text = _require_str(body, "text")
    if len(text) > _MAX_MANUAL_TEXT_CHARS:
        raise ApiError(f"text is too long: max {_MAX_MANUAL_TEXT_CHARS} characters")

    title = str(body.get("title") or "manual-note").strip() or "manual-note"
    db_path = str(body.get("db_path") or DEFAULT_RAG_DB_PATH)
    raw_source_url = body.get("source_url")
    source_url = raw_source_url.strip() if isinstance(raw_source_url, str) else ""

    manual_dir = Path("local_docs") / "manual"
    manual_dir.mkdir(parents=True, exist_ok=True)
    save_path = _unique_path(manual_dir / _safe_manual_doc_filename(title))

    saved_at = datetime.now(UTC).isoformat()
    metadata = [
        "# Manual imported investment document",
        f"title: {title}",
        f"saved_at: {saved_at}",
    ]
    if source_url:
        metadata.append(f"source_url: {source_url}")
    content = "\n".join(metadata) + "\n\n" + text.strip() + "\n"
    save_path.write_text(content, encoding="utf-8")

    indexed = cli.run_rag_index(path=save_path, db_path=db_path)
    return {
        "saved_path": str(save_path),
        "chars": len(text),
        "source_url": source_url or None,
        "indexed": indexed,
    }


def _scoring_rank(body: JsonDict) -> JsonDict:
    csv_text = body.get("csv_text")
    if csv_text:
        with tempfile.NamedTemporaryFile(
            "w",
            suffix=".csv",
            delete=False,
            encoding="utf-8",
        ) as handle:
            handle.write(str(csv_text))
            path = handle.name
        try:
            return cli.run_scoring_rank(path=path, limit=_as_int(body.get("limit"), 10))
        finally:
            Path(path).unlink(missing_ok=True)
    return cli.run_scoring_rank(
        path=_require_str(body, "path"),
        limit=_as_int(body.get("limit"), 10),
    )


def _scoring_stocks(body: JsonDict) -> JsonDict:
    from investment_assistant.scoring.stock import run_stock_scoring

    min_equity = body.get("min_equity_ratio")
    limit_value = _as_int(body.get("limit"), 0)
    return run_stock_scoring(
        financials_csv=str(body.get("financials_csv") or DEFAULT_FINANCIALS_CSV),
        strategy=str(body.get("strategy") or "balanced"),
        exclude_dividend_cut=_as_bool(body.get("exclude_dividend_cut"), False),
        min_equity_ratio=_as_float(min_equity, 0.0) if min_equity is not None else None,
        min_periods=_as_int(body.get("min_periods"), 1),
        limit=limit_value or None,
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
    path = body.get("path")
    if path:
        return cli.run_fetch_job(path=str(path), dry_run=dry_run)
    return _run_fetch_job_sources(_require_sources(body), dry_run=dry_run)


def _fetch_job_auto(body: JsonDict) -> JsonDict:
    sources = _require_sources(body)
    db_path = str(body.get("db_path") or DEFAULT_RAG_DB_PATH)
    index_path = str(body.get("index_path") or "local_docs")
    index_after_fetch = _as_bool(body.get("index_after_fetch"), True)

    dry_run = _run_fetch_job_sources(sources, dry_run=True)
    allowed_sources, blocked = _filter_allowed_sources(sources, dry_run)
    run_result: JsonDict | None = None
    index_result: JsonDict | None = None

    if allowed_sources:
        run_result = _run_fetch_job_sources(allowed_sources, dry_run=False)
        if index_after_fetch:
            index_result = cli.run_rag_index_dir(path=index_path, db_path=db_path)

    return {
        "status": "completed" if allowed_sources else "blocked",
        "policy": {
            "robots_checked": True,
            "robots_blocked_count": len(blocked),
            "ssrf_protection": True,
            "rate_limit": True,
            "response_size_limit": True,
            "auto_trading": False,
        },
        "dry_run": dry_run,
        "run": run_result,
        "index": index_result,
        "allowed_sources_count": len(allowed_sources),
        "blocked_results": blocked,
    }



def _edinet_ingest(body: JsonDict) -> JsonDict:
    registry_path = str(
        body.get("registry_path") or "examples/source_registry_edinet_sample.yaml"
    )
    end_date_value = body.get("end_date")
    end_date = str(end_date_value).strip() if end_date_value else None
    max_periods_value = body.get("max_periods")
    max_periods = _as_int(max_periods_value, 0) if max_periods_value is not None else None
    years_value = body.get("years")
    years = _as_int(years_value, 0) if years_value is not None else None
    return cli.run_edinet_ingest(
        registry_path=registry_path,
        end_date=end_date or None,
        days=_as_int(body.get("days"), 7),
        years=years if years and years > 0 else None,
        output_dir=str(body.get("output_dir") or "local_docs/edinet"),
        db_path=str(body.get("db_path") or DEFAULT_RAG_DB_PATH),
        index_after=_as_bool(body.get("index_after_fetch"), True),
        max_periods=max_periods if max_periods and max_periods > 0 else None,
    )


def _edinet_ingest_async(body: JsonDict) -> JsonDict:
    """Start an EDINET ingest in the background and return a job id to poll.

    A multi-year / many-ticker ingest runs for minutes and would otherwise time
    out the editor's port-forward proxy as an HTTP 504. The work runs on a
    daemon thread; the frontend polls ``/api/jobs/status``.
    """

    job_id = JOBS.start("edinet-ingest", lambda: _edinet_ingest(body))
    return {"job_id": job_id, "status": "running", "kind": "edinet-ingest"}


def _job_status(body: JsonDict) -> JsonDict:
    job_id = _require_str(body, "job_id")
    job = JOBS.get(job_id)
    if job is None:
        raise ApiError(f"unknown job_id: {job_id}")
    return job


def _feedback(body: JsonDict) -> JsonDict:
    from investment_assistant.feedback import DEFAULT_FEEDBACK_DB_PATH, FeedbackStore

    raw_sources = body.get("sources")
    sources = [str(item) for item in raw_sources] if isinstance(raw_sources, list) else []
    store = FeedbackStore(str(body.get("feedback_db") or DEFAULT_FEEDBACK_DB_PATH))
    try:
        result = store.record(
            rating=_require_str(body, "rating"),
            sources=sources,
            question=str(body.get("question") or ""),
            answer_preview=str(body.get("answer_preview") or ""),
        )
    except ValueError as exc:
        raise ApiError(str(exc)) from exc
    result["summary"] = store.summary()
    return result


def _feedback_stats(body: JsonDict) -> JsonDict:
    from investment_assistant.feedback import DEFAULT_FEEDBACK_DB_PATH, FeedbackStore

    return FeedbackStore(str(body.get("feedback_db") or DEFAULT_FEEDBACK_DB_PATH)).summary()


def _knowledge_diff(body: JsonDict) -> JsonDict:
    from investment_assistant import knowledge

    return knowledge.run_knowledge_diff(
        db_path=str(body.get("db_path") or DEFAULT_RAG_DB_PATH),
        financials_csv=str(body.get("financials_csv") or DEFAULT_FINANCIALS_CSV),
        snapshot_path=str(body.get("snapshot_path") or knowledge.DEFAULT_SNAPSHOT_PATH),
        save=_as_bool(body.get("save"), True),
    )


def _storage_prune(body: JsonDict) -> JsonDict:
    from investment_assistant import maintenance
    from investment_assistant.ingestion.fetcher import DEFAULT_HTTP_CACHE_PATH

    raw_roots = body.get("docs_roots")
    roots: list[str | Path] = (
        [str(item) for item in raw_roots]
        if isinstance(raw_roots, list) and raw_roots
        else ["local_docs/edinet", "local_docs/crawl"]
    )
    prune_cache = _as_bool(body.get("prune_cache"), True)
    cache_path = str(body.get("cache_path") or DEFAULT_HTTP_CACHE_PATH) if prune_cache else None
    return maintenance.run_storage_prune(
        docs_roots=roots,
        cache_path=cache_path,
        keep_per_dir=_as_int(body.get("keep_per_dir"), 8),
        http_max_rows=_as_int(body.get("http_max_rows"), 500),
    )


def _provider_policy_ledger(body: JsonDict) -> JsonDict:
    from investment_assistant.investment.provider_policy import provider_policy_ledger

    raw_provider_ids = body.get("provider_ids")
    provider_ids = (
        [str(provider_id) for provider_id in raw_provider_ids]
        if isinstance(raw_provider_ids, list)
        else None
    )
    return provider_policy_ledger(
        runtime_mode=str(body.get("runtime_mode") or "development"),
        provider_ids=provider_ids,
    )


def _financials_compare(body: JsonDict) -> JsonDict:
    path = str(body.get("path") or "examples/financials_sample.csv")
    return compare_financials(load_financials(path))


# --- helpers ---------------------------------------------------------------

_SAMPLE_SP500 = str(
    Path(__file__).resolve().parents[3] / "examples" / "sp500_monthly_sample.csv"
)
_MAX_MANUAL_TEXT_CHARS = 200_000


def _request_api_key(body: JsonDict) -> str:
    return str(body.get("api_key") or "").strip()


def _apply_request_api_key(body: JsonDict) -> bool:
    key = _request_api_key(body)
    if not key:
        return False
    os.environ["GEMINI_API_KEY"] = key
    return True


def _looks_like_internal_prompt(text: str) -> bool:
    markers = (
        "あなたはアシスタントです",
        "あなたは投資調査アシスタントです",
        "以下のドラフト群とレビュー指摘",
        "最終回答を作成してください",
        "ユーザーに見せる最終回答だけを書いてください",
        "ローカル文書コンテキスト",
        "出力要件",
        "ドラフト群",
        "レビュー指摘",
        "【生成プロセス】",
    )
    return any(marker in text for marker in markers)


def _clean_user_answer(text: object) -> str:
    raw = str(text or "").strip()
    if not raw or _looks_like_internal_prompt(raw):
        return ""

    remove_markers = (
        "統合最終回答（ローカル擬似・実API未使用）",
        "ドラフト回答（ローカル擬似・実API未使用）",
        "ドラフト回答",
        "統合担当",
        "レビュー担当",
        "厳格なレビュアー",
        "ローカル擬似",
        "実API未使用",
        "担当:",
        "担当：",
    )

    cleaned = raw
    for marker in remove_markers:
        cleaned = cleaned.replace(marker, "")

    lines = []
    for line in cleaned.splitlines():
        stripped = line.strip()
        if stripped.startswith(("質問:", "質問：")):
            continue
        if stripped.startswith(("専用観点:", "専用観点：")):
            continue
        if stripped.startswith("ドラフト"):
            continue
        lines.append(line)

    return "\n".join(lines).strip()


def _direct_final_answer(query: str) -> JsonDict:
    prompt = "\n".join(
        (
            "ユーザーに見せる最終回答だけを書いてください。",
            "内部プロンプト、担当名、ドラフト名、レビュー名は出さないでください。",
            "事実が不明な場合は不明と明記してください。",
            "",
            "出力形式:",
            "1. 弱点指摘（誤り優先）",
            "2. 重大リスク",
            "3. 現実的代替案",
            "4. 【危険ポイント】",
            "5. 次アクション",
            "",
            "質問:",
            query,
        )
    )
    try:
        direct = cli.run_gemini_live(
            task_type="direct_final_answer",
            prompt=prompt,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "text": "",
            "source": "direct_gemini_error",
            "error": f"{type(exc).__name__}: {exc}",
        }

    source = str(direct.get("source") or "")
    text = str(direct.get("text") or "").strip()

    if source.startswith("fallback") or direct.get("skipped"):
        return {
            "text": "",
            "source": source,
            "error": "Gemini returned fallback instead of final answer",
        }

    return {
        "text": text,
        "source": source,
        "warning": direct.get("warning"),
        "skipped": direct.get("skipped"),
        "cache_key": direct.get("cache_key"),
    }



def _local_final_answer(query: str, result: JsonDict) -> str:
    """Build a user-facing final answer when Gemini/orchestration returns no answer."""
    results = result.get("results") or []
    source_count = len(results) if isinstance(results, list) else 0

    evidence_lines: list[str] = []
    if isinstance(results, list):
        for item in results[:3]:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source") or "取得資料")
            text = str(item.get("text") or "").strip()
            if text:
                evidence_lines.append(f"- {source}: {text[:180]}")

    evidence = (
        "\n".join(evidence_lines)
        if evidence_lines
        else "取得済み資料から十分な根拠を抽出できませんでした。"
    )

    return "\n".join(
        (
            "1. 弱点指摘（誤り優先）",
            "現時点では、取得済み資料だけでは十分な比較根拠が不足しています。",
            "そのため、結論は暫定です。",
            "",
            "2. 重大リスク",
            f"RAG検索で利用できた根拠候補は {source_count} 件です。",
            "根拠が少ない場合、S&P500と高配当ETFの長期保有上の弱点比較は不完全になります。",
            "",
            "3. 現実的代替案",
            "最小案: 取得済み資料だけで、判断保留点を整理する。",
            "標準案: 有価証券報告書、決算短信、財務諸表、IR資料を追加取得してから再回答する。",
            "強化案: PDF/XBRL本文も抽出し、配当方針・営業CF・自己資本比率・減配履歴を比較する。",
            "",
            "4. 【危険ポイント】",
            "Gemini API失敗、API KEY未反映、RAG未登録、PDF/XBRL未抽出があると回答精度が落ちます。",
            "特に高配当ETFは構成銘柄・分配方針・減配リスクを確認しないと評価が反転し得ます。",
            "",
            "5. 次アクション",
            "Data Intakeで開示資料を一括取得し、RAG登録完了後に同じ質問を再実行してください。",
            "",
            "根拠候補:",
            evidence,
        )
    )


def _finalize_answer(
    result: JsonDict,
    *,
    real_api_requested: bool,
    query: str,
) -> JsonDict:
    raw_answer = result.get("answer", "")
    clean_answer = _clean_user_answer(raw_answer)
    direct_result: JsonDict | None = None

    if real_api_requested and result.get("call_real_api") and not clean_answer:
        direct_result = _direct_final_answer(query)
        clean_answer = _clean_user_answer(direct_result.get("text", ""))

    result["generation_process"] = {
        "raw_answer": raw_answer,
        "drafts": result.get("drafts"),
        "critique": result.get("critique"),
        "orchestration": result.get("orchestration"),
        "call_real_api": result.get("call_real_api"),
        "real_api_requested": real_api_requested,
        "real_api_note": result.get("real_api_note"),
        "direct_gemini": direct_result,
    }

    if not clean_answer:
        local_answer = _local_final_answer(query, result)
        result["answer"] = local_answer
        result["final_answer"] = local_answer
        result["warning"] = (
            "Geminiの最終回答生成に失敗したため、"
            "ローカルRAG結果から暫定回答を作成しました。"
        )
        result.pop("error", None)
        return result

    result["answer"] = clean_answer
    result["final_answer"] = clean_answer
    result.pop("error", None)
    return result


def _real_api_decision(body: JsonDict) -> tuple[bool, str | None]:
    requested = _as_bool(body.get("call_real_api"), False)
    if not requested:
        return False, None

    request_has_key = _apply_request_api_key(body)
    env_allowed = _as_bool(os.getenv(_REAL_API_ENV), False)
    runtime_allowed = bool(_REAL_API_RUNTIME_ENABLED)
    has_key = bool(os.getenv("GEMINI_API_KEY"))

    if has_key and (request_has_key or env_allowed or runtime_allowed):
        return True, None

    if not has_key:
        return False, "GEMINI_API_KEY is not configured on backend"

    return False, "real API is not enabled"


def _require_str(body: JsonDict, key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ApiError(f"missing required string field: {key}")
    return value


def _require_sources(body: JsonDict) -> list[Any]:
    sources = body.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ApiError("provide a non-empty 'sources' list")
    for source in sources:
        if not isinstance(source, dict):
            raise ApiError("each source must be an object")
    return sources


def _run_fetch_job_sources(sources: list[Any], *, dry_run: bool) -> JsonDict:
    yaml_text = _sources_to_yaml(sources)
    with tempfile.NamedTemporaryFile(
        "w",
        suffix=".yaml",
        delete=False,
        encoding="utf-8",
    ) as handle:
        handle.write(yaml_text)
        temp_path = handle.name
    try:
        return cli.run_fetch_job(path=temp_path, dry_run=dry_run)
    finally:
        Path(temp_path).unlink(missing_ok=True)


def _filter_allowed_sources(
    sources: list[Any],
    dry_run: JsonDict,
) -> tuple[list[Any], list[JsonDict]]:
    dry_results = dry_run.get("results")
    if not isinstance(dry_results, list):
        return [], []

    allowed_names: set[str] = set()
    blocked: list[JsonDict] = []
    for item in dry_results:
        if not isinstance(item, dict):
            continue
        fetch = item.get("fetch")
        if isinstance(fetch, dict) and fetch.get("allowed_by_robots") is True:
            allowed_names.add(str(item.get("name", "")))
        else:
            blocked.append(item)

    allowed_sources = [
        source
        for source in sources
        if isinstance(source, dict) and str(source.get("name", "")) in allowed_names
    ]
    return allowed_sources, blocked


def _as_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.lower().strip()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    return default


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


def _safe_manual_doc_filename(title: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z一-龯ぁ-んァ-ンー_-]+", "-", title).strip("-_")
    safe = normalized[:80] if normalized else "manual-note"
    return f"{safe}.txt"


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    candidate = path.with_name(f"{path.stem}-{stamp}{path.suffix}")
    counter = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}-{stamp}-{counter}{path.suffix}")
        counter += 1
    return candidate


def _sources_to_yaml(sources: list[Any]) -> str:
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


def _dev_build(_: JsonDict) -> JsonDict:
    """開発用: フロントエンドをビルドする（npm run build）。"""
    import subprocess
    import sys
    web_dir = Path(__file__).resolve().parents[3] / "web"
    # Windows では cmd /c 経由で npm.cmd を呼ぶ
    if sys.platform == "win32":
        cmd = ["cmd", "/c", "npm", "run", "build"]
    else:
        cmd = ["npm", "run", "build"]
    result = subprocess.run(
        cmd,
        cwd=str(web_dir),
        capture_output=True,
        text=True,
        timeout=180,
    )
    return {
        "returncode": result.returncode,
        "stdout": result.stdout[-2000:] if result.stdout else "",
        "stderr": result.stderr[-2000:] if result.stderr else "",
        "ok": result.returncode == 0,
    }


_ROUTES: dict[tuple[str, str], Handler] = {
    ("GET", "/api/health"): _health,
    ("GET", "/api/system/diagnostics"): _system_diagnostics,
    ("GET", "/api/market-dashboard/status"): _market_dashboard_status,
    ("POST", "/api/market-dashboard/status"): _market_dashboard_status,
    ("POST", "/api/system/diagnostics"): _system_diagnostics,
    ("GET", "/api/budget"): _budget,
    ("GET", "/api/runtime/real-api"): _runtime_real_api_status,
    ("POST", "/api/runtime/real-api"): _runtime_real_api_set,
    ("POST", "/api/rag/stats"): _rag_stats,
    ("POST", "/api/rag/search"): _rag_search,
    ("POST", "/api/rag/answer-context"): _rag_answer_context,
    ("POST", "/api/rag/answer"): _rag_answer,
    ("POST", "/api/chat/turn"): chat_api.chat_turn,
    ("POST", "/api/chat/simulate"): _chat_simulate,
    ("POST", "/api/yahoo/dps"): _yahoo_dps,
    ("POST", "/api/simulations/save"): _save_simulation,
    ("POST", "/api/simulations/delete"): _delete_simulation,
    ("GET", "/api/simulations"): _list_simulations,
    ("POST", "/api/simulations"): _list_simulations,
    ("POST", "/api/simulations/compute-plans"): _compute_plans,
    ("POST", "/api/dev/build"): _dev_build,
    ("POST", "/api/orchestrate"): _orchestrate,
    ("POST", "/api/rag/index-dir"): _rag_index_dir,
    ("POST", "/api/manual-doc/save"): _manual_doc_save,
    ("POST", "/api/scoring/rank"): _scoring_rank,
    ("POST", "/api/scoring/stocks"): _scoring_stocks,
    ("POST", "/api/forecast/evaluate"): _forecast_evaluate,
    ("POST", "/api/forecast/predict"): _forecast_predict,
    ("POST", "/api/portfolio/dividends"): portfolio_api.portfolio_dividends,
    ("POST", "/api/portfolio/simulate"): portfolio_api.portfolio_simulate,
    ("POST", "/api/portfolio/target"): portfolio_api.portfolio_target,
    ("POST", "/api/portfolio/universe"): portfolio_api.portfolio_universe,
    ("POST", "/api/market/prices"): market_api.market_prices,
    ("POST", "/api/market/ohlcv"): market_api.market_ohlcv,
    ("POST", "/api/market/bars"): market_api.market_bars,
    ("POST", "/api/market/bars/universe"): market_api.market_bars_universe,
    ("POST", "/api/market/financials"): market_api.market_financials,
    ("POST", "/api/market/intraday"): market_api.market_intraday,
    ("POST", "/api/market/inbox"): market_api.market_inbox,
    ("POST", "/api/market/rag/build"): market_api.market_rag_build,
    ("POST", "/api/market/forecast"): market_api.market_forecast,
    ("POST", "/api/market/forecast/screen"): market_api.market_forecast_screen,
    ("POST", "/api/market/heatmap"): market_api.market_heatmap,
    ("POST", "/api/market/names"): market_api.market_names,
    ("POST", "/api/market/gaps"): market_api.market_gaps,
    ("POST", "/api/market/backfill"): market_api.market_backfill,
    ("POST", "/api/market/refresh"): market_api.market_refresh,
    ("GET", "/api/data/status"): data_status_api.data_status,
    ("POST", "/api/data/status"): data_status_api.data_status,
    ("GET", "/api/data/quality"): data_status_api.data_quality_profile,
    ("POST", "/api/data/quality"): data_status_api.data_quality_profile,
    ("POST", "/api/financials/preview"): data_status_api.financials_preview,
    ("POST", "/api/providers/policy"): _provider_policy_ledger,
    ("POST", "/api/portfolio/performance"): portfolio_api.portfolio_performance,
    ("POST", "/api/holdings/import"): investment_api.holdings_import,
    ("POST", "/api/holdings/validate"): investment_api.holdings_validate,
    ("POST", "/api/holdings/template"): investment_api.holdings_template,
    ("POST", "/api/funds/validate"): investment_api.funds_validate,
    ("POST", "/api/funds/template"): investment_api.funds_template,
    ("POST", "/api/portfolio/analyze"): investment_api.portfolio_analyze,
    ("POST", "/api/investment/detail"): investment_api.investment_detail,
    ("POST", "/api/candidates/screen"): investment_api.candidates_screen,
    ("POST", "/api/reports/investment-monthly"): report_api.investment_monthly_report,
    ("POST", "/api/reports/investment-monthly/audit"): report_api.investment_report_audit,
    ("POST", "/api/reports/investment-monthly/markdown"): report_api.investment_report_markdown,
    (
        "POST",
        "/api/reports/investment-monthly/markdown/save",
    ): report_api.investment_report_markdown_save,
    (
        "POST",
        "/api/reports/investment-monthly/markdown/library",
    ): report_api.investment_report_markdown_library,
    ("GET", "/api/reports/investment-monthly/history"): report_api.investment_report_history,
    ("POST", "/api/reports/investment-monthly/history"): report_api.investment_report_history,
    (
        "POST",
        "/api/reports/investment-monthly/history/load",
    ): report_api.investment_report_history_load,
    (
        "POST",
        "/api/reports/investment-monthly/history/delete",
    ): report_api.investment_report_history_delete,
    (
        "POST",
        "/api/reports/investment-monthly/history/verify",
    ): report_api.investment_report_history_verify,
    (
        "POST",
        "/api/reports/investment-monthly/history/compare",
    ): report_api.investment_report_history_compare,
    ("POST", "/api/financials/compare"): _financials_compare,
    ("POST", "/api/cache/maintenance"): _cache_maintenance,
    ("POST", "/api/fetch-job/dry-run"): lambda body: _fetch_job(body, dry_run=True),
    ("POST", "/api/fetch-job/run"): lambda body: _fetch_job(body, dry_run=False),
    ("POST", "/api/fetch-job/auto"): _fetch_job_auto,
    ("POST", "/api/edinet/status"): edinet_api.edinet_status,
    ("POST", "/api/edinet/api-key"): edinet_api.edinet_save_api_key,
    ("POST", "/api/edinet/ingest"): _edinet_ingest,
    ("POST", "/api/edinet/ingest-async"): _edinet_ingest_async,
    ("POST", "/api/jobs/status"): _job_status,
    ("POST", "/api/storage/prune"): _storage_prune,
    ("POST", "/api/knowledge/diff"): _knowledge_diff,
    ("POST", "/api/feedback"): _feedback,
    ("POST", "/api/feedback/stats"): _feedback_stats,
    # Investment AI — data pipeline + scoring + LLM analysis
    ("POST", "/api/stocks/collect"): stock_analysis_api.stocks_collect,
    ("POST", "/api/stocks/import"): stock_analysis_api.stocks_import,
    ("POST", "/api/stocks/score"): stock_analysis_api.stocks_score,
    ("POST", "/api/stocks/analyze"): stock_analysis_api.stocks_analyze,
    ("POST", "/api/stocks/status"): stock_analysis_api.stocks_status,
    # JPX NeuroFinance — データ状態・ML結果取得・パイプライン実行
    ("GET",  "/api/jpx/status"):  jpx_api.jpx_status,
    ("POST", "/api/jpx/status"):  jpx_api.jpx_status,
    ("POST", "/api/jpx/results"): jpx_api.jpx_results,
    ("POST", "/api/jpx/run"):     jpx_api.jpx_run,
    # Flick（入力系）— 差分収集・陳腐化チェック
    ("POST", "/api/flick/update"): sprint_api.flick_update,
    ("POST", "/api/flick/status"): sprint_api.flick_status,
    ("POST", "/api/flick/append"): sprint_api.flick_append,
    ("POST", "/api/flick/score-all"): sprint_api.flick_score_all,
    # Sprint（出力系）— キャッシュからの即時応答
    ("POST", "/api/sprint/rank"): sprint_api.sprint_rank,
    ("POST", "/api/sprint/status"): sprint_api.sprint_status,
}


def available_routes() -> list[str]:
    return sorted(f"{method} {path}" for method, path in _ROUTES)


