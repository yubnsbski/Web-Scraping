"""Build local market data lineage artifacts from existing dashboard files."""

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
DEFAULT_LOCAL_MARKET_ROOT = Path("local_docs/market")
DEFAULT_MIRROR_ROOTS = (Path("web/dist/market-dashboard"), Path("local_docs/market"))
LINEAGE_FILES = ("lineage.json", "lineage.csv", "lineage.html", "lineage.md")


def build_data_lineage_artifacts(
    *,
    dashboard_root: str | Path = DEFAULT_DASHBOARD_ROOT,
    local_market_root: str | Path = DEFAULT_LOCAL_MARKET_ROOT,
    mirror_roots: Sequence[str | Path] = DEFAULT_MIRROR_ROOTS,
    generated_at: str | None = None,
) -> JsonDict:
    root = Path(dashboard_root)
    local_root = Path(local_market_root)
    mirrors = [Path(path) for path in mirror_roots]
    root.mkdir(parents=True, exist_ok=True)
    generated = generated_at or _now_jst()

    control_report = _read_json(root / "data_quality_control_report.json")
    cleansing = _read_json(root / "source_cleansing_preview.json")
    profile = _read_json(root / "data_quality_profile.json")
    gap = _read_json(root / "data_gap_dashboard.json")
    drift = _read_json(root / "source_drift_audit.json")
    reconciliation = _read_json(root / "jpx_ticker_map_reconciliation.json")

    control_summary = _as_dict(control_report.get("summary"))
    cleansing_summary = _as_dict(cleansing.get("summary"))
    gap_summary = _as_dict(gap.get("summary"))
    profile_summary = _as_dict(profile.get("summary"))
    drift_summary = _as_dict(drift.get("summary"))
    reconciliation_summary = _as_dict(reconciliation.get("summary"))

    nodes = _build_nodes(
        root=root,
        local_root=local_root,
        control_report=control_report,
        control_summary=control_summary,
        cleansing=cleansing,
        cleansing_summary=cleansing_summary,
        profile_summary=profile_summary,
        gap_summary=gap_summary,
        drift=drift,
        drift_summary=drift_summary,
        reconciliation=reconciliation,
        reconciliation_summary=reconciliation_summary,
    )
    edges = _build_edges()
    ready_nodes = [node for node in nodes if node["status"] in {"ready", "pass", "fixed"}]
    needs_attention_nodes = [
        node for node in nodes if node["status"] == "needs_attention"
    ]
    status = (
        "needs_attention"
        if control_report.get("status") == "needs_attention" or needs_attention_nodes
        else "ready"
    )
    payload: JsonDict = {
        "schema_version": 2,
        "status": status,
        "title": "Market Data Lineage",
        "generated_at": generated,
        "objective": "seamless_market_data_visualization",
        "summary": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "ready_node_count": len(ready_nodes),
            "needs_attention_node_count": len(needs_attention_nodes),
            "source_of_truth_count": _as_int(
                reconciliation_summary.get("official_domestic_stock_issues")
            )
            or _as_int(cleansing_summary.get("reference_count")),
            "clean_preview_count": len(
                [
                    node
                    for node in nodes
                    if node["kind"] == "dataset"
                    and node["lineage_role"] == "clean_preview"
                ]
            ),
            "safe_data_mode": control_summary.get(
                "safe_data_mode", "clean_preview_only"
            ),
            "raw_source_ingestion_allowed": bool(
                control_summary.get("raw_source_ingestion_allowed", False)
            ),
            "clean_preview_available": bool(
                control_summary.get("clean_preview_available", False)
            ),
            "downstream_ready": bool(control_summary.get("downstream_ready", False)),
            "latest_as_of": gap_summary.get("latest_as_of"),
        },
        "nodes": nodes,
        "edges": edges,
        "policy": {
            "source_of_truth": "JPX domestic stock snapshot + reconciled ticker map",
            "allowed_downstream_input": control_summary.get(
                "safe_data_mode", "clean_preview_only"
            ),
            "raw_source_ingestion_allowed": False,
            "missing_tickers_are_reported_not_synthesized": True,
            "non_advisory": True,
        },
        "guardrails": {
            "auto_trading": False,
            "call_real_api": False,
            "external_fetch_executed": False,
            "source_data_write_executed": False,
            "write_to_source_data": False,
        },
    }
    _write_artifacts(root, payload)
    _copy_to_mirrors(root, mirrors)
    return {
        "status": "ready",
        "dashboard_root": str(root),
        "mirror_roots": [str(path) for path in mirrors],
        "lineage_status": payload["status"],
        "summary": payload["summary"],
        "written_files": [str(root / filename) for filename in LINEAGE_FILES],
        "auto_trading": False,
        "call_real_api": False,
        "external_fetch_executed": False,
        "write_to_source_data": False,
    }


