"""Tests for knowledge-base snapshots and diffs (context analysis)."""

from __future__ import annotations

from pathlib import Path

from investment_assistant import cli
from investment_assistant.knowledge import (
    diff_snapshots,
    run_knowledge_diff,
    snapshot_knowledge,
)

_CSV_HEADER = "ticker,name,fiscal_year,operating_cf,equity_ratio,dividend_per_share,payout_policy\n"


def _index(tmp_path: Path, *files: tuple[str, str]) -> Path:
    root = tmp_path / "edinet"
    for relpath, text in files:
        path = root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    db = tmp_path / "rag.sqlite"
    cli.run_rag_index_dir(path=str(root), db_path=str(db), content_only=False)
    return db


def _csv(tmp_path: Path, rows: str, name: str = "financials.csv") -> Path:
    path = tmp_path / name
    path.write_text(_CSV_HEADER + rows, encoding="utf-8")
    return path


def test_snapshot_captures_rag_and_financials(tmp_path: Path) -> None:
    db = _index(tmp_path, ("8306/a.txt", "三菱UFJ 配当方針 配当性向 40%"))
    csv = _csv(
        tmp_path,
        "8306,MUFG,2023,1000,5.0,32,安定配当\n8306,MUFG,2024,1100,5.2,41,安定配当\n",
    )
    snap = snapshot_knowledge(db_path=str(db), financials_csv=str(csv))
    assert snap["rag"]["sources"] == 1  # type: ignore[index]
    assert snap["rag"]["chunks"] >= 1  # type: ignore[index]
    assert snap["financials"]["8306"]["periods"] == 2  # type: ignore[index]
    assert snap["financials"]["8306"]["dividend_per_share"] == 41.0  # type: ignore[index]


def test_diff_detects_new_source_and_dividend_change(tmp_path: Path) -> None:
    prev = snapshot_knowledge(
        db_path=str(_index(tmp_path / "a", ("8306/a.txt", "配当"))),
        financials_csv=str(_csv(tmp_path / "a", "8306,MUFG,2023,1000,5.0,41,安定配当\n")),
    )
    # New ticker source + a dividend cut for 8306 in 2024 + a brand-new 9432.
    curr = snapshot_knowledge(
        db_path=str(
            _index(
                tmp_path / "b",
                ("8306/a.txt", "配当"),
                ("9432/n.txt", "NTT 配当"),
            )
        ),
        financials_csv=str(
            _csv(
                tmp_path / "b",
                "8306,MUFG,2023,1000,5.0,41,安定配当\n"
                "8306,MUFG,2024,900,4.8,30,安定配当\n"
                "9432,NTT,2024,500,40,5,累進配当\n",
            )
        ),
    )
    diff = diff_snapshots(prev, curr)
    assert diff["has_changes"] is True
    assert diff["rag"]["sources_delta"] == 1  # type: ignore[index]
    changed = {str(c["ticker"]): c for c in diff["financial_changes"]}  # type: ignore[union-attr]
    assert "9432" in changed and changed["9432"]["kind"] == "new"
    fields = [str(ch["field"]) for ch in changed["8306"]["changes"]]  # type: ignore[index]
    assert "1株配当" in fields  # 41 -> 30
    assert "新規減配年" in fields  # 2024 cut now detected


def test_run_knowledge_diff_saves_and_reports_no_change_on_repeat(tmp_path: Path) -> None:
    db = _index(tmp_path, ("8306/a.txt", "配当 方針"))
    csv = _csv(tmp_path, "8306,MUFG,2024,1000,5.0,41,安定配当\n")
    snap_path = tmp_path / "snap.json"

    first = run_knowledge_diff(
        db_path=str(db), financials_csv=str(csv), snapshot_path=str(snap_path)
    )
    assert first["previous_at"] is None
    assert snap_path.is_file()

    second = run_knowledge_diff(
        db_path=str(db), financials_csv=str(csv), snapshot_path=str(snap_path)
    )
    assert second["previous_at"] is not None
    assert second["diff"]["has_changes"] is False  # type: ignore[index]
