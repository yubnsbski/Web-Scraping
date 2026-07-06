"""History-aware helpers for stateless multi-turn RAG chat.

The web chat endpoint is stateless: the client resends the full message
history on every turn. These helpers turn that history into (1) a retrieval
string for local RAG search and (2) a single self-contained "standalone"
question for the LLM prompt -- both using pure string operations only. No
LLM calls, no I/O.
"""

from __future__ import annotations

import unicodedata
from typing import Any

from investment_assistant.rag.search import extract_query_tickers

Message = dict[str, Any]
# Post-validation shape: exactly {"role": ..., "content": ...}, both ``str``.
_ValidatedMessage = dict[str, str]

# Only the tail of a conversation matters for retrieval/standalone-question
# resolution; older turns are ignored entirely (not even validated).
_MAX_HISTORY_MESSAGES = 12
# Up to this many of the most recent *user* turns are scanned for carried
# ticker/company mentions.
_MAX_TICKER_LOOKBACK_TURNS = 3
_MAX_RETRIEVAL_CHARS = 512
_MAX_CARRIED_TURN_CHARS = 200
_FOLLOWUP_MIN_LEN = 12
_FOLLOWUP_PREFIXES = ("で", "じゃあ", "その", "それ", "あと", "なら")
_VALID_ROLES = ("user", "assistant")
# Common greetings/acknowledgements that must never be treated as
# follow-up-like (no ticker carry, no previous-turn concatenation), even
# though they are short. Compared against the NFKC-normalized, casefolded,
# stripped full message text.
_GREETINGS = frozenset(
    (
        "こんにちは",
        "こんばんは",
        "おはよう",
        "ありがとう",
        "ありがとうございます",
        "はい",
        "いいえ",
        "ok",
        "了解",
        "わかった",
        "わかりました",
        "お願いします",
        "よろしく",
    )
)


def _validate_messages(messages: list[Message]) -> list[_ValidatedMessage]:
    validated: list[_ValidatedMessage] = []
    for message in messages:
        if not isinstance(message, dict):
            raise ValueError("each message must be a dict")
        role = message.get("role")
        if role not in _VALID_ROLES:
            raise ValueError(f"invalid message role: {role!r}")
        content = message.get("content")
        if not isinstance(content, str):
            raise ValueError("message content must be a string")
        validated.append({"role": role, "content": content})
    return validated


def _windowed_messages(messages: list[Message]) -> list[_ValidatedMessage]:
    """Validate and return only the last ``_MAX_HISTORY_MESSAGES`` messages.

    Messages outside the window are ignored entirely -- they are neither
    validated nor considered by any downstream logic.
    """

    if not messages:
        raise ValueError("messages must not be empty")
    return _validate_messages(messages[-_MAX_HISTORY_MESSAGES:])


def _latest_user_text(windowed: list[_ValidatedMessage]) -> str:
    if windowed[-1]["role"] != "user":
        raise ValueError("the latest message must be from the user")
    text = windowed[-1]["content"]
    if not text.strip():
        raise ValueError("the latest user message must not be empty")
    return text


def _recent_user_turns(windowed: list[_ValidatedMessage], count: int) -> list[str]:
    """Up to ``count`` most recent user turn texts, oldest-first.

    The latest user turn (validated to be ``windowed[-1]``) is always the
    last element of the returned list.
    """

    user_texts = [message["content"] for message in windowed if message["role"] == "user"]
    return user_texts[-count:]


def _is_greeting(text: str) -> bool:
    """Whole-message greeting/acknowledgement check (NFKC + casefold)."""

    normalized = unicodedata.normalize("NFKC", text).strip().casefold()
    return normalized in _GREETINGS


def _is_followup_like(text: str) -> bool:
    """Heuristic: does ``text`` read like a short, elliptical follow-up?

    Greetings/acknowledgements are explicitly excluded -- "ありがとう" after
    a ticker question is a conversation closer, not a follow-up question.
    """

    if _is_greeting(text):
        return False
    stripped = text.strip()
    if len(stripped) < _FOLLOWUP_MIN_LEN:
        return True
    if stripped.startswith(_FOLLOWUP_PREFIXES):
        return True
    return "について" in stripped and not extract_query_tickers(stripped)


def _carried_tickers(earlier_user_turns: list[str]) -> list[str]:
    """Ordered, de-duplicated tickers mentioned in earlier (non-latest) turns."""

    seen: set[str] = set()
    ordered: list[str] = []
    for turn in earlier_user_turns:
        for ticker in sorted(extract_query_tickers(turn)):
            if ticker not in seen:
                seen.add(ticker)
                ordered.append(ticker)
    return ordered


def _history_context(
    messages: list[Message],
) -> tuple[str, list[str], list[str], bool, str | None]:
    """Shared parsing used by both public helpers.

    Returns ``(latest_text, latest_tickers, carried_tickers, is_followup,
    previous_user_text)``. A greeting/acknowledgement latest turn disables
    both ticker carry and follow-up handling entirely.
    """

    windowed = _windowed_messages(messages)
    latest_text = _latest_user_text(windowed)

    recent_turns = _recent_user_turns(windowed, _MAX_TICKER_LOOKBACK_TURNS)
    earlier_turns = recent_turns[:-1]

    latest_tickers = sorted(extract_query_tickers(latest_text))
    if _is_greeting(latest_text):
        carried: list[str] = []
        followup = False
    else:
        carried = _carried_tickers(earlier_turns) if not latest_tickers else []
        followup = _is_followup_like(latest_text)
    previous_user_text = earlier_turns[-1] if earlier_turns else None
    return latest_text, latest_tickers, carried, followup, previous_user_text


def build_retrieval_query(messages: list[Message]) -> str:
    """Build a search string for local RAG retrieval from a chat history.

    - The latest turn must be from the user and non-blank (raises
      ``ValueError`` otherwise).
    - Tickers detected in the latest turn's full (untruncated) text are
      prepended, so a ticker mentioned beyond the 512-char cap still scopes
      retrieval.
    - Tickers/companies mentioned in earlier turns (of the last 3 user turns)
      are carried forward -- prepended to the retrieval string -- only when
      the latest turn itself names no ticker.
    - When the latest turn looks like a short follow-up, the previous user
      turn's text (truncated to ~200 chars) is appended for extra context.
    - Greetings/acknowledgements ("ありがとう", "こんにちは", ...) get no
      carry and no follow-up concatenation.
    - The result is capped at 512 characters.
    """

    latest_text, latest_tickers, carried, followup, previous_user_text = _history_context(
        messages
    )

    parts: list[str] = []
    if latest_tickers:
        parts.append(" ".join(latest_tickers))
    if carried:
        parts.append(" ".join(carried))
    parts.append(latest_text)
    if followup and previous_user_text is not None:
        parts.append(previous_user_text[:_MAX_CARRIED_TURN_CHARS])

    query = " ".join(part for part in parts if part)
    return query[:_MAX_RETRIEVAL_CHARS]


def standalone_question(messages: list[Message]) -> str:
    """Build a single, self-contained question text for the LLM prompt.

    v1: the latest user turn verbatim. When it looks like a short follow-up
    and a ticker/company was carried from earlier turns, the carried tokens
    are prefixed so the question stands alone, e.g. ``"9433: で、配当は？"``.
    The prefix is derived from carried ticker tokens only -- transcript text
    from earlier turns is never included in the standalone question.
    """

    latest_text, _latest_tickers, carried, followup, _previous = _history_context(messages)
    if followup and carried:
        return f"{' '.join(carried)}: {latest_text}"
    return latest_text