def _build_nodes(
    *,
    root: Path,
    local_root: Path,
    control_report: JsonDict,
    control_summary: JsonDict,
    cleansing: JsonDict,
    cleansing_summary: JsonDict,
    profile_summary: JsonDict,
    gap_summary: JsonDict,
    drift: JsonDict,
    drift_summary: JsonDict,
    reconciliation: JsonDict,
    reconciliation_summary: JsonDict,
) -> list[JsonDict]:
    nodes = [
        _node(
            node_id="jpx_domestic_snapshot",
            label="JPX domestic stock snapshot",
            kind="source_of_truth",
            lineage_role="reference_universe",
            status="pass",
            path=local_root / "jpx_domestic_stock_snapshot_20260630.csv",
            metrics={
                "reference_count": _as_int(
                    reconciliation_summary.get("official_domestic_stock_issues")
                )
                or _as_int(cleansing_summary.get("reference_count")),
            },
        ),
        _node(
            node_id="ticker_data_map",
            label="Reconciled ticker data map",
            kind="dataset",
            lineage_role="canonical_map",
            status=str(reconciliation.get("status") or "ready"),
            path=root / "ticker_data_map.json",
            metrics={
                "row_count": _as_int(
                    reconciliation_summary.get("reconciled_ticker_map_rows")
                ),
                "extra_removed_count": _as_int(
                    reconciliation_summary.get("extra_removed_count")
                ),
                "missing_added_count": _as_int(
                    reconciliation_summary.get("missing_added_count")
                ),
            },
        ),
        _node(
            node_id="data_quality_profile",
            label="Six-dimension quality profile",
            kind="quality_gate",
            lineage_role="profile",
            status=str(profile_summary.get("status") or "needs_attention"),
            path=root / "data_quality_profile.json",
            metrics={
                "dimension_count": _as_int(profile_summary.get("dimension_count")),
                "pass_count": _as_int(profile_summary.get("pass_count")),
                "needs_attention_count": _as_int(
                    profile_summary.get("needs_attention_count")
                ),
            },
        ),
        _node(
            node_id="source_drift_audit",
            label="Raw source drift audit",
            kind="quality_gate",
            lineage_role="raw_source_check",
            status=str(drift.get("status") or "needs_attention"),
            path=root / "source_drift_audit.json",
            metrics={
                "total_extra_ticker_count": _as_int(
                    drift_summary.get("total_extra_ticker_count")
                ),
                "total_missing_ticker_count": _as_int(
                    drift_summary.get("total_missing_ticker_count")
                ),
            },
        ),
        _node(
            node_id="source_cleansing_preview",
            label="Source cleansing preview",
            kind="quality_gate",
            lineage_role="cleaning_rule",
            status=str(cleansing.get("status") or "needs_attention"),
            path=root / "source_cleansing_preview.json",
            metrics={
                "total_dropped_ticker_count": _as_int(
                    cleansing_summary.get("total_dropped_ticker_count")
                ),
                "total_missing_ticker_count": _as_int(
                    cleansing_summary.get("total_missing_ticker_count")
                ),
            },
        ),
    ]
    for source in _as_list(cleansing.get("sources")):
        source_id = str(source.get("source_id") or "")
        if not source_id:
            continue
        nodes.append(
            _node(
                node_id=f"raw_{source_id}",
                label=f"Raw source: {source_id}",
                kind="dataset",
                lineage_role="raw_source",
                status=str(source.get("status") or "needs_attention"),
                path=Path(str(source.get("source_path") or "")),
                metrics={
                    "raw_row_count": _as_int(source.get("raw_row_count")),
                    "raw_ticker_count": _as_int(source.get("raw_ticker_count")),
                    "dropped_ticker_count": _as_int(
                        source.get("dropped_ticker_count")
                    ),
                    "missing_ticker_count": _as_int(
                        source.get("missing_ticker_count")
                    ),
                },
            )
        )
        nodes.append(
            _node(
                node_id=f"clean_{source_id}",
                label=f"Clean preview: {source_id}",
                kind="dataset",
                lineage_role="clean_preview",
                status="ready",
                path=Path(str(source.get("preview_path") or "")),
                metrics={
                    "clean_preview_row_count": _as_int(
                        source.get("clean_preview_row_count")
                    ),
                    "clean_preview_ticker_count": _as_int(
                        source.get("clean_preview_ticker_count")
                    ),
                    "kept_reference_coverage_pct": source.get(
                        "kept_reference_coverage_pct"
                    ),
                },
            )
        )
    nodes.extend(
        [
            _node(
                node_id="data_gap_dashboard",
                label="Downstream gap dashboard",
                kind="quality_gate",
                lineage_role="downstream_gap_check",
                status=str(gap_summary.get("status") or "needs_attention"),
                path=root / "data_gap_dashboard.json",
                metrics={
                    "price_gap": _as_int(gap_summary.get("price_gap")),
                    "yield_gap": _as_int(gap_summary.get("yield_gap")),
                    "yield_coverage_pct": gap_summary.get("yield_coverage_pct"),
                },
            ),
            _node(
                node_id="data_quality_control_report",
                label="Integrated data quality control report",
                kind="governance",
                lineage_role="control_gate",
                status=str(control_report.get("status") or "needs_attention"),
                path=root / "data_quality_control_report.json",
                metrics={
                    "gate_count": _as_int(control_summary.get("gate_count")),
                    "pass_count": _as_int(control_summary.get("pass_count")),
                    "safe_data_mode": control_summary.get("safe_data_mode"),
                },
            ),
        ]
    )
    return nodes


