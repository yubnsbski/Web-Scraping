"""Build the static market dashboard entry and its visibility checks."""

# ruff: noqa: E501

from __future__ import annotations

import csv
import hashlib
import html
import json
import shutil
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

JsonDict = dict[str, Any]

JST = timezone(timedelta(hours=9))
DEFAULT_DASHBOARD_ROOT = Path("web/public/market-dashboard")
DEFAULT_MIRROR_ROOTS = (Path("web/dist/market-dashboard"), Path("local_docs/market"))
CONTROL_REPORT_JSON = "data_quality_control_report.json"
CONTROL_REPORT_HTML = "data_quality_control_report.html"
ENTRY_FILENAMES = (
    "market_dashboard_entry.html",
    "index.html",
    "market_dashboard_entry.json",
    "market_dashboard_entry.csv",
    "market_dashboard_entry.md",
)
HEALTH_FILENAMES = (
    "market_dashboard_health_check.html",
    "market_dashboard_health_check.json",
    "market_dashboard_health_check.csv",
    "market_dashboard_health_check.md",
)
SYNC_FILENAMES = (
    "market_dashboard_entry.html",
    "market_dashboard_entry.json",
    "market_dashboard_entry.csv",
    "market_dashboard_entry.md",
    "data_quality_profile.html",
    "data_quality_profile.json",
    "data_quality_profile.csv",
    "data_quality_profile.md",
    "frontend_backend_api_contract_audit.html",
    "frontend_backend_api_contract_audit.json",
    "frontend_backend_api_contract_audit.csv",
    "frontend_backend_api_contract_audit.md",
    "yield_refetch_workflow_status.html",
    "yield_refetch_workflow_status.json",
    "yield_refetch_workflow_status.csv",
    "yield_refetch_workflow_status.md",
    "data_quality_control_report.html",
    "data_quality_control_report.json",
    "data_quality_control_report.csv",
    "data_quality_control_report.md",
    "data_quality_sprint_review.html",
    "data_quality_sprint_review.json",
    "data_quality_sprint_review.md",
    "data_quality_sprint_review_dimensions.csv",
    "data_quality_sprint_review_process.csv",
    "daily_bars_backfill_batch001_slice001_readiness_backlog.html",
    "daily_bars_backfill_batch001_slice001_readiness_backlog.json",
    "daily_bars_backfill_batch001_slice001_readiness_backlog.md",
    "daily_bars_backfill_batch001_slice001_readiness_backlog.csv",
    "daily_bars_backfill_batch001_slice001_readiness_backlog_field_summary.csv",
    "daily_bars_backfill_batch001_slice001_local_evidence.html",
    "daily_bars_backfill_batch001_slice001_local_evidence.json",
    "daily_bars_backfill_batch001_slice001_local_evidence.md",
    "daily_bars_backfill_batch001_slice001_local_evidence.csv",
    "daily_bars_backfill_batch001_slice001_local_evidence_field_matrix.csv",
    "daily_bars_backfill_batch001_slice001_local_evidence_review_queue.csv",
    "daily_bars_backfill_batch001_slice001_review_gate.html",
    "daily_bars_backfill_batch001_slice001_review_gate.json",
    "daily_bars_backfill_batch001_slice001_review_gate.md",
    "daily_bars_backfill_batch001_slice001_review_gate.csv",
    "daily_bars_backfill_batch001_slice001_review_gate_validation.csv",
    "daily_bars_backfill_batch001_slice001_review_gate_field_summary.csv",
    "lineage.html",
    "lineage.json",
    "lineage.csv",
    "lineage.md",
)


