"""Repeatable quality gates for daily-bars backfill slices."""

from __future__ import annotations

import csv
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

REQUIRED_FIELDS = (
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "source_provider",
    "source_url",
    "checked_at",
)
INPUT_COLUMNS = ("ticker", *REQUIRED_FIELDS, "note")
MANIFEST_COLUMNS = (
    "slice_id",
    "slice_rank",
    "batch_id",
    "batch_rank",
    "queue_rank",
    "priority",
    "ticker",
    "name",
    "segment_bucket",
    "segment",
    "has_current_price",
    "has_market_financials",
)
VALIDATION_COLUMNS = ("slice_id", "row_number", "ticker", "name", "status", "issue_count", "issues")
FIELD_COLUMNS = (
    "slice_id",
    "field",
    "completed_rows",
    "missing_rows",
    "total_rows",
    "completion_rate",
)
PREVIEW_COLUMNS = ("slice_id", *INPUT_COLUMNS)
DEFAULT_NOTE = "Enter reviewed OHLCV evidence only; do not infer values."
NOT_ADVICE = "\u6295\u8cc7\u5224\u65ad\u3067\u306f\u3042\u308a\u307e\u305b\u3093"
NO_TRADING = "\u58f2\u8cb7\u6a5f\u80fd\u306f\u3042\u308a\u307e\u305b\u3093"


@dataclass(frozen=True)
class SliceBuildConfig:
    batch_manifest_path: Path
    output_dir: Path
    slice_id: str = "daily-bars-batch001-slice001"
    batch_id: str = "daily-bars-batch001"
    slice_size: int = 5
    generated_at: str | None = None
    mirror_dirs: tuple[Path, ...] = ()


def build_daily_bars_slice(config: SliceBuildConfig) -> dict[str, Any]:
    if config.slice_size <= 0:
        raise ValueError("slice_size must be positive")
    config.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = _read_csv(config.batch_manifest_path)[: config.slice_size]
    if len(manifest) != config.slice_size:
        raise ValueError(f"expected {config.slice_size} manifest rows, got {len(manifest)}")

    prefix = _prefix(config.batch_id, config.slice_id)
    input_path = config.output_dir / f"{prefix}_input_template.csv"
    input_rows = _input_rows(manifest, input_path)
    slice_manifest = _slice_manifest(config, manifest)
    validation = _validation_rows(config.slice_id, manifest, input_rows)
    field_completion = _field_completion(config.slice_id, input_rows)
    preview = _append_preview(config.slice_id, input_rows, validation)
    blockers = sum(int(row["issue_count"]) for row in validation)
    ready_rows = sum(1 for row in validation if row["status"] == "ready")
    generated_at = config.generated_at or datetime.now().astimezone().isoformat(timespec="seconds")
    summary: dict[str, Any] = {
        "generated_at": generated_at,
        "status": "ready" if blockers == 0 else "blocked",
        "slice_id": config.slice_id,
        "batch_id": config.batch_id,
        "slice_size": len(input_rows),
        "ready_rows": ready_rows,
        "template_rows": len(input_rows),
        "blockers": blockers,
        "append_candidate_rows": len(preview),
        "append_ready": blockers == 0 and ready_rows == len(input_rows),
        "current_stage": "append_dry_run" if blockers == 0 else "data_entry",
        "next_action": _next_action(blockers),
        "write_executed": False,
        "external_fetch_executed": False,
        "auto_trading": False,
        "call_real_api": False,
    }
    safe_flags = {
        "write_executed": False,
        "external_fetch_executed": False,
        "auto_trading": False,
        "call_real_api": False,
        "advisory_output": False,
    }
    links = _links(prefix)
    overview = {
        "status": summary["status"],
        "title": "Daily Bars Batch 001 Slice 001",
        "summary": summary,
        "tickers": slice_manifest,
        "required_fields": list(REQUIRED_FIELDS),
        "field_completion": field_completion,
        "safe_flags": safe_flags,
        "links": links,
        "disclaimer": "Data quality workflow only. No advice, no trading, no write.",
    }
    intake = {
        "status": summary["status"],
        "title": "Daily Bars Batch 001 Slice 001 Intake Validation",
        "summary": summary,
        "required_fields": list(REQUIRED_FIELDS),
        "validation_rows": validation,
        "field_completion": field_completion,
        "safe_flags": safe_flags,
        "links": links,
    }
    dry_run = {
        "status": summary["status"],
        "title": "Daily Bars Batch 001 Slice 001 Append Dry Run",
        "summary": summary,
        "append_ready": summary["append_ready"],
        "append_candidate_rows": len(preview),
        "blocked_rows": [row for row in validation if row["status"] != "ready"],
        "append_preview_rows": preview,
        "safe_flags": safe_flags,
        "links": links,
    }
    contract = _contract(config.slice_id, generated_at, safe_flags)

    _write_csv(config.output_dir / f"{prefix}_manifest.csv", slice_manifest, MANIFEST_COLUMNS)
    _write_csv(input_path, input_rows, INPUT_COLUMNS)
    _write_csv(
        config.output_dir / f"{prefix}_intake_validation.csv", validation, VALIDATION_COLUMNS
    )
    _write_csv(
        config.output_dir / f"{prefix}_field_completion.csv", field_completion, FIELD_COLUMNS
    )
    _write_csv(config.output_dir / f"{prefix}_append_preview.csv", preview, PREVIEW_COLUMNS)
    _write_json(config.output_dir / f"{prefix}.json", overview)
    _write_json(config.output_dir / f"{prefix}_intake_validation.json", intake)
    _write_json(config.output_dir / f"{prefix}_append_dry_run.json", dry_run)
    _write_json(config.output_dir / f"{prefix}_validation_contract.json", contract)
    _write_text(
        config.output_dir / f"{prefix}.html",
        _html("Batch 001 Slice 001", summary, links, slice_manifest, validation, field_completion),
    )
    _write_text(
        config.output_dir / f"{prefix}_intake_validation.html",
        _html("Slice 001 Intake Validation", summary, links, [], validation, field_completion),
    )
    _write_text(
        config.output_dir / f"{prefix}_append_dry_run.html",
        _html("Slice 001 Append Dry Run", summary, links, [], validation, []),
    )
    _write_text(config.output_dir / f"{prefix}.md", _md("Daily Bars Batch 001 Slice 001", summary))
    _write_text(
        config.output_dir / f"{prefix}_intake_validation.md",
        _md("Daily Bars Batch 001 Slice 001 Intake Validation", summary),
    )
    _write_text(
        config.output_dir / f"{prefix}_append_dry_run.md",
        _md("Daily Bars Batch 001 Slice 001 Append Dry Run", summary),
    )
    _update_context(config.output_dir, prefix, summary)
    _mirror(config.output_dir, config.mirror_dirs, prefix)
    return overview


