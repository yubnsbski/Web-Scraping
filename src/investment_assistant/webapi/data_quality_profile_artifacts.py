"""Static artifact builder for the market data-quality profile."""

from __future__ import annotations

import csv
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from investment_assistant.webapi.data_status import data_quality_profile

JsonDict = dict[str, Any]


@dataclass(frozen=True)
class DataQualityProfileArtifactConfig:
    output_dir: Path
    mirror_dirs: tuple[Path, ...] = field(default_factory=tuple)
    request_body: JsonDict = field(default_factory=dict)
    generated_at: str | None = None


def build_data_quality_profile_artifacts(
    config: DataQualityProfileArtifactConfig,
) -> JsonDict:
    """Build JSON/CSV/HTML/Markdown profile artifacts from the read-only API logic."""

    config.output_dir.mkdir(parents=True, exist_ok=True)
    profile = data_quality_profile(dict(config.request_body))
    generated_at = config.generated_at or datetime.now().astimezone().isoformat(
        timespec="seconds"
    )
    payload: JsonDict = {
        "status": profile["status"],
        "title": "Data Quality Profile",
        "generated_at": generated_at,
        "profile_checked_at": profile["checked_at"],
        "source_api": "GET /api/data/quality",
        "summary": profile["summary"],
        "sources": profile["sources"],
        "dimensions": profile["dimensions"],
        "recommended_actions": profile["recommended_actions"],
        "write_executed": profile["write_executed"],
        "external_fetch_executed": profile["external_fetch_executed"],
        "auto_trading": profile["auto_trading"],
        "call_real_api": profile["call_real_api"],
        "notes": [
            "Artifacts are generated from local files only.",
            "Raw source gaps remain visible even when downstream cleaned maps are reconciled.",
            "This is a data-quality workflow, not investment advice.",
        ],
    }

    _write_json(config.output_dir / "data_quality_profile.json", payload)
    _write_csv(config.output_dir / "data_quality_profile.csv", payload)
    _write_html(config.output_dir / "data_quality_profile.html", payload)
    _write_markdown(config.output_dir / "data_quality_profile.md", payload)
    _mirror_artifacts(config.output_dir, config.mirror_dirs)
    return payload


