"use client";

import React, { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";

import {
  createSession,
  createUser,
  decideApproval,
  getSession,
  getSessionMessages,
  listApprovals,
  listSessions,
  listSkills,
  listTools,
  listUsers,
  streamSessionMessage,
  updateUser,
} from "../lib/api";
import type { ActivityEntry, ApprovalItem, ConversationMessage, SessionItem, StreamEvent, UserProfile } from "../lib/types";

type ChatWorkspaceProps = {
  initialSessionId?: string;
};

type UserDraft = {
  username: string;
  displayName: string;
  note: string;
  defaultModel: string;
};

function emptyUserDraft(): UserDraft {
  return {
    username: "",
    displayName: "",
    note: "",
    defaultModel: "qwen-plus",
  };
}

function messageText(message: ConversationMessage) {
  return message.content
    .map((block) => {
      if (block.type === "text") {
        return block.text;
      }
      if (block.type === "tool_use") {
        return `调用工具：${block.name}\n${JSON.stringify(block.input, null, 2)}`;
      }
      return block.content;
    })
    .join("\n")
    .trim();
}

function hasVisibleText(message: ConversationMessage) {
  return messageText(message).length > 0;
}

function formatDate(value?: string) {
  if (!value) {
    return "-";
  }
  return new Date(value).toLocaleString("zh-CN");
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

function updateAddress(sessionId: string) {
  if (typeof window === "undefined") {
    return;
  }
  window.history.pushState(null, "", sessionId ? `/chat/${sessionId}` : "/");
}

export function ChatWorkspace({ initialSessionId }: ChatWorkspaceProps) {
  const formRef = useRef<HTMLFormElement | null>(null);
  const [users, setUsers] = useState<UserProfile[]>([]);
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [approvals, setApprovals] = useState<ApprovalItem[]>([]);
  const [selectedUserId, setSelectedUserId] = useState("");
  const [currentSessionId, setCurrentSessionId] = useState(initialSessionId ?? "");
  const [bootError, setBootError] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSwitchingSession, setIsSwitchingSession] = useState(false);
  const [draft, setDraft] = useState("");
  const [streamingReply, setStreamingReply] = useState("");
  const [activityEntries, setActivityEntries] = useState<ActivityEntry[]>([]);
  const [isSending, setIsSending] = useState(false);
  const [createUserOpen, setCreateUserOpen] = useState(false);
  const [createUserDraft, setCreateUserDraft] = useState<UserDraft>(emptyUserDraft());
  const [editUserDraft, setEditUserDraft] = useState<UserDraft>(emptyUserDraft());
  const [referenceCounts, setReferenceCounts] = useState({ skills: 0, tools: 0 });
  const [dialogApproval, setDialogApproval] = useState<ApprovalItem | null>(null);

  const currentUser = users.find((item) => item.user_id === selectedUserId) ?? null;
  const currentSession = sessions.find((item) => item.session_id === currentSessionId) ?? null;
  const currentApproval =
    dialogApproval ?? approvals.find((item) => item.session_id === currentSessionId) ?? approvals[0] ?? null;
  const hasVisibleMessages = messages.some(hasVisibleText);

  async function refreshSessions(userId: string, preferredSessionId?: string) {
    if (!userId) {
      setSessions([]);
      setCurrentSessionId("");
      setMessages([]);
      return "";
    }

    try {
      const sessionList = await listSessions(userId);
      setSessions(sessionList);

      const preferred =
        preferredSessionId && sessionList.some((item) => item.session_id === preferredSessionId)
          ? preferredSessionId
          : "";
      const currentStillExists = sessionList.some((item) => item.session_id === currentSessionId);
      const nextSessionId = preferred || (currentStillExists ? currentSessionId : "") || sessionList[0]?.session_id || "";

      if (nextSessionId && nextSessionId !== currentSessionId) {
        setCurrentSessionId(nextSessionId);
        updateAddress(nextSessionId);
      }
      if (!nextSessionId) {
        setMessages([]);
        updateAddress("");
      }
      return nextSessionId;
    } catch (error) {
      setBootError(errorMessage(error, "加载历史会话失败"));
      return currentSessionId;
    }
  }

  async function refreshMessages(sessionId: string) {
    if (!sessionId) {
      setMessages([]);
      return;
    }
    try {
      setMessages(await getSessionMessages(sessionId));
    } catch (error) {
      setBootError(errorMessage(error, "加载消息失败"));
    }
  }

  async function refreshApprovals(preferredSessionId = currentSessionId) {
    try {
      const approvalList = await listApprovals();
      setApprovals(approvalList);
      const preferred = approvalList.find((item) => item.session_id === preferredSessionId) ?? null;
      setDialogApproval((current) => current ?? preferred);
    } catch {
      // 审批列表失败不应影响主聊天体验。
    }
  }

  async function ensureSession(userId: string) {
    if (currentSessionId) {
      return currentSessionId;
    }
    const created = await createSession({
      user_id: userId,
      metadata: { user_id: userId },
    });
    await refreshSessions(userId, created.session_id);
    return created.session_id;
  }

  function handleStreamEvent(event: StreamEvent, sessionId: string) {
    switch (event.type) {
      case "assistant_text_delta":
        setStreamingReply((current) => current + event.text);
        return;
      case "assistant_turn_complete":
        setStreamingReply("");
        if (event.message) {
          setMessages((current) => [...current, event.message]);
        }
        return;
      case "tool_execution_started":
        setActivityEntries((current) => [
          ...current,
          {
            id: `${Date.now()}-${current.length}`,
            level: "info",
            title: `调用工具：${event.tool_name}`,
            detail: JSON.stringify(event.tool_input),
          },
        ]);
        return;
      case "tool_execution_completed":
        setActivityEntries((current) => [
          ...current,
          {
            id: `${Date.now()}-${current.length}`,
            level: event.is_error ? "error" : "success",
            title: event.is_error ? `工具失败：${event.tool_name}` : `工具完成：${event.tool_name}`,
            detail: event.output,
          },
        ]);
        return;
      case "status":
        setActivityEntries((current) => [
          ...current,
          {
            id: `${Date.now()}-${current.length}`,
            level: "info",
            title: "状态更新",
            detail: event.message,
          },
        ]);
        return;
      case "approval_required": {
        const approval: ApprovalItem = {
          approval_id: event.approval_id,
          session_id: sessionId,
          tool_name: event.tool_name,
          tool_use_id: "",
          tool_input: event.tool_input,
          status: "pending",
          reason: event.reason,
          actor: "web",
          trace_id: "",
          created_at: new Date().toISOString(),
        };
        setDialogApproval(approval);
        setApprovals((current) => [approval, ...current.filter((item) => item.approval_id !== approval.approval_id)]);
        return;
      }
      case "error":
        setBootError(event.message);
        return;
    }
  }

  async function runConversation(sessionId: string, payload: { message?: string; resume?: boolean }) {
    setIsSending(true);
    setBootError("");
    setStreamingReply("");
    setActivityEntries([]);
    try {
      await streamSessionMessage(sessionId, payload, (event) => handleStreamEvent(event, sessionId));
    } catch (error) {
      setBootError(errorMessage(error, "对话请求失败"));
    } finally {
      setIsSending(false);
      await refreshMessages(sessionId);
      if (selectedUserId) {
        await refreshSessions(selectedUserId, sessionId);
      }
      await refreshApprovals(sessionId);
    }
  }

  useEffect(() => {
    let mounted = true;

    async function bootstrap() {
      setIsLoading(true);
      setBootError("");
      try {
        const [userList, approvalResult, skillResult, toolResult] = await Promise.all([
          listUsers(),
          listApprovals().catch(() => []),
          listSkills().catch(() => []),
          listTools().catch(() => []),
        ]);

        if (!mounted) {
          return;
        }

        setUsers(userList);
        setApprovals(approvalResult);
        setReferenceCounts({ skills: skillResult.length, tools: toolResult.length });
        setCreateUserOpen(userList.length === 0);

        let nextUserId = "";
        if (typeof window !== "undefined") {
          const storedUserId = window.localStorage.getItem("agent.selectedUserId") ?? "";
          nextUserId = userList.some((item) => item.user_id === storedUserId) ? storedUserId : "";
        }

        if (initialSessionId) {
          try {
            const session = await getSession(initialSessionId);
            if (!mounted) {
              return;
            }
            setCurrentSessionId(session.session_id);
            nextUserId = session.user_id ?? nextUserId;
          } catch (error) {
            setBootError(errorMessage(error, "无法恢复 URL 中的会话"));
          }
        }

        setSelectedUserId(nextUserId || userList[0]?.user_id || "");
      } catch (error) {
        setBootError(errorMessage(error, "前端初始化失败"));
      } finally {
        if (mounted) {
          setIsLoading(false);
        }
      }
    }

    void bootstrap();
    return () => {
      mounted = false;
    };
  }, [initialSessionId]);

  useEffect(() => {
    if (!currentUser) {
      setEditUserDraft(emptyUserDraft());
      return;
    }
    setEditUserDraft({
      username: currentUser.username,
      displayName: currentUser.display_name,
      note: currentUser.note,
      defaultModel: currentUser.default_model || "qwen-plus",
    });
  }, [currentUser]);

  useEffect(() => {
    if (!selectedUserId) {
      setSessions([]);
      setMessages([]);
      return;
    }
    if (typeof window !== "undefined") {
      window.localStorage.setItem("agent.selectedUserId", selectedUserId);
    }
    void refreshSessions(selectedUserId, currentSessionId || initialSessionId);
  }, [selectedUserId]);

  useEffect(() => {
    void refreshMessages(currentSessionId);
  }, [currentSessionId]);

  useEffect(() => {
    void refreshApprovals(currentSessionId);
    const timer = window.setInterval(() => {
      void refreshApprovals(currentSessionId);
    }, 8000);
    return () => window.clearInterval(timer);
  }, [currentSessionId]);

  function handleSelectSession(sessionId: string) {
    if (sessionId === currentSessionId || isSwitchingSession) {
      return;
    }
    setIsSwitchingSession(true);
    setBootError("");
    setStreamingReply("");
    setActivityEntries([]);
    setCurrentSessionId(sessionId);
    updateAddress(sessionId);
    void refreshMessages(sessionId).finally(() => setIsSwitchingSession(false));
  }

  async function handleCreateSession(userIdOverride?: string) {
    const targetUserId = userIdOverride || selectedUserId;
    if (!targetUserId) {
      setCreateUserOpen(true);
      return;
    }
    try {
      const created = await createSession({
        user_id: targetUserId,
        metadata: { user_id: targetUserId },
      });
      await refreshSessions(targetUserId, created.session_id);
    } catch (error) {
      setBootError(errorMessage(error, "创建会话失败"));
    }
  }

  async function handleCreateUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const username = createUserDraft.username.trim();
    const displayName = createUserDraft.displayName.trim();
    if (!username || !displayName) {
      setBootError("请填写用户名和显示名。");
      return;
    }
    try {
      const created = await createUser({
        username,
        display_name: displayName,
        note: createUserDraft.note,
        default_model: createUserDraft.defaultModel || "qwen-plus",
        preferences: {},
      });
      setUsers(await listUsers());
      setSelectedUserId(created.user_id);
      setCreateUserDraft(emptyUserDraft());
      setCreateUserOpen(false);
      await handleCreateSession(created.user_id);
    } catch (error) {
      setBootError(errorMessage(error, "创建用户失败"));
    }
  }

  async function handleSaveUser() {
    if (!currentUser) {
      return;
    }
    try {
      await updateUser(currentUser.user_id, {
        display_name: editUserDraft.displayName,
        note: editUserDraft.note,
        default_model: editUserDraft.defaultModel || "qwen-plus",
        preferences: {},
      });
      setUsers(await listUsers());
    } catch (error) {
      setBootError(errorMessage(error, "保存用户资料失败"));
    }
  }

  async function submitDraft() {
    const content = draft.trim();
    if (!content || isSending) {
      return;
    }
    if (!selectedUserId) {
      setCreateUserOpen(true);
      return;
    }

    const sessionId = await ensureSession(selectedUserId);
    setDraft("");
    setMessages((current) => [
      ...current,
      {
        role: "user",
        content: [{ type: "text", text: content }],
      },
    ]);
    await runConversation(sessionId, { message: content, resume: false });
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submitDraft();
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) {
      return;
    }
    event.preventDefault();
    formRef.current?.requestSubmit();
  }

  async function handleApprovalDecision(approved: boolean) {
    if (!currentApproval) {
      return;
    }
    await decideApproval(currentApproval.approval_id, approved);
    setDialogApproval(null);
    await runConversation(currentApproval.session_id, { resume: true });
  }

  if (isLoading) {
    return <main className="shell shell-loading">正在加载智能体工作区...</main>;
  }

  return (
    <>
      <main className="shell">
        <aside className="shell-sidebar">
          <div className="sidebar-header">
            <h1>智能体工作台</h1>
            <p>多用户、多会话、流式交互</p>
          </div>

          <div className="sidebar-actions">
            <button className="primary-button" type="button" onClick={() => setCreateUserOpen(true)}>
              新建用户
            </button>
            <button className="secondary-button" type="button" onClick={() => void handleCreateSession()}>
              新建会话
            </button>
          </div>

          <label className="field">
            <span>当前用户</span>
            <select
              value={selectedUserId}
              onChange={(event) => {
                setSelectedUserId(event.target.value);
                setCurrentSessionId("");
                setMessages([]);
                updateAddress("");
              }}
            >
              <option value="">请选择用户</option>
              {users.map((user) => (
                <option key={user.user_id} value={user.user_id}>
                  {user.display_name}
                </option>
              ))}
            </select>
          </label>

          <div className="session-list">
            <div className="section-title">历史会话</div>
            {sessions.map((session) => (
              <button
                key={session.session_id}
                className={session.session_id === currentSessionId ? "session-item active" : "session-item"}
                type="button"
                onClick={() => handleSelectSession(session.session_id)}
              >
                <strong>{session.title}</strong>
                <span>{session.last_message_preview || "暂无消息"}</span>
              </button>
            ))}
            {!sessions.length && <div className="empty-hint">当前用户还没有会话。</div>}
          </div>
        </aside>

        <section className="shell-main">
          <header className="main-header">
            <div>
              <h2>{currentSession?.title ?? "欢迎使用智能体前端"}</h2>
              <p>{currentSession?.summary || "请选择用户并创建会话，然后开始与智能体对话。"}</p>
            </div>
            {currentApproval ? <span className="approval-badge">待审批：{currentApproval.tool_name}</span> : null}
          </header>

          {bootError ? <div className="error-banner">{bootError}</div> : null}

          <div className="message-list" aria-busy={isSending || isSwitchingSession}>
            {activityEntries.length ? (
              <div className="activity-list">
                {activityEntries.map((entry) => (
                  <div key={entry.id} className={`activity-card ${entry.level}`}>
                    <strong>{entry.title}</strong>
                    <span>{entry.detail}</span>
                  </div>
                ))}
              </div>
            ) : null}
            {messages.map((message, index) => {
              const text = messageText(message);
              if (!text) {
                return null;
              }
              return (
                <article key={`${message.role}-${index}`} className={`message-card ${message.role}`}>
                  <span className="message-role">{message.role === "user" ? "用户" : "助手"}</span>
                  <p>{text}</p>
                </article>
              );
            })}
            {streamingReply ? (
              <article className="message-card assistant streaming">
                <span className="message-role">助手正在回复</span>
                <p>
                  {streamingReply}
                  <span className="typing-cursor" aria-hidden="true" />
                </p>
              </article>
            ) : null}
            {!hasVisibleMessages && !streamingReply && !activityEntries.length && (
              <div className="empty-state">
                <h3>准备开始新的对话</h3>
                <p>当前版本已接入用户、会话、审批和流式消息主链路。</p>
              </div>
            )}
          </div>

          <form ref={formRef} className="composer chatgpt-composer" onSubmit={handleSubmit}>
            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={handleComposerKeyDown}
              placeholder="输入消息，Enter 发送，Shift + Enter 换行"
              rows={3}
            />
            <div className="composer-actions">
              <span>{isSending ? "正在回复..." : "Enter 发送，Shift + Enter 换行"}</span>
              <button className="primary-button send-button" type="submit" disabled={isSending || !draft.trim()}>
                {isSending ? "发送中" : "发送"}
              </button>
            </div>
          </form>
        </section>

        <aside className="shell-panel">
          <div className="panel-card">
            <div className="section-title">用户信息</div>
            {currentUser ? (
              <>
                <label className="field compact">
                  <span>用户名</span>
                  <input value={editUserDraft.username} disabled />
                </label>
                <label className="field compact">
                  <span>显示名</span>
                  <input
                    value={editUserDraft.displayName}
                    onChange={(event) =>
                      setEditUserDraft((current) => ({ ...current, displayName: event.target.value }))
                    }
                  />
                </label>
                <label className="field compact">
                  <span>默认模型</span>
                  <input
                    value={editUserDraft.defaultModel}
                    onChange={(event) =>
                      setEditUserDraft((current) => ({ ...current, defaultModel: event.target.value }))
                    }
                  />
                </label>
                <label className="field compact">
                  <span>备注</span>
                  <textarea
                    value={editUserDraft.note}
                    onChange={(event) => setEditUserDraft((current) => ({ ...current, note: event.target.value }))}
                    rows={3}
                  />
                </label>
                <button className="secondary-button" type="button" onClick={() => void handleSaveUser()}>
                  保存用户资料
                </button>
              </>
            ) : (
              <div className="empty-hint">还没有用户。</div>
            )}
          </div>

          <div className="panel-card">
            <div className="section-title">会话与能力</div>
            {currentSession ? (
              <>
                <div className="kv-row">
                  <span>消息数</span>
                  <strong>{currentSession.message_count}</strong>
                </div>
                <div className="kv-row">
                  <span>状态</span>
                  <strong>{currentSession.status}</strong>
                </div>
                <div className="kv-row">
                  <span>最后更新</span>
                  <strong>{formatDate(currentSession.updated_at)}</strong>
                </div>
              </>
            ) : (
              <div className="empty-hint">请选择一个会话。</div>
            )}
            <div className="kv-row">
              <span>Skills</span>
              <strong>{referenceCounts.skills}</strong>
            </div>
            <div className="kv-row">
              <span>Tools</span>
              <strong>{referenceCounts.tools}</strong>
            </div>
          </div>

          <div className="panel-card">
            <div className="section-title">审批状态</div>
            {currentApproval ? (
              <>
                <div className="kv-row">
                  <span>工具</span>
                  <strong>{currentApproval.tool_name}</strong>
                </div>
                <p className="approval-reason">{currentApproval.reason}</p>
                <button className="secondary-button" type="button" onClick={() => setDialogApproval(currentApproval)}>
                  处理审批
                </button>
              </>
            ) : (
              <div className="empty-hint">暂无待审批操作。</div>
            )}
          </div>
        </aside>
      </main>

      {createUserOpen ? (
        <div className="modal-backdrop">
          <div className="modal-card">
            <h3>创建用户</h3>
            <form className="modal-form" onSubmit={handleCreateUser}>
              <label className="field compact">
                <span>用户名</span>
                <input
                  value={createUserDraft.username}
                  onChange={(event) =>
                    setCreateUserDraft((current) => ({ ...current, username: event.target.value }))
                  }
                />
              </label>
              <label className="field compact">
                <span>显示名</span>
                <input
                  value={createUserDraft.displayName}
                  onChange={(event) =>
                    setCreateUserDraft((current) => ({ ...current, displayName: event.target.value }))
                  }
                />
              </label>
              <label className="field compact">
                <span>默认模型</span>
                <input
                  value={createUserDraft.defaultModel}
                  onChange={(event) =>
                    setCreateUserDraft((current) => ({ ...current, defaultModel: event.target.value }))
                  }
                />
              </label>
              <label className="field compact">
                <span>备注</span>
                <textarea
                  rows={3}
                  value={createUserDraft.note}
                  onChange={(event) => setCreateUserDraft((current) => ({ ...current, note: event.target.value }))}
                />
              </label>
              <div className="modal-actions">
                <button className="secondary-button" type="button" onClick={() => setCreateUserOpen(false)}>
                  取消
                </button>
                <button className="primary-button" type="submit">
                  创建并开始对话
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}

      {dialogApproval ? (
        <div className="modal-backdrop">
          <div className="modal-card">
            <h3>需要审批</h3>
            <p className="approval-reason">{dialogApproval.reason}</p>
            <pre className="json-preview">{JSON.stringify(dialogApproval.tool_input, null, 2)}</pre>
            <div className="modal-actions">
              <button className="secondary-button" type="button" onClick={() => void handleApprovalDecision(false)}>
                拒绝
              </button>
              <button className="primary-button" type="button" onClick={() => void handleApprovalDecision(true)}>
                批准并继续
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
