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
- report/watch/detail/forecast/plans were demoted to the advanced ("more")
  group.
- the real-AI toggle drives call_real_api from state instead of a hardcoded
  false.

Sprint B (chat-first frontend, web/src/chat/) added a new ChatView that
replaces the legacy ChatPanel as the chat-tab render. Sprint D1 (dead-code
cleanup) removed the legacy ChatPanel component, the `ia.chatV2` escape
hatch, StockAiPanel, and the hidden `aistock` tab entirely -- the chat tab
now always renders ChatView, and StockAiPanel/aistock no longer exist in
the codebase (their backend routes are untouched).
The evidence-rendering components (CitationLinkedText, RagEvidenceCards,
RagEvidenceQuality) live in web/src/rag/Evidence.tsx, used by
web/src/chat/ChatMessageView.tsx.

Sprint D4 (tab consolidation) removed the `rag` (RAG検索) and `dashboard`
(全体) tabs entirely -- their sole components (RagSearchPanel and
Dashboard/OneClickPanel) and the helpers used only by them are gone from
App.tsx. App.tsx no longer imports RagEvidenceQuality (it was only used by
the now-removed RagSearchPanel). The RAG and one-click-batch backend routes
are untouched; chat still uses /api/rag/* internally via the backend.
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
    """The 5 tabs demoted out of the primary nav must still exist, in the
    "more" group, in this exact order (Sprint D4: rag/dashboard removed).
    """
    source = _read_app_tsx()
    tabs_block = _tabs_block(source)
    entries = _tab_entries(tabs_block)

    more_ids = [entry[0] for entry in entries if entry[2] == "more"]
    assert more_ids == ["report", "watch", "forecast", "detail", "plans"], (
        f"advanced (more) nav group must be exactly report/watch/forecast/detail/plans, "
        f"in that order: {more_ids!r}"
    )
    # aistock (StockAiPanel) was removed in Sprint D1 -- no longer part of TABS.
    assert "aistock" not in more_ids

    # The advanced group's disclosure label was renamed from その他.
    assert re.search(r"<summary>詳細機能</summary>", source), (
        "advanced nav group summary label must be 詳細機能"
    )


def test_rag_and_dashboard_tabs_are_removed() -> None:
    """Sprint D4: the rag (RAG検索) and dashboard (全体) tabs, their sole
    components, and the frontend's only /api/flick and /api/sprint
    references must all be gone. Backend /api/rag/* routes are untouched --
    chat still calls them internally.
    """
    source = _read_app_tsx()
    tabs_block = _tabs_block(source)
    entries = _tab_entries(tabs_block)
    all_ids = [entry[0] for entry in entries]

    assert "rag" not in all_ids
    assert "dashboard" not in all_ids
    assert "function RagSearchPanel(" not in source
    assert "function Dashboard(" not in source
    assert "function OneClickPanel(" not in source
    assert "/api/flick" not in source
    assert "/api/sprint" not in source


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
