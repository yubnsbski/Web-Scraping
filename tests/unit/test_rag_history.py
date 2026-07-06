from __future__ import annotations

import pytest

from investment_assistant.rag.history import build_retrieval_query, standalone_question


def test_build_retrieval_query_carries_ticker_from_earlier_turn_on_followup() -> None:
    messages = [
        {"role": "user", "content": "KDDIの長期保有リスク"},
        {"role": "user", "content": "で、配当は？"},
    ]

    query = build_retrieval_query(messages)

    assert "9433" in query
    assert "KDDI" in query


def test_build_retrieval_query_does_not_carry_when_latest_turn_has_own_ticker() -> None:
    messages = [
        {"role": "user", "content": "KDDIの長期保有リスク"},
        {"role": "user", "content": "9613の配当利回りはどのくらいですか"},
    ]

    query = build_retrieval_query(messages)

    assert "9433" not in query
    assert "KDDI" not in query
    assert "9613" in query


def test_build_retrieval_query_appends_previous_turn_on_followup_without_ticker() -> None:
    messages = [
        {"role": "user", "content": "わかりました、ありがとうございます、次に進めます"},
        {"role": "assistant", "content": "承知しました。"},
        {"role": "user", "content": "じゃあ次は？"},
    ]

    query = build_retrieval_query(messages)

    assert "わかりました" in query
    assert query.startswith("じゃあ次は？")


def test_build_retrieval_query_ignores_messages_outside_12_message_window() -> None:
    history: list[dict[str, str]] = [
        {"role": "user", "content": "KDDIの配当方針を教えてください"},
    ]
    for i in range(11):
        role = "assistant" if i % 2 == 0 else "user"
        history.append({"role": role, "content": f"filler message {i} 一般的な会話"})
    history.append({"role": "user", "content": "じゃあ配当は？"})

    assert len(history) == 13
    query = build_retrieval_query(history)

    # The KDDI-mentioning turn (index 0) falls outside the last-12 window and
    # must be ignored entirely -- no ticker carry, and it never even reaches
    # validation.
    assert "9433" not in query
    assert "KDDI" not in query
    # The nearest in-window filler turn is still concatenated (follow-up).
    assert "filler message 9" in query


def test_build_retrieval_query_caps_result_at_512_chars() -> None:
    messages = [{"role": "user", "content": "あ" * 600}]

    query = build_retrieval_query(messages)

    assert len(query) == 512


def test_build_retrieval_query_raises_when_latest_message_not_user() -> None:
    messages = [
        {"role": "user", "content": "こんにちは"},
        {"role": "assistant", "content": "こんにちは、ご質問はありますか？"},
    ]

    with pytest.raises(ValueError):
        build_retrieval_query(messages)


def test_build_retrieval_query_raises_on_empty_messages() -> None:
    with pytest.raises(ValueError):
        build_retrieval_query([])


def test_build_retrieval_query_raises_on_invalid_role() -> None:
    messages = [{"role": "system", "content": "hello"}]

    with pytest.raises(ValueError):
        build_retrieval_query(messages)


def test_build_retrieval_query_greeting_gets_no_carry_or_concat() -> None:
    messages = [
        {"role": "user", "content": "KDDIの長期保有リスク"},
        {"role": "assistant", "content": "長期保有リスクは限定的です。"},
        {"role": "user", "content": "ありがとう"},
    ]

    query = build_retrieval_query(messages)

    assert query == "ありがとう"
    assert standalone_question(messages) == "ありがとう"


def test_build_retrieval_query_greeting_matches_after_nfkc_casefold() -> None:
    # Fullwidth "ＯＫ" normalizes to "ok" and must count as a greeting too.
    messages = [
        {"role": "user", "content": "KDDIの長期保有リスク"},
        {"role": "user", "content": "ＯＫ"},
    ]

    query = build_retrieval_query(messages)

    assert "9433" not in query
    assert "KDDI" not in query


def test_build_retrieval_query_keeps_latest_ticker_mentioned_beyond_cap() -> None:
    # The ticker appears only after the 512-char cap; it must still be
    # prepended so retrieval stays scoped to it.
    messages = [{"role": "user", "content": "あ" * 600 + " 9613の配当利回りは？"}]

    query = build_retrieval_query(messages)

    assert query.startswith("9613")
    assert len(query) <= 512


def test_build_retrieval_query_raises_on_whitespace_only_latest_turn() -> None:
    with pytest.raises(ValueError):
        build_retrieval_query([{"role": "user", "content": "   "}])


def test_standalone_question_is_verbatim_when_no_carry() -> None:
    messages = [{"role": "user", "content": "KDDIの配当性向は？"}]

    assert standalone_question(messages) == "KDDIの配当性向は？"


def test_standalone_question_prefixes_carried_ticker_on_followup() -> None:
    messages = [
        {"role": "user", "content": "KDDIの長期保有リスク"},
        {"role": "user", "content": "で、配当は？"},
    ]

    assert standalone_question(messages) == "9433: で、配当は？"


def test_standalone_question_raises_when_latest_message_not_user() -> None:
    messages = [
        {"role": "user", "content": "こんにちは"},
        {"role": "assistant", "content": "こんにちは、ご質問はありますか？"},
    ]

    with pytest.raises(ValueError):
        standalone_question(messages)