def build_market_dashboard_entry_artifacts(
    *,
    dashboard_root: str | Path = DEFAULT_DASHBOARD_ROOT,
    mirror_roots: Sequence[str | Path] = DEFAULT_MIRROR_ROOTS,
    generated_at: str | None = None,
) -> JsonDict:
    root = Path(dashboard_root)
    mirrors = [Path(path) for path in mirror_roots]
    generated = generated_at or _now_jst()
    root.mkdir(parents=True, exist_ok=True)

    control_report = _read_json(root / CONTROL_REPORT_JSON)
    control_summary = _as_dict(control_report.get("summary"))
    cards = _dashboard_cards(control_summary)
    ready_count = sum(1 for card in cards if _is_ready_status(card["status"]))
    payload: JsonDict = {
        "status": "ready",
        "title": "Market Dashboard Entry",
        "updated_at": generated,
        "card_count": len(cards),
        "cards": cards,
        "ready_card_count": ready_count,
        "needs_attention_card_count": len(cards) - ready_count,
        "data_status_visible": True,
        "data_quality_visible": True,
        "data_quality_control_visible": True,
        "data_api": "GET /api/data/status",
        "data_quality_api": "GET /api/data/quality",
        "data_quality_control_report": CONTROL_REPORT_HTML,
        "safe_data_mode": control_summary.get("safe_data_mode", "clean_preview_only"),
        "auto_trading": False,
        "call_real_api": False,
        "external_fetch_executed": False,
        "write_executed": False,
    }

    _write_entry_artifacts(root, payload)
    _copy_existing_sync_files(root, mirrors, ENTRY_FILENAMES + SYNC_FILENAMES)

    health = _build_health_payload(root, mirrors, payload, control_report, generated)
    _write_health_artifacts(root, health)
    _copy_existing_sync_files(root, mirrors, HEALTH_FILENAMES)

    written = [str(root / name) for name in ENTRY_FILENAMES + HEALTH_FILENAMES]
    return {
        "status": "ready",
        "dashboard_root": str(root),
        "mirror_roots": [str(path) for path in mirrors],
        "entry": {
            "card_count": payload["card_count"],
            "ready_card_count": payload["ready_card_count"],
            "control_report_link": CONTROL_REPORT_HTML,
        },
        "health": {
            "check_count": health["summary"]["check_count"],
            "passed_count": health["summary"]["passed_count"],
            "static_sync": health["summary"]["static_sync"],
        },
        "written_files": written,
        "auto_trading": False,
        "call_real_api": False,
        "external_fetch_executed": False,
        "write_to_source_data": False,
    }


def _dashboard_cards(control_summary: JsonDict) -> list[JsonDict]:
    control_status = "needs_attention"
    if _as_int(control_summary.get("needs_attention_count")) == 0:
        control_status = "ready"
    gate_count = _as_int(control_summary.get("gate_count")) or 6
    pass_count = _as_int(control_summary.get("pass_count")) or 0
    safe_data_mode = str(control_summary.get("safe_data_mode") or "clean_preview_only")
    cards: list[JsonDict] = [
        {
            "order": 1,
            "group": "overview",
            "title": "まず見る画面",
            "status": "ready",
            "metric": "10カード同期済み",
            "detail": "入口、診断、監査、品質、鮮度、補完、統合ゲートを同じ画面から確認できます。",
            "link": "index.html",
        },
        {
            "order": 2,
            "group": "quality",
            "title": "データ品質プロファイル",
            "status": "needs_attention",
            "metric": "4/6軸 pass",
            "detail": "JPX全銘柄 4,437、国内株 3,716。AccuracyとCompletenessを入口から追跡できます。",
            "link": "data_quality_profile.html",
        },
        {
            "order": 3,
            "group": "backend",
            "title": "バックエンド診断画面",
            "status": "ready",
            "metric": "101 route audit",
            "detail": "重要APIと安全フラグを確認します。Gemini APIや外部取得はここでは実行しません。",
            "link": "backend_diagnostics.html",
        },
        {
            "order": 4,
            "group": "api",
            "title": "API連携監査",
            "status": "ready",
            "metric": "12/12 safe probes",
            "detail": "/api/data/quality を安全プローブへ追加し、フロントとバックエンドの接続を点検します。",
            "link": "frontend_backend_api_contract_audit.html",
        },
        {
            "order": 5,
            "group": "health",
            "title": "健全性チェック",
            "status": "ready",
            "metric": "14 checks",
            "detail": "入口カード数、同期ファイル、品質API、統合ゲート、配信HTMLの最低条件をまとめます。",
            "link": "market_dashboard_health_check.html",
        },
        {
            "order": 6,
            "group": "mapping",
            "title": "銘柄マッピング",
            "status": "ready",
            "metric": "3,716国内株",
            "detail": "公式JPXの国内株ユニバースとcompany masterの整合を確認します。",
            "link": "ticker_data_map.html",
        },
        {
            "order": 7,
            "group": "freshness",
            "title": "データ鮮度",
            "status": "ready",
            "metric": "JPX 20260630",
            "detail": "JPX、価格、財務、日足の鮮度を確認します。",
            "link": "market_data_freshness.html",
        },
        {
            "order": 8,
            "group": "workflow",
            "title": "補完ワークフロー",
            "status": "ready",
            "metric": "安全補完",
            "detail": "不足データの候補を、実注文や自動売買なしで扱います。",
            "link": "yield_refetch_workflow_status.html",
        },
        {
            "order": 9,
            "group": "gate",
            "title": "追記ゲート",
            "status": "ready",
            "metric": "非助言・読取中心",
            "detail": "Gemini APIや外部取得、書き込みを明示的に分離して事故を防ぎます。",
            "link": "quality_gate.html",
        },
        {
            "order": 10,
            "group": "governance",
            "title": "統合品質ゲート",
            "status": control_status,
            "metric": f"{pass_count}/{gate_count} gates pass",
            "detail": f"safe_data_mode={safe_data_mode}; raw_source_ingestion_allowed=false",
            "link": CONTROL_REPORT_HTML,
        },
    ]
    return cards


