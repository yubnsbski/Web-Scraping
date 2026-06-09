// Minimal typed fetch wrapper for the local Python JSON API.
// GET when no body is provided, POST (JSON) otherwise.

// Same-origin by default (web / installed PWA). A packaged native app sets
// VITE_API_BASE to a hosted backend at build time. Absolute paths pass through.
const API_BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/+$/, "");

export function apiUrl(path: string): string {
  return /^https?:\/\//.test(path) ? path : `${API_BASE}${path}`;
}

export async function api<T = unknown>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(apiUrl(path), {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data: unknown = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }
  if (!response.ok) {
    const message =
      data && typeof data === "object" && "error" in data
        ? String((data as { error: unknown }).error)
        : `HTTP ${response.status}`;
    throw new Error(message);
  }
  return data as T;
}
