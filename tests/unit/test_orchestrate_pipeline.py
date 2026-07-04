"""End-to-end (offline) tests for run_orchestrate_answer retrieval + drafts."""

from __future__ import annotations

from pathlib import Path

from investment_assistant import cli


def _gemini_config(tmp_path: Path) -> Path:
    config = tmp_path / "gemini.yaml"
    config.write_text(
        "\n".join(
            (
                "gemini:",
                "  enabled: true",
                "  model: test-model",
                "  daily_request_limit: 1000",
                "  monthly_request_limit: 10000",
                "  usage_db_path: " + str(tmp_path / "usage.sqlite"),
                "  cache:",
                "    enabled: true",
                "    ttl_days: 1",
                "    db_path: " + str(tmp_path / "cache.sqlite"),
                "  allowed_tasks:",
                "    - rag_answer",
                "    - important_report_summary",
            )
        ),
        encoding="utf-8",
    )
    return config


def _index_doc(tmp_path: Path) -> Path:
    docs = tmp_path / "edinet" / "8306"
    docs.mkdir(parents=True)
    (docs / "S100Y24.txt").write_text(
        "三菱UFJ 有価証券報告書 2024-03-31\n"
        "配当方針: 安定的な配当の継続を基本方針とする。\n"
        "1株当たり配当: 40円 配当性向: 30%\n",
        encoding="utf-8",
    )
    db = tmp_path / "rag.sqlite"
    cli.run_rag_index_dir(path=str(tmp_path / "edinet"), db_path=str(db), content_only=False)
    return db


def test_orchestrate_uses_orchestrator_perspectives(tmp_path: Path) -> None:
    db = _index_doc(tmp_path)
    payload = cli.run_orchestrate_answer(
        query="配当 方針 配当性向",
        config_path=_gemini_config(tmp_path),
        db_path=str(db),
        limit=8,
        drafts=3,
        hybrid=True,
    )
    assert not payload.get("skipped")
    assert len(payload["results"]) >= 1  # type: ignore[arg-type]
    assert payload["perspectives"] == [
        "配当・財務安全性",
        "下落リスク・競争環境",
        "NISA長期保有・分散",
    ]


def test_orchestrate_search_query_drives_retrieval(tmp_path: Path) -> None:
    db = _index_doc(tmp_path)
    # The generation query has no document terms; retrieval must use search_query.
    payload = cli.run_orchestrate_answer(
        query="【財務根拠】減配年: 2024 / 営業CF 増加傾向",
        search_query="配当 方針",
        config_path=_gemini_config(tmp_path),
        db_path=str(db),
        limit=8,
        hybrid=True,
    )
    assert not payload.get("skipped")
    assert len(payload["results"]) >= 1  # type: ignore[arg-type]
