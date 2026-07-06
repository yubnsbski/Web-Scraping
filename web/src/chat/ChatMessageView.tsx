// Renders one message in the chat thread: right-aligned bubble for the user,
// full-width "no bubble" block (with citations/evidence/disclaimer) for the
// assistant. Reuses the extracted evidence components so citation links and
// evidence cards render identically to the RAG search tab.
import { useState } from "react";
import { CitationLinkedText, RagEvidenceCards } from "../rag/Evidence";
import type { ChatMessage } from "./types";

export function ChatMessageView(props: { message: ChatMessage; onNavigateData: () => void; onRetry: (message: ChatMessage) => void }) {
  const { message } = props;
  if (message.role === "user") {
    return (
      <div className="chat-row chat-row-user">
        <div className="chat-bubble chat-bubble-user">{message.content}</div>
      </div>
    );
  }
  if (message.error) {
    return (
      <div className="chat-row chat-row-assistant">
        <div className="chat-assistant">
          <ChatAvatar />
          <div className="chat-assistant-body">
            <div className="chat-error-block">
              <p>{message.content || "通信に失敗しました。"}</p>
              <button className="table-action" onClick={() => props.onRetry(message)}>
                再試行
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }
  const evidence = message.evidence ?? [];
  const citations = message.citations ?? [];
  const citationCount = citations.length || evidence.length;
  const retrieval = message.meta?.retrieval;
  const showSearchChip =
    !!retrieval && retrieval.resolved_query && retrieval.resolved_query !== retrieval.original_query;

  if (message.kind === "no_evidence") {
    return (
      <div className="chat-row chat-row-assistant">
        <div className="chat-assistant">
          <ChatAvatar />
          <div className="chat-assistant-body">
            <div className="chat-no-evidence">
              <strong>根拠が見つかりませんでした</strong>
              <p>{message.content || "一致する根拠が0件でした。データ更新で資料を追加すると回答できるようになります。"}</p>
              <button className="table-action" onClick={props.onNavigateData}>
                データ更新へ
              </button>
            </div>
            {message.meta?.disclaimer && <p className="chat-disclaimer">{message.meta.disclaimer}</p>}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="chat-row chat-row-assistant">
      <div className="chat-assistant">
        <ChatAvatar />
        <div className="chat-assistant-body">
          {showSearchChip && <span className="chat-search-chip">検索: {retrieval!.resolved_query}</span>}
          <CitationLinkedText text={message.content} citationCount={citationCount} targetPrefix={`chat-${message.id}`} />
          {evidence.length > 0 && <EvidenceDisclosure evidence={evidence} idPrefix={`chat-${message.id}`} />}
          {message.meta?.disclaimer && <p className="chat-disclaimer">{message.meta.disclaimer}</p>}
        </div>
      </div>
    </div>
  );
}

function ChatAvatar() {
  return (
    <div className="chat-avatar" aria-hidden="true">
      AI
    </div>
  );
}

function EvidenceDisclosure({ evidence, idPrefix }: { evidence: Record<string, any>[]; idPrefix: string }) {
  const [open, setOpen] = useState(false);
  return (
    <details className="chat-evidence-disclosure" open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>根拠 {evidence.length}件</summary>
      {open && <RagEvidenceCards title="根拠" results={evidence} idPrefix={idPrefix} />}
    </details>
  );
}
