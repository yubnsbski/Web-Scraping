"""Regression: _unique_path must never return a path that already exists.

The previous implementation appended only a second-precision timestamp without
checking the result, so two saves in the same second collided and the second
silently overwrote the first -- losing a saved report/manual doc (and its RAG
entry). The guard now disambiguates with a counter.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from investment_assistant.webapi import reports, service


class _FixedClock:
    @staticmethod
    def now(tz: object = None) -> datetime:
        return datetime(2026, 6, 18, 12, 0, 0, tzinfo=UTC)


def _check(unique_path, tmp_path: Path) -> None:
    base = tmp_path / "report.md"
    base.write_text("a", encoding="utf-8")

    first = unique_path(base)
    assert first != base and not first.exists()
    first.write_text("b", encoding="utf-8")

    # Same second as `first` -> must not collide with it.
    second = unique_path(base)
    assert second not in {base, first}
    assert not second.exists()


def test_reports_unique_path_no_same_second_collision(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(reports, "datetime", _FixedClock)
    _check(reports._unique_path, tmp_path)


def test_service_unique_path_no_same_second_collision(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(service, "datetime", _FixedClock)
    _check(service._unique_path, tmp_path)
