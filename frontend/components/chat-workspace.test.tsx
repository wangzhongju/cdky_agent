import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatWorkspace } from "./chat-workspace";
import type { ApprovalItem, ConversationMessage, SessionItem, UserProfile } from "../lib/types";

const api = vi.hoisted(() => ({
  createSession: vi.fn(),
  createUser: vi.fn(),
  decideApproval: vi.fn(),
  getSession: vi.fn(),
  getSessionMessages: vi.fn(),
  listApprovals: vi.fn(),
  listSessions: vi.fn(),
  listSkills: vi.fn(),
  listTools: vi.fn(),
  listUsers: vi.fn(),
  streamSessionMessage: vi.fn(),
  updateUser: vi.fn(),
}));

vi.mock("../lib/api", () => api);

const user: UserProfile = {
  user_id: "user-1",
  username: "demo",
  display_name: "测试用户",
  note: "默认用户",
  default_model: "qwen-plus",
  preferences: {},
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const sessionA: SessionItem = {
  session_id: "session-1",
  user_id: "user-1",
  title: "测试会话 A",
  model_name: "qwen-plus",
  summary: "",
  metadata: {},
  status: "active",
  pending_approval_id: null,
  message_count: 1,
  last_message_preview: "你好 A",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const sessionB: SessionItem = {
  ...sessionA,
  session_id: "session-2",
  title: "测试会话 B",
  last_message_preview: "你好 B",
};

const messagesA: ConversationMessage[] = [
  {
    role: "assistant",
    content: [{ type: "text", text: "欢迎回来 A" }],
  },
];

const messagesB: ConversationMessage[] = [
  {
    role: "assistant",
    content: [{ type: "text", text: "欢迎回来 B" }],
  },
];

const approval: ApprovalItem = {
  approval_id: "approval-1",
  session_id: "session-1",
  tool_name: "write_file",
  tool_use_id: "tool-use-1",
  tool_input: { path: "demo.txt" },
  status: "pending",
  reason: "写文件需要审批",
  actor: "web",
  trace_id: "",
  created_at: "2026-01-01T00:00:00Z",
};

function setupDefaultMocks() {
  api.listUsers.mockResolvedValue([user]);
  api.listApprovals.mockResolvedValue([]);
  api.listSkills.mockResolvedValue([{ id: "report", name: "报告", description: "生成报告" }]);
  api.listTools.mockResolvedValue([{ name: "read_file", description: "读取文件", schema: {} }]);
  api.listSessions.mockResolvedValue([sessionA, sessionB]);
  api.getSession.mockResolvedValue(sessionA);
  api.getSessionMessages.mockImplementation(async (sessionId: string) => (sessionId === "session-2" ? messagesB : messagesA));
  api.createSession.mockResolvedValue(sessionA);
  api.createUser.mockResolvedValue(user);
  api.updateUser.mockResolvedValue(user);
  api.decideApproval.mockResolvedValue({ approval_id: "approval-1", status: "approved" });
  api.streamSessionMessage.mockImplementation(async (_sessionId, _payload, onEvent) => {
    onEvent({ type: "assistant_text_delta", text: "收到" });
    onEvent({
      type: "assistant_turn_complete",
      message: { role: "assistant", content: [{ type: "text", text: "收到" }] },
      usage: {},
    });
  });
}

describe("ChatWorkspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    window.history.pushState(null, "", "/");
    setupDefaultMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("renders the Chinese workspace with users and sessions", async () => {
    render(<ChatWorkspace />);

    expect(await screen.findByText("智能体工作台")).toBeInTheDocument();
    expect(await screen.findByText("测试用户")).toBeInTheDocument();
    expect((await screen.findAllByText("测试会话 A")).length).toBeGreaterThan(0);
    expect(await screen.findByText("欢迎回来 A")).toBeInTheDocument();
  });

  it("creates a user and opens the first session", async () => {
    const createdUser = { ...user, user_id: "user-2", username: "new-user", display_name: "新用户" };
    const createdSession = { ...sessionA, session_id: "session-new", user_id: "user-2", title: "新对话" };
    api.listUsers.mockResolvedValueOnce([]).mockResolvedValueOnce([createdUser]);
    api.createUser.mockResolvedValue(createdUser);
    api.createSession.mockResolvedValue(createdSession);
    api.listSessions.mockResolvedValue([createdSession]);

    render(<ChatWorkspace />);

    const usernameInputs = await screen.findAllByLabelText("用户名");
    const displayNameInputs = screen.getAllByLabelText("显示名");
    fireEvent.change(usernameInputs[usernameInputs.length - 1], { target: { value: "new-user" } });
    fireEvent.change(displayNameInputs[displayNameInputs.length - 1], { target: { value: "新用户" } });
    fireEvent.click(screen.getByRole("button", { name: "创建并开始对话" }));

    await waitFor(() => expect(api.createUser).toHaveBeenCalledWith(expect.objectContaining({ username: "new-user" })));
    await waitFor(() => expect(api.createSession).toHaveBeenCalledWith(expect.objectContaining({ user_id: "user-2" })));
  });

  it("uses Enter to send and Shift+Enter to insert a newline", async () => {
    render(<ChatWorkspace />);

    const input = await screen.findByPlaceholderText("输入消息，Enter 发送，Shift + Enter 换行");
    fireEvent.change(input, { target: { value: "第一行" } });
    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });

    expect(api.streamSessionMessage).not.toHaveBeenCalled();

    fireEvent.keyDown(input, { key: "Enter", shiftKey: false });

    await waitFor(() =>
      expect(api.streamSessionMessage).toHaveBeenCalledWith(
        "session-1",
        { message: "第一行", resume: false },
        expect.any(Function),
      ),
    );
  });

  it("switches sessions without clearing the history list", async () => {
    render(<ChatWorkspace />);

    expect((await screen.findAllByText("测试会话 A")).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: /测试会话 B/ }));

    expect(await screen.findByText("欢迎回来 B")).toBeInTheDocument();
    expect(screen.getAllByText("测试会话 A").length).toBeGreaterThan(0);
    expect(screen.getAllByText("测试会话 B").length).toBeGreaterThan(0);
    expect(window.location.pathname).toBe("/chat/session-2");
  });

  it("shows tool activity and tool outputs during tool calls", async () => {
    let weatherHistory = messagesA;
    api.getSessionMessages.mockImplementation(async () => weatherHistory);
    api.streamSessionMessage.mockImplementation(async (_sessionId, _payload, onEvent) => {
      onEvent({ type: "tool_execution_started", tool_name: "mcp__gaode__get_weather", tool_input: { city: "北京" } });
      await new Promise((resolve) => setTimeout(resolve, 50));
      onEvent({
        type: "tool_execution_completed",
        tool_name: "mcp__gaode__get_weather",
        output: "北京，晴，18度",
        is_error: false,
      });
      onEvent({ type: "assistant_text_delta", text: "北京现在天气晴朗，约 18 度。" });
      const finalMessage: ConversationMessage = {
        role: "assistant",
        content: [{ type: "text", text: "北京现在天气晴朗，约 18 度。" }],
      };
      weatherHistory = [
        ...messagesA,
        { role: "user", content: [{ type: "text", text: "现在天气怎么样？" }] },
        finalMessage,
      ];
      onEvent({
        type: "assistant_turn_complete",
        message: finalMessage,
        usage: {},
      });
    });

    render(<ChatWorkspace />);

    const input = await screen.findByPlaceholderText("输入消息，Enter 发送，Shift + Enter 换行");
    fireEvent.change(input, { target: { value: "现在天气怎么样？" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(await screen.findByText("调用工具：mcp__gaode__get_weather")).toBeInTheDocument();
    expect(await screen.findByText("工具完成：mcp__gaode__get_weather")).toBeInTheDocument();
    expect(await screen.findByText("北京，晴，18度")).toBeInTheDocument();
    expect(await screen.findByText("北京现在天气晴朗，约 18 度。")).toBeInTheDocument();
  });

  it("renders tool-result-only history messages", async () => {
    api.getSessionMessages.mockResolvedValue([
      { role: "assistant", content: [{ type: "tool_result", tool_use_id: "tool-1", content: "内部工具结果" }] },
      { role: "assistant", content: [{ type: "text", text: "这是最终回答" }] },
    ]);

    render(<ChatWorkspace />);

    expect(await screen.findByText("内部工具结果")).toBeInTheDocument();
    expect(await screen.findByText("这是最终回答")).toBeInTheDocument();
  });

  it("approves pending tool calls and resumes the session", async () => {
    api.listApprovals.mockResolvedValue([approval]);
    render(<ChatWorkspace />);

    expect(await screen.findByText("待审批：write_file")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "处理审批" }));
    fireEvent.click(await screen.findByRole("button", { name: "批准并继续" }));

    await waitFor(() => expect(api.decideApproval).toHaveBeenCalledWith("approval-1", true));
    await waitFor(() =>
      expect(api.streamSessionMessage).toHaveBeenCalledWith("session-1", { resume: true }, expect.any(Function)),
    );
  });
});
