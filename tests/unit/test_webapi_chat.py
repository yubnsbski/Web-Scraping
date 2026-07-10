from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from investment_assistant import cli
from investment_assistant.rag.chunker import chunk_text, load_document
from investment_assistant.rag.store import RagStore
from investment_assistant.webapi.service import available_routes, handle_api


def _index_kddi_doc(db_path: Path, tmp_path: Path) -> None:
    doc = tmp_path / "9433.md"
    doc.write_text(
        "# KDDI（9433） 市場データ\n"
        "特徴: 高配当（利回り≥3.5%）\n"
        "予測（統計推定・非助言）: +5営業日 4,000 円\n"
        "KDDIは通信事業を中心に安定した配当方針を維持しています。\n",
        encoding="utf-8",
    )
    document = load_document(doc)
    RagStore(db_path).upsert_document(
        document,
        chunk_text(source=document.source, text=document.text, content_hash=document.content_hash),
    )


def test_chat_turn_route_is_registered() -> None:
    assert "POST /api/chat/turn" in available_routes()


def test_chat_turn_answer_mode_happy_path_with_followup(tmp_path: Path) -> None:
    db = tmp_path / "rag.sqlite"
    _index_kddi_doc(db, tmp_path)

    messages = [
        {"role": "user", "content": "KDDIの長期保有リスク"},
        {"role": "assistant", "content": "長期保有リスクは限定的です。"},
        {"role": "user", "content": "で、配当は？"},
    ]

    status, payload = handle_api(
        "POST",
        "/api/chat/turn",
        {"messages": messages, "db_path": str(db)},
    )

    assert status == 200
    assert payload["contract"] == {"version": "chat.turn.v1", "stream_ready": True}

    message = payload["message"]
    assert message["role"] == "assistant"
    assert message["kind"] == "rag_answer"
    assert message["content"]
    assert message["citations"]
    assert message["evidence"]
    assert message["evidence"][0]["citation"] == message["citations"][0]

    meta = message["meta"]
    assert meta["mode"] == "answer"
    assert meta["llm"] is not None
    assert meta["llm"]["skipped"] is False
    assert meta["disclaimer"]
    assert meta["budget"]
    assert meta["simulation"] is None

    retrieval = meta["retrieval"]
    assert retrieval["original_query"] == "で、配当は？"
    assert retrieval["resolved_query"] != retrieval["original_query"]
    assert "9433" in retrieval["resolved_query"]
    assert retrieval["hybrid"] is True
    assert retrieval["result_count"] > 0
    assert retrieval["no_evidence"] is False


def test_chat_turn_detailed_mode_normalizes_orchestrate_output(tmp_path: Path) -> None:
    db = tmp_path / "rag.sqlite"
    _index_kddi_doc(db, tmp_path)

    messages = [{"role": "user", "content": "KDDIの配当方針について教えてください"}]

    status, payload = handle_api(
        "POST",
        "/api/chat/turn",
        {"messages": messages, "db_path": str(db), "mode": "detailed"},
    )

    assert status == 200
    message = payload["message"]
    assert message["kind"] == "orchestrate"
    assert message["content"]
    assert message["evidence"]

    meta = message["meta"]
    assert meta["mode"] == "detailed"
    assert "stock_score" in meta
    assert "forecast" in meta
    assert meta["stock_score"] is None
    assert meta["forecast"] is None
    assert meta["llm"] is not None


def test_chat_turn_zero_evidence_skips_llm(tmp_path: Path) -> None:
    db = tmp_path / "rag.sqlite"
    RagStore(db)  # empty store, no documents indexed

    status, payload = handle_api(
        "POST",
        "/api/chat/turn",
        {"messages": [{"role": "user", "content": "存在しない話題について"}], "db_path": str(db)},
    )

    assert status == 200
    message = payload["message"]
    assert message["kind"] == "no_evidence"
    assert message["content"]
    assert message["evidence"] == []
    assert message["citations"] == []

    meta = message["meta"]
    assert meta["llm"] is not None
    assert meta["llm"]["skipped"] is True
    assert meta["retrieval"]["no_evidence"] is True
    assert meta["retrieval"]["result_count"] == 0


