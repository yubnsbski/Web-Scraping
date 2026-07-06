// Scrollable message list for the active conversation. Auto-scrolls to the
// bottom whenever a message is added or the "thinking" indicator toggles.
import { useEffect, useRef } from "react";
import { ChatMessageView } from "./ChatMessageView";
import type { ChatMessage } from "./types";

export function ChatThread(props: {
  messages: ChatMessage[];
  sending: boolean;
  onNavigateData: () => void;
  onRetry: (message: ChatMessage) => void;
}) {
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [props.messages.length, props.sending]);

  return (
    <div className="chat-thread" role="log" aria-live="polite">
      <div className="chat-thread-inner">
        {props.messages.map((message) => (
          <ChatMessageView key={message.id} message={message} onNavigateData={props.onNavigateData} onRetry={props.onRetry} />
        ))}
        {props.sending && (
          <div className="chat-row chat-row-assistant">
            <div className="chat-assistant">
              <div className="chat-avatar" aria-hidden="true">
                AI
              </div>
              <div className="chat-thinking" aria-label="考え中">
                <span>考え中</span>
                <span className="chat-thinking-dots">
                  <i />
                  <i />
                  <i />
                </span>
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
