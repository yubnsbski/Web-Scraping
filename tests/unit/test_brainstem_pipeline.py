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
    source_mode: str = "rag",
    db_path: str = "unused.sqlite",
    limit: int = 6,
    hybrid: bool = True,
    alpha: float = 0.5,
    call_real_api: bool = False,
) -> BrainstemRequest:
    return BrainstemRequest(
        messages=tuple(dict(m) for m in messages),
        answer_mode=answer_mode,  # type: ignore[arg-type]
        source_mode=source_mode,  # type: ignore[arg-type]
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


def test_router_source_mode_web_routes_to_web_grounded() -> None:
    router = QueryRouter()
    request = _request([{"role": "user", "content": "KDDIについて"}], source_mode="web")
    decision = router.decide(request)
    assert decision.route == "web_grounded"
    assert decision.allow_context_rewrite is False


def test_router_source_mode_web_detailed_still_routes_to_web_grounded() -> None:
    """source_mode="web" wins regardless of answer_mode -- orchestrate is a
    local-RAG-context concept, so a Web turn never reaches it."""

    router = QueryRouter()
    request = _request(
        [{"role": "user", "content": "KDDIについて"}], source_mode="web", answer_mode="detailed"
    )
    decision = router.decide(request)
    assert decision.route == "web_grounded"


def test_router_small_talk_wins_over_web_source_mode() -> None:
    router = QueryRouter()
    request = _request([{"role": "user", "content": "ありがとう"}], source_mode="web")
    decision = router.decide(request)
    assert decision.route == "small_talk"


def test_router_source_mode_auto_does_not_change_v0_routing() -> None:
    """auto's fallback behavior lives in generation.py, not the router --
    routing itself stays identical to plain "rag" for v0."""

    router = QueryRouter()
    request = _request([{"role": "user", "content": "KDDIについて"}], source_mode="auto")
    decision = router.decide(request)
    assert decision.route == "gemini_chain"


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


def test_generator_calls_web_answer_fn_for_web_grounded_route() -> None:
    captured: dict[str, Any] = {}

    def fake_web_answer(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"answer": "web fake", "results": [], "web": True}

    def fake_rag_answer(**kwargs: Any) -> dict[str, Any]:
        raise AssertionError("rag_answer_fn must not be called for the web_grounded route")

    def fake_orchestrate_answer(**kwargs: Any) -> dict[str, Any]:
        raise AssertionError("orchestrate_answer_fn must not be called for the web_grounded route")

    generator = Generator(
        rag_answer_fn=fake_rag_answer,
        orchestrate_answer_fn=fake_orchestrate_answer,
        web_answer_fn=fake_web_answer,
    )
    resolver = ContextResolver()
    request = _request([{"role": "user", "content": "KDDIについて"}], source_mode="web")
    resolved = resolver.resolve(request)
    route = RouteDecision(route="web_grounded", allow_context_rewrite=False, reason="test")

    attempt = generator.generate(request=request, resolved=resolved, route=route)

    assert attempt.route == "web_grounded"
    assert attempt.raw["answer"] == "web fake"
    assert captured == {"query": resolved.prompt_question, "call_real_api": False}


def test_generator_auto_mode_falls_back_to_web_when_rag_returns_zero_results() -> None:
    rag_calls: list[dict[str, Any]] = []
    web_calls: list[dict[str, Any]] = []

    def fake_rag_answer(**kwargs: Any) -> dict[str, Any]:
        rag_calls.append(kwargs)
        return {"answer": "no evidence", "results": []}

    def fake_web_answer(**kwargs: Any) -> dict[str, Any]:
        web_calls.append(kwargs)
        return {
            "answer": "web fallback answer",
            "results": [{"citation": {"url": "https://x"}}],
            "web": True,
        }

    generator = Generator(rag_answer_fn=fake_rag_answer, web_answer_fn=fake_web_answer)
    resolver = ContextResolver()
    request = _request([{"role": "user", "content": "存在しない話題"}], source_mode="auto")
    resolved = resolver.resolve(request)
    route = RouteDecision(route="gemini_chain", allow_context_rewrite=False, reason="test")

    attempt = generator.generate(request=request, resolved=resolved, route=route)

    assert len(rag_calls) == 1
    assert len(web_calls) == 1
    assert attempt.raw["answer"] == "web fallback answer"
    assert attempt.raw["web"] is True
    assert attempt.raw["auto_fallback"] is True


def test_generator_auto_mode_falls_back_when_answer_lacks_context() -> None:
    """結果は返っているが「コンテキスト不足」回答 → Webへフォールバックする。

    実コーパスはほぼ全クエリに数件の緩い一致を返すため、0件条件だけでは
    auto がまず発火しない（実測: 2026-07-10 の動作確認）。ガード付き
    プロンプトのマーカー文言が信頼できる無根拠シグナルになる。
    """

    web_calls: list[dict[str, Any]] = []

    def fake_rag_answer(**kwargs: Any) -> dict[str, Any]:
        return {
            "answer": "コンテキスト不足のため回答できません [1][2]",
            "results": [{"citation": {"source": "irrelevant.md"}}],
        }

    def fake_web_answer(**kwargs: Any) -> dict[str, Any]:
        web_calls.append(kwargs)
        return {"answer": "web answer", "results": [], "web": True}

    generator = Generator(rag_answer_fn=fake_rag_answer, web_answer_fn=fake_web_answer)
    resolver = ContextResolver()
    request = _request([{"role": "user", "content": "米国の直近のCPIは"}], source_mode="auto")
    resolved = resolver.resolve(request)
    route = RouteDecision(route="gemini_chain", allow_context_rewrite=False, reason="test")

    attempt = generator.generate(request=request, resolved=resolved, route=route)

    assert len(web_calls) == 1
    assert attempt.raw["auto_fallback"] is True
    assert attempt.raw["answer"] == "web answer"


def test_generator_auto_mode_with_rag_results_never_calls_web() -> None:
    def fake_rag_answer(**kwargs: Any) -> dict[str, Any]:
        return {"answer": "rag answer", "results": [{"citation": {"source": "x.md"}}]}

    def explode_web(**kwargs: Any) -> dict[str, Any]:
        raise AssertionError("web_answer_fn must not be called when rag already has results")

    generator = Generator(rag_answer_fn=fake_rag_answer, web_answer_fn=explode_web)
    resolver = ContextResolver()
    request = _request([{"role": "user", "content": "KDDIについて"}], source_mode="auto")
    resolved = resolver.resolve(request)
    route = RouteDecision(route="gemini_chain", allow_context_rewrite=False, reason="test")

    attempt = generator.generate(request=request, resolved=resolved, route=route)

    assert attempt.raw["answer"] == "rag answer"
    assert "auto_fallback" not in attempt.raw


def test_generator_plain_rag_mode_zero_results_never_calls_web() -> None:
    """source_mode="rag" (not "auto") must never trigger the web fallback."""

    def fake_rag_answer(**kwargs: Any) -> dict[str, Any]:
        return {"answer": "no evidence", "results": []}

    def explode_web(**kwargs: Any) -> dict[str, Any]:
        raise AssertionError("web_answer_fn must not be called for plain source_mode=rag")

    generator = Generator(rag_answer_fn=fake_rag_answer, web_answer_fn=explode_web)
    resolver = ContextResolver()
    request = _request([{"role": "user", "content": "存在しない話題"}], source_mode="rag")
    resolved = resolver.resolve(request)
    route = RouteDecision(route="gemini_chain", allow_context_rewrite=False, reason="test")

    attempt = generator.generate(request=request, resolved=resolved, route=route)

    assert attempt.raw["answer"] == "no evidence"


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


def test_compliance_guard_web_answer_shape_with_results() -> None:
    guard = ComplianceGuard()
    resolver = ContextResolver()
    request = _request([{"role": "user", "content": "KDDIの最新ニュースは？"}], source_mode="web")
    resolved = resolver.resolve(request)
    attempt = GenerationAttempt(
        route="web_grounded",
        raw={
            "answer": "Web回答本文",
            "results": [
                {
                    "source": "https://a.example/",
                    "text": "A社ニュース",
                    "score": None,
                    "citation": {"label": "A社ニュース", "url": "https://a.example/"},
                }
            ],
            "web": True,
            "disclaimer": "これはWeb検索に基づく調査メモです。",
            "llm": {"source": "gemini_web", "warning": False, "skipped": False, "cache_key": "k"},
        },
    )

    payload = guard.assemble(request=request, resolved=resolved, attempt=attempt)

    message = payload["message"]
    assert message["kind"] == "web_answer"
    assert message["content"] == "Web回答本文"
    assert message["citations"] == [{"label": "A社ニュース", "url": "https://a.example/"}]
    assert message["meta"]["disclaimer"] == "これはWeb検索に基づく調査メモです。"
    assert message["meta"]["retrieval"]["no_evidence"] is False


def test_compliance_guard_web_answer_with_zero_results_is_not_no_evidence() -> None:
    """A web answer with zero grounding sources is still kind "web_answer",
    never "no_evidence" -- Gemini may answer confidently with no citation."""

    guard = ComplianceGuard()
    resolver = ContextResolver()
    request = _request([{"role": "user", "content": "KDDIの最新ニュースは？"}], source_mode="web")
    resolved = resolver.resolve(request)
    attempt = GenerationAttempt(
        route="web_grounded",
        raw={
            "answer": "Web回答本文（根拠なし）",
            "results": [],
            "web": True,
            "disclaimer": "これはWeb検索に基づく調査メモです。",
            "llm": {"source": "gemini_web", "warning": False, "skipped": False, "cache_key": "k"},
        },
    )

    payload = guard.assemble(request=request, resolved=resolved, attempt=attempt)

    message = payload["message"]
    assert message["kind"] == "web_answer"
    assert message["meta"]["retrieval"]["no_evidence"] is True
    assert message["meta"]["disclaimer"] == "これはWeb検索に基づく調査メモです。"


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


def test_brainstem_service_run_turn_small_talk_never_calls_rag_or_orchestrate() -> None:
    def explode_rag(**kwargs: Any) -> dict[str, Any]:
        raise AssertionError("rag_answer_fn must not be called for small_talk")

    def explode_orchestrate(**kwargs: Any) -> dict[str, Any]:
        raise AssertionError("orchestrate_answer_fn must not be called for small_talk")

    service = BrainstemService(
        generator=Generator(
            rag_answer_fn=explode_rag, orchestrate_answer_fn=explode_orchestrate
        )
    )
    request = _request([{"role": "user", "content": "ありがとう"}])

    payload = service.run_turn(request)

    message = payload["message"]
    assert message["kind"] == "small_talk"
    assert message["citations"] == []
    assert message["evidence"] == []
    assert payload["message"]["meta"]["disclaimer"] == ""
    assert payload["message"]["meta"]["llm"]["source"] == "local_small_talk"


def test_brainstem_service_run_turn_normal_question_still_routes_to_gemini_chain() -> None:
    def fake_rag_answer(**kwargs: Any) -> dict[str, Any]:
        return {
            "answer": "fake answer",
            "results": [{"citation": {"source": "x.md"}, "text": "t"}],
            "llm": {"source": "local", "warning": None, "skipped": False, "cache_key": "k"},
        }

    service = BrainstemService(generator=Generator(rag_answer_fn=fake_rag_answer))
    request = _request([{"role": "user", "content": "KDDIについて教えて"}])

    payload = service.run_turn(request)

    assert payload["message"]["kind"] == "rag_answer"


def test_brainstem_service_run_turn_detailed_mode_small_talk_still_small_talk() -> None:
    def explode_orchestrate(**kwargs: Any) -> dict[str, Any]:
        raise AssertionError("orchestrate_answer_fn must not be called for small_talk")

    service = BrainstemService(generator=Generator(orchestrate_answer_fn=explode_orchestrate))
    request = _request([{"role": "user", "content": "ありがとう"}], answer_mode="detailed")

    payload = service.run_turn(request)

    assert payload["message"]["kind"] == "small_talk"


def test_brainstem_service_run_turn_web_source_mode_routes_to_web_answer() -> None:
    def explode_rag(**kwargs: Any) -> dict[str, Any]:
        raise AssertionError("rag_answer_fn must not be called for source_mode=web")

    def fake_web_answer(**kwargs: Any) -> dict[str, Any]:
        return {
            "answer": "Web回答",
            "results": [{"citation": {"label": "A", "url": "https://a.example/"}}],
            "web": True,
            "llm": {"source": "gemini_web", "warning": False, "skipped": False, "cache_key": "k"},
        }

    service = BrainstemService(
        generator=Generator(rag_answer_fn=explode_rag, web_answer_fn=fake_web_answer)
    )
    request = _request([{"role": "user", "content": "KDDIの最新ニュースは？"}], source_mode="web")

    payload = service.run_turn(request)

    assert payload["message"]["kind"] == "web_answer"
    assert payload["message"]["content"] == "Web回答"


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
