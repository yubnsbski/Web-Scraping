from __future__ import annotations

import os

from investment_assistant.webapi.local_env import load_local_env_files


def test_load_local_env_files_loads_ignored_local_files(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("EDINET_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    (tmp_path / ".env.local").write_text(
        "\n".join(
            [
                "# local secrets are ignored by git",
                "EDINET_API_KEY=edinet-test-key",
                "GEMINI_API_KEY='gemini-test-key'",
                "invalid-key=skipped",
            ]
        ),
        encoding="utf-8",
    )

    result = load_local_env_files(tmp_path)

    assert os.environ["EDINET_API_KEY"] == "edinet-test-key"
    assert os.environ["GEMINI_API_KEY"] == "gemini-test-key"
    assert result["loaded_keys"] == ["EDINET_API_KEY", "GEMINI_API_KEY"]
    assert result["skipped_keys"] == ["invalid-key"]
    assert "edinet-test-key" not in str(result)
    assert "gemini-test-key" not in str(result)


def test_load_local_env_files_does_not_override_existing_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("EDINET_API_KEY", "already-set")
    (tmp_path / ".env").write_text("EDINET_API_KEY=from-file\n", encoding="utf-8")

    result = load_local_env_files(tmp_path)

    assert os.environ["EDINET_API_KEY"] == "already-set"
    assert result["loaded_keys"] == []
    assert result["skipped_keys"] == ["EDINET_API_KEY"]