def _build_edges() -> list[JsonDict]:
    return [
        _edge("jpx_domestic_snapshot", "ticker_data_map", "defines universe"),
        _edge("ticker_data_map", "source_drift_audit", "reference comparison"),
        _edge("ticker_data_map", "source_cleansing_preview", "cleaning reference"),
        _edge("raw_current_prices", "source_drift_audit", "raw drift check"),
        _edge("raw_market_financials", "source_drift_audit", "raw drift check"),
        _edge("raw_current_prices", "source_cleansing_preview", "preview input"),
        _edge("raw_market_financials", "source_cleansing_preview", "preview input"),
        _edge("source_cleansing_preview", "clean_current_prices", "write preview"),
        _edge("source_cleansing_preview", "clean_market_financials", "write preview"),
        _edge("data_quality_profile", "data_quality_control_report", "quality gate"),
        _edge("source_drift_audit", "data_quality_control_report", "drift gate"),
        _edge("source_cleansing_preview", "data_quality_control_report", "cleaning gate"),
        _edge("data_gap_dashboard", "data_quality_control_report", "coverage gate"),
        _edge("clean_current_prices", "data_gap_dashboard", "downstream input"),
        _edge("clean_market_financials", "data_gap_dashboard", "downstream input"),
    ]


def _node(
    *,
    node_id: str,
    label: str,
    kind: str,
    lineage_role: str,
    status: str,
    path: str | Path,
    metrics: JsonDict,
) -> JsonDict:
    path_text = str(path)
    resolved = _resolve_path(Path(path_text))
    file_info = _file_info(resolved)
    return {
        "id": node_id,
        "label": label,
        "kind": kind,
        "lineage_role": lineage_role,
        "status": status,
        "path": path_text,
        "exists": file_info["exists"],
        "bytes": file_info["bytes"],
        "sha256": file_info["sha256"],
        "metrics": metrics,
    }


def _edge(source: str, target: str, label: str) -> JsonDict:
    return {"from": source, "to": target, "label": label}


def _write_artifacts(root: Path, payload: JsonDict) -> None:
    (root / "lineage.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _write_csv(root / "lineage.csv", payload)
    _write_md(root / "lineage.md", payload)
    (root / "lineage.html").write_text(_render_html(payload), encoding="utf-8")


def _write_csv(path: Path, payload: JsonDict) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "id",
                "label",
                "kind",
                "lineage_role",
                "status",
                "exists",
                "bytes",
                "sha256",
                "path",
            ],
        )
        writer.writeheader()
        for node in payload["nodes"]:
            writer.writerow(
                {field: node.get(field, "") for field in writer.fieldnames or []}
            )


