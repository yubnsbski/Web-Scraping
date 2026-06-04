from __future__ import annotations

import json

from investment_assistant.cli import build_budget_report, main, run_smoke


def write_config(tmp_path):
    config_path = tmp_path / "gemini.yaml"
    config_path.write_text(
        f"""
gemini:
  enabled: true
  model: gemini-test
  daily_request_limit: 5
  monthly_request_limit: 20
  warning_threshold_ratio: 0.8
  hard_stop_threshold_ratio: 1.0
  usage_db_path: {tmp_path / "usage.sqlite"}
  cache:
    enabled: true
    ttl_days: 30
    db_path: {tmp_path / "cache.sqlite"}
  fallback:
    on_daily_limit: local_summary
    on_monthly_limit: skip_llm
    on_error: cached_or_skip
  allowed_tasks:
    - rag_answer
  blocked_tasks: []
""",
        encoding="utf-8",
    )
    return config_path


def test_build_budget_report_does_not_call_gemini(tmp_path):
    config_path = write_config(tmp_path)

    report = build_budget_report(config_path)

    assert report.model == "gemini-test"
    assert report.daily_used == 0
    assert report.daily_remaining == 5


def test_run_smoke_uses_guarded_service_with_echo_client(tmp_path):
    config_path = write_config(tmp_path)

    result = run_smoke(config_path=config_path, prompt="hello")

    assert result["text"] == "[smoke:gemini-test] hello"
    assert result["source"] == "gemini"
    assert result["skipped"] is False


def test_cli_budget_json_outputs_report(tmp_path, capsys):
    config_path = write_config(tmp_path)

    exit_code = main(["--config", str(config_path), "budget", "--json"])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["model"] == "gemini-test"
    assert output["daily_used"] == 0


def test_cli_smoke_outputs_json(tmp_path, capsys):
    config_path = write_config(tmp_path)

    exit_code = main(["--config", str(config_path), "smoke", "--prompt", "hello"])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["text"] == "[smoke:gemini-test] hello"


def test_cli_gemini_live_requires_explicit_acknowledgement(tmp_path, capsys):
    config_path = write_config(tmp_path)

    exit_code = main(
        [
            "--config",
            str(config_path),
            "gemini-live",
            "--prompt",
            "hello",
        ]
    )

    assert exit_code == 2
    assert "--call-real-api" in capsys.readouterr().out


def test_cli_fetch_url_dry_run_outputs_json(monkeypatch, capsys):
    class FakeFetcher:
        def fetch(self, url: str, *, dry_run: bool, preview_chars: int):
            from investment_assistant.ingestion.fetcher import FetchResult

            assert url == "https://example.com/funds"
            assert dry_run is True
            assert preview_chars == 120
            return FetchResult(
                url=url,
                status_code=None,
                source="dry_run",
                allowed_by_robots=True,
                robots_url="https://example.com/robots.txt",
                bytes_read=0,
                content_type=None,
                text_preview=None,
                dry_run=True,
            )

    monkeypatch.setattr("investment_assistant.cli.SafeFetcher", FakeFetcher)

    exit_code = main(
        [
            "fetch-url",
            "--url",
            "https://example.com/funds",
            "--dry-run",
            "--preview-chars",
            "120",
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["source"] == "dry_run"
    assert output["allowed_by_robots"] is True


def test_cli_rag_index_search_and_context(tmp_path, capsys):
    db_path = tmp_path / "rag.sqlite"
    doc_path = tmp_path / "memo.md"
    doc_path.write_text(
        "投資判断はユーザーが行います。\n自動売買は行いません。",
        encoding="utf-8",
    )

    index_exit = main(
        [
            "rag-index",
            "--path",
            str(doc_path),
            "--db-path",
            str(db_path),
        ]
    )
    assert index_exit == 0
    index_output = json.loads(capsys.readouterr().out)
    assert index_output["chunks_indexed"] == 1

    search_exit = main(
        [
            "rag-search",
            "--query",
            "投資判断",
            "--db-path",
            str(db_path),
        ]
    )
    assert search_exit == 0
    search_output = json.loads(capsys.readouterr().out)
    assert search_output[0]["source"] == str(doc_path)

    context_exit = main(
        [
            "rag-answer-context",
            "--query",
            "自動売買",
            "--db-path",
            str(db_path),
        ]
    )
    assert context_exit == 0
    context_output = json.loads(capsys.readouterr().out)
    assert "自動売買" in context_output["context"]


def test_cli_scoring_rank_outputs_guarded_report(tmp_path, capsys):
    csv_path = tmp_path / "funds.csv"
    csv_path.write_text(
        "name,expense_ratio,annual_return,volatility,diversification_score\n"
        "低コスト全世界株式,0.12,0.065,0.18,0.95\n"
        "高コストテーマ型,1.20,0.080,0.35,0.45\n"
        "債券バランス型,0.35,0.030,0.08,0.80\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "scoring-rank",
            "--path",
            str(csv_path),
            "--limit",
            "2",
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["call_real_api"] is False
    assert output["auto_trading"] is False
    assert len(output["results"]) == 2
    assert output["results"][0]["name"] == "低コスト全世界株式"
    assert "投資助言" in output["disclaimer"]


def test_cli_scoring_validate_outputs_valid_json(tmp_path, capsys):
    csv_path = tmp_path / "funds.csv"
    csv_path.write_text(
        "name,expense_ratio,annual_return,volatility,diversification_score\n"
        "低コスト全世界株式,0.12,0.065,0.18,0.95\n"
        "高コストテーマ型,1.20,0.080,0.35,0.45\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "scoring-validate",
            "--path",
            str(csv_path),
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["valid"] is True
    assert output["rows"] == 2
    assert output["warnings"] == []
    assert output["call_real_api"] is False
    assert output["auto_trading"] is False


def test_cli_scoring_validate_outputs_errors_for_invalid_csv(tmp_path, capsys):
    csv_path = tmp_path / "funds.csv"
    csv_path.write_text(
        "name,expense_ratio,annual_return,volatility,diversification_score\n"
        ",0.12,0.065,0.18,0.95\n"
        "BadDiversification,0.1,0.05,0.2,1.2\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "scoring-validate",
            "--path",
            str(csv_path),
        ]
    )

    assert exit_code == 1
    output = json.loads(capsys.readouterr().out)
    assert output["valid"] is False
    assert output["rows"] == 2
    assert len(output["errors"]) == 2
    assert any("name is required" in error for error in output["errors"])
    assert any(
        "diversification_score must be between 0 and 1" in error for error in output["errors"]
    )
