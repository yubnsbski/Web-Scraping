from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from investment_assistant.llm.chain import ChainLlmService
from investment_assistant.llm.codex_client import CodexUnavailableError
from investment_assistant.llm.service import LlmService
from investment_assistant.orchestration.factory import build_orchestrator
from investment_assistant.orchestration.orchestrator import OrchestrationConfig

CONTEXT = "[1] source=memo.md chunk=0\n投資判断はユーザー本人が行います。分散投資が重要です。"


@dataclass
class FakeCodexClient:
    calls: int = 0
    raise_reason: str | None = None
    marker: str = "CODEX_MARKER critique text"

    def generate(self, prompt: str, *, model: str) -> str:
        self.calls += 1
        if self.raise_reason is not None:
            raise CodexUnavailableError(self.raise_reason)
        return self.marker


@dataclass
class RecordingGeminiClient:
    """Stage-aware fake standing in for the real Gemini call under call_real_api=True."""

    prompts: list[str] = field(default_factory=list)

    def generate(self, prompt: str, *, model: str) -> str:
        self.prompts.append(prompt)
        if "統合担当" in prompt:
            return "FINAL synthesized answer [1] 信頼度: 中"
        if "厳格なレビュアー" in prompt:
            return "重大な問題なし"
        return "DRAFT grounded answer [1]"


def _write_gemini_config(tmp_path: Path) -> Path:
    config = tmp_path / "gemini.yaml"
    config.write_text(
        "\n".join(
            (
                "gemini:",
                "  enabled: true",
                "  model: test-model",
                "  daily_request_limit: 100",
                "  monthly_request_limit: 1000",
                "  usage_db_path: " + str(tmp_path / "gemini_usage.sqlite"),
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


def _write_llm_config(tmp_path: Path, *, enabled: bool = True) -> Path:
    config = tmp_path / "llm.yaml"
    config.write_text(
        "\n".join(
            (
                "providers:",
                "  codex_cli:",
                f"    enabled: {'true' if enabled else 'false'}",
                "    exe: codex",
                '    model: ""',
                "    timeout_s: 180",
                "    usage_db_path: " + str(tmp_path / "codex_usage.sqlite"),
                "    daily_request_limit: 10",
                "    hard_stop_threshold_ratio: 1.0",
                "    cooldown_minutes: 30",
                "roles:",
                "  critic:",
                "    - codex_cli",
                "    - gemini",
                "  drafter:",
                "    - gemini",
                "  synthesizer:",
                "    - gemini",
            )
        ),
        encoding="utf-8",
    )
    return config


def test_codex_marker_propagates_through_critic_when_codex_succeeds(tmp_path: Path) -> None:
    gemini_config = _write_gemini_config(tmp_path)
    llm_config = _write_llm_config(tmp_path, enabled=True)
    gemini_client = RecordingGeminiClient()
    codex_client = FakeCodexClient()

    orchestrator = build_orchestrator(
        gemini_config,
        config=OrchestrationConfig(n_drafts=1, include_critique=True),
        client=gemini_client,
        call_real_api=True,
        llm_config_path=llm_config,
        codex_client=codex_client,
    )

    assert isinstance(orchestrator.critic, ChainLlmService)

    result = orchestrator.run(query="配当方針は?", context=CONTEXT)

    assert result.critique is not None
    assert result.critique.text == "CODEX_MARKER critique text"
    assert result.critique.source == "codex_cli"
    assert codex_client.calls == 1
    # The gemini critic prompt (厳格なレビュアー) must never have been sent,
    # since codex answered first.
    assert not any("厳格なレビュアー" in p for p in gemini_client.prompts)


def test_codex_failure_falls_back_to_gemini_critic(tmp_path: Path) -> None:
    gemini_config = _write_gemini_config(tmp_path)
    llm_config = _write_llm_config(tmp_path, enabled=True)
    gemini_client = RecordingGeminiClient()
    codex_client = FakeCodexClient(raise_reason="auth")

    orchestrator = build_orchestrator(
        gemini_config,
        config=OrchestrationConfig(n_drafts=1, include_critique=True),
        client=gemini_client,
        call_real_api=True,
        llm_config_path=llm_config,
        codex_client=codex_client,
    )

    result = orchestrator.run(query="配当方針は?", context=CONTEXT)

    assert result.critique is not None
    assert result.critique.text == "重大な問題なし"
    assert result.critique.source == "gemini"
    assert codex_client.calls == 1
    assert any("厳格なレビュアー" in p for p in gemini_client.prompts)


def test_build_orchestrator_offline_unaffected_by_codex_config(tmp_path: Path) -> None:
    """call_real_api=False must be exactly today's behavior regardless of llm.yaml."""

    gemini_config = _write_gemini_config(tmp_path)
    llm_config = _write_llm_config(tmp_path, enabled=True)

    orchestrator = build_orchestrator(
        gemini_config,
        config=OrchestrationConfig(n_drafts=1, include_critique=True),
        call_real_api=False,
        llm_config_path=llm_config,
    )

    assert type(orchestrator.critic) is LlmService
    result = orchestrator.run(query="分散投資とは?", context=CONTEXT)
    assert "統合最終回答" in result.answer


def test_build_orchestrator_identical_to_today_when_llm_config_absent(tmp_path: Path) -> None:
    """Absent config/llm.yaml -> pure-Gemini critic even with call_real_api=True."""

    gemini_config = _write_gemini_config(tmp_path)
    missing_llm_config = tmp_path / "does-not-exist.yaml"
    gemini_client = RecordingGeminiClient()

    orchestrator = build_orchestrator(
        gemini_config,
        config=OrchestrationConfig(n_drafts=1, include_critique=True),
        client=gemini_client,
        call_real_api=True,
        llm_config_path=missing_llm_config,
    )

    assert type(orchestrator.critic) is LlmService

    result = orchestrator.run(query="配当方針は?", context=CONTEXT)
    assert result.critique is not None
    assert result.critique.text == "重大な問題なし"
    assert result.critique.source == "gemini"


def test_build_orchestrator_unaffected_when_codex_disabled(tmp_path: Path) -> None:
    gemini_config = _write_gemini_config(tmp_path)
    llm_config = _write_llm_config(tmp_path, enabled=False)
    gemini_client = RecordingGeminiClient()

    orchestrator = build_orchestrator(
        gemini_config,
        config=OrchestrationConfig(n_drafts=1, include_critique=True),
        client=gemini_client,
        call_real_api=True,
        llm_config_path=llm_config,
    )

    assert type(orchestrator.critic) is LlmService
