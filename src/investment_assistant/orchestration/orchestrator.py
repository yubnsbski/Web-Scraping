"""Multi-model orchestration pipeline: draft -> critique -> synthesize."""

from __future__ import annotations

from dataclasses import dataclass, field

from investment_assistant.llm.service import LlmResponse, LlmService
from investment_assistant.observability import get_logger
from investment_assistant.orchestration.prompts import (
    DISCLAIMER,
    critique_prompt,
    draft_prompt,
    synthesis_prompt,
)

_logger = get_logger("orchestration")

DRAFT_TASK_TYPE = "rag_answer"
CRITIQUE_TASK_TYPE = "important_report_summary"
SYNTHESIS_TASK_TYPE = "rag_answer"

# Default perspectives used to diversify self-consistency drafts.
_DEFAULT_PERSPECTIVES = (
    "コスト・手数料の観点",
    "リスク・ボラティリティの観点",
    "分散・長期保有の観点",
)


@dataclass(frozen=True)
class RoleModels:
    """Model id assigned to each pipeline role (may all be the same)."""

    drafter: str
    critic: str
    synthesizer: str


DEFAULT_ROLE_MODELS = RoleModels(
    drafter="gemini-2.0-flash",
    critic="gemini-2.0-flash",
    synthesizer="gemini-2.0-flash",
)


@dataclass(frozen=True)
class OrchestrationConfig:
    """Pipeline behavior configuration."""

    n_drafts: int = 1
    include_critique: bool = True
    perspectives: tuple[str, ...] = _DEFAULT_PERSPECTIVES


@dataclass
class StageResult:
    """One pipeline stage's text plus guarded-service metadata."""

    role: str
    text: str
    source: str
    warning: bool
    skipped: bool
    cache_key: str

    @classmethod
    def from_response(cls, role: str, response: LlmResponse) -> StageResult:
        return cls(
            role=role,
            text=response.text,
            source=response.source,
            warning=response.warning,
            skipped=response.skipped,
            cache_key=response.cache_key,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "role": self.role,
            "text": self.text,
            "source": self.source,
            "warning": self.warning,
            "skipped": self.skipped,
            "cache_key": self.cache_key,
        }


@dataclass
class OrchestrationResult:
    """Full pipeline output."""

    query: str
    answer: str
    drafts: list[StageResult] = field(default_factory=list)
    critique: StageResult | None = None
    synthesis: StageResult | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "query": self.query,
            "answer": self.answer,
            "drafts": [draft.to_dict() for draft in self.drafts],
            "critique": None if self.critique is None else self.critique.to_dict(),
            "synthesis": None if self.synthesis is None else self.synthesis.to_dict(),
            "disclaimer": DISCLAIMER,
        }


class MultiModelOrchestrator:
    """Coordinate drafter/critic/synthesizer LlmServices over shared guards."""

    def __init__(
        self,
        *,
        drafter: LlmService,
        critic: LlmService,
        synthesizer: LlmService,
        config: OrchestrationConfig | None = None,
    ) -> None:
        self.drafter = drafter
        self.critic = critic
        self.synthesizer = synthesizer
        self.config = config or OrchestrationConfig()
        if self.config.n_drafts < 1:
            msg = "n_drafts must be at least 1"
            raise ValueError(msg)

    def run(self, *, query: str, context: str) -> OrchestrationResult:
        """Run draft(s) -> optional critique -> synthesis and return all stages."""

        drafts = self._draft(query=query, context=context)
        result = OrchestrationResult(query=query, answer="", drafts=drafts)

        draft_texts = [draft.text for draft in drafts if draft.text.strip()]
        if not draft_texts:
            result.answer = drafts[-1].text if drafts else ""
            _logger.warning("orchestration produced no usable drafts query_len=%d", len(query))
            return result

        critique_text = ""
        if self.config.include_critique:
            critique_response = self.critic.generate(
                task_type=CRITIQUE_TASK_TYPE,
                prompt=critique_prompt(query=query, context=context, drafts=draft_texts),
            )
            result.critique = StageResult.from_response("critic", critique_response)
            critique_text = critique_response.text

        synthesis_response = self.synthesizer.generate(
            task_type=SYNTHESIS_TASK_TYPE,
            prompt=synthesis_prompt(
                query=query,
                context=context,
                drafts=draft_texts,
                critique=critique_text or "重大な問題なし",
            ),
        )
        result.synthesis = StageResult.from_response("synthesizer", synthesis_response)
        # Prefer the synthesized answer; fall back to the first draft if skipped.
        result.answer = synthesis_response.text or draft_texts[0]
        if (
            result.answer
            and "統合最終回答" not in result.answer
            and not result.answer.startswith("FINAL")
        ):
            result.answer = f"統合最終回答\\n\\n{result.answer}"
        _logger.info(
            "orchestration done drafts=%d critique=%s synthesis_source=%s",
            len(draft_texts),
            self.config.include_critique,
            synthesis_response.source,
        )
        return result

    def _draft(self, *, query: str, context: str) -> list[StageResult]:
        drafts: list[StageResult] = []
        for index in range(self.config.n_drafts):
            perspective = self._perspective(index)
            response = self.drafter.generate(
                task_type=DRAFT_TASK_TYPE,
                prompt=draft_prompt(query=query, context=context, perspective=perspective),
            )
            drafts.append(StageResult.from_response("drafter", response))
        return drafts

    def _perspective(self, index: int) -> str | None:
        if self.config.n_drafts <= 1 or not self.config.perspectives:
            return None
        return self.config.perspectives[index % len(self.config.perspectives)]
