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
replaces the legacy ChatPanel as the chat-tab render. Sprint D1 (dead-code
cleanup) removed the legacy ChatPanel component, the `ia.chatV2` escape
hatch, StockAiPanel, and the hidden `aistock` tab entirely -- the chat tab
now always renders ChatView, and StockAiPanel/aistock no longer exist in
the codebase (their backend routes are untouched).
The evidence-rendering components (CitationLinkedText, RagEvidenceCards,
RagEvidenceQuality) moved out of App.tsx into web/src/rag/Evidence.tsx;
App.tsx no longer imports CitationLinkedText/RagEvidenceCards directly
(only RagEvidenceQuality, used by RagSearchPanel) since those two are only
used by web/src/chat/ChatMessageView.tsx now.
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
    "more" group.
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
    # aistock (StockAiPanel) was removed in Sprint D1 -- no longer part of TABS.
    assert "aistock" not in more_ids

    # The advanced group's disclosure label was renamed from その他.
    assert re.search(r"<summary>詳細機能</summary>", source), (
        "advanced nav group summary label must be 詳細機能"
    )


def test_chat_is_the_default_landing_tab() -> None:
    """Every load lands on the chat (AI advisor) tab — AI-first product
    direction; the remembered ia.tab no longer overrides the landing tab.
    """
    source = _read_app_tsx()
    assert re.search(r'useState<TabId>\("chat"\)', source), (
        'startup tab must be hardcoded to "chat" (AI-first landing)'
    )


def test_aistock_and_legacy_chat_panel_are_removed() -> None:
    """Sprint D1 (dead-code cleanup): StockAiPanel/aistock, the
    SHOW_ADVANCED_TABS gating flag, the legacy ChatPanel component, and the
    ia.chatV2 escape hatch must all be gone from App.tsx. Backend routes
    (/api/stocks/*) are untouched by this cleanup -- only the frontend went.
    """
    source = _read_app_tsx()

    assert "SHOW_ADVANCED_TABS" not in source
    assert "function StockAiPanel(" not in source
    assert "function StockAiRow(" not in source
    assert '"aistock"' not in source
    assert "function ChatPanel(" not in source
    assert "ia.chatV2" not in source


def test_chat_tab_always_renders_chat_view() -> None:
    """The chat tab has no more branching -- it always renders the new
    ChatView (web/src/chat/ChatView.tsx), with no legacy fallback.
    """
    source = _read_app_tsx()

    assert re.search(
        r'\{tab === "chat" && <ChatView onNavigate=\{', source
    ), "chat tab must render ChatView unconditionally"
    assert 'import { ChatView } from "./chat/ChatView";' in source, (
        "ChatView must be imported from web/src/chat/ChatView"
    )
