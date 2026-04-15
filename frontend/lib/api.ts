import { consumeSseStream } from "./sse";
import type { ApprovalItem, ConversationMessage, SessionItem, SkillDescriptor, StreamEvent, ToolDescriptor, UserProfile } from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_AGENT_API_BASE_URL ?? "http://127.0.0.1:8000";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

export function listUsers() {
  return apiFetch<UserProfile[]>("/v2/users");
}

export function createUser(payload: {
  username: string;
  display_name: string;
  note: string;
  default_model: string;
  preferences: Record<string, unknown>;
}) {
  return apiFetch<UserProfile>("/v2/users", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateUser(
  userId: string,
  payload: Partial<{
    display_name: string;
    note: string;
    default_model: string;
    preferences: Record<string, unknown>;
  }>,
) {
  return apiFetch<UserProfile>(`/v2/users/${userId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function listSessions(userId?: string) {
  const query = userId ? `?user_id=${encodeURIComponent(userId)}` : "";
  return apiFetch<SessionItem[]>(`/v2/sessions${query}`);
}

export function createSession(payload: { title?: string; user_id?: string; metadata?: Record<string, unknown> }) {
  return apiFetch<SessionItem>("/v2/sessions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getSession(sessionId: string) {
  return apiFetch<SessionItem>(`/v2/sessions/${sessionId}`);
}

export function getSessionMessages(sessionId: string) {
  return apiFetch<ConversationMessage[]>(`/v2/sessions/${sessionId}/messages`);
}

export function listApprovals(status = "pending") {
  return apiFetch<ApprovalItem[]>(`/v2/approvals?status=${encodeURIComponent(status)}`);
}

export function decideApproval(approvalId: string, approved: boolean) {
  return apiFetch<{ approval_id: string; status: string }>(`/v2/approvals/${approvalId}/decision`, {
    method: "POST",
    body: JSON.stringify({ approved }),
  });
}

export function listSkills() {
  return apiFetch<SkillDescriptor[]>("/v2/skills");
}

export function listTools() {
  return apiFetch<ToolDescriptor[]>("/v2/tools");
}

export async function streamSessionMessage(
  sessionId: string,
  payload: { message?: string; resume?: boolean },
  onEvent: (event: StreamEvent) => void,
) {
  const response = await fetch(`${API_BASE_URL}/v2/sessions/${sessionId}/messages/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok || !response.body) {
    const detail = await response.text();
    throw new Error(detail || `Stream request failed: ${response.status}`);
  }
  await consumeSseStream(response.body, (event) => onEvent(event as StreamEvent));
}
