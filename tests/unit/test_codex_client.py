from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from investment_assistant.llm.codex_client import (
    CodexCliClient,
    CodexUnavailableError,
    build_codex_argv,
    classify_codex_error,
)


def test_build_codex_argv_without_model():
    argv = build_codex_argv("codex", None, Path("out.txt"))

    assert argv == [
        "codex",
        "exec",
        "--ephemeral",
        "--sandbox",
        "read-only",
        "--color",
        "never",
        "--skip-git-repo-check",
        "--output-last-message",
        "out.txt",
        "-",
    ]


def test_build_codex_argv_with_empty_model_omits_flag():
    argv = build_codex_argv("codex", "", Path("out.txt"))
    assert "--model" not in argv


def test_build_codex_argv_with_model():
    argv = build_codex_argv("codex", "gpt-5-codex", Path("out.txt"))

    assert argv == [
        "codex",
        "exec",
        "--ephemeral",
        "--sandbox",
        "read-only",
        "--color",
        "never",
        "--skip-git-repo-check",
        "--output-last-message",
        "out.txt",
        "--model",
        "gpt-5-codex",
        "-",
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Rate limit exceeded, try again later", "rate_limit"),
        ("You have hit your usage limit for today", "rate_limit"),
        ("quota exceeded", "rate_limit"),
        ("HTTP 429 Too Many Requests", "rate_limit"),
        ("daily limit reached", "rate_limit"),
        ("Error: 401 Unauthorized", "auth"),
        ("not logged in. Run `codex login`.", "auth"),
        ("please run codex login first", "auth"),
        ("some unexpected crash", "error"),
        ("", "error"),
    ],
)
def test_classify_codex_error(text: str, expected: str) -> None:
    assert classify_codex_error(text) == expected


def test_classify_codex_error_is_case_insensitive() -> None:
    assert classify_codex_error("RATE LIMIT EXCEEDED") == "rate_limit"
    assert classify_codex_error("NOT LOGGED IN") == "auth"


def test_codex_unavailable_error_carries_reason() -> None:
    err = CodexUnavailableError("rate_limit")
    assert err.reason == "rate_limit"
    assert str(err) == "rate_limit"


def test_construction_raises_when_binary_missing() -> None:
    with (
        patch("investment_assistant.llm.codex_client.shutil.which", return_value=None),
        pytest.raises(CodexUnavailableError) as exc_info,
    ):
        CodexCliClient(exe="codex-does-not-exist")
    assert exc_info.value.reason == "error"


def _fake_popen(*, returncode: int, stdout: bytes = b"", stderr: bytes = b"") -> MagicMock:
    proc = MagicMock()
    proc.pid = 4321
    proc.returncode = returncode
    proc.communicate.return_value = (stdout, stderr)
    return proc


def test_generate_reads_output_file_on_success(tmp_path) -> None:
    """No real subprocess is spawned: Popen is patched with a fake."""

    def fake_popen_factory(argv, **kwargs):
        # The output path is the argument right after --output-last-message.
        output_path = Path(argv[argv.index("--output-last-message") + 1])
        output_path.write_text("codex critique text", encoding="utf-8")
        return _fake_popen(returncode=0, stdout=b"", stderr=b"")

    with (
        patch("investment_assistant.llm.codex_client.shutil.which", return_value="C:/codex.exe"),
        patch(
            "investment_assistant.llm.codex_client.subprocess.Popen",
            side_effect=fake_popen_factory,
        ),
    ):
        client = CodexCliClient(exe="codex")
        result = client.generate("critique this draft", model="")

    assert result == "codex critique text"


def test_generate_raises_rate_limit_on_nonzero_exit() -> None:
    with (
        patch("investment_assistant.llm.codex_client.shutil.which", return_value="C:/codex.exe"),
        patch(
            "investment_assistant.llm.codex_client.subprocess.Popen",
            return_value=_fake_popen(returncode=1, stderr=b"Error: usage limit reached"),
        ),
    ):
        client = CodexCliClient(exe="codex")
        with pytest.raises(CodexUnavailableError) as exc_info:
            client.generate("prompt", model="")

    assert exc_info.value.reason == "rate_limit"


def test_generate_raises_auth_on_nonzero_exit() -> None:
    with (
        patch("investment_assistant.llm.codex_client.shutil.which", return_value="C:/codex.exe"),
        patch(
            "investment_assistant.llm.codex_client.subprocess.Popen",
            return_value=_fake_popen(returncode=1, stderr=b"401 Unauthorized"),
        ),
    ):
        client = CodexCliClient(exe="codex")
        with pytest.raises(CodexUnavailableError) as exc_info:
            client.generate("prompt", model="")

    assert exc_info.value.reason == "auth"


def test_generate_raises_timeout() -> None:
    proc = _fake_popen(returncode=0)
    proc.communicate.side_effect = subprocess.TimeoutExpired(cmd=["codex"], timeout=1)

    with (
        patch("investment_assistant.llm.codex_client.shutil.which", return_value="C:/codex.exe"),
        patch("investment_assistant.llm.codex_client.subprocess.Popen", return_value=proc),
        patch.object(CodexCliClient, "_kill_process_tree") as kill_tree,
    ):
        client = CodexCliClient(exe="codex")
        with pytest.raises(CodexUnavailableError) as exc_info:
            client.generate("prompt", model="")

    assert exc_info.value.reason == "timeout"
    kill_tree.assert_called_once()


def test_generate_sends_containment_header_and_prompt_over_stdin() -> None:
    captured: dict[str, bytes] = {}

    def fake_communicate(*, input: bytes, timeout: int):  # noqa: A002
        captured["input"] = input
        return b"", b""

    proc = _fake_popen(returncode=0)
    proc.communicate.side_effect = fake_communicate

    with (
        patch("investment_assistant.llm.codex_client.shutil.which", return_value="C:/codex.exe"),
        patch("investment_assistant.llm.codex_client.subprocess.Popen", return_value=proc),
    ):
        client = CodexCliClient(exe="codex")
        with pytest.raises(CodexUnavailableError):
            # stdout empty and no output file written -> raises (no text produced)
            client.generate("what do you think?", model="")

    sent = captured["input"].decode("utf-8")
    assert "ツールの使用・ファイルの読み取り・コマンド実行は一切禁止です" in sent
    assert "what do you think?" in sent
