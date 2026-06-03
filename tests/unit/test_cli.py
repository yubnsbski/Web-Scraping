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
  usage_db_path: {tmp_path / 'usage.sqlite'}
  cache:
    enabled: true
    ttl_days: 30
    db_path: {tmp_path / 'cache.sqlite'}
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

    exit_code = main([
        "--config",
        str(config_path),
        "gemini-live",
        "--prompt",
        "hello",
    ])

    assert exit_code == 2
    assert "--call-real-api" in capsys.readouterr().out