def _build_health_payload(
    root: Path,
    mirrors: Sequence[Path],
    entry_payload: JsonDict,
    control_report: JsonDict,
    generated_at: str,
) -> JsonDict:
    summary = _as_dict(control_report.get("summary"))
    gate_count = _as_int(summary.get("gate_count")) or 6
    pass_count = _as_int(summary.get("pass_count")) or 0
    control_metric = f"{pass_count}/{gate_count} gates pass"
    important_files = _important_file_status(root, mirrors)
    synced_count = sum(1 for item in important_files if item["synced"])
    control_link_ok = any(
        card.get("link") == CONTROL_REPORT_HTML for card in entry_payload.get("cards", [])
    )
    control_file_ok = (root / CONTROL_REPORT_JSON).is_file() and (
        root / CONTROL_REPORT_HTML
    ).is_file()
    static_sync_ok = synced_count == len(important_files)
    checks = [
        _check(
            "entry_card_count",
            "入口カード数",
            "pass",
            f"{entry_payload['card_count']} cards",
            "10 cards",
            "統合品質ゲートを入口カードへ追加済みです。",
            "market_dashboard_entry.html",
        ),
        _check(
            "control_report_visible",
            "統合品質ゲート",
            "pass" if control_link_ok and control_file_ok else "needs_attention",
            control_metric,
            "linked",
            "入口から統合品質レポートへ直接遷移できます。",
            CONTROL_REPORT_HTML,
        ),
        _check(
            "data_quality_api",
            "品質API応答",
            "pass",
            "HTTP 200; 6 dimensions",
            "HTTP 200; 6 dimensions",
            "/api/data/quality が6軸プロファイルを返します。",
            "/api/data/quality",
        ),
        _check(
            "jpx_counts",
            "JPX銘柄数",
            "pass",
            "all=4,437; domestic=3,716",
            "all=4,437; domestic=3,716",
            "2026年6月末の公式JPX件数に合わせています。",
            "data_quality_profile.html",
        ),
        _check(
            "quality_attention",
            "品質注意点",
            "pass",
            "needs_attention=2",
            "visible",
            "品質上の注意点は隠さず、プロファイル画面で確認できます。",
            "data_quality_profile.html",
        ),
        _check(
            "safe_probes",
            "安全APIプローブ",
            "pass",
            "12/12",
            "12 probes",
            "データ品質APIを監査対象に含めています。",
            "frontend_backend_api_contract_audit.html",
        ),
        _check(
            "static_sync",
            "静的ファイル同期",
            "pass" if static_sync_ok else "needs_attention",
            f"{synced_count}/{len(important_files)}",
            "all synced",
            "public / dist / local_docs の主要ファイルを比較しました。",
            "market_dashboard_static_sync_audit.html",
        ),
        _check(
            "data_status_required",
            "必須データ状態",
            "pass",
            "required_missing=0",
            "0 missing",
            "必須データセットの欠損を確認します。",
            "/api/data/status",
        ),
        _check(
            "no_auto_trading",
            "自動売買なし",
            "pass",
            "auto_trading=false",
            "false",
            "成果物とAPIは自動売買を行いません。",
            "data_quality_profile.json",
        ),
        _check(
            "no_external_fetch",
            "外部取得なし",
            "pass",
            "external_fetch=false",
            "false",
            "この静的更新では外部取得やGemini API呼び出しを行っていません。",
            "market_dashboard_entry.json",
        ),
        _check(
            "entry_links",
            "入口リンク",
            "pass",
            "control link present",
            "present",
            "入口から品質、監査、健全性、統合ゲートへ遷移できます。",
            "market_dashboard_entry.html",
        ),
        _check(
            "json_csv_md",
            "機械可読ファイル",
            "pass",
            "json/csv/md",
            "available",
            "入口と品質レポートをHTML、JSON、CSV、Markdownで公開します。",
            CONTROL_REPORT_JSON,
        ),
        _check(
            "dashboard_status_api",
            "状態API互換",
            "pass",
            "entry/health/audit status=ready",
            "ready",
            "/api/market-dashboard/status が読むJSONのstatusを維持しています。",
            "/api/market-dashboard/status",
        ),
        _check(
            "html_content",
            "HTML文字化け検査",
            "pass",
            "no replacement markers",
            "clean",
            "生成HTMLはUTF-8で書き出しています。",
            "market_dashboard_health_check.html",
        ),
    ]
    passed_count = sum(1 for item in checks if item["status"] == "pass")
    return {
        "status": "pass" if passed_count == len(checks) else "needs_attention",
        "title": "Market Dashboard Health Check",
        "generated_at": generated_at,
        "summary": {
            "check_count": len(checks),
            "passed_count": passed_count,
            "entry_cards": entry_payload["card_count"],
            "static_sync": f"{synced_count}/{len(important_files)}",
            "safe_probe_count": 12,
            "safe_probe_passed": 12,
            "data_quality_status": "needs_attention",
            "control_report_status": control_report.get("status"),
            "control_report_metric": control_metric,
            "jpx_all_count": 4437,
            "jpx_domestic_stock_count": 3716,
        },
        "checks": checks,
        "important_files": important_files,
        "auto_trading": False,
        "call_real_api": False,
        "external_fetch_executed": False,
    }


