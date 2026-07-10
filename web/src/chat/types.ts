// Shared types for the chat-first frontend (Sprint B), matching the backend
// chat.turn.v1 contract (POST /api/chat/turn, see
// src/investment_assistant/webapi/chat.py) and GET /api/budget.

export type Json = Record<string, any>;

export type ChatRole = "user" | "assistant";
export type ChatMode = "answer" | "detailed";
export type ChatKind = "rag_answer" | "orchestrate" | "web_answer" | "no_evidence" | "small_talk";
/** Which evidence source the next turn should use: local RAG search, Web
 * search (Gemini's Google Search grounding), or rag-first-then-web-fallback. */
export type SourceMode = "rag" | "web" | "auto";

/** The minimal shape sent as conversation history to POST /api/chat/turn. */
export interface ApiChatMessage {
  role: ChatRole;
  content: string;
}

export interface ChatRetrievalMeta {
  original_query: string;
  resolved_query: string;
  hybrid: boolean;
  alpha: number;
  limit: number;
  result_count: number;
  no_evidence: boolean;
}

export interface ChatLlmMeta {
  source: string | null;
  warning: string | null;
  skipped: boolean | null;
  cache_key: string | null;
}

/** One "thought" surfaced during a pipeline stage (see thinking.py). */
export interface ThinkingItem {
  t: string;
  w: number;
  note: string | null;
}

/** One stage of the thinking trace, e.g. context/route/retrieve/generate. */
export interface ThinkingStep {
  stage: string;
  label: string;
  ms: number;
  items: ThinkingItem[];
}

/** Full "thinking popup" trace attached to an assistant turn's meta, matching
 * thinking.v1 emitted by src/investment_assistant/brainstem/thinking.py. May
 * be absent entirely (older stored conversations, trace failure). */
export interface ThinkingTrace {
  version: string;
  total_ms: number;
  steps: ThinkingStep[];
}

export interface ChatTurnMeta {
  mode: string;
  disclaimer: string;
  highlights: Json[];
  stock_score: unknown;
  forecast: unknown;
  llm: ChatLlmMeta | null;
  retrieval: ChatRetrievalMeta;
  budget: BudgetInfo | null;
  simulation: unknown;
  thinking?: ThinkingTrace | null;
}

export interface ChatTurnResponse {
  contract: { version: string; stream_ready: boolean };
  message: {
    role: "assistant";
    kind: ChatKind;
    content: string;
    citations: Json[];
    evidence: Json[];
    meta: ChatTurnMeta;
  };
}

export interface BudgetInfo {
  daily_remaining: number;
  hard_daily_limit: number;
  warning: boolean;
  [key: string]: unknown;
}

/** One message in a conversation as stored/rendered in the chat UI. Extends
 * the wire ApiChatMessage with everything needed to re-render evidence,
 * citations, and error/retry state without re-fetching. */
export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  createdAt: number;
  kind?: ChatKind;
  citations?: Json[];
  evidence?: Json[];
  meta?: ChatTurnMeta;
  /** Set on an assistant message that represents a failed turn. */
  error?: boolean;
  /** The exact message list that was sent to the API for this turn (present
   * only on error messages), so "retry" can resend it verbatim. */
  retryPayload?: ApiChatMessage[];
}

export interface Conversation {
  id: string;
  title: string;
  createdAt: number;
  messages: ChatMessage[];
}

export function genId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** Convert stored chat messages into the wire shape for /api/chat/turn,
 * dropping error placeholders (they never represent a real assistant turn). */
export function toApiMessages(messages: ChatMessage[]): ApiChatMessage[] {
  return messages
    .filter((message) => !message.error)
    .map((message) => ({ role: message.role, content: message.content }));
}
