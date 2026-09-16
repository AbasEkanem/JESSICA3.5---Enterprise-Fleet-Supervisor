import { StreamEvent } from "@/types/chat";

// In production (static export served by FastAPI), use relative URLs (same origin).
// For local dev with separate frontend/backend, set NEXT_PUBLIC_API_URL=http://localhost:8000
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

export async function* streamChat(
  message: string,
  threadId: string,
  signal?: AbortSignal,
  attachments?: string[]  // server-side file paths from /api/upload
): AsyncGenerator<StreamEvent> {
  const response = await fetch(`${API_BASE}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      thread_id: threadId,
      ...(attachments && attachments.length > 0 ? { attachments } : {}),
    }),
    credentials: "include",
    signal,
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`API error ${response.status}: ${text}`);
  }

  const reader = response.body?.getReader();
  if (!reader) throw new Error("No response body");

  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const raw = line.slice(6).trim();
        if (!raw) continue;
        if (raw === "[DONE]") {
          return;
        }
        try {
          const event = JSON.parse(raw) as StreamEvent;
          yield event;
        } catch {
          // skip malformed lines
        }
      }
    }
  } finally {
    try { await reader.cancel(); } catch {}
  }
}

export async function fetchThreadHistory(threadId: string): Promise<
  { role: string; content: string }[]
> {
  try {
    const res = await fetch(`${API_BASE}/api/threads/${threadId}/history`, {
      credentials: "include",
    });
    if (!res.ok) return [];
    const data = await res.json();
    return data.messages ?? [];
  } catch (error) {
    console.warn("Backend unreachable for history fetch:", error);
    return [];
  }
}

/* ── Google Workspace connect (per-user OAuth) ── */

export interface GoogleStatus {
  /** true when the current user has a stored, valid Google refresh token */
  connected: boolean;
  /** false when the server isn't configured for per-user connect at all */
  available: boolean;
  detail?: string;
}

/**
 * Fetch whether the signed-in user has connected their Google account.
 * Never throws — returns a safe "not connected / unavailable" shape on failure
 * so the Settings UI can render a sensible fallback.
 */
export async function getGoogleStatus(): Promise<GoogleStatus> {
  try {
    const res = await fetch(`${API_BASE}/google/status`, { credentials: "include" });
    if (!res.ok) {
      return { connected: false, available: false, detail: `status ${res.status}` };
    }
    return (await res.json()) as GoogleStatus;
  } catch {
    return { connected: false, available: false, detail: "Backend unreachable" };
  }
}

/**
 * The backend endpoint that kicks off Google's OAuth consent flow. This must be
 * a full-page browser navigation (not fetch) so Google can redirect the user
 * and set/read cookies. Session auth rides along via the same-site cookie.
 */
export function googleConnectUrl(): string {
  return `${API_BASE}/google/connect`;
}

/** Delete the current user's stored Google token. Returns true on success. */
export async function disconnectGoogle(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/google/disconnect`, {
      method: "POST",
      credentials: "include",
    });
    return res.ok;
  } catch {
    return false;
  }
}


export async function uploadFile(file: File): Promise<{ filename: string; path: string }> {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`${API_BASE}/api/upload`, {
    method: "POST",
    body: formData,
    credentials: "include",
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Upload failed ${res.status}: ${text}`);
  }

  return res.json();
}

export async function* resumeAgent(
  threadId: string,
  decision: "approve" | "reject",
  editedArgs?: Record<string, unknown>,
  signal?: AbortSignal
): AsyncGenerator<import("@/types/chat").StreamEvent> {
  const response = await fetch(`${API_BASE}/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    signal,
    body: JSON.stringify({
      thread_id: threadId,
      decision,
      ...(editedArgs ? { edited_args: editedArgs } : {}),
    }),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Resume failed ${response.status}: ${text}`);
  }

  const reader = response.body?.getReader();
  if (!reader) throw new Error("No response body from /resume");

  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const raw = line.slice(6).trim();
        if (!raw) continue;
        if (raw === "[DONE]") {
          return;
        }
        try {
          yield JSON.parse(raw) as import("@/types/chat").StreamEvent;
        } catch {
          // skip malformed
        }
      }
    }
  } finally {
    try { await reader.cancel(); } catch {}
  }
}