def _prefix(batch_id: str, slice_id: str) -> str:
    suffix = slice_id.split("-batch001-", 1)[-1].replace("-", "_")
    if batch_id.startswith("daily-bars-") and "backfill" not in batch_id:
        batch_prefix = batch_id.replace("daily-bars-", "daily-bars-backfill-")
    else:
        batch_prefix = batch_id
    return f"{batch_prefix.replace('-', '_')}_{suffix}"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: tuple[str, ...]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _input_rows(manifest: list[dict[str, str]], input_path: Path) -> list[dict[str, str]]:
    existing = (
        {row.get("ticker", ""): row for row in _read_csv(input_path)} if input_path.exists() else {}
    )
    rows: list[dict[str, str]] = []
    for manifest_row in manifest:
        ticker = manifest_row.get("ticker", "")
        source = existing.get(ticker, {})
        row = {column: source.get(column, "") for column in INPUT_COLUMNS}
        row["ticker"] = ticker
        row["note"] = row.get("note") or DEFAULT_NOTE
        rows.append(row)
    return rows


def _slice_manifest(config: SliceBuildConfig, rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        output.append(
            {
                "slice_id": config.slice_id,
                "slice_rank": index,
                "batch_id": row.get("batch_id", config.batch_id),
                "batch_rank": row.get("batch_rank", ""),
                "queue_rank": row.get("queue_rank", ""),
                "priority": row.get("priority", ""),
                "ticker": row.get("ticker", ""),
                "name": row.get("name", ""),
                "segment_bucket": row.get("segment_bucket", ""),
                "segment": row.get("segment", ""),
                "has_current_price": row.get("has_current_price", ""),
                "has_market_financials": row.get("has_market_financials", ""),
            }
        )
    return output


def _validation_rows(
    slice_id: str, manifest: list[dict[str, str]], inputs: list[dict[str, str]]
) -> list[dict[str, Any]]:
    names = {row.get("ticker", ""): row.get("name", "") for row in manifest}
    rows: list[dict[str, Any]] = []
    for row_number, row in enumerate(inputs, start=2):
        issues = _issues(row)
        rows.append(
            {
                "slice_id": slice_id,
                "row_number": row_number,
                "ticker": row.get("ticker", ""),
                "name": names.get(row.get("ticker", ""), ""),
                "status": "ready" if not issues else "needs_input",
                "issue_count": len(issues),
                "issues": ";".join(issues),
            }
        )
    return rows


def _issues(row: dict[str, str]) -> list[str]:
    issues: list[str] = [
        f"missing_{field}" for field in REQUIRED_FIELDS if not _clean(row.get(field))
    ]
    if _clean(row.get("date")) and not _is_date(_clean(row.get("date"))):
        issues.append("invalid_date")
    if _clean(row.get("checked_at")) and not _is_datetime(_clean(row.get("checked_at"))):
        issues.append("invalid_checked_at")
    url = _clean(row.get("source_url"))
    if url and not url.startswith(("http://", "https://")):
        issues.append("invalid_source_url")
    numeric: dict[str, float] = {}
    for field in ("open", "high", "low", "close"):
        value = _clean(row.get(field))
        if value:
            parsed = _number(value)
            if parsed is None or parsed <= 0:
                issues.append(f"invalid_{field}")
            else:
                numeric[field] = parsed
    volume = _clean(row.get("volume"))
    if volume:
        parsed_volume = _number(volume)
        if parsed_volume is None or parsed_volume < 0 or not parsed_volume.is_integer():
            issues.append("invalid_volume")
    if set(numeric) == {"open", "high", "low", "close"}:
        if numeric["high"] < max(numeric.values()):
            issues.append("invalid_high_below_price")
        if numeric["low"] > min(numeric.values()):
            issues.append("invalid_low_above_price")
    return issues


def _field_completion(slice_id: str, inputs: list[dict[str, str]]) -> list[dict[str, Any]]:
    total = len(inputs)
    rows = []
    for field in REQUIRED_FIELDS:
        done = sum(1 for row in inputs if _clean(row.get(field)))
        rows.append(
            {
                "slice_id": slice_id,
                "field": field,
                "completed_rows": done,
                "missing_rows": total - done,
                "total_rows": total,
                "completion_rate": round(done / total * 100 if total else 0, 2),
            }
        )
    return rows


def _append_preview(
    slice_id: str, inputs: list[dict[str, str]], validation: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    ready = {row["ticker"] for row in validation if row["status"] == "ready"}
    return [{"slice_id": slice_id, **row} for row in inputs if row.get("ticker") in ready]


def _contract(slice_id: str, generated_at: str, safe_flags: dict[str, bool]) -> dict[str, Any]:
    return {
        "status": "ready",
        "title": "Daily Bars Slice Validation Contract",
        "generated_at": generated_at,
        "slice_id": slice_id,
        "required_fields": list(REQUIRED_FIELDS),
        "rules": [
            "required_fields",
            "numeric_validity",
            "ohlc_consistency",
            "source_evidence_required",
            "no_write_without_review",
            "no_trading",
        ],
        "safe_flags": safe_flags,
    }


def _links(prefix: str) -> dict[str, str]:
    return {
        "overview": f"{prefix}.html",
        "input_template": f"{prefix}_input_template.csv",
        "intake_validation": f"{prefix}_intake_validation.html",
        "append_dry_run": f"{prefix}_append_dry_run.html",
        "append_preview": f"{prefix}_append_preview.csv",
        "json": f"{prefix}.json",
        "batch_workflow": "daily_bars_backfill_batch001_workflow.html",
        "sprint_review": "data_quality_sprint_review.html",
    }


def _next_action(blockers: int) -> str:
    if blockers:
        return "Fill reviewed OHLCV/source evidence in the input template, then rerun this gate."
    return "Review append preview; this gate still performs no write."


def _html(
    title: str,
    summary: dict[str, Any],
    links: dict[str, str],
    tickers: list[dict[str, Any]],
    validation: list[dict[str, Any]],
    fields: list[dict[str, Any]],
) -> str:
    ticker_rows = "".join(
        f"<tr><td><code>{escape(str(r['ticker']))}</code></td><td>{escape(str(r['name']))}</td><td>{escape(str(r['priority']))}</td></tr>"
        for r in tickers
    )
    validation_rows = "".join(
        f"<tr><td>{r['row_number']}</td><td><code>{escape(str(r['ticker']))}</code></td><td>{escape(str(r['status']))}</td><td>{r['issue_count']}</td><td><code>{escape(str(r['issues']))}</code></td></tr>"
        for r in validation
    )
    field_rows = "".join(
        f"<tr><td><code>{r['field']}</code></td><td>{r['completed_rows']}</td><td>{r['missing_rows']}</td><td>{r['completion_rate']}%</td></tr>"
        for r in fields
    )
    link_html = "".join(
        f"<a class='btn' href='{escape(v)}'>{escape(k)}</a>" for k, v in links.items()
    )
    css = (
        ":root{color-scheme:light;font-family:Inter,'Noto Sans JP','Segoe UI',sans-serif;"
        "color:#172033;background:#f6f8fb}body{margin:0}"
        ".shell{max-width:1180px;margin:auto;padding:32px 22px}"
        ".grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}"
        ".card{background:white;border:1px solid #dbe3ee;border-radius:8px;"
        "padding:18px;margin:14px 0}"
        ".metric{font-size:28px;font-weight:850}"
        ".btn{display:inline-flex;margin:8px;padding:10px;border:1px solid #cbd5e1;"
        "border-radius:8px;text-decoration:none;color:#0f172a;font-weight:800}"
        "table{width:100%;border-collapse:collapse}"
        "th,td{border-bottom:1px solid #e5eaf2;text-align:left;padding:9px}"
        "th{background:#f1f5f9}"
    )
    return (
        "<!doctype html><html lang='ja'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{escape(title)}</title><style>{css}</style></head>"
        "<body><main class='shell'><p><strong>Daily Bars Backfill</strong></p>"
        f"<h1>{escape(title)}</h1>"
        "<p>A repeatable data-quality gate. "
        f"No external fetch, no write, {NOT_ADVICE}, and {NO_TRADING}.</p>"
        "<section class='grid'>"
        "<article class='card'><h2>Input ready</h2>"
        f"<div class='metric'>{summary['ready_rows']}/{summary['template_rows']}</div>"
        "</article><article class='card'><h2>Blockers</h2>"
        f"<div class='metric'>{summary['blockers']}</div></article>"
        "<article class='card'><h2>Append candidates</h2>"
        f"<div class='metric'>{summary['append_candidate_rows']}/"
        f"{summary['template_rows']}</div></article>"
        "<article class='card'><h2>Writes</h2><div class='metric'>0</div>"
        "<p>write_executed=false</p></article></section>"
        f"<section class='card'><h2>Links</h2>{link_html}</section>"
        "<section class='card'><h2>Tickers</h2><table><thead><tr>"
        "<th>Ticker</th><th>Name</th><th>Priority</th></tr></thead>"
        f"<tbody>{ticker_rows}</tbody></table></section>"
        "<section class='card'><h2>Validation</h2><table><thead><tr>"
        "<th>Row</th><th>Ticker</th><th>Status</th><th>Issue count</th><th>Issues</th>"
        f"</tr></thead><tbody>{validation_rows}</tbody></table></section>"
        "<section class='card'><h2>Field completion</h2><table><thead><tr>"
        "<th>Field</th><th>Done</th><th>Missing</th><th>Rate</th></tr></thead>"
        f"<tbody>{field_rows}</tbody></table></section></main></body></html>\n"
    )


def _md(title: str, summary: dict[str, Any]) -> str:
    return (
        f"# {title}\n\n"
        f"- status: {summary['status']}\n"
        f"- ready_rows: {summary['ready_rows']}/{summary['template_rows']}\n"
        f"- blockers: {summary['blockers']}\n"
        f"- append_candidate_rows: {summary['append_candidate_rows']}/"
        f"{summary['template_rows']}\n"
        "- write_executed: false\n"
        "- external_fetch_executed: false\n"
        "- auto_trading: false\n"
    )


def _update_context(output_dir: Path, prefix: str, summary: dict[str, Any]) -> None:
    href = f"{prefix}.html"
    for html_name in (
        "daily_bars_backfill_batch001_workflow.html",
        "data_quality_sprint_review.html",
    ):
        path = output_dir / html_name
        if path.exists():
            text = path.read_text(encoding="utf-8-sig")
            if href not in text:
                text = text.replace(
                    "</section>", f"<a class='btn' href='{href}'>Slice 001</a></section>", 1
                )
                _write_text(path, text)
    for json_name in (
        "daily_bars_backfill_batch001_workflow.json",
        "data_quality_sprint_review.json",
    ):
        path = output_dir / json_name
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            payload.setdefault("links", {})["batch001_slice001"] = href
            payload.setdefault("summary", {})["active_slice_id"] = summary["slice_id"]
            payload["summary"]["active_slice_ready_rows"] = summary["ready_rows"]
            payload["summary"]["active_slice_template_rows"] = summary["template_rows"]
            payload["summary"]["active_slice_blockers"] = summary["blockers"]
            _write_json(path, payload)


def _mirror(output_dir: Path, mirror_dirs: tuple[Path, ...], prefix: str) -> None:
    names = [path.name for path in output_dir.glob(f"{prefix}*")]
    names.extend(
        [
            "daily_bars_backfill_batch001_workflow.html",
            "daily_bars_backfill_batch001_workflow.json",
            "data_quality_sprint_review.html",
            "data_quality_sprint_review.json",
        ]
    )
    for mirror_dir in mirror_dirs:
        mirror_dir.mkdir(parents=True, exist_ok=True)
        for name in names:
            source = output_dir / name
            if source.exists():
                shutil.copy2(source, mirror_dir / name)


def _clean(value: object) -> str:
    return str(value or "").strip()


def _number(value: str) -> float | None:
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return None


def _is_date(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _is_datetime(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True