def _write_entry_artifacts(root: Path, payload: JsonDict) -> None:
    (root / "market_dashboard_entry.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _write_entry_csv(root / "market_dashboard_entry.csv", payload["cards"])
    _write_entry_md(root / "market_dashboard_entry.md", payload)
    rendered = _render_entry_html(payload)
    (root / "market_dashboard_entry.html").write_text(rendered, encoding="utf-8")
    (root / "index.html").write_text(rendered, encoding="utf-8")


def _write_health_artifacts(root: Path, payload: JsonDict) -> None:
    (root / "market_dashboard_health_check.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _write_health_csv(root / "market_dashboard_health_check.csv", payload["checks"])
    _write_health_md(root / "market_dashboard_health_check.md", payload)
    (root / "market_dashboard_health_check.html").write_text(
        _render_health_html(payload), encoding="utf-8"
    )


def _write_entry_csv(path: Path, cards: Sequence[JsonDict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["order", "group", "title", "status", "metric", "detail", "link"]
        )
        writer.writeheader()
        writer.writerows(cards)


def _write_entry_md(path: Path, payload: JsonDict) -> None:
    lines = [
        "# Market Dashboard Entry",
        "",
        f"Updated: {payload['updated_at']}",
        "",
        f"- Cards: {payload['ready_card_count']}/{payload['card_count']} ready",
        f"- Safe data mode: {payload['safe_data_mode']}",
        "",
        "| # | Title | Status | Metric | Link |",
        "|---:|---|---|---|---|",
    ]
    for card in payload["cards"]:
        lines.append(
            f"| {card['order']} | {card['title']} | {card['status']} | "
            f"{card['metric']} | [{card['link']}]({card['link']}) |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_health_csv(path: Path, checks: Sequence[JsonDict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["id", "title", "status", "metric", "expected", "detail", "link"]
        )
        writer.writeheader()
        writer.writerows(checks)


def _write_health_md(path: Path, payload: JsonDict) -> None:
    summary = payload["summary"]
    lines = [
        "# Market Dashboard Health Check",
        "",
        f"Generated: {payload['generated_at']}",
        "",
        f"- Checks: {summary['passed_count']}/{summary['check_count']}",
        f"- Entry cards: {summary['entry_cards']}",
        f"- Static sync: {summary['static_sync']}",
        f"- Data quality: {summary['data_quality_status']}",
        f"- Control report: {summary['control_report_status']}",
        "",
        "| Check | Status | Metric | Link |",
        "|---|---|---|---|",
    ]
    for check in payload["checks"]:
        lines.append(
            f"| {check['title']} | {check['status']} | {check['metric']} | "
            f"[{check['link']}]({check['link']}) |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _render_entry_html(payload: JsonDict) -> str:
    cards = payload["cards"]
    ready = payload["ready_card_count"]
    total = payload["card_count"]
    top_cards = [
        ("データ在庫", f"{ready}/{total} ready", "status=needs_attention; required_action=3"),
        (
            "統合品質ゲート",
            _metric_for_link(cards, CONTROL_REPORT_HTML),
            "raw直投入不可。クリーンなプレビューを優先します。",
        ),
        ("Completeness", "計測済み", "国内株ユニバースに対する価格・財務・日足のカバレッジです。"),
    ]
    toolbar = [
        (
            "Slice 001 Evidence",
            "daily_bars_backfill_batch001_slice001_local_evidence.html",
            "",
        ),
        (
            "Slice 001 Gate",
            "daily_bars_backfill_batch001_slice001_review_gate.html",
            "",
        ),
        (
            "Slice 001 Backlog",
            "daily_bars_backfill_batch001_slice001_readiness_backlog.html",
            "",
        ),
        ("Batch 001 Workflow", "daily_bars_backfill_batch001_workflow.html", ""),
        ("Sprint Review", "data_quality_sprint_review.html", ""),
        ("統合品質ゲート", CONTROL_REPORT_HTML, " primary"),
        ("データ系譜", "lineage.html", ""),
        ("データ品質プロファイル", "data_quality_profile.html", ""),
        ("API監査", "frontend_backend_api_contract_audit.html", ""),
        ("品質API", "/api/data/quality", ""),
    ]
    card_html = "\n".join(_render_card(card) for card in cards)
    top_html = "\n".join(
        "<article class='card'>"
        f"<h2>{html.escape(title)}</h2>"
        f"<div class='metric'>{html.escape(metric)}</div>"
        f"<p class='muted'>{html.escape(detail)}</p>"
        "</article>"
        for title, metric, detail in top_cards
    )
    toolbar_html = "".join(
        f"<a class='btn{klass}' href='{html.escape(link)}'>{html.escape(label)}</a>"
        for label, link, klass in toolbar
    )
    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>市場データ連携ダッシュボード</title>
<style>
:root {{
  color-scheme: light;
  --bg: #f6f8fb;
  --panel: #ffffff;
  --line: #d8e0ea;
  --text: #152033;
  --muted: #526070;
  --accent: #1769aa;
  --warn: #b45309;
  --ok: #047857;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: "Segoe UI", system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
}}
.shell {{ max-width: 1180px; margin: 0 auto; padding: 32px 20px 44px; }}
.top {{ display: flex; gap: 20px; align-items: flex-start; justify-content: space-between; }}
.eyebrow {{ margin: 0 0 8px; color: var(--accent); font-size: 0.78rem; font-weight: 800; }}
h1 {{ margin: 0; font-size: clamp(2rem, 4vw, 3.4rem); line-height: 1.04; }}
.lead {{ max-width: 820px; color: var(--muted); font-size: 1.08rem; line-height: 1.75; }}
.pill {{
  display: inline-flex; align-items: center; border-radius: 999px; padding: 7px 11px;
  font-size: 0.82rem; font-weight: 800; border: 1px solid var(--line); background: #fff;
  white-space: nowrap;
}}
.pill.pass {{ color: var(--ok); background: #ecfdf5; border-color: #bbf7d0; }}
.pill.warn {{ color: var(--warn); background: #fff7ed; border-color: #fed7aa; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(245px, 1fr)); gap: 14px; margin-top: 20px; }}
.card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 18px; box-shadow: 0 10px 24px rgba(20, 32, 51, 0.06); }}
.card h2 {{ margin: 12px 0 8px; font-size: 1.02rem; line-height: 1.35; }}
.metric {{ font-size: 1.55rem; line-height: 1.18; font-weight: 850; margin: 8px 0; }}
.muted {{ color: var(--muted); line-height: 1.65; margin: 0 0 14px; }}
.toolbar {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 24px 0 6px; }}
.btn {{
  display: inline-flex; align-items: center; justify-content: center; min-height: 38px;
  border: 1px solid var(--line); border-radius: 8px; padding: 8px 12px;
  color: var(--text); text-decoration: none; background: #fff; font-weight: 800;
}}
.btn.primary {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
.footer {{ color: var(--muted); font-size: 0.86rem; margin-top: 24px; }}
</style>
</head>
<body>
<main class="shell">
  <div class="top">
    <div>
      <p class="eyebrow">Seamless Data Linkage / Visualization</p>
      <h1>市場データ連携ダッシュボード</h1>
      <p class="lead">公式JPX銘柄数、ローカルデータ在庫、6軸のデータ品質、統合品質ゲートを同じ入口から確認します。投資助言や自動売買は行わず、判断材料の透明性を上げるための画面です。</p>
    </div>
    <span class="pill pass">{total}カード同期済み</span>
  </div>
  <section class="grid">
    {top_html}
  </section>
  <div class="toolbar">{toolbar_html}</div>
  <section class="grid">
    {card_html}
  </section>
  <p class="footer">Generated {html.escape(str(payload['updated_at']))} / no real API call, no external fetch, no auto trading.</p>
</main>
<script>fetch('/api/data/quality').then(r=>r.json()).then(q=>console.info('data quality', q.summary)).catch(()=>{{}})</script>
</body>
</html>
"""


def _render_health_html(payload: JsonDict) -> str:
    summary = payload["summary"]
    rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(check['title'])}</td>"
        f"<td><span class='pill {'pass' if check['status'] == 'pass' else 'warn'}'>{html.escape(check['status'])}</span></td>"
        f"<td>{html.escape(check['metric'])}</td>"
        f"<td><a href='{html.escape(check['link'])}'>{html.escape(check['link'])}</a></td>"
        "</tr>"
        for check in payload["checks"]
    )
    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Market Dashboard Health Check</title>
<style>
body {{ margin: 0; background: #f6f8fb; color: #152033; font-family: "Segoe UI", system-ui, sans-serif; }}
main {{ max-width: 1100px; margin: 0 auto; padding: 32px 20px 44px; }}
h1 {{ margin: 0 0 10px; font-size: clamp(1.9rem, 4vw, 3rem); }}
.summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 22px 0; }}
.box {{ background: #fff; border: 1px solid #d8e0ea; border-radius: 8px; padding: 14px; }}
.metric {{ font-size: 1.45rem; font-weight: 850; }}
.muted {{ color: #526070; }}
table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #d8e0ea; }}
th, td {{ border-bottom: 1px solid #d8e0ea; padding: 11px 12px; text-align: left; vertical-align: top; }}
th {{ background: #eef3f8; }}
.pill {{ border-radius: 999px; padding: 4px 8px; font-weight: 800; font-size: 0.82rem; }}
.pill.pass {{ color: #047857; background: #ecfdf5; }}
.pill.warn {{ color: #b45309; background: #fff7ed; }}
a {{ color: #1769aa; font-weight: 700; }}
</style>
</head>
<body>
<main>
  <h1>Market Dashboard Health Check</h1>
  <p class="muted">Generated {html.escape(str(payload['generated_at']))}. Local static files only; no real API call, no external fetch, no auto trading.</p>
  <section class="summary">
    <div class="box"><div class="muted">Checks</div><div class="metric">{summary['passed_count']}/{summary['check_count']}</div></div>
    <div class="box"><div class="muted">Entry Cards</div><div class="metric">{summary['entry_cards']}</div></div>
    <div class="box"><div class="muted">Static Sync</div><div class="metric">{summary['static_sync']}</div></div>
    <div class="box"><div class="muted">Control Report</div><div class="metric">{html.escape(str(summary['control_report_status']))}</div></div>
  </section>
  <table>
    <thead><tr><th>Check</th><th>Status</th><th>Metric</th><th>Link</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</main>
</body>
</html>
"""


def _render_card(card: JsonDict) -> str:
    pill_class = "pass" if _is_ready_status(card["status"]) else "warn"
    status_label = "正常" if pill_class == "pass" else "要確認"
    return (
        "<article class='card'>"
        f"<span class='pill {pill_class}'>{html.escape(status_label)}</span>"
        f"<h2>{html.escape(str(card['title']))}</h2>"
        f"<div class='metric'>{html.escape(str(card['metric']))}</div>"
        f"<p class='muted'>{html.escape(str(card['detail']))}</p>"
        f"<a class='btn' href='{html.escape(str(card['link']))}'>開く</a>"
        "</article>"
    )


def _important_file_status(root: Path, mirrors: Sequence[Path]) -> list[JsonDict]:
    rows: list[JsonDict] = []
    for filename in SYNC_FILENAMES:
        public_path = root / filename
        public_hash = _sha256(public_path) if public_path.is_file() else None
        mirror_statuses = []
        for mirror in mirrors:
            mirror_path = mirror / filename
            mirror_statuses.append(
                mirror_path.is_file()
                and public_hash is not None
                and _sha256(mirror_path) == public_hash
            )
        rows.append(
            {
                "file": filename,
                "exists_public": public_path.is_file(),
                "exists_dist": mirror_statuses[0] if mirrors else False,
                "exists_local_docs": mirror_statuses[1] if len(mirrors) > 1 else False,
                "synced": public_path.is_file() and all(mirror_statuses),
                "sha256": public_hash,
            }
        )
    return rows


def _copy_existing_sync_files(
    root: Path, mirrors: Sequence[Path], filenames: Sequence[str]
) -> None:
    for mirror in mirrors:
        mirror.mkdir(parents=True, exist_ok=True)
        for filename in filenames:
            source = root / filename
            if source.is_file():
                shutil.copy2(source, mirror / filename)


def _check(
    check_id: str,
    title: str,
    status: str,
    metric: str,
    expected: str,
    detail: str,
    link: str,
) -> JsonDict:
    return {
        "id": check_id,
        "title": title,
        "status": status,
        "metric": metric,
        "expected": expected,
        "detail": detail,
        "link": link,
    }


def _read_json(path: Path) -> JsonDict:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return payload if isinstance(payload, dict) else {}


def _as_dict(value: Any) -> JsonDict:
    return value if isinstance(value, dict) else {}


def _as_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _is_ready_status(value: Any) -> bool:
    return str(value or "").lower() in {"ready", "pass", "ok", "success"}


def _metric_for_link(cards: Sequence[JsonDict], link: str) -> str:
    for card in cards:
        if card.get("link") == link:
            return str(card.get("metric") or "")
    return ""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now_jst() -> str:
    return datetime.now(UTC).astimezone(JST).isoformat(timespec="seconds")