def _write_md(path: Path, payload: JsonDict) -> None:
    summary = payload["summary"]
    lines = [
        "# Market Data Lineage",
        "",
        f"Generated: {payload['generated_at']}",
        "",
        f"- Status: {payload['status']}",
        f"- Nodes: {summary['ready_node_count']}/{summary['node_count']} ready",
        f"- Source of truth count: {summary['source_of_truth_count']}",
        f"- Safe data mode: {summary['safe_data_mode']}",
        f"- Clean previews: {summary['clean_preview_count']}",
        "",
        "| Node | Role | Status | Exists | Path |",
        "|---|---|---|---|---|",
    ]
    for node in payload["nodes"]:
        lines.append(
            f"| {node['label']} | {node['lineage_role']} | {node['status']} | "
            f"{node['exists']} | `{node['path']}` |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _render_html(payload: JsonDict) -> str:
    summary = payload["summary"]
    rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(node['label'])}</td>"
        f"<td>{html.escape(node['lineage_role'])}</td>"
        f"<td>{html.escape(node['status'])}</td>"
        f"<td>{'yes' if node['exists'] else 'no'}</td>"
        f"<td><code>{html.escape(node['path'])}</code></td>"
        "</tr>"
        for node in payload["nodes"]
    )
    edge_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(edge['from'])}</td>"
        f"<td>{html.escape(edge['to'])}</td>"
        f"<td>{html.escape(edge['label'])}</td>"
        "</tr>"
        for edge in payload["edges"]
    )
    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Market Data Lineage</title>
<style>
body {{ margin: 0; background: #f6f8fb; color: #172033; font-family: "Segoe UI", system-ui, sans-serif; }}
main {{ max-width: 1180px; margin: 0 auto; padding: 32px 20px 44px; }}
h1 {{ margin: 0 0 10px; font-size: clamp(1.9rem, 4vw, 3rem); }}
.summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 22px 0; }}
.box {{ background: #fff; border: 1px solid #d8e0ea; border-radius: 8px; padding: 14px; }}
.metric {{ font-size: 1.4rem; font-weight: 850; }}
.muted {{ color: #526070; }}
table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #d8e0ea; margin: 18px 0 28px; }}
th, td {{ border-bottom: 1px solid #d8e0ea; padding: 10px 12px; text-align: left; vertical-align: top; }}
th {{ background: #eef3f8; }}
code {{ font-size: 0.86rem; }}
</style>
</head>
<body>
<main>
  <h1>Market Data Lineage</h1>
  <p class="muted">JPX基準、raw source、clean preview、品質ゲート、下流準備状態を同じ系譜で確認します。外部取得、実API呼び出し、自動売買は行いません。</p>
  <section class="summary">
    <div class="box"><div class="muted">Nodes</div><div class="metric">{summary['ready_node_count']}/{summary['node_count']}</div></div>
    <div class="box"><div class="muted">Source of Truth</div><div class="metric">{summary['source_of_truth_count']}</div></div>
    <div class="box"><div class="muted">Clean Previews</div><div class="metric">{summary['clean_preview_count']}</div></div>
    <div class="box"><div class="muted">Safe Data Mode</div><div class="metric">{html.escape(str(summary['safe_data_mode']))}</div></div>
  </section>
  <h2>Nodes</h2>
  <table>
    <thead><tr><th>Node</th><th>Role</th><th>Status</th><th>Exists</th><th>Path</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <h2>Edges</h2>
  <table>
    <thead><tr><th>From</th><th>To</th><th>Meaning</th></tr></thead>
    <tbody>{edge_rows}</tbody>
  </table>
</main>
</body>
</html>
"""


def _copy_to_mirrors(root: Path, mirrors: Sequence[Path]) -> None:
    for mirror in mirrors:
        mirror.mkdir(parents=True, exist_ok=True)
        for filename in LINEAGE_FILES:
            shutil.copy2(root / filename, mirror / filename)


def _read_json(path: Path) -> JsonDict:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return payload if isinstance(payload, dict) else {}


def _as_dict(value: Any) -> JsonDict:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[JsonDict]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _as_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _resolve_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return Path.cwd() / path


def _file_info(path: Path) -> JsonDict:
    if not path.is_file():
        return {"exists": False, "bytes": 0, "sha256": None}
    return {
        "exists": True,
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now_jst() -> str:
    return datetime.now(UTC).astimezone(JST).isoformat(timespec="seconds")