def test_chat_turn_source_mode_web_returns_web_answer_with_fake_sources(tmp_path: Path) -> None:
    """source_mode="web", offline (call_real_api defaults False): the guarded
    path resolves to the deterministic LocalWebAnswerClient (no network), and
    the response is normalized to kind "web_answer" with URL citations.

    The query embeds a random token so its guarded-service cache key (which
    binds today's date + prompt, see GroundedLlmService) never collides with
    another test run's cached entry in the shared on-disk LLM cache -- this
    keeps the "local_template" (never "cache") assertion below deterministic.
    """

    import uuid

    db = tmp_path / "rag.sqlite"
    RagStore(db)  # unused by the web route, but keep db_path harmless

    status, payload = handle_api(
        "POST",
        "/api/chat/turn",
        {
            "messages": [
                {"role": "user", "content": f"KDDIの最新ニュースは？ ({uuid.uuid4()})"}
            ],
            "db_path": str(db),
            "source_mode": "web",
        },
    )

    assert status == 200
    message = payload["message"]
    assert message["kind"] == "web_answer"
    assert message["content"]
    assert message["citations"]
    assert all(citation.get("url") for citation in message["citations"])
    assert message["evidence"]

    meta = message["meta"]
    assert meta["disclaimer"]
    assert meta["llm"] is not None
    assert meta["llm"]["source"] == "local_template"


def test_chat_turn_invalid_source_mode_returns_400() -> None:
    status, payload = handle_api(
        "POST",
        "/api/chat/turn",
        {"messages": [{"role": "user", "content": "hi"}], "source_mode": "bogus"},
    )

    assert status == 400
    assert "source_mode" in str(payload)


def test_chat_turn_limit_is_hard_capped(tmp_path: Path) -> None:
    db = tmp_path / "rag.sqlite"
    _index_kddi_doc(db, tmp_path)

    status, payload = handle_api(
        "POST",
        "/api/chat/turn",
        {
            "messages": [{"role": "user", "content": "KDDIについて教えてください"}],
            "db_path": str(db),
            "limit": 100,
        },
    )

    assert status == 200
    assert payload["message"]["meta"]["retrieval"]["limit"] == 16


def test_chat_turn_rejects_empty_messages() -> None:
    status, payload = handle_api("POST", "/api/chat/turn", {"messages": []})
    assert status == 400
    assert "messages" in payload["error"]


def test_chat_turn_rejects_when_last_message_is_not_user() -> None:
    status, payload = handle_api(
        "POST",
        "/api/chat/turn",
        {
            "messages": [
                {"role": "user", "content": "こんにちは"},
                {"role": "assistant", "content": "ご質問はありますか？"},
            ]
        },
    )
    assert status == 400
    assert "error" in payload


def test_chat_turn_rejects_invalid_mode(tmp_path: Path) -> None:
    db = tmp_path / "rag.sqlite"
    _index_kddi_doc(db, tmp_path)

    status, payload = handle_api(
        "POST",
        "/api/chat/turn",
        {
            "messages": [{"role": "user", "content": "KDDIについて"}],
            "db_path": str(db),
            "mode": "bogus",
        },
    )
    assert status == 400
    assert "mode" in payload["error"]


def test_chat_turn_detailed_mode_zero_evidence_reports_llm_skipped(tmp_path: Path) -> None:
    db = tmp_path / "rag.sqlite"
    RagStore(db)  # empty store

    status, payload = handle_api(
        "POST",
        "/api/chat/turn",
        {
            "messages": [{"role": "user", "content": "存在しない話題について"}],
            "db_path": str(db),
            "mode": "detailed",
        },
    )

    assert status == 200
    message = payload["message"]
    assert message["kind"] == "no_evidence"
    assert message["meta"]["llm"] is not None
    assert message["meta"]["llm"]["skipped"] is True


