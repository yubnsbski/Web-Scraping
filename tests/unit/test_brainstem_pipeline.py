"""Unit tests for the brainstem package's stage seams (Sprint B0).

These exercise ``ContextResolver``, ``RagEvidenceRetriever``, ``QueryRouter``,
``Generator``, and ``ComplianceGuard`` directly with fakes/small local
fixtures -- separately from ``tests/unit/test_webapi_chat.py``, which locks
the end-to-end ``chat.turn.v1`` contract through the real HTTP handler and
must keep passing unmodified.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from investment_assistant.brainstem.compliance import ComplianceGuard
from investment_assistant.brainstem.context import ContextResolver
from investment_assistant.brainstem.contracts import (
    BrainstemRequest,
    GenerationAttempt,
    RouteDecision,
)
from investment_assistant.brainstem.generation import Generator
from investment_assistant.brainstem.pipeline import BrainstemService
from investment_assistant.brainstem.retrieval import RagEvidenceRetriever
from investment_assistant.brainstem.router import QueryRouter
from investment_assistant.rag.chunker import chunk_text, load_document
from investment_assistant.rag.store import RagStore


def _request(
    messages: list[dict[str, str]],
    *,
    answer_mode: str = "answer",
    db_path: str = "unused.sqlite",
    limit: int = 6,
    hybrid: bool = True,
    alpha: float = 0.5,
    call_real_api: bool = False,
) -> BrainstemRequest:
    return BrainstemRequest(
        messages=tuple(dict(m) for m in messages),
        answer_mode=answer_mode,  # type: ignore[arg-type]
        source_mode="rag",
        db_path=db_path,
        limit=limit,
        call_real_api=call_real_api,
        hybrid=hybrid,
        alpha=alpha,
    )


def _index_kddi_doc(db_path: Path, tmp_path: Path) -> None:
    doc = tmp_path / "9433.md"
    doc.write_text(
        "# KDDI（9433） 市場データ\n"
        "特徴: 高配当（利回り≥3.5%）\n"
        "KDDIは通信事業を中心に安定した配当方針を維持しています。\n",
        encoding="utf-8",
    )
    document = load_document(doc)
    RagStore(db_path).upsert_document(
        document,
        chunk_text(source=document.source, text=document.text, content_hash=document.content_hash),
    )


# --- Cache invariant (blueprint section 2, absolute rule 1) ----------------


def test_cache_invariant_prompt_question_ignores_history_text() -> None:
    """prompt_question must never contain earlier-turn transcript text --
    only the latest turn plus carried entity tokens. retrieval_query, in
    contrast, must be history-aware (it may carry prior turn text)."""

    resolver = ContextResolver()

    messages_no_history = [{"role": "user", "content": "で、配当は？"}]
    messages_with_history = [
        {"role": "user", "content": "KDDIの長期保有リスクについて詳しく教えてください"},
        {"role": "assistant", "content": "長期保有リスクは限定的です。"},
        {"role": "user", "content": "で、配当は？"},
    ]

    resolved_bare = resolver.resolve(_request(messages_no_history))
    resolved_with_history = resolver.resolve(_request(messages_with_history))

    # Same latest turn, different history -> retrieval_query differs (history-aware).
    assert resolved_bare.retrieval_query != resolved_with_history.retrieval_query
    assert "KDDI" in resolved_with_history.retrieval_query or (
        "9433" in resolved_with_history.retrieval_query
    )

    # prompt_question must not leak the earlier turn's transcript text,
    # regardless of how much history is fed in.
    assert "長期保有リスク" not in resolved_with_history.prompt_question
    assert "KDDIの長期保有リスクについて詳しく教えてください" not in (
        resolved_with_history.prompt_question
    )


def test_cache_invariant_prompt_question_is_deterministic_function_of_latest_turn() -> None:
    """Two different histories that carry the same entity token and share the
    same latest turn must produce the identical prompt_question -- proving it
    is a deterministic function of (latest turn, carried tokens) only."""

    resolver = ContextResolver()

    history_a = [
        {"role": "user", "content": "KDDIについて教えて"},
        {"role": "assistant", "content": "回答A"},
        {"role": "user", "content": "で、配当は？"},
    ]
    history_b = [
        {"role": "user", "content": "KDDI(9433)の株価水準はどうですか"},
        {"role": "assistant", "content": "全く異なる長文の回答をここに書きます。" * 5},
        {"role": "user", "content": "で、配当は？"},
    ]

    resolved_a = resolver.resolve(_request(history_a))
    resolved_b = resolver.resolve(_request(history_b))

    assert resolved_a.prompt_question == resolved_b.prompt_question
    assert resolved_a.retrieval_query != resolved_b.retrieval_query


# --- ContextResolver ---------------------------------------------------------


def test_context_resolver_rejects_non_user_latest_turn() -> None:
    resolver = ContextResolver()
    request = _request(
        [
            {"role": "user", "content": "こんにちは"},
            {"role": "assistant", "content": "ご質問はありますか？"},
        ]
    )
    with pytest.raises(ValueError):
        resolver.resolve(request)


# --- RagEvidenceRetriever -----------------------------------------------------


def test_rag_evidence_retriever_returns_evidence_items(tmp_path: Path) -> None:
    db = tmp_path / "rag.sqlite"
    _index_kddi_doc(db, tmp_path)

    retriever = RagEvidenceRetriever()
    items = retriever.retrieve(query="KDDIの配当方針", db_path=db, limit=5, hybrid=True)

    assert items
    assert all(item.source for item in items)
    assert all("citation" in item.raw for item in items)


def test_rag_evidence_retriever_empty_store_returns_no_items(tmp_path: Path) -> None:
    db = tmp_path / "rag.sqlite"
    RagStore(db)  # empty store

    retriever = RagEvidenceRetriever()
    items = retriever.retrieve(query="存在しない話題について", db_path=db, limit=5)

    assert items == []


# --- QueryRouter ---------------------------------------------------------


def test_router_routes_detailed_to_orchestrate() -> None:
    router = QueryRouter()
    decision = router.decide(_request([{"role": "user", "content": "x"}], answer_mode="detailed"))
    assert decision.route == "orchestrate"
    assert decision.allow_context_rewrite is False


def test_router_routes_answer_to_gemini_chain() -> None:
    router = QueryRouter()
    decision = router.decide(_request([{"role": "user", "content": "x"}], answer_mode="answer"))
    assert decision.route == "gemini_chain"
    assert decision.allow_context_rewrite is False


def test_route_decision_rejects_context_rewrite_on_non_local_route() -> None:
    """Absolute rule 2: only the local_ollama route may allow context rewrite."""

    with pytest.raises(ValueError):
        RouteDecision(route="gemini_chain", allow_context_rewrite=True, reason="bad")

    with pytest.raises(ValueError):
        RouteDecision(route="orchestrate", allow_context_rewrite=True, reason="bad")

    # local_ollama is allowed to rewrite; this must not raise.
    RouteDecision(route="local_ollama", allow_context_rewrite=True, reason="ok")


# --- Generator (fake injection seam) -----------------------------------------


def test_generator_calls_rag_answer_fn_for_gemini_chain_route() -> None:
    captured: dict[str, Any] = {}

    def fake_rag_answer(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"answer": "fake", "results": [{"citation": {"source": "x"}}]}

    def fake_orchestrate_answer(**kwargs: Any) -> dict[str, Any]:
        raise AssertionError("must not be called for the gemini_chain route")

    generator = Generator(
        rag_answer_fn=fake_rag_answer, orchestrate_answer_fn=fake_orchestrate_answer
    )
    resolver = ContextResolver()
    request = _request([{"role": "user", "content": "KDDIについて"}])
    resolved = resolver.resolve(request)
    route = RouteDecision(route="gemini_chain", allow_context_rewrite=False, reason="test")

    attempt = generator.generate(request=request, resolved=resolved, route=route)

    assert attempt.route == "gemini_chain"
    assert attempt.raw["answer"] == "fake"
    assert captured["query"] == resolved.prompt_question
    assert captured["retrieval_query"] == resolved.retrieval_query


def test_generator_calls_orchestrate_answer_fn_for_orchestrate_route() -> None:
    captured: dict[str, Any] = {}

    def fake_orchestrate_answer(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"answer": "fake", "synthesis": {"text": "fake synth"}, "results": []}

    generator = Generator(orchestrate_answer_fn=fake_orchestrate_answer)
    resolver = ContextResolver()
    request = _request([{"role": "user", "content": "KDDIについて"}], answer_mode="detailed")
    resolved = resolver.resolve(request)
    route = RouteDecision(route="orchestrate", allow_context_rewrite=False, reason="test")

    attempt = generator.generate(request=request, resolved=resolved, route=route)

    assert attempt.route == "orchestrate"
    assert captured["query"] == resolved.prompt_question
    assert captured["search_query"] == resolved.retrieval_query


# --- ComplianceGuard -----------------------------------------------------


def test_compliance_guard_no_evidence_shape() -> None:
    guard = ComplianceGuard()
    resolver = ContextResolver()
    request = _request([{"role": "user", "content": "存在しない話題"}])
    resolved = resolver.resolve(request)
    attempt = GenerationAttempt(
        route="gemini_chain",
        raw={"answer": "スキップしました", "results": []},
    )

    payload = guard.assemble(request=request, resolved=resolved, attempt=attempt)

    assert payload["contract"] == {"version": "chat.turn.v1", "stream_ready": True}
    message = payload["message"]
    assert message["kind"] == "no_evidence"
    assert message["evidence"] == []
    assert message["meta"]["llm"]["skipped"] is True


def test_compliance_guard_orchestrate_shape() -> None:
    guard = ComplianceGuard()
    resolver = ContextResolver()
    request = _request([{"role": "user", "content": "KDDI"}], answer_mode="detailed")
    resolved = resolver.resolve(request)
    attempt = GenerationAttempt(
        route="orchestrate",
        raw={
            "answer": "fallback",
            "synthesis": {"text": "統合回答", "source": "local", "skipped": False},
            "results": [{"citation": {"source": "x.md"}}],
        },
    )

    payload = guard.assemble(request=request, resolved=resolved, attempt=attempt)

    message = payload["message"]
    assert message["kind"] == "orchestrate"
    assert message["content"] == "統合回答"
    assert message["citations"] == [{"source": "x.md"}]


# --- BrainstemService (full pipeline with fakes) -----------------------------


def test_brainstem_service_run_turn_end_to_end_with_fake_generator() -> None:
    def fake_rag_answer(**kwargs: Any) -> dict[str, Any]:
        return {
            "answer": "fake answer",
            "results": [{"citation": {"source": "x.md"}, "text": "t"}],
            "llm": {"source": "local", "warning": None, "skipped": False, "cache_key": "k"},
        }

    service = BrainstemService(generator=Generator(rag_answer_fn=fake_rag_answer))
    request = _request([{"role": "user", "content": "KDDIについて教えて"}])

    payload = service.run_turn(request)

    assert payload["contract"]["version"] == "chat.turn.v1"
    assert payload["message"]["kind"] == "rag_answer"
    assert payload["message"]["content"] == "fake answer"
    assert payload["message"]["meta"]["retrieval"]["result_count"] == 1


def test_brainstem_service_run_turn_propagates_context_errors() -> None:
    service = BrainstemService()
    request = _request(
        [
            {"role": "user", "content": "こんにちは"},
            {"role": "assistant", "content": "ご質問はありますか？"},
        ]
    )
    with pytest.raises(ValueError):
        service.run_turn(request)
