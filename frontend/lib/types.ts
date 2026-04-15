export type MessageRole = "user" | "assistant";

export interface UserProfile {
  user_id: string;
  username: string;
  display_name: string;
  note: string;
  default_model: string;
  preferences: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface SessionItem {
  session_id: string;
  user_id: string | null;
  title: string;
  model_name: string;
  summary: string;
  metadata: Record<string, unknown>;
  status: string;
  pending_approval_id: string | null;
  message_count: number;
  last_message_preview: string;
  created_at: string;
  updated_at: string;
}

export interface TextBlock {
  type: "text";
  text: string;
}

export interface ToolUseBlock {
  type: "tool_use";
  id: string;
  name: string;
  input: Record<string, unknown>;
}

export interface ToolResultBlock {
  type: "tool_result";
  tool_use_id: string;
  content: string;
  is_error?: boolean;
}

export type ContentBlock = TextBlock | ToolUseBlock | ToolResultBlock;

export interface ConversationMessage {
  role: MessageRole;
  content: ContentBlock[];
}

export interface ApprovalItem {
  approval_id: string;
  session_id: string;
  tool_name: string;
  tool_use_id: string;
  tool_input: Record<string, unknown>;
  status: string;
  reason: string;
  actor: string;
  trace_id: string;
  created_at: string;
}

export interface ToolDescriptor {
  name: string;
  description: string;
  schema: Record<string, unknown>;
}

export interface SkillDescriptor {
  id: string;
  name: string;
  description: string;
}

export type StreamEvent =
  | { type: "assistant_text_delta"; text: string }
  | { type: "assistant_turn_complete"; message: ConversationMessage; usage: Record<string, number> }
  | { type: "tool_execution_started"; tool_name: string; tool_input: Record<string, unknown> }
  | { type: "tool_execution_completed"; tool_name: string; output: string; is_error: boolean }
  | { type: "approval_required"; approval_id: string; tool_name: string; tool_input: Record<string, unknown>; reason: string }
  | { type: "status"; message: string }
  | { type: "error"; message: string };

export interface ActivityEntry {
  id: string;
  level: "info" | "success" | "warning" | "error";
  title: string;
  detail: string;
}
