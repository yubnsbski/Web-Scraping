from __future__ import annotations

from investment_assistant.webapi import service as webapi_service
from investment_assistant.webapi.service import available_routes, handle_api


def test_system_diagnostics_reports_frontend_and_routes() -> None:
    status, payload = handle_api("GET", "/api/system/diagnostics")

    assert status == 200
    assert payload["status"] == "ok"
    assert payload["auto_trading"] is False
    assert payload["call_real_api"] is False
    assert payload["route_count"] == len(available_routes())
    assert payload["frontend"]["dist_path"].endswith("web\\dist") or payload["frontend"][
        "dist_path"
    ].endswith("web/dist")
    assert payload["critical_routes"]["GET /api/data/status"] is True
    assert payload["critical_routes"]["POST /api/data/status"] is True
    assert payload["critical_routes"]["GET /api/data/quality"] is True
    assert payload["critical_routes"]["POST /api/data/quality"] is True
    assert payload["critical_routes"]["GET /api/market-dashboard/status"] is True
    assert payload["critical_routes"]["POST /api/market-dashboard/status"] is True
    assert payload["critical_routes"]["POST /api/market/rag/build"] is True
    assert payload["market_dashboard"]["entry_url"] == "/market-dashboard/"
    assert payload["market_dashboard"]["auto_trading"] is False
    assert payload["market_dashboard"]["call_real_api"] is False


def test_data_status_route_supports_get_and_post(tmp_path) -> None:
    body = {
        "financials_csv": "examples/financials_sample.csv",
        "market_financials_path": str(tmp_path / "missing_market.csv"),
        "daily_bars_path": str(tmp_path / "missing_bars.csv"),
        "price_inbox_path": str(tmp_path / "missing_inbox.csv"),
        "edinet_financials_path": str(tmp_path / "missing_edinet.csv"),
        "rag_db_path": str(tmp_path / "missing.sqlite"),
        "market_log_path": str(tmp_path / "missing.log"),
    }

    get_status, get_payload = handle_api("GET", "/api/data/status", body)
    post_status, post_payload = handle_api("POST", "/api/data/status", body)

    assert get_status == 200
    assert post_status == 200
    assert get_payload["summary"]["dataset_count"] == post_payload["summary"]["dataset_count"]
    assert get_payload["auto_trading"] is False
    assert post_payload["call_real_api"] is False
    assert "GET /api/data/status" in available_routes()
    assert "POST /api/data/status" in available_routes()
    assert "GET /api/data/quality" in available_routes()
    assert "POST /api/data/quality" in available_routes()


def test_unknown_endpoint_explains_available_routes() -> None:
    status, payload = handle_api("POST", "/api/market/rag/buld")

    assert status == 404
    assert payload["kind"] == "endpoint_not_found"
    assert payload["requested"] == {"method": "POST", "path": "/api/market/rag/buld"}
    assert payload["auto_trading"] is False
    assert payload["call_real_api"] is False
    assert "POST /api/market/rag/build" in payload["available_routes"]
    assert payload["closest_routes"]
    stale_frontend_hint = "\u30d5\u30ed\u30f3\u30c8\u5074\u306e\u30b3\u30fc\u30c9\u304c\u53e4\u3044"
    assert stale_frontend_hint in payload["hint"]
    assert "/api/system/diagnostics" in payload["hint"]
    assert "\u7e5d" not in payload["hint"]


