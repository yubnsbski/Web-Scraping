"""Frontend smoke checks for web/src/App.tsx.

Stopgap: web/ has no JS test runner (vitest/jest) configured, only
`tsc --noEmit` / `vite build` (see web/package.json). Introducing a full
component test harness (jsdom + React Testing Library) for a single smoke
check was judged too heavy for this sprint, so we assert the same invariants
by parsing App.tsx as text. This is brittle by nature (it will need updating
if App.tsx is restructured) and should be replaced by a real JS test runner.

Sprint 2 (nav reorg: AI advisor as the front door) updated these invariants:
- chat is now the default landing tab and the first entry in the primary
  ("main") nav group, relabeled "AIアドバイザー".
- holdings/screen/data round out the 4 primary tabs.
- dashboard/report/watch/detail/forecast/rag/plans were demoted to the
  advanced ("more") group.
- the real-AI toggle drives call_real_api from state instead of a hardcoded
  false.

Sprint B (chat-first frontend, web/src/chat/) added a new ChatView that
replaces the legacy ChatPanel as the default chat-tab render, behind an
`ia.chatV2` localStorage escape hatch that falls back to the old ChatPanel.
The evidence-rendering components (CitationLinkedText, RagEvidenceCards,
RagEvidenceQuality) moved out of App.tsx into web/src/rag/Evidence.tsx; App.tsx
now imports them instead of defining them inline.
"""

from __future__ import annotations

import re
from pathlib import Path

APP_TSX = Path(__file__).resolve().parents[2] / "web" / "src" / "App.tsx"


def _read_app_tsx() -> str:
    return APP_TSX.read_text(encoding="utf-8")


def _tabs_block(source: str) -> str:
    tabs_block_match = re.search(r"const TABS: Array<\{.*?\]\s*;", source, re.DOTALL)
    assert tabs_block_match, "could not locate the TABS array literal in App.tsx"
    return tabs_block_match.group(0)


def _tab_entries(tabs_block: str) -> list[tuple[str, str, str]]:
    """Return (id, label, group) tuples in source order."""

    entries: list[tuple[str, str, str]] = []
    for match in re.finditer(
        r'\{\s*id:\s*"(?P<id>[a-z]+)"\s*,\s*label:\s*"(?P<label>[^"]+)"\s*,'
        r'\s*short:\s*"[^"]*"\s*,\s*group:\s*"(?P<group>main|more)"',
        tabs_block,
    ):
        entries.append((match.group("id"), match.group("label"), match.group("group")))
    return entries


def test_primary_nav_is_the_ai_advisor_workflow() -> None:
    """Sprint 2: 4 primary tabs, AI advisor first, in this exact order."""
    source = _read_app_tsx()
    tabs_block = _tabs_block(source)
    entries = _tab_entries(tabs_block)
    assert entries, "could not parse any TABS entries"

    main_entries = [entry for entry in entries if entry[2] == "main"]
    assert main_entries == [
        ("chat", "AIアドバイザー", "main"),
        ("holdings", "保有分析", "main"),
        ("screen", "候補抽出", "main"),
        ("data", "データ更新", "main"),
    ], f"primary (main) nav group is no longer the 4-tab AI-advisor workflow: {main_entries!r}"


def test_advanced_group_holds_the_demoted_tabs() -> None:
    """The 7 tabs demoted out of the primary nav must still exist, in the
    "more" group (aistock is checked separately since it is also hidden).
    """
    source = _read_app_tsx()
    tabs_block = _tabs_block(source)
    entries = _tab_entries(tabs_block)

    more_ids = [entry[0] for entry in entries if entry[2] == "more"]
    expected_demoted = ["dashboard", "report", "watch", "detail", "forecast", "rag", "plans"]
    for expected_id in expected_demoted:
        assert expected_id in more_ids, (
            f"{expected_id!r} must remain in the advanced (more) nav group"
        )
    # aistock also lives in "more" (and is additionally hidden -- see below).
    assert "aistock" in more_ids

    # The advanced group's disclosure label was renamed from その他.
    assert re.search(r"<summary>詳細機能</summary>", source), (
        "advanced nav group summary label must be 詳細機能"
    )


def test_chat_is_the_default_landing_tab() -> None:
    """Default tab is now chat (AI advisor), both for the initial state and
    the localStorage fallback.
    """
    source = _read_app_tsx()
    assert re.search(
        r'return VISIBLE_TABS\.some\(\(item\) => item\.id === saved\)'
        r' \? \(saved as TabId\) : "chat"',
        source,
    ), "default/fallback tab must be \"chat\" (AI advisor front door)"


