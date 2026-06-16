from __future__ import annotations

import os

from investment_assistant.webapi.local_env import (
    LOCAL_ENV_ROOT_ENV,
    inspect_local_env_keys,
    load_local_env_files,
)


def test_load_local_env_files_loads_ignored_local_files(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv(LOCAL_ENV_ROOT_ENV, raising=False)
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
    monkeypatch.delenv(LOCAL_ENV_ROOT_ENV, raising=False)
    monkeypatch.setenv("EDINET_API_KEY", "already-set")
    (tmp_path / ".env").write_text("EDINET_API_KEY=from-file\n", encoding="utf-8")

    result = load_local_env_files(tmp_path)

    assert os.environ["EDINET_API_KEY"] == "already-set"
    assert result["loaded_keys"] == []
    assert result["skipped_keys"] == ["EDINET_API_KEY"]


def test_load_local_env_files_checks_codex_worktree_parent(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv(LOCAL_ENV_ROOT_ENV, raising=False)
    monkeypatch.delenv("EDINET_API_KEY", raising=False)

    repo_root = tmp_path / "repo"
    worktree = repo_root / ".codex-worktrees" / "feature"
    worktree.mkdir(parents=True)
    (repo_root / ".env.local").write_text("EDINET_API_KEY=from-parent\n", encoding="utf-8")

    result = load_local_env_files(worktree)

    assert os.environ["EDINET_API_KEY"] == "from-parent"
    assert result["checked_roots"] == [str(worktree.resolve()), str(repo_root.resolve())]
    assert result["loaded_keys"] == ["EDINET_API_KEY"]
    assert "from-parent" not in str(result)


def test_load_local_env_files_honors_explicit_root(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("EDINET_API_KEY", raising=False)

    explicit_root = tmp_path / "env-root"
    explicit_root.mkdir()
    (explicit_root / ".env.local").write_text("EDINET_API_KEY=explicit\n", encoding="utf-8")
    monkeypatch.setenv(LOCAL_ENV_ROOT_ENV, str(explicit_root))

    result = load_local_env_files(tmp_path / "repo")

    assert os.environ["EDINET_API_KEY"] == "explicit"
    assert result["checked_roots"][0] == str(explicit_root.resolve())
    assert result["loaded_keys"] == ["EDINET_API_KEY"]
    assert "explicit" not in str(result)


def test_inspect_local_env_keys_reports_key_names_without_values(tmp_path) -> None:
    (tmp_path / ".env.local").write_text(
        "\n".join(
            [
                "EDINET_API_KEY=",
                "EDINET_KEY=wrong-name-value",
                "GEMINI_API_KEY=hidden",
            ]
        ),
        encoding="utf-8",
    )

    result = inspect_local_env_keys(
        ["EDINET_API_KEY"],
        tmp_path,
        include_key_contains=("EDINET",),
    )

    assert result["expected"] == [
        {
            "key": "EDINET_API_KEY",
            "present": True,
            "has_value": False,
            "valid_name": True,
        }
    ]
    assert result["related_keys"] == ["EDINET_KEY"]
    assert [entry["key"] for entry in result["entries"]] == ["EDINET_API_KEY", "EDINET_KEY"]
    assert "wrong-name-value" not in str(result)
    assert "hidden" not in str(result)
