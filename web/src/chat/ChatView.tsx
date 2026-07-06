// Chat-first screen shell (Sprint B): collapsible left sidebar (conversation
// list + navigation into the surviving tabs) and a main column that shows
// the WelcomeScreen (empty conversation) or the ChatThread, with the
// Composer always docked at the bottom.
import { useEffect, useRef, useState } from "react";
import { fetchBudget, postChatTurn } from "./chatApi";
import { useConversations } from "./chatStore";
import { ChatThread } from "./ChatThread";
import { Composer } from "./Composer";
import { WelcomeScreen } from "./WelcomeScreen";
import { genId, toApiMessages, type ApiChatMessage, type BudgetInfo, type ChatMessage, type ChatMode } from "./types";

const DEFAULT_RAG_DB_PATH = ".cache/investment_assistant/rag.sqlite";
const DEFAULT_LIMIT = 6;

// Mirrors the surviving TABS entries in App.tsx (main group minus "chat",
// plus the "more" group; aistock stays hidden per SHOW_ADVANCED_TABS there).
// Duplicated here (rather than imported) because TABS is a module-private
// constant in App.tsx -- this is the "mirror the labels/ids" case called out
// in the Sprint B spec, not a shared source of truth.
const MAIN_NAV_ITEMS = [
  { id: "holdings", label: "保有分析" },
  { id: "screen", label: "候補抽出" },
  { id: "data", label: "データ更新" },
];
const MORE_NAV_ITEMS = [
  { id: "dashboard", label: "全体" },
  { id: "report", label: "レポート" },
  { id: "watch", label: "ウォッチ" },
  { id: "detail", label: "詳細" },
  { id: "forecast", label: "予測スクリーニング" },
  { id: "rag", label: "RAG検索" },
  { id: "plans", label: "プラン設計" },
];

export function ChatView(props: { onNavigate: (tabId: string) => void }) {
  const {
    conversations,
    activeConversation,
    selectConversation,
    newConversation,
    deleteConversation,
    appendMessages,
  } = useConversations();

  const [draftText, setDraftText] = useState("");
  const [sending, setSending] = useState(false);
  const [mode, setMode] = useState<ChatMode>("answer");
  const [realAi, setRealAi] = useState<boolean>(() => localStorage.getItem("ia.realAi") === "1");
  const [budgetInfo, setBudgetInfo] = useState<BudgetInfo | null>(null);
  const [dbPath, setDbPath] = useState(DEFAULT_RAG_DB_PATH);
  const [limit, setLimit] = useState(DEFAULT_LIMIT);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    localStorage.setItem("ia.realAi", realAi ? "1" : "0");
  }, [realAi]);

  const refreshBudget = async () => {
    setBudgetInfo(await fetchBudget());
  };

  useEffect(() => {
    if (realAi) void refreshBudget();
    else setBudgetInfo(null);
    // Event-driven only (toggle flip / post-call), no polling loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [realAi]);

  const conversationId = activeConversation.id;
  const conversationMessages = activeConversation.messages;

  const sendTurn = async (userText: string | null, retryPayload?: ApiChatMessage[]) => {
    const payload: ApiChatMessage[] =
      retryPayload ?? [...toApiMessages(conversationMessages), { role: "user", content: userText ?? "" }];
    if (!retryPayload && userText) {
      appendMessages(conversationId, [
        { id: genId(), role: "user", content: userText, createdAt: Date.now() },
      ]);
    }
    setSending(true);
    try {
      const res = await postChatTurn(payload, {
        dbPath,
        limit,
        callRealApi: realAi,
        mode,
        hybrid: true,
      });
      const reply: ChatMessage = {
        id: genId(),
        role: "assistant",
        content: res.message.content,
        createdAt: Date.now(),
        kind: res.message.kind,
        citations: res.message.citations,
        evidence: res.message.evidence,
        meta: res.message.meta,
      };
      appendMessages(conversationId, [reply]);
      if (realAi) void refreshBudget();
    } catch (caught) {
      const errorMessage: ChatMessage = {
        id: genId(),
        role: "assistant",
        content: caught instanceof Error ? caught.message : String(caught),
        createdAt: Date.now(),
        error: true,
        retryPayload: payload,
      };
      appendMessages(conversationId, [errorMessage]);
    } finally {
      setSending(false);
    }
  };

  const handleComposerSend = (text: string) => {
    setDraftText("");
    void sendTurn(text);
  };

  const handleSuggestion = (text: string) => {
    setDraftText("");
    void sendTurn(text);
  };

  const handleRetry = (message: ChatMessage) => {
    if (message.retryPayload) void sendTurn(null, message.retryPayload);
  };

  return (
    <div className={sidebarCollapsed ? "chatview chatview-collapsed" : "chatview"}>
      <aside className="chatview-sidebar">
        <div className="chatview-sidebar-head">
          <button
            className="chatview-collapse-btn"
            onClick={() => setSidebarCollapsed((value) => !value)}
            aria-label={sidebarCollapsed ? "サイドバーを開く" : "サイドバーを閉じる"}
            title={sidebarCollapsed ? "サイドバーを開く" : "サイドバーを閉じる"}
          >
            {sidebarCollapsed ? "»" : "«"}
          </button>
          {!sidebarCollapsed && <span className="chatview-brand">投資AIアシスタント</span>}
        </div>
        {!sidebarCollapsed && (
          <>
            <button className="chatview-new-btn" onClick={newConversation}>
              + 新しいチャット
            </button>
            <div className="chatview-conv-list" aria-label="チャット履歴">
              {conversations.map((conversation) => (
                <div
                  key={conversation.id}
                  className={
                    conversation.id === activeConversation.id ? "chatview-conv-item active" : "chatview-conv-item"
                  }
                >
                  <button
                    className="chatview-conv-select"
                    onClick={() => selectConversation(conversation.id)}
                    title={conversation.title}
                  >
                    {conversation.title}
                  </button>
                  <button
                    className="chatview-conv-delete"
                    onClick={() => deleteConversation(conversation.id)}
                    aria-label={`${conversation.title} を削除`}
                    title="削除"
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
            <nav className="chatview-nav" aria-label="他の機能">
              {MAIN_NAV_ITEMS.map((item) => (
                <button key={item.id} className="chatview-nav-item" onClick={() => props.onNavigate(item.id)}>
                  {item.label}
                </button>
              ))}
              <details className="chatview-nav-more">
                <summary>詳細機能</summary>
                <div className="chatview-nav-more-list">
                  {MORE_NAV_ITEMS.map((item) => (
                    <button key={item.id} className="chatview-nav-item" onClick={() => props.onNavigate(item.id)}>
                      {item.label}
                    </button>
                  ))}
                </div>
              </details>
            </nav>
          </>
        )}
      </aside>

      <div className="chatview-main">
        {conversationMessages.length === 0 ? (
          <WelcomeScreen onStart={() => composerRef.current?.focus()} onSuggestion={handleSuggestion} />
        ) : (
          <ChatThread
            messages={conversationMessages}
            sending={sending}
            onNavigateData={() => props.onNavigate("data")}
            onRetry={handleRetry}
          />
        )}
        <Composer
          ref={composerRef}
          value={draftText}
          onChange={setDraftText}
          onSend={handleComposerSend}
          sending={sending}
          mode={mode}
          onModeChange={setMode}
          realAi={realAi}
          onRealAiChange={setRealAi}
          budgetInfo={budgetInfo}
          dbPath={dbPath}
          onDbPathChange={setDbPath}
          limit={limit}
          onLimitChange={setLimit}
        />
      </div>
    </div>
  );
}
