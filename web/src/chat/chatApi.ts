// Typed client for the chat.turn.v1 contract (POST /api/chat/turn) and
// GET /api/budget. Uses the same same-origin fetch conventions as ../api.ts.
import { api } from "../api";
import type { ApiChatMessage, BudgetInfo, ChatMode, ChatTurnResponse, SourceMode } from "./types";

export interface PostChatTurnOptions {
  dbPath?: string;
  limit?: number;
  callRealApi?: boolean;
  mode?: ChatMode;
  hybrid?: boolean;
  alpha?: number;
  sourceMode?: SourceMode;
}

export async function postChatTurn(
  messages: ApiChatMessage[],
  opts: PostChatTurnOptions = {},
): Promise<ChatTurnResponse> {
  const body: Record<string, unknown> = { messages };
  if (opts.dbPath !== undefined) body.db_path = opts.dbPath;
  if (opts.limit !== undefined) body.limit = opts.limit;
  if (opts.callRealApi !== undefined) body.call_real_api = opts.callRealApi;
  if (opts.mode !== undefined) body.mode = opts.mode;
  if (opts.hybrid !== undefined) body.hybrid = opts.hybrid;
  if (opts.alpha !== undefined) body.alpha = opts.alpha;
  if (opts.sourceMode !== undefined) body.source_mode = opts.sourceMode;
  return api<ChatTurnResponse>("/api/chat/turn", body);
}

/** Best-effort budget fetch: a failed/misconfigured budget check must never
 * block the chat UI, so callers get null instead of a thrown error. */
export async function fetchBudget(): Promise<BudgetInfo | null> {
  try {
    return await api<BudgetInfo>("/api/budget");
  } catch {
    return null;
  }
}