def test_chat_turn_zero_evidence_never_invokes_llm_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hard proof: on zero evidence, no LlmService.generate call happens."""

    def _explode(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("LlmService.generate must not be called on zero evidence")

    monkeypatch.setattr("investment_assistant.llm.service.LlmService.generate", _explode)

    db = tmp_path / "rag.sqlite"
    RagStore(db)  # empty store
    for mode in ("answer", "detailed"):
        status, payload = handle_api(
            "POST",
            "/api/chat/turn",
            {
                "messages": [{"role": "user", "content": "存在しない話題について"}],
                "db_path": str(db),
                "mode": mode,
            },
        )
        assert status == 200
        assert payload["message"]["kind"] == "no_evidence"


def test_chat_turn_alpha_is_clamped_and_nan_defaults(tmp_path: Path) -> None:
    db = tmp_path / "rag.sqlite"
    _index_kddi_doc(db, tmp_path)
    base = {
        "messages": [{"role": "user", "content": "KDDIについて教えてください"}],
        "db_path": str(db),
    }

    status, payload = handle_api("POST", "/api/chat/turn", {**base, "alpha": 5.0})
    assert status == 200
    assert payload["message"]["meta"]["retrieval"]["alpha"] == 1.0

    status, payload = handle_api("POST", "/api/chat/turn", {**base, "alpha": "nan"})
    assert status == 200
    assert payload["message"]["meta"]["retrieval"]["alpha"] == 0.5


def test_chat_turn_budget_failure_degrades_to_null_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _broken_budget(*args: Any, **kwargs: Any) -> Any:
        raise FileNotFoundError("gemini config missing")

    monkeypatch.setattr(cli, "build_budget_report", _broken_budget)

    db = tmp_path / "rag.sqlite"
    _index_kddi_doc(db, tmp_path)
    status, payload = handle_api(
        "POST",
        "/api/chat/turn",
        {
            "messages": [{"role": "user", "content": "KDDIについて教えてください"}],
            "db_path": str(db),
        },
    )

    assert status == 200
    assert payload["message"]["meta"]["budget"] is None
    assert payload["message"]["content"]


def test_chat_turn_rejects_too_many_messages() -> None:
    messages = [{"role": "user", "content": f"メッセージ {i}"} for i in range(201)]
    status, payload = handle_api("POST", "/api/chat/turn", {"messages": messages})
    assert status == 400
    assert "messages" in payload["error"]


def test_chat_turn_rejects_whitespace_only_latest_turn(tmp_path: Path) -> None:
    db = tmp_path / "rag.sqlite"
    _index_kddi_doc(db, tmp_path)
    status, payload = handle_api(
        "POST",
        "/api/chat/turn",
        {"messages": [{"role": "user", "content": "   "}], "db_path": str(db)},
    )
    assert status == 400
    assert "error" in payload


def test_chat_turn_detailed_mode_splits_standalone_and_retrieval_queries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    def _fake_orchestrate(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "answer": "ダミー回答",
            "synthesis": {"text": "ダミー統合回答", "source": "local", "skipped": False},
            "results": [{"citation": {"source": "dummy.md"}, "source": "dummy.md", "text": "x"}],
            "highlights": [],
        }

    monkeypatch.setattr(cli, "run_orchestrate_answer", _fake_orchestrate)

    db = tmp_path / "rag.sqlite"
    _index_kddi_doc(db, tmp_path)
    status, payload = handle_api(
        "POST",
        "/api/chat/turn",
        {
            "messages": [
                {"role": "user", "content": "KDDIの長期保有リスク"},
                {"role": "assistant", "content": "限定的です。"},
                {"role": "user", "content": "で、配当は？"},
            ],
            "db_path": str(db),
            "mode": "detailed",
        },
    )

    assert status == 200
    # The LLM-facing question is the standalone question (ticker prefix only,
    # never transcript text); the search query carries history context.
    assert captured["query"] == "9433: で、配当は？"
    assert "9433" in captured["search_query"]
    assert "KDDIの長期保有リスク" in captured["search_query"]
    assert payload["message"]["kind"] == "orchestrate"
    assert payload["message"]["content"] == "ダミー統合回答"


def test_chat_turn_hybrid_threads_store_embedder_into_search(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: hybrid queries must embed in the corpus's stored space,
    not silently fall back to the default hashing embedder."""

    captured: dict[str, Any] = {}

    def _fake_hybrid_search(store: Any, **kwargs: Any) -> list[Any]:
        captured.update(kwargs)
        return []

    monkeypatch.setattr("investment_assistant.rag.answer.hybrid_search", _fake_hybrid_search)

    db = tmp_path / "rag.sqlite"
    _index_kddi_doc(db, tmp_path)
    status, payload = handle_api(
        "POST",
        "/api/chat/turn",
        {
            "messages": [{"role": "user", "content": "KDDIについて教えてください"}],
            "db_path": str(db),
            "hybrid": True,
        },
    )

    assert status == 200
    assert "embedder" in captured
    assert captured["embedder"] is not None


def test_chat_turn_small_talk_skips_search_and_llm(tmp_path: Path) -> None:
    db = tmp_path / "rag.sqlite"
    _index_kddi_doc(db, tmp_path)

    status, payload = handle_api(
        "POST",
        "/api/chat/turn",
        {"messages": [{"role": "user", "content": "ありがとう"}], "db_path": str(db)},
    )

    assert status == 200
    message = payload["message"]
    assert message["kind"] == "small_talk"
    assert message["citations"] == []
    assert message["evidence"] == []

    meta = message["meta"]
    assert meta["disclaimer"] == ""
    assert meta["llm"]["source"] == "local_small_talk"
    assert meta["llm"]["skipped"] is True


def test_chat_turn_call_real_api_false_stays_offline(tmp_path: Path) -> None:
    db = tmp_path / "rag.sqlite"
    _index_kddi_doc(db, tmp_path)

    # call_real_api explicitly False (also the default): completes with no
    # network access, using the deterministic local client only.
    status, payload = handle_api(
        "POST",
        "/api/chat/turn",
        {
            "messages": [{"role": "user", "content": "KDDIについて教えてください"}],
            "db_path": str(db),
            "call_real_api": False,
        },
    )

    assert status == 200
    assert payload["message"]["meta"]["llm"]["skipped"] is False
    # The offline template must be labeled honestly -- never as "gemini".
    assert payload["message"]["meta"]["llm"]["source"] == "local_template"
