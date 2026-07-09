"""Unit tests for ``rag/answer.py``'s blank-LLM-text fallback (see
``generate_rag_answer``): when the guarded ``LlmService`` returns empty text
(e.g. after a Gemini 503 with no successful retry), the response must carry a
deterministic Japanese message instead of an empty string, so the chat UI
never shows a blank assistant bubble.
"""

from __future__ import annotations

from pathlib import Path

from investment_assistant.llm.service import LlmResponse
from investment_assistant.rag.answer import generate_rag_answer
from investment_assistant.rag.chunker import chunk_text, load_document
from investment_assistant.rag.store import RagStore


class _FakeBlankService:
    """Duck-types ``LlmServiceProtocol.generate``, always returning blank text."""

    def __init__(self, source: str) -> None:
        self.source = source

    def generate(self, *, task_type: str, prompt: str, priority: str = "normal") -> LlmResponse:
        _ = (task_type, prompt, priority)
        return LlmResponse(text="", source=self.source, cache_key="k", warning=True)


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


def test_blank_text_transient_error_gets_non_empty_message_with_highlights(
    tmp_path: Path,
) -> None:
    db = tmp_path / "rag.sqlite"
    _index_kddi_doc(db, tmp_path)

    service = _FakeBlankService(source="fallback:local_summary:error")
    result = generate_rag_answer(
        store=RagStore(db), service=service, query="KDDIについて教えて"
    )

    answer = result["answer"]
    assert isinstance(answer, str)
    assert answer.strip() != ""
    assert "AIによる回答生成に一時的に失敗しました" in answer
    # Up to 3 highlight bullets appended.
    assert "検索で見つかった根拠の抜粋" in answer
    assert "KDDI" in answer or "9433" in answer
    # llm meta/results untouched so the UI still shows the fallback source.
    assert result["llm"] == {
        "source": "fallback:local_summary:error",
        "warning": True,
        "skipped": False,
        "cache_key": "k",
    }
    assert result["results"]


def test_blank_text_daily_limit_gets_budget_exhausted_message(tmp_path: Path) -> None:
    db = tmp_path / "rag.sqlite"
    _index_kddi_doc(db, tmp_path)

    service = _FakeBlankService(source="fallback:skip_llm:daily_limit_reached")
    result = generate_rag_answer(
        store=RagStore(db), service=service, query="KDDIについて教えて"
    )

    answer = result["answer"]
    assert "AI利用枠の上限に達したため" in answer
    assert "本日" not in answer  # wording must stay period-neutral (daily+monthly)


def test_blank_text_monthly_limit_gets_budget_exhausted_message(tmp_path: Path) -> None:
    db = tmp_path / "rag.sqlite"
    _index_kddi_doc(db, tmp_path)

    service = _FakeBlankService(source="fallback:skip_llm:monthly_limit_reached")
    result = generate_rag_answer(
        store=RagStore(db), service=service, query="KDDIについて教えて"
    )

    answer = result["answer"]
    assert "AI利用枠の上限に達したため" in answer
    assert "本日" not in answer  # wording must stay period-neutral (daily+monthly)


def test_non_blank_text_is_left_untouched(tmp_path: Path) -> None:
    db = tmp_path / "rag.sqlite"
    _index_kddi_doc(db, tmp_path)

    class _FakeOkService:
        def generate(
            self, *, task_type: str, prompt: str, priority: str = "normal"
        ) -> LlmResponse:
            _ = (task_type, prompt, priority)
            return LlmResponse(text="通常の回答テキスト", source="gemini", cache_key="k")

    result = generate_rag_answer(
        store=RagStore(db), service=_FakeOkService(), query="KDDIについて教えて"
    )

    assert result["answer"] == "通常の回答テキスト"
