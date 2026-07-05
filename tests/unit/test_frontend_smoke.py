"""Frontend smoke checks for web/src/App.tsx.

Stopgap: web/ has no JS test runner (vitest/jest) configured, only
`tsc --noEmit` / `vite build` (see web/package.json). Introducing a full
component test harness (jsdom + React Testing Library) for a single smoke
check was judged too heavy for this sprint, so we assert the same invariants
by parsing App.tsx as text. This is brittle by nature (it will need updating
if App.tsx is restructured) and should be replaced by a real JS test runner
in the Sprint-2 nav reorg.
"""

from __future__ import annotations

import re
from pathlib import Path

APP_TSX = Path(__file__).resolve().parents[2] / "web" / "src" / "App.tsx"


def _read_app_tsx() -> str:
    return APP_TSX.read_text(encoding="utf-8")


def test_core_tabs_are_defined() -> None:
    """The four core Sprint-1 nav destinations must exist in TABS."""
    source = _read_app_tsx()
    tabs_block_match = re.search(r"const TABS: Array<\{.*?\]\s*;", source, re.DOTALL)
    assert tabs_block_match, "could not locate the TABS array literal in App.tsx"
    tabs_block = tabs_block_match.group(0)

    for expected_id, expected_label in [
        ("holdings", "保有分析"),
        ("screen", "候補抽出"),
        ("chat", "AI確認"),
        ("data", "データ更新"),
    ]:
        entry_pattern = re.compile(
            r'\{\s*id:\s*"'
            + re.escape(expected_id)
            + r'"\s*,\s*label:\s*"'
            + re.escape(expected_label)
            + r'"'
        )
        assert entry_pattern.search(tabs_block), (
            f"TABS is missing the expected entry id={expected_id!r} "
            f"label={expected_label!r}"
        )


def test_aistock_tab_is_hidden_from_navigation() -> None:
    """aistock (StockAiPanel, /api/stocks/*) must stay in the codebase but be
    gated out of the visible nav so its quota-heavy LLM-per-stock path isn't
    casually reachable (Sprint 1 task).
    """
    source = _read_app_tsx()

    # The gating flag must exist and default to off.
    assert re.search(r"SHOW_ADVANCED_TABS\s*=\s*false\s*;", source), (
        "SHOW_ADVANCED_TABS flag not found or not defaulted to false"
    )

    # aistock's TABS entry must be marked hidden.
    aistock_entry_match = re.search(
        r'\{\s*id:\s*"aistock"[^}]*\}', source, re.DOTALL
    )
    assert aistock_entry_match, "aistock entry not found in TABS"
    assert "hidden: true" in aistock_entry_match.group(0), (
        "aistock TABS entry must be marked hidden: true"
    )

    # The visible tab lists must be derived with the hidden flag respected.
    assert re.search(
        r"VISIBLE_TABS\s*=\s*TABS\.filter\(\(item\)\s*=>\s*SHOW_ADVANCED_TABS \|\| !item\.hidden\)",
        source,
    ), "VISIBLE_TABS filter no longer excludes hidden tabs behind SHOW_ADVANCED_TABS"
    assert "MAIN_TABS = VISIBLE_TABS.filter" in source
    assert "MORE_TABS = VISIBLE_TABS.filter" in source

    # The component and its API client code must still be present (not deleted).
    assert "function StockAiPanel()" in source, (
        "StockAiPanel component must remain in App.tsx"
    )
    assert "/api/stocks/" in source, (
        "/api/stocks/* client code must remain reachable in App.tsx"
    )

    # The tab route itself must still exist (only the nav entry is hidden).
    assert '{tab === "aistock" && <StockAiPanel />}' in source


def test_send_to_chat_handoff_is_wired() -> None:
    """RAG search results can be handed off to the AI chat panel via
    sendToChat -> onAskDraft -> setChatDraft/setTab("chat").
    """
    source = _read_app_tsx()

    assert re.search(r"const sendToChat = \(\) => \{", source), (
        "sendToChat function not found"
    )
    assert "props.onAskDraft({" in source, (
        "sendToChat must call props.onAskDraft with the built draft"
    )
    assert re.search(r'onClick=\{sendToChat\}', source), (
        "sendToChat is not wired to a button onClick handler"
    )

    # RagSearchPanel is rendered with onAskDraft wired to promote the draft
    # into chat state and switch tabs.
    ask_draft_block_match = re.search(
        r"onAskDraft=\{\(draft\) => \{(.*?)\}\}", source, re.DOTALL
    )
    assert ask_draft_block_match, "onAskDraft prop wiring not found on RagSearchPanel"
    ask_draft_block = ask_draft_block_match.group(1)
    assert "setChatDraft(draft)" in ask_draft_block
    assert 'setTab("chat")' in ask_draft_block