def test_market_dashboard_status_reads_static_artifacts(tmp_path, monkeypatch) -> None:
    root = tmp_path / "market-dashboard"
    root.mkdir()
    (root / "index.html").write_text("<html></html>", encoding="utf-8")
    (root / "market_dashboard_entry.html").write_text("<html></html>", encoding="utf-8")
    (root / "market_dashboard_health_check.html").write_text("<html></html>", encoding="utf-8")
    (root / "frontend_backend_api_contract_audit.html").write_text(
        "<html></html>", encoding="utf-8"
    )
    (root / "yield_refetch_workflow_status.html").write_text("<html></html>", encoding="utf-8")
    entry_json = (
        '{"status":"ready","title":"Market Dashboard",'
        '"updated_at":"2026-07-04T17:17:01+09:00",'
        '"data_status_visible":true,"data_api":"POST /api/data/status","cards":['
        '{"title":"API audit","link":"frontend_backend_api_contract_audit.html",'
        '"status":"pass","metric":"10/10"}]}'
    )
    (root / "market_dashboard_entry.json").write_text(entry_json, encoding="utf-8")
    (root / "market_dashboard_health_check.json").write_text(
        '{"status":"pass","summary":{"passed":9,"failed":0,"entry_cards":1}}',
        encoding="utf-8",
    )
    (root / "frontend_backend_api_contract_audit.json").write_text(
        '{"status":"pass","summary":{"missing":0,"safe_probe_passed":10}}',
        encoding="utf-8",
    )
    (root / "yield_refetch_workflow_status.json").write_text(
        '{"status":"ready","current_coverage_pct":6.86,"steps":[{"status":"done"}]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(webapi_service, "_market_dashboard_root", lambda: root)

    status, payload = handle_api("GET", "/api/market-dashboard/status")

    assert status == 200
    assert payload["status"] == "pass"
    assert payload["entry_url"] == "/market-dashboard/"
    assert payload["entry"]["card_count"] == 1
    assert payload["entry"]["updated_at"] == "2026-07-04T17:17:01+09:00"
    assert payload["entry"]["data_status_visible"] is True
    assert payload["entry"]["data_quality_control_visible"] is False
    assert payload["entry"]["lineage_visible"] is False
    assert payload["entry"]["data_api"] == "POST /api/data/status"
    assert payload["entry_link_status"]["frontend_backend_api_contract_audit.html"] == {
        "kind": "local_file",
        "exists": True,
    }
    assert payload["html_content_status"]["frontend_backend_api_contract_audit.html"] == {
        "exists": True,
        "mojibake": False,
        "content_ok": True,
    }
    assert payload["health"]["summary"]["passed"] == 9
    assert payload["api_contract"]["summary"]["missing"] == 0
    assert payload["workflow"]["step_count"] == 1
    assert payload["control_report"] == {
        "status": None,
        "summary": {},
        "visible_from_entry": False,
        "link": None,
    }
    assert payload["lineage"] == {
        "status": None,
        "summary": {},
        "visible_from_entry": False,
        "link": None,
    }
    assert payload["readiness_backlog"] == {
        "status": None,
        "summary": {},
        "visible_from_entry": False,
        "link": None,
    }
    assert payload["local_evidence"] == {
        "status": None,
        "summary": {},
        "visible_from_entry": False,
        "link": None,
    }
    assert payload["review_gate"] == {
        "status": None,
        "summary": {},
        "visible_from_entry": False,
        "link": None,
    }
    assert payload["warnings"] == []
    assert payload["write_to_current_yields"] is False
    assert payload["external_fetch_executed"] is False
    assert payload["auto_trading"] is False
    assert payload["call_real_api"] is False


def test_market_dashboard_status_handles_missing_artifacts(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(webapi_service, "_market_dashboard_root", lambda: tmp_path)

    status, payload = handle_api("POST", "/api/market-dashboard/status")

    assert status == 200
    assert payload["status"] == "needs_attention"
    assert payload["entry"]["card_count"] == 0
    assert payload["entry"]["data_status_visible"] is False
    assert payload["entry"]["data_api"] is None
    assert "missing market_dashboard_entry.json" in payload["warnings"]
    assert payload["static_files"]["index.html"] is False
    assert payload["auto_trading"] is False
    assert payload["call_real_api"] is False


def test_market_dashboard_status_warns_on_card_count_mismatch(tmp_path, monkeypatch) -> None:
    root = tmp_path / "market-dashboard"
    root.mkdir()
    (root / "index.html").write_text("<html></html>", encoding="utf-8")
    (root / "market_dashboard_entry.html").write_text("<html></html>", encoding="utf-8")
    (root / "market_dashboard_entry.json").write_text(
        '{"status":"ready","cards":[{"title":"one"}]}', encoding="utf-8"
    )
    (root / "market_dashboard_health_check.json").write_text(
        '{"status":"pass","summary":{"entry_cards":2}}', encoding="utf-8"
    )
    (root / "frontend_backend_api_contract_audit.json").write_text(
        '{"status":"pass","summary":{"missing":0}}', encoding="utf-8"
    )
    (root / "yield_refetch_workflow_status.json").write_text(
        '{"status":"ready","steps":[]}', encoding="utf-8"
    )
    monkeypatch.setattr(webapi_service, "_market_dashboard_root", lambda: root)

    status, payload = handle_api("GET", "/api/market-dashboard/status")

    assert status == 200
    assert payload["status"] == "needs_attention"
    assert "entry card count mismatch: entry=1 health=2" in payload["warnings"]


def test_market_dashboard_status_reports_control_report_visibility(
    tmp_path, monkeypatch
) -> None:
    root = tmp_path / "market-dashboard"
    root.mkdir()
    (root / "index.html").write_text("<html></html>", encoding="utf-8")
    (root / "market_dashboard_entry.html").write_text("<html></html>", encoding="utf-8")
    (root / "data_quality_control_report.html").write_text(
        "<html></html>", encoding="utf-8"
    )
    (root / "market_dashboard_entry.json").write_text(
        (
            '{"status":"ready","data_status_visible":true,'
            '"cards":[{"title":"Control","link":"data_quality_control_report.html"}]}'
        ),
        encoding="utf-8",
    )
    (root / "market_dashboard_health_check.json").write_text(
        '{"status":"pass","summary":{"entry_cards":1}}', encoding="utf-8"
    )
    (root / "frontend_backend_api_contract_audit.json").write_text(
        '{"status":"pass","summary":{"missing":0}}', encoding="utf-8"
    )
    (root / "yield_refetch_workflow_status.json").write_text(
        '{"status":"ready","steps":[]}', encoding="utf-8"
    )
    (root / "data_quality_control_report.json").write_text(
        (
            '{"status":"needs_attention",'
            '"summary":{"gate_count":6,"pass_count":3,'
            '"safe_data_mode":"clean_preview_only"}}'
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(webapi_service, "_market_dashboard_root", lambda: root)

    status, payload = handle_api("GET", "/api/market-dashboard/status")

    assert status == 200
    assert payload["entry"]["data_quality_control_visible"] is True
    assert payload["control_report"]["visible_from_entry"] is True
    assert payload["control_report"]["status"] == "needs_attention"
    assert payload["control_report"]["summary"]["safe_data_mode"] == "clean_preview_only"
    assert payload["static_files"]["data_quality_control_report.html"] is True
    assert payload["static_files"]["data_quality_control_report.json"] is True
    assert payload["entry_link_status"]["data_quality_control_report.html"] == {
        "kind": "local_file",
        "exists": True,
    }


def test_market_dashboard_status_reports_lineage_visibility(tmp_path, monkeypatch) -> None:
    root = tmp_path / "market-dashboard"
    root.mkdir()
    (root / "index.html").write_text("<html></html>", encoding="utf-8")
    (root / "market_dashboard_entry.html").write_text(
        '<html><a href="lineage.html">lineage</a></html>', encoding="utf-8"
    )
    (root / "lineage.html").write_text("<html></html>", encoding="utf-8")
    (root / "market_dashboard_entry.json").write_text(
        (
            '{"status":"ready","data_status_visible":true,'
            '"cards":[{"title":"API audit",'
            '"link":"frontend_backend_api_contract_audit.html"}]}'
        ),
        encoding="utf-8",
    )
    (root / "market_dashboard_health_check.json").write_text(
        '{"status":"pass","summary":{"entry_cards":1}}', encoding="utf-8"
    )
    (root / "frontend_backend_api_contract_audit.html").write_text(
        "<html></html>", encoding="utf-8"
    )
    (root / "frontend_backend_api_contract_audit.json").write_text(
        '{"status":"pass","summary":{"missing":0}}', encoding="utf-8"
    )
    (root / "yield_refetch_workflow_status.json").write_text(
        '{"status":"ready","steps":[]}', encoding="utf-8"
    )
    (root / "lineage.json").write_text(
        (
            '{"status":"needs_attention",'
            '"summary":{"node_count":11,"source_of_truth_count":3716,'
            '"safe_data_mode":"clean_preview_only"}}'
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(webapi_service, "_market_dashboard_root", lambda: root)

    status, payload = handle_api("GET", "/api/market-dashboard/status")

    assert status == 200
    assert payload["entry"]["lineage_visible"] is True
    assert payload["lineage"]["visible_from_entry"] is True
    assert payload["lineage"]["status"] == "needs_attention"
    assert payload["lineage"]["summary"]["source_of_truth_count"] == 3716
    assert payload["lineage"]["summary"]["safe_data_mode"] == "clean_preview_only"
    assert payload["lineage"]["link"] == "lineage.html"
    assert payload["static_files"]["lineage.html"] is True
    assert payload["static_files"]["lineage.json"] is True


def test_market_dashboard_status_reports_readiness_backlog(
    tmp_path, monkeypatch
) -> None:
    root = tmp_path / "market-dashboard"
    root.mkdir()
    backlog_link = "daily_bars_backfill_batch001_slice001_readiness_backlog.html"
    (root / "index.html").write_text("<html></html>", encoding="utf-8")
    (root / "market_dashboard_entry.html").write_text(
        f'<html><a href="{backlog_link}">backlog</a></html>', encoding="utf-8"
    )
    (root / backlog_link).write_text("<html></html>", encoding="utf-8")
    (root / "daily_bars_backfill_batch001_slice001_readiness_backlog.csv").write_text(
        "rank,ticker,field\n1,1419,date\n", encoding="utf-8"
    )
    (
        root
        / "daily_bars_backfill_batch001_slice001_readiness_backlog_field_summary.csv"
    ).write_text("field,missing_rows\ndate,5\n", encoding="utf-8")
    (root / "market_dashboard_entry.json").write_text(
        (
            '{"status":"ready","data_status_visible":true,'
            '"cards":[{"title":"API audit",'
            '"link":"frontend_backend_api_contract_audit.html"}]}'
        ),
        encoding="utf-8",
    )
    (root / "market_dashboard_health_check.json").write_text(
        '{"status":"pass","summary":{"entry_cards":1}}', encoding="utf-8"
    )
    (root / "frontend_backend_api_contract_audit.html").write_text(
        "<html></html>", encoding="utf-8"
    )
    (root / "frontend_backend_api_contract_audit.json").write_text(
        '{"status":"pass","summary":{"missing":0}}', encoding="utf-8"
    )
    (root / "yield_refetch_workflow_status.json").write_text(
        '{"status":"ready","steps":[]}', encoding="utf-8"
    )
    (root / "daily_bars_backfill_batch001_slice001_readiness_backlog.json").write_text(
        (
            '{"status":"blocked",'
            '"summary":{"blockers":45,"blocked_ticker_count":5,'
            '"blocked_field_count":9,"auto_trading":false,"call_real_api":false}}'
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(webapi_service, "_market_dashboard_root", lambda: root)

    status, payload = handle_api("GET", "/api/market-dashboard/status")

    assert status == 200
    assert payload["entry"]["readiness_backlog_visible"] is True
    assert payload["readiness_backlog"]["visible_from_entry"] is True
    assert payload["readiness_backlog"]["status"] == "blocked"
    assert payload["readiness_backlog"]["summary"]["blockers"] == 45
    assert payload["readiness_backlog"]["summary"]["blocked_ticker_count"] == 5
    assert payload["readiness_backlog"]["link"] == backlog_link
    assert payload["static_files"][backlog_link] is True
    assert (
        payload["static_files"][
            "daily_bars_backfill_batch001_slice001_readiness_backlog.json"
        ]
        is True
    )


def test_market_dashboard_status_reports_local_evidence(
    tmp_path, monkeypatch
) -> None:
    root = tmp_path / "market-dashboard"
    root.mkdir()
    evidence_link = "daily_bars_backfill_batch001_slice001_local_evidence.html"
    (root / "index.html").write_text("<html></html>", encoding="utf-8")
    (root / "market_dashboard_entry.html").write_text(
        f'<html><a href="{evidence_link}">evidence</a></html>', encoding="utf-8"
    )
    (root / evidence_link).write_text("<html></html>", encoding="utf-8")
    (root / "daily_bars_backfill_batch001_slice001_local_evidence.csv").write_text(
        "ticker,latest_date\n1419,2026-07-03\n", encoding="utf-8"
    )
    (root / "daily_bars_backfill_batch001_slice001_local_evidence_field_matrix.csv").write_text(
        "ticker,field\n1419,source_url\n", encoding="utf-8"
    )
    (root / "daily_bars_backfill_batch001_slice001_local_evidence_review_queue.csv").write_text(
        "ticker,date,source_url,checked_at\n1419,2026-07-03,,\n", encoding="utf-8"
    )
    (root / "market_dashboard_entry.json").write_text(
        (
            '{"status":"ready","data_status_visible":true,'
            '"cards":[{"title":"API audit",'
            '"link":"frontend_backend_api_contract_audit.html"}]}'
        ),
        encoding="utf-8",
    )
    (root / "market_dashboard_health_check.json").write_text(
        '{"status":"pass","summary":{"entry_cards":1}}', encoding="utf-8"
    )
    (root / "frontend_backend_api_contract_audit.html").write_text(
        "<html></html>", encoding="utf-8"
    )
    (root / "frontend_backend_api_contract_audit.json").write_text(
        '{"status":"pass","summary":{"missing":0}}', encoding="utf-8"
    )
    (root / "yield_refetch_workflow_status.json").write_text(
        '{"status":"ready","steps":[]}', encoding="utf-8"
    )
    (root / "daily_bars_backfill_batch001_slice001_local_evidence.json").write_text(
        (
            '{"status":"needs_attention",'
            '"summary":{"local_ohlcv_candidate_rows":5,'
            '"source_url_gap_count":5,"auto_trading":false,"call_real_api":false}}'
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(webapi_service, "_market_dashboard_root", lambda: root)

    status, payload = handle_api("GET", "/api/market-dashboard/status")

    assert status == 200
    assert payload["entry"]["local_evidence_visible"] is True
    assert payload["local_evidence"]["visible_from_entry"] is True
    assert payload["local_evidence"]["status"] == "needs_attention"
    assert payload["local_evidence"]["summary"]["local_ohlcv_candidate_rows"] == 5
    assert payload["local_evidence"]["summary"]["source_url_gap_count"] == 5
    assert payload["local_evidence"]["link"] == evidence_link
    assert payload["static_files"][evidence_link] is True
    assert (
        payload["static_files"][
            "daily_bars_backfill_batch001_slice001_local_evidence.json"
        ]
        is True
    )


def test_market_dashboard_status_reports_review_gate(tmp_path, monkeypatch) -> None:
    root = tmp_path / "market-dashboard"
    root.mkdir()
    gate_link = "daily_bars_backfill_batch001_slice001_review_gate.html"
    (root / "index.html").write_text("<html></html>", encoding="utf-8")
    (root / "market_dashboard_entry.html").write_text(
        f'<html><a href="{gate_link}">gate</a></html>', encoding="utf-8"
    )
    (root / gate_link).write_text("<html></html>", encoding="utf-8")
    (root / "daily_bars_backfill_batch001_slice001_review_gate.csv").write_text(
        "rank,ticker,field\n1,1419,source_url\n", encoding="utf-8"
    )
    (root / "daily_bars_backfill_batch001_slice001_review_gate_validation.csv").write_text(
        "ticker,status\n1419,blocked\n", encoding="utf-8"
    )
    (
        root / "daily_bars_backfill_batch001_slice001_review_gate_field_summary.csv"
    ).write_text("field,issue_count\nsource_url,5\n", encoding="utf-8")
    (root / "market_dashboard_entry.json").write_text(
        (
            '{"status":"ready","data_status_visible":true,'
            '"cards":[{"title":"API audit",'
            '"link":"frontend_backend_api_contract_audit.html"}]}'
        ),
        encoding="utf-8",
    )
    (root / "market_dashboard_health_check.json").write_text(
        '{"status":"pass","summary":{"entry_cards":1}}', encoding="utf-8"
    )
    (root / "frontend_backend_api_contract_audit.html").write_text(
        "<html></html>", encoding="utf-8"
    )
    (root / "frontend_backend_api_contract_audit.json").write_text(
        '{"status":"pass","summary":{"missing":0}}', encoding="utf-8"
    )
    (root / "yield_refetch_workflow_status.json").write_text(
        '{"status":"ready","steps":[]}', encoding="utf-8"
    )
    (root / "daily_bars_backfill_batch001_slice001_review_gate.json").write_text(
        (
            '{"status":"blocked",'
            '"summary":{"review_queue_rows":5,"blockers":15,'
            '"field_blockers":10,"copy_approval_blockers":5,'
            '"auto_trading":false,"call_real_api":false}}'
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(webapi_service, "_market_dashboard_root", lambda: root)

    status, payload = handle_api("GET", "/api/market-dashboard/status")

    assert status == 200
    assert payload["entry"]["review_gate_visible"] is True
    assert payload["review_gate"]["visible_from_entry"] is True
    assert payload["review_gate"]["status"] == "blocked"
    assert payload["review_gate"]["summary"]["blockers"] == 15
    assert payload["review_gate"]["summary"]["field_blockers"] == 10
    assert payload["review_gate"]["link"] == gate_link
    assert payload["static_files"][gate_link] is True
    assert (
        payload["static_files"]["daily_bars_backfill_batch001_slice001_review_gate.json"]
        is True
    )


def test_market_dashboard_status_warns_on_missing_entry_link(tmp_path, monkeypatch) -> None:
    root = tmp_path / "market-dashboard"
    root.mkdir()
    (root / "index.html").write_text("<html></html>", encoding="utf-8")
    (root / "market_dashboard_entry.html").write_text("<html></html>", encoding="utf-8")
    (root / "market_dashboard_entry.json").write_text(
        '{"status":"ready","cards":[{"title":"Broken","link":"missing.html"}]}',
        encoding="utf-8",
    )
    (root / "market_dashboard_health_check.json").write_text(
        '{"status":"pass","summary":{"entry_cards":1}}', encoding="utf-8"
    )
    (root / "frontend_backend_api_contract_audit.json").write_text(
        '{"status":"pass","summary":{"missing":0}}', encoding="utf-8"
    )
    (root / "yield_refetch_workflow_status.json").write_text(
        '{"status":"ready","steps":[]}', encoding="utf-8"
    )
    monkeypatch.setattr(webapi_service, "_market_dashboard_root", lambda: root)

    status, payload = handle_api("GET", "/api/market-dashboard/status")

    assert status == 200
    assert payload["status"] == "needs_attention"
    assert payload["entry_link_status"]["missing.html"] == {
        "kind": "local_file",
        "exists": False,
    }
    assert "entry link missing: Broken -> missing.html" in payload["warnings"]


def test_market_dashboard_status_warns_on_mojibake_html(tmp_path, monkeypatch) -> None:
    root = tmp_path / "market-dashboard"
    root.mkdir()
    (root / "index.html").write_text("<html></html>", encoding="utf-8")
    (root / "market_dashboard_entry.html").write_text("<html></html>", encoding="utf-8")
    (root / "bad.html").write_text("bad \u7e5d text", encoding="utf-8")
    (root / "market_dashboard_entry.json").write_text(
        '{"status":"ready","cards":[{"title":"Bad","link":"bad.html"}]}',
        encoding="utf-8",
    )
    (root / "market_dashboard_health_check.json").write_text(
        '{"status":"pass","summary":{"entry_cards":1}}', encoding="utf-8"
    )
    (root / "frontend_backend_api_contract_audit.json").write_text(
        '{"status":"pass","summary":{"missing":0}}', encoding="utf-8"
    )
    (root / "yield_refetch_workflow_status.json").write_text(
        '{"status":"ready","steps":[]}', encoding="utf-8"
    )
    monkeypatch.setattr(webapi_service, "_market_dashboard_root", lambda: root)

    status, payload = handle_api("GET", "/api/market-dashboard/status")

    assert status == 200
    assert payload["status"] == "needs_attention"
    assert payload["entry_link_status"]["bad.html"]["exists"] is True
    assert payload["html_content_status"]["bad.html"] == {
        "exists": True,
        "mojibake": True,
        "content_ok": False,
    }
    assert "html content mojibake: bad.html" in payload["warnings"]
