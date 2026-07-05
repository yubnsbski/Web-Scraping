from __future__ import annotations

import json
from pathlib import Path

from investment_assistant.webapi.source_drift_audit import (
    SourceDriftAuditConfig,
    build_source_drift_audit,
)


def _write_sources(root: Path) -> dict[str, Path]:
    reference = root / "domestic_universe.csv"
    reference.write_text(
        "ticker,name,segment\n"
        "1301,Kyokuyo,Prime\n"
        "1302,Missing Source,Standard\n",
        encoding="utf-8",
    )
    cleaned = root / "ticker_data_map.csv"
    cleaned.write_text(
        "ticker,name,segment,current_price,dividend_yield_pct\n"
        "1301,Kyokuyo,Prime,100,1.0\n"
        "1302,Missing Source,Standard,,\n",
        encoding="utf-8",
    )
    current_prices = root / "current_prices.csv"
    current_prices.write_text(
        "ticker,price,as_of\n"
        "1301,100,2026-07-01\n"
        "9999,10,2026-07-01\n"
        "9999,11,2026-07-02\n",
        encoding="utf-8",
    )
    market_financials = root / "yahoo_financials.csv"
    market_financials.write_text(
        "ticker,name,price\n"
        "1301,Kyokuyo,100\n"
        "1302,Missing Source,200\n",
        encoding="utf-8",
    )
    return {
        "reference": reference,
        "cleaned": cleaned,
        "current_prices": current_prices,
        "market_financials": market_financials,
    }


def test_source_drift_audit_reports_raw_extra_missing_and_duplicates(
    tmp_path: Path,
) -> None:
    paths = _write_sources(tmp_path)
    output_dir = tmp_path / "public"
    mirror_dir = tmp_path / "mirror"

    payload = build_source_drift_audit(
        SourceDriftAuditConfig(
            output_dir=output_dir,
            reference_universe_path=paths["reference"],
            cleaned_map_path=paths["cleaned"],
            current_prices_path=paths["current_prices"],
            market_financials_path=paths["market_financials"],
            mirror_dirs=(mirror_dir,),
            generated_at="2026-07-05T00:00:00+09:00",
        )
    )

    assert payload["status"] == "needs_attention"
    assert payload["summary"]["reference_count"] == 2
    assert payload["summary"]["cleaned_map_matches_reference"] is True
    assert payload["summary"]["source_with_drift_count"] == 1
    assert payload["summary"]["total_extra_ticker_count"] == 1
    assert payload["summary"]["total_missing_ticker_count"] == 1
    assert payload["summary"]["total_duplicate_ticker_count"] == 1
    assert payload["summary"]["action_candidate_count"] == 3
    assert payload["summary"]["action_queue_complete"] is True
    assert payload["summary"]["external_fetch_executed"] is False
    assert payload["summary"]["auto_trading"] is False

    current = {item["source_id"]: item for item in payload["sources"]}["current_prices"]
    assert current["extra_ticker_sample"] == ["9999"]
    assert current["missing_ticker_sample"] == ["1302"]
    assert current["duplicate_ticker_sample"] == ["9999"]

    queue_keys = {(row["issue_type"], row["ticker"]) for row in payload["action_queue"]}
    assert ("extra_ticker", "9999") in queue_keys
    assert ("missing_ticker", "1302") in queue_keys
    assert ("duplicate_ticker", "9999") in queue_keys

    raw_json = (output_dir / "source_drift_audit.json").read_text(encoding="utf-8")
    assert all(ord(character) < 128 for character in raw_json)
    assert json.loads(raw_json)["title"] == "Source Drift Audit"
    assert "Source Drift Audit" in (
        output_dir / "source_drift_audit.html"
    ).read_text(encoding="utf-8")

    for suffix in ("json", "csv", "html", "md"):
        filename = f"source_drift_audit.{suffix}"
        assert (output_dir / filename).exists()
        assert (mirror_dir / filename).exists()
        assert (output_dir / filename).read_bytes() == (mirror_dir / filename).read_bytes()


def test_source_drift_action_queue_uses_full_issue_lists_not_samples(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "domestic_universe.csv"
    reference.write_text(
        "ticker,name,segment\n"
        + "".join(f"{1000 + index},Ref{index},Prime\n" for index in range(12)),
        encoding="utf-8",
    )
    cleaned = tmp_path / "ticker_data_map.csv"
    cleaned.write_text(
        "ticker,name,segment\n"
        + "".join(f"{1000 + index},Ref{index},Prime\n" for index in range(12)),
        encoding="utf-8",
    )
    current_prices = tmp_path / "current_prices.csv"
    current_prices.write_text(
        "ticker,price,as_of\n"
        + "".join(f"{2000 + index},100,2026-07-01\n" for index in range(12)),
        encoding="utf-8",
    )
    market_financials = tmp_path / "yahoo_financials.csv"
    market_financials.write_text(
        "ticker,name,price\n"
        + "".join(f"{1000 + index},Ref{index},100\n" for index in range(12)),
        encoding="utf-8",
    )

    payload = build_source_drift_audit(
        SourceDriftAuditConfig(
            output_dir=tmp_path / "public",
            reference_universe_path=reference,
            cleaned_map_path=cleaned,
            current_prices_path=current_prices,
            market_financials_path=market_financials,
            generated_at="2026-07-05T00:00:00+09:00",
        )
    )

    assert payload["summary"]["total_extra_ticker_count"] == 12
    assert payload["summary"]["total_missing_ticker_count"] == 12
    assert payload["summary"]["action_candidate_count"] == 24
    assert payload["summary"]["action_queue_count"] == 24
    assert payload["summary"]["action_queue_complete"] is True

    queue_keys = {(row["issue_type"], row["ticker"]) for row in payload["action_queue"]}
    assert ("extra_ticker", "2011") in queue_keys
    assert ("missing_ticker", "1011") in queue_keys
