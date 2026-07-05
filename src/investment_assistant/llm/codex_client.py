"""Codex CLI (``codex exec``) client used only for the critic role.

This module is the only place that shells out to the Codex CLI. It is
reachable only through ``LlmService`` (see ``llm/factory.py``'s
``build_codex_service``), so cache, budget, and fallback controls always
apply before any process is spawned. Unit tests must never spawn a real
subprocess -- they patch ``subprocess.Popen`` in this module instead.

Compliance note: this client only ever invokes the local ``codex exec`` CLI
via subprocess. It never extracts or reuses a ChatGPT OAuth token, and never
calls a ChatGPT/OpenAI HTTP API directly -- see AGENTS.md's Codex provider
rules.
"""

from __future__ import annotations

import contextlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Final

# Prepended to every prompt sent to Codex. The live spike confirmed this
# instruction keeps Codex a text-only critic: no tool use, no file reads, no
# command execution, even though ``--sandbox read-only`` also constrains it.
CONTAINMENT_HEADER: Final[str] = (
    "あなたはテキストのみで回答する批評担当です。"
    "ツールの使用・ファイルの読み取り・コマンド実行は一切禁止です。"
)

DEFAULT_TIMEOUT_S: Final[int] = 180

_RATE_LIMIT_PATTERN = re.compile(
    r"rate limit|usage limit|quota|429|too many requests|limit reached", re.IGNORECASE
)
_AUTH_PATTERN = re.compile(r"401|unauthorized|not logged in|codex login", re.IGNORECASE)


class CodexUnavailableError(RuntimeError):
    """Raised when the Codex CLI cannot answer; carries a classified reason.

    ``reason`` is one of ``rate_limit``, ``auth``, ``timeout``, or ``error``.
    ``LlmService`` reads this attribute (duck-typed, no import needed there) to
    decide whether to put the provider into cooldown and to build the
    ``fallback:<mode>:<reason>`` source label.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def classify_codex_error(text: str) -> str:
    """Classify Codex CLI output/stderr text into a coarse error reason."""

    if _RATE_LIMIT_PATTERN.search(text):
        return "rate_limit"
    if _AUTH_PATTERN.search(text):
        return "auth"
    return "error"


def build_codex_argv(exe: str, model: str | None, output_path: str | Path) -> list[str]:
    """Build the ``codex exec`` argv. Pure/no-exec so it is directly unit-testable.

    ``model`` is omitted from the argv (CLI default is used) when it is empty
    or ``None``.
    """

    argv = [
        exe,
        "exec",
        "--ephemeral",
        "--sandbox",
        "read-only",
        "--color",
        "never",
        "--skip-git-repo-check",
        "--output-last-message",
        str(output_path),
    ]
    if model:
        argv += ["--model", model]
    argv.append("-")
    return argv


class CodexCliClient:
    """``TextGenerationClient`` backed by the local ``codex exec`` CLI.

    The binary is located via ``shutil.which`` at construction time; a missing
    binary raises immediately so the factory can treat the provider as
    disabled instead of failing later during a request.
    """

    def __init__(self, *, exe: str = "codex", timeout_s: int = DEFAULT_TIMEOUT_S) -> None:
        resolved = shutil.which(exe)
        if resolved is None:
            raise CodexUnavailableError("error")
        self.exe = resolved
        self.timeout_s = timeout_s

    def generate(self, prompt: str, *, model: str) -> str:
        """Generate text via ``codex exec``, feeding the prompt over stdin.

        Reached only through ``LlmService`` so cache/budget/fallback always
        apply first. Raises ``CodexUnavailableError`` on any failure.
        """

        full_prompt = f"{CONTAINMENT_HEADER}\n\n{prompt}"
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "codex_last_message.txt"
            argv = build_codex_argv(self.exe, model or None, output_path)
            proc = self._spawn(argv)
            try:
                stdout_bytes, stderr_bytes = proc.communicate(
                    input=full_prompt.encode("utf-8"), timeout=self.timeout_s
                )
            except subprocess.TimeoutExpired:
                self._kill_process_tree(proc.pid)
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except Exception:  # noqa: BLE001 -- best-effort cleanup only
                    pass
                raise CodexUnavailableError("timeout") from None

            stdout_text = stdout_bytes.decode("utf-8", errors="replace")
            stderr_text = stderr_bytes.decode("utf-8", errors="replace")
            combined = f"{stdout_text}\n{stderr_text}"

            if proc.returncode != 0:
                raise CodexUnavailableError(classify_codex_error(combined))

            if output_path.exists():
                text = output_path.read_text(encoding="utf-8").strip()
            else:
                text = stdout_text.strip()

            if not text:
                raise CodexUnavailableError(classify_codex_error(combined))
            return text

    def _spawn(self, argv: list[str]) -> subprocess.Popen[bytes]:
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW
        try:
            return subprocess.Popen(  # argv list, never shell=True
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=creationflags,
            )
        except OSError as exc:
            raise CodexUnavailableError("error") from exc

    @staticmethod
    def _kill_process_tree(pid: int) -> None:
        """Best-effort kill of the whole process tree after a timeout.

        ``Popen.kill()`` alone only signals the immediate child; on Windows the
        Codex CLI may have spawned children, so fall back to ``taskkill /T /F``
        to reap the whole tree.
        """

        if sys.platform != "win32":
            return
        with contextlib.suppress(OSError):
            subprocess.run(  # fixed argv, never shell=True
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
