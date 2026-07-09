"""Small-talk detection: a conservative, pure, offline heuristic.

Lets the router (see ``router.py``) short-circuit greetings/thanks/acks like
「ありがとう」 or 「こんにちは」 straight to a local canned reply instead of
burning a RAG search + Gemini call on them. False negatives (missing an
actual small-talk turn) just fall back to today's guarded RAG behavior, so
the heuristic errs toward returning ``None`` whenever a turn could plausibly
be an investment question.

Detection is whole-message based: after normalization (strip, lowercase
Latin, drop all whitespace and leading/trailing punctuation/emoji), the
ENTIRE remaining string must fully match one anchored per-category pattern.
This is what keeps substring traps out -- "is NVDA high" must not become a
greeting just because it contains "hi", and 「ありがとう、次はトヨタを見せて」
must not swallow the real request that follows the thanks.
"""

from __future__ import annotations

import re

SmallTalkCategory = str  # "thanks" | "greeting" | "ack"

_MAX_LEN = 30

# Any of these appearing anywhere in the text disqualifies it from small
# talk -- it is plausibly an investment question.
_INVESTMENT_KEYWORDS: tuple[str, ...] = (
    "株",
    "配当",
    "利回",
    "銘柄",
    "円",
    "市場",
    "投資",
    "買",
    "売",
    "ニュース",
    "予想",
    "決算",
    "指数",
    "ドル",
    "金利",
)

_DIGIT_RE = re.compile(r"\d")

# Normalization: whitespace anywhere plus punctuation/emoji at the edges are
# removed before the anchored match, so 「ありがとう！」 or "thank you." still
# match while any residual real content (e.g. a follow-up request after the
# thanks) makes the full match fail.
_WHITESPACE_RE = re.compile(r"\s+")
_EDGE_PUNCT_RE = re.compile(
    r"^[・、。．,.!！?？~〜…☀-➿\U0001f300-\U0001faff]+"
    r"|[・、。．,.!！?？~〜…☀-➿\U0001f300-\U0001faff]+$"
)

# Anchored whole-message patterns per category. The normalized text must
# fully match one of these; any extra text -> None (guarded RAG route).
_THANKS_RE = re.compile(
    r"^(どうも)?(ありがとう?(ございま(す|した))?|感謝(します)?|サンキュー"
    r"|thanks|thankyou|thx|thankyouverymuch)$"
)
_GREETING_RE = re.compile(
    r"^(こんにちは|こんばんは|おはよう(ございます)?|おやすみ(なさい)?|はじめまして"
    r"|やあ|ハロー|hello|hi|hey|よろしく(お願いします|おねがいします)?)$"
)
_ACK_RE = re.compile(
    r"^(了解(です|しました)?|りょうかい(です)?|わかった|わかりました|分かった|分かりました"
    r"|ok|okay|オッケー|おけ|いいね|すごい(です)?(ね)?|なるほど(です)?(ね)?"
    r"|最高(です)?(ね)?|完璧(です)?(ね)?)$"
)


def _normalize(text: str) -> str:
    """Lowercase Latin, drop all whitespace, strip edge punctuation/emoji."""

    normalized = _WHITESPACE_RE.sub("", text.lower())
    # Strip repeatedly so mixed edge runs like 「！！…」 all come off.
    while True:
        stripped = _EDGE_PUNCT_RE.sub("", normalized)
        if stripped == normalized:
            return normalized
        normalized = stripped


def detect_small_talk(text: str) -> str | None:
    """Return ``"thanks" | "greeting" | "ack"`` for a small-talk turn, else ``None``.

    Conservative by design: any ambiguity (question marks, digits, an
    investment keyword, text longer than ``_MAX_LEN`` characters, or any
    residual text beyond one anchored small-talk form) returns ``None`` so
    the turn falls through to the existing guarded RAG path.
    """

    if not text:
        return None
    stripped = text.strip()
    if not stripped:
        return None
    if len(stripped) > _MAX_LEN:
        return None
    if "?" in stripped or "？" in stripped:
        return None
    if _DIGIT_RE.search(stripped):
        return None
    if any(keyword in stripped for keyword in _INVESTMENT_KEYWORDS):
        return None

    normalized = _normalize(stripped)
    if not normalized:
        return None

    if _THANKS_RE.fullmatch(normalized):
        return "thanks"
    if _GREETING_RE.fullmatch(normalized):
        return "greeting"
    if _ACK_RE.fullmatch(normalized):
        return "ack"
    return None


def small_talk_reply(category: str) -> str:
    """Return a short, friendly Japanese reply for a small-talk ``category``."""

    if category == "thanks":
        return "どういたしまして！ほかにも投資で気になることがあれば、いつでも聞いてください。"
    if category == "greeting":
        return "こんにちは！保有銘柄や市場の気になること、なんでも聞いてください。"
    return "はい！続けて気になることがあれば、なんでも聞いてください。"