def test_aistock_tab_is_hidden_from_navigation() -> None:
    """aistock (StockAiPanel, /api/stocks/*) must stay in the codebase but be
    gated out of the visible nav so its quota-heavy LLM-per-stock path isn't
    casually reachable (Sprint 1 task, unchanged by the Sprint-2 nav reorg).
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


def test_chat_tab_renders_the_weekly_workflow_strip() -> None:
    """Task 2 (pre-Sprint-B): the legacy one-shot chat view still shows the
    reused OneClickPanel workflow strip above the chat box, not a duplicated
    copy of its logic. Sprint B moved this view behind the `ia.chatV2 ===
    "off"` escape hatch (see test_chat_v2_escape_hatch_falls_back_to_legacy_chat_panel
    below) -- the old ChatPanel/OneClickPanel wiring itself is unchanged.
    """
    source = _read_app_tsx()

    chat_tab_block_match = re.search(
        r'\{tab === "chat" && \((.*?)\n        \)\}', source, re.DOTALL
    )
    assert chat_tab_block_match, "chat tab render block not found"
    chat_tab_block = chat_tab_block_match.group(1)

    assert "<OneClickPanel" in chat_tab_block, (
        "chat tab must render OneClickPanel (the weekly workflow strip) in its legacy branch"
    )
    assert "<ChatPanel" in chat_tab_block, "chat tab must still render ChatPanel in its legacy branch"
    # Only one function component definition of OneClickPanel should exist --
    # i.e. its logic is reused, not duplicated, across dashboard and chat.
    assert source.count("function OneClickPanel(") == 1


def test_chat_v2_escape_hatch_falls_back_to_legacy_chat_panel() -> None:
    """Sprint B: the chat tab defaults to the new ChatView (chat-first UI),
    but setting localStorage["ia.chatV2"] = "off" must still render the old
    one-shot ChatPanel (kept as dead code, not deleted) so the legacy view
    stays reachable as a rollback path.
    """
    source = _read_app_tsx()

    chat_tab_block_match = re.search(
        r'\{tab === "chat" && \((.*?)\n        \)\}', source, re.DOTALL
    )
    assert chat_tab_block_match, "chat tab render block not found"
    chat_tab_block = chat_tab_block_match.group(1)

    assert 'localStorage.getItem("ia.chatV2") === "off"' in chat_tab_block, (
        "chat tab must gate the legacy ChatPanel behind the ia.chatV2 escape hatch"
    )
    assert "<ChatView" in chat_tab_block, (
        "chat tab must render the new ChatView component when ia.chatV2 is not \"off\""
    )
    assert 'import { ChatView } from "./chat/ChatView";' in source, (
        "ChatView must be imported from web/src/chat/ChatView"
    )


def test_real_ai_toggle_drives_call_real_api_from_state() -> None:
    """Task 3: call_real_api must come from a stateful real-AI toggle, not a
    hardcoded false, on both the rag/answer and orchestrate requests that
    ChatPanel issues.
    """
    source = _read_app_tsx()

    # The literal hardcoded false must be gone from ChatPanel's API calls.
    assert "call_real_api: false" not in source, (
        "call_real_api must no longer be hardcoded to false anywhere in App.tsx"
    )
    assert re.search(r"call_real_api:\s*realAi", source), (
        "orchestrate / rag-answer calls must send call_real_api driven by the realAi toggle state"
    )

    # Persistent toggle backed by localStorage, default OFF.
    assert re.search(
        r'localStorage\.getItem\("ia\.realAi"\)\s*===\s*"1"', source
    ), "real-AI toggle must read its persisted default from localStorage key ia.realAi"
    assert re.search(
        r'localStorage\.setItem\("ia\.realAi",\s*realAi \? "1" : "0"\)', source
    ), "real-AI toggle must persist its state to localStorage key ia.realAi"

    # Always-visible hint when OFF so the user knows which brain answered.
    assert "オフライン簡易応答モード" in source

    # Budget meter: fetched on toggle-on (not a polling loop) and displayed.
    assert re.search(r'api<Json>\("/api/budget"\)', source)
    assert "残り本日" in source


def test_budget_meter_is_event_driven_not_a_new_polling_loop() -> None:
    """The budget fetch must only run in response to the toggle / a real
    call, never on an interval -- TickerTape already owns the one polling
    loop in this app.
    """
    source = _read_app_tsx()
    refresh_fn_match = re.search(
        r"const refreshBudget = async \(\) => \{.*?\n  \};", source, re.DOTALL
    )
    assert refresh_fn_match, "refreshBudget helper not found in ChatPanel"
    assert "setInterval" not in refresh_fn_match.group(0)

    # No new setInterval loop should be wired to budget/realAi -- the meter is
    # only refreshed from the toggle-on effect and the post-call .then()s.
    for match in re.finditer(r"setInterval\([\s\S]{0,200}", source):
        assert "udget" not in match.group(0) and "realAi" not in match.group(0), (
            "budget meter must not be driven by a new setInterval polling loop"
        )
