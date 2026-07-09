"""Unit tests for the small-talk heuristic (see ``brainstem/smalltalk.py``).

Pure/offline: no I/O, no network. Exercises the conservative
detect-then-reply contract used by ``QueryRouter``/``Generator`` to
short-circuit greetings/thanks/acks around search and the LLM.
"""

from __future__ import annotations

import pytest

from investment_assistant.brainstem.smalltalk import detect_small_talk, small_talk_reply


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ありがとう", "thanks"),
        ("ありがとうございます", "thanks"),
        ("どうもありがとう！", "thanks"),
        ("thank you", "thanks"),
        ("こんにちは", "greeting"),
        ("おはようございます", "greeting"),
        ("OK", "ack"),
        ("了解です", "ack"),
        ("なるほど", "ack"),
    ],
)
def test_detect_small_talk_positives(text: str, expected: str) -> None:
    assert detect_small_talk(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "KDDIの配当利回りは？",
        "ありがとう。ところで9433の配当は？",
        "配当",
        "",
        "あ" * 31,
        # QA counterexamples: substring traps that must NOT be small talk.
        "is NVDA high",
        "should I book profit",
        "NVDA outlook",
        "buy high",
        "Tokyo stocks",
        "ok now show me Tesla",
        "ありがとう、次はトヨタを見せて",
    ],
)
def test_detect_small_talk_negatives(text: str) -> None:
    assert detect_small_talk(text) is None


@pytest.mark.parametrize("category", ["thanks", "greeting", "ack"])
def test_small_talk_reply_is_non_empty_per_category(category: str) -> None:
    reply = small_talk_reply(category)
    assert isinstance(reply, str)
    assert reply.strip() != ""