def _write_json(path: Path, payload: JsonDict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _write_csv(path: Path, payload: JsonDict) -> None:
    fieldnames = [
        "dimension_id",
        "label",
        "status",
        "score",
        "metric_count",
        "recommended_action_count",
        "key_metrics",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for dimension in payload["dimensions"]:
            metrics = dimension.get("metrics") or {}
            writer.writerow(
                {
                    "dimension_id": dimension.get("id", ""),
                    "label": dimension.get("label", ""),
                    "status": dimension.get("status", ""),
                    "score": dimension.get("score", ""),
                    "metric_count": len(metrics),
                    "recommended_action_count": len(
                        dimension.get("recommended_actions") or []
                    ),
                    "key_metrics": json.dumps(metrics, ensure_ascii=True, sort_keys=True),
                }
            )


def _write_html(path: Path, payload: JsonDict) -> None:
    summary = payload["summary"]
    cards = [
        ("Dimensions", summary["dimension_count"]),
        ("Pass", summary["pass_count"]),
        ("Needs Attention", summary["needs_attention_count"]),
        ("JPX Domestic Stocks", f"{summary['jpx_domestic_stock_count']:,}"),
    ]
    card_html = "".join(
        "<article class='card'>"
        f"<h2>{escape(label)}</h2><div class='metric'>{escape(str(value))}</div>"
        "</article>"
        for label, value in cards
    )
    dimension_rows = "".join(
        "<tr>"
        f"<td><code>{escape(str(item.get('id', '')))}</code></td>"
        f"<td>{escape(str(item.get('label', '')))}</td>"
        f"<td>{escape(str(item.get('status', '')))}</td>"
        f"<td>{escape(str(item.get('score', '')))}</td>"
        f"<td>{escape(str(len(item.get('recommended_actions') or [])))}</td>"
        "</tr>"
        for item in payload["dimensions"]
    )
    source_rows = "".join(
        "<tr>"
        f"<td><code>{escape(source_id)}</code></td>"
        f"<td>{escape(str(source.get('status', '')))}</td>"
        f"<td>{escape(str(source.get('row_count', '')))}</td>"
        f"<td>{escape(str(source.get('latest_value', '')))}</td>"
        f"<td>{escape(str(source.get('path', '')))}</td>"
        "</tr>"
        for source_id, source in payload["sources"].items()
    )
    actions = "".join(
        f"<li>{escape(str(action))}</li>" for action in payload["recommended_actions"]
    )
    css = (
        ":root{color-scheme:light;font-family:Inter,'Segoe UI',sans-serif;"
        "color:#172033;background:#f6f8fb}body{margin:0}.shell{max-width:1180px;"
        "margin:auto;padding:32px 22px}.grid{display:grid;grid-template-columns:"
        "repeat(auto-fit,minmax(220px,1fr));gap:14px}.card{background:white;"
        "border:1px solid #dbe3ee;border-radius:8px;padding:18px;margin:14px 0}"
        ".metric{font-size:28px;font-weight:850}table{width:100%;border-collapse:"
        "collapse}th,td{border-bottom:1px solid #e5eaf2;text-align:left;padding:9px}"
        "th{background:#f1f5f9}.notice{font-weight:700;color:#44546a}"
    )
    html = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{escape(str(payload['title']))}</title><style>{css}</style></head>"
        "<body><main class='shell'>"
        f"<h1>{escape(str(payload['title']))}</h1>"
        "<p class='notice'>Local-file quality profile. No write, no external fetch, "
        "no real API call, no trading.</p>"
        f"<section class='grid'>{card_html}</section>"
        "<section class='card'><h2>Dimensions</h2><table><thead><tr>"
        "<th>ID</th><th>Label</th><th>Status</th><th>Score</th><th>Actions</th>"
        f"</tr></thead><tbody>{dimension_rows}</tbody></table></section>"
        "<section class='card'><h2>Sources</h2><table><thead><tr>"
        "<th>ID</th><th>Status</th><th>Rows</th><th>Latest</th><th>Path</th>"
        f"</tr></thead><tbody>{source_rows}</tbody></table></section>"
        f"<section class='card'><h2>Recommended Actions</h2><ul>{actions}</ul></section>"
        "</main></body></html>"
    )
    path.write_text(html, encoding="utf-8")


def _write_markdown(path: Path, payload: JsonDict) -> None:
    summary = payload["summary"]
    lines = [
        "# Data Quality Profile",
        "",
        f"- status: {payload['status']}",
        f"- generated_at: {payload['generated_at']}",
        f"- profile_checked_at: {payload['profile_checked_at']}",
        f"- dimension_count: {summary['dimension_count']}",
        f"- pass_count: {summary['pass_count']}",
        f"- needs_attention_count: {summary['needs_attention_count']}",
        f"- jpx_domestic_stock_count: {summary['jpx_domestic_stock_count']}",
        "",
        "## Dimensions",
    ]
    for dimension in payload["dimensions"]:
        lines.append(
            "- "
            f"{dimension.get('id')}: {dimension.get('status')} "
            f"(score {dimension.get('score')})"
        )
    lines.extend(["", "## Recommended Actions"])
    lines.extend(f"- {action}" for action in payload["recommended_actions"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _mirror_artifacts(output_dir: Path, mirror_dirs: tuple[Path, ...]) -> None:
    filenames = (
        "data_quality_profile.json",
        "data_quality_profile.csv",
        "data_quality_profile.html",
        "data_quality_profile.md",
    )
    for mirror_dir in mirror_dirs:
        mirror_dir.mkdir(parents=True, exist_ok=True)
        for filename in filenames:
            shutil.copy2(output_dir / filename, mirror_dir / filename)
