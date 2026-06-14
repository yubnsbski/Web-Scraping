"""Guard the offline pipeline demo so it can't silently rot."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_demo():
    path = _REPO_ROOT / "scripts" / "demo_offline_pipeline.py"
    spec = importlib.util.spec_from_file_location("demo_offline_pipeline", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_offline_pipeline_demo_runs_clean(capsys) -> None:
    demo = _load_demo()
    assert demo.main() == 0
    out = capsys.readouterr().out
    # Each stage ran and the crawler surfaced the PDF rather than crawling it.
    assert "STAGE 1" in out and "STAGE 4" in out
    assert "kessan_tanshin.pdf" in out
    assert "ran offline" in out
