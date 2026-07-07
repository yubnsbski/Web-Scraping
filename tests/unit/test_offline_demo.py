"""Guard the offline pipeline demo so it can't silently rot."""

from __future__ import annotations

from investment_assistant import cli
from investment_assistant.demo import run_offline_demo


def test_offline_pipeline_demo_runs_clean(capsys) -> None:
    assert run_offline_demo() == 0
    out = capsys.readouterr().out
    # Each stage ran end to end: EDINET ingest -> RAG index/search -> simulator.
    assert "STAGE 1" in out and "STAGE 3" in out
    assert "financials.csv" in out
    assert "ran offline" in out


def test_demo_is_reachable_via_cli(capsys) -> None:
    assert cli.main(["demo"]) == 0
    assert "ran offline" in capsys.readouterr().out
