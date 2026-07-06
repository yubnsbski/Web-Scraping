// localStorage-backed conversation store for the chat-first UI.
import { useCallback, useEffect, useMemo, useState } from "react";
import { genId, type ChatMessage, type Conversation } from "./types";

const STORAGE_KEY = "ia.chat.conversations.v1";
const MAX_CONVERSATIONS = 50;
const MAX_MESSAGES_PER_CONVERSATION = 100;
const TITLE_MAX_LENGTH = 40;

function titleFromMessages(messages: ChatMessage[]): string {
  const firstUser = messages.find((message) => message.role === "user");
  const text = (firstUser?.content ?? "").trim().replace(/\s+/g, " ");
  if (!text) return "新しいチャット";
  return text.length > TITLE_MAX_LENGTH ? `${text.slice(0, TITLE_MAX_LENGTH)}…` : text;
}

function sanitizeConversation(value: unknown): Conversation | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  const id = typeof raw.id === "string" && raw.id ? raw.id : null;
  if (!id) return null;
  const messages = Array.isArray(raw.messages) ? (raw.messages as ChatMessage[]) : [];
  return {
    id,
    title: typeof raw.title === "string" && raw.title ? raw.title : "新しいチャット",
    createdAt: typeof raw.createdAt === "number" ? raw.createdAt : Date.now(),
    messages,
  };
}

function loadConversations(): Conversation[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .map(sanitizeConversation)
      .filter((conversation): conversation is Conversation => conversation !== null);
  } catch {
    return [];
  }
}

function persist(conversations: Conversation[]): void {
  // Cap conversation count and per-conversation message history so
  // localStorage never grows unbounded across a long-lived install.
  const capped = conversations.slice(0, MAX_CONVERSATIONS).map((conversation) => ({
    ...conversation,
    messages: conversation.messages.slice(-MAX_MESSAGES_PER_CONVERSATION),
  }));
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(capped));
  } catch {
    // Storage full/unavailable is not fatal for the in-memory session.
  }
}

function makeConversation(): Conversation {
  return { id: genId(), title: "新しいチャット", createdAt: Date.now(), messages: [] };
}

export interface UseConversationsResult {
  conversations: Conversation[];
  activeId: string;
  activeConversation: Conversation;
  selectConversation: (id: string) => void;
  newConversation: () => void;
  deleteConversation: (id: string) => void;
  clearAll: () => void;
  appendMessages: (conversationId: string, messages: ChatMessage[]) => void;
}

export function useConversations(): UseConversationsResult {
  const [conversations, setConversations] = useState<Conversation[]>(() => {
    const loaded = loadConversations();
    return loaded.length > 0 ? loaded : [makeConversation()];
  });
  const [activeId, setActiveId] = useState<string>(() => conversations[0]!.id);

  useEffect(() => {
    persist(conversations);
  }, [conversations]);

  const selectConversation = useCallback((id: string) => {
    setActiveId(id);
  }, []);

  const newConversation = useCallback(() => {
    const fresh = makeConversation();
    setConversations((prev) => [fresh, ...prev]);
    setActiveId(fresh.id);
  }, []);

  const deleteConversation = useCallback((id: string) => {
    setConversations((prev) => {
      const next = prev.filter((conversation) => conversation.id !== id);
      const replacement = next.length > 0 ? next : [makeConversation()];
      setActiveId((current) => (current === id ? replacement[0]!.id : current));
      return replacement;
    });
  }, []);

  const clearAll = useCallback(() => {
    const fresh = makeConversation();
    setConversations([fresh]);
    setActiveId(fresh.id);
  }, []);

  const appendMessages = useCallback((conversationId: string, messages: ChatMessage[]) => {
    if (messages.length === 0) return;
    setConversations((prev) =>
      prev.map((conversation) => {
        if (conversation.id !== conversationId) return conversation;
        const nextMessages = [...conversation.messages, ...messages];
        const isFirstUserMessage =
          conversation.messages.every((message) => message.role !== "user") &&
          conversation.title === "新しいチャット";
        return {
          ...conversation,
          messages: nextMessages,
          title: isFirstUserMessage ? titleFromMessages(nextMessages) : conversation.title,
        };
      }),
    );
  }, []);

  const activeConversation = useMemo(
    () => conversations.find((conversation) => conversation.id === activeId) ?? conversations[0]!,
    [conversations, activeId],
  );

  return {
    conversations,
    activeId: activeConversation.id,
    activeConversation,
    selectConversation,
    newConversation,
    deleteConversation,
    clearAll,
    appendMessages,
  };
}
