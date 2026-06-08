from __future__ import annotations

from pathlib import Path

from investment_assistant.llm.budget_guard import BudgetConfig, BudgetGuard
from investment_assistant.llm.cache import LlmCache
from investment_assistant.llm.service import LlmService
from investment_assistant.orchestration.factory import LocalOrchestrationClient, build_orchestrator
from investment_assistant.orchestration.orchestrator import (
    MultiModelOrchestrator,
    OrchestrationConfig,
)

CONTEXT = "[1] source=memo.md chunk=0\n投資判断はユーザー本人が行います。分散投資が重要です。"


def _write_config(tmp_path: Path) -> Path:
    config = tmp_path / "gemini.yaml"
    config.write_text(
        "\n".join(
            (
                "gemini:",
                "  enabled: true",
                "  model: test-model",
                "  daily_request_limit: 100",
                "  monthly_request_limit: 1000",
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


class _RecordingClient:
    """Captures prompts and returns stage-aware deterministic text."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(self, prompt: str, *, model: str) -> str:
        self.prompts.append(prompt)
        if "統合担当" in prompt:
            return "FINAL synthesized answer [1] 信頼度: 中"
        if "厳格なレビュアー" in prompt:
            return "重大な問題なし"
        return "DRAFT grounded answer [1]"


def _service(tmp_path: Path, model: str, client: object) -> LlmService:
    return LlmService(
        model=model,
        client=client,  # type: ignore[arg-type]
        cache=LlmCache(tmp_path / "c.sqlite", ttl_days=1),
        budget_guard=BudgetGuard(
            tmp_path / "u.sqlite",
            BudgetConfig(daily_request_limit=100, monthly_request_limit=1000),
        ),
    )


def test_pipeline_runs_draft_critique_synthesis(tmp_path) -> None:
    client = _RecordingClient()
    orchestrator = MultiModelOrchestrator(
        drafter=_service(tmp_path, "m-draft", client),
        critic=_service(tmp_path, "m-critic", client),
        synthesizer=_service(tmp_path, "m-synth", client),
        config=OrchestrationConfig(n_drafts=1, include_critique=True),
    )
    result = orchestrator.run(query="投資判断は誰が行う?", context=CONTEXT)

    assert result.answer.startswith("FINAL")
    assert len(result.drafts) == 1
    assert result.critique is not None
    assert result.synthesis is not None
    # drafter, critic, synthesizer each called once.
    assert len(client.prompts) == 3


def test_self_consistency_runs_multiple_drafts(tmp_path) -> None:
    client = _RecordingClient()
    orchestrator = MultiModelOrchestrator(
        drafter=_service(tmp_path, "m", client),
        critic=_service(tmp_path, "m", client),
        synthesizer=_service(tmp_path, "m", client),
        config=OrchestrationConfig(n_drafts=3, include_critique=False),
    )
    result = orchestrator.run(query="Q", context=CONTEXT)
    assert len(result.drafts) == 3
    assert result.critique is None
    assert result.synthesis is not None


def test_build_orchestrator_offline_uses_local_client(tmp_path) -> None:
    config = _write_config(tmp_path)
    orchestrator = build_orchestrator(config, config=OrchestrationConfig(n_drafts=2))
    assert isinstance(orchestrator.drafter.client, LocalOrchestrationClient)
    result = orchestrator.run(query="分散投資とは?", context=CONTEXT)
    assert result.answer.startswith("統合最終回答\n")  # real newline, not literal \n
    assert "\\n" not in result.answer
    assert result.to_dict()["disclaimer"]


def test_default_perspectives_are_investment_aligned() -> None:
    assert OrchestrationConfig().perspectives == (
        "配当・財務安全性",
        "下落リスク・競争環境",
        "NISA長期保有・分散",
    )
