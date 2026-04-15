from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from typing import Any

import requests
import streamlit as st


API_BASE_URL = os.getenv("AGENT_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
API_KEY = os.getenv("AGENT_API_KEY", "streamlit-user")

st.set_page_config(page_title="Agent Console", layout="wide")


def ensure_state() -> None:
    defaults = {
        "messages": [],
        "session_id": "",
        "pending_approval": None,
        "resume_requested": False,
        "latest_usage": None,
        "timeline": [],
        "approval_history": [],
        "error_message": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def reset_chat() -> None:
    st.session_state["messages"] = []
    st.session_state["session_id"] = ""
    st.session_state["pending_approval"] = None
    st.session_state["resume_requested"] = False
    st.session_state["latest_usage"] = None
    st.session_state["timeline"] = []
    st.session_state["approval_history"] = []
    st.session_state["error_message"] = ""


def current_session_id() -> str:
    if not st.session_state["session_id"]:
        st.session_state["session_id"] = str(uuid.uuid4())
    return st.session_state["session_id"]


def build_headers() -> dict[str, str]:
    return {
        "x-api-key": API_KEY,
        "x-trace-id": str(uuid.uuid4()),
    }


def append_message(role: str, content: str) -> None:
    content = content.strip()
    if not content:
        return
    st.session_state["messages"].append({"role": role, "content": content})


def add_timeline_entry(
    kind: str,
    title: str,
    detail: str = "",
    *,
    status: str = "info",
    meta: dict[str, Any] | None = None,
) -> None:
    entry = {
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "kind": kind,
        "title": title,
        "detail": detail.strip(),
        "status": status,
        "meta": meta or {},
    }
    st.session_state["timeline"] = [entry, *st.session_state["timeline"][:39]]


def track_approval_history(decision: str, approval_id: str, reason: str = "") -> None:
    record = {
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "decision": decision,
        "approval_id": approval_id,
        "reason": reason.strip(),
    }
    st.session_state["approval_history"] = [record, *st.session_state["approval_history"][:9]]


def session_stats() -> dict[str, int]:
    messages = st.session_state["messages"]
    timeline = st.session_state["timeline"]
    tool_events = [item for item in timeline if item["kind"] == "tool"]
    approval_events = [item for item in timeline if item["kind"] == "approval"]
    return {
        "message_count": len(messages),
        "assistant_count": sum(1 for item in messages if item["role"] == "assistant"),
        "tool_events": len(tool_events),
        "approval_events": len(approval_events),
    }


def iter_ndjson(path: str, payload: dict[str, Any]):
    response = requests.post(
        f"{API_BASE_URL}{path}",
        json=payload,
        headers=build_headers(),
        stream=True,
        timeout=300,
    )
    response.raise_for_status()
    response.encoding = "utf-8"
    for line in response.iter_lines(decode_unicode=True):
        if line and line.strip():
            yield json.loads(line)


def handle_stream(path: str, payload: dict[str, Any], *, render_in_chat: bool = True) -> str:
    assistant_chunks: list[str] = []
    assistant_complete = ""
    approval_event: dict[str, Any] | None = None
    assistant_placeholder = None

    if render_in_chat:
        assistant_placeholder = st.chat_message("assistant").empty()

    for event in iter_ndjson(path, payload):
        session_id = event.get("session_id")
        if session_id:
            st.session_state["session_id"] = session_id

        event_type = event.get("type", "")
        if event_type == "assistant_delta":
            assistant_chunks.append(event.get("text", ""))
            if assistant_placeholder is not None:
                assistant_placeholder.markdown("".join(assistant_chunks))
        elif event_type == "assistant_complete":
            message = event.get("message", {}) or {}
            content = str(message.get("content", "") or "")
            if content:
                assistant_complete = content
                add_timeline_entry(
                    "assistant",
                    "Assistant response completed",
                    content[:400],
                    status="success",
                )
                if assistant_placeholder is not None:
                    assistant_placeholder.markdown(content)
        elif event_type == "tool_start":
            add_timeline_entry(
                "tool",
                f"Started {event.get('tool_name', 'unknown')}",
                json.dumps(event.get("tool_input", {}), ensure_ascii=False, indent=2),
                meta={"tool_name": event.get("tool_name", "unknown")},
            )
        elif event_type == "tool_result":
            add_timeline_entry(
                "tool",
                f"Finished {event.get('tool_name', 'unknown')}",
                str(event.get("output", ""))[:800],
                status="error" if event.get("is_error") else "success",
                meta={
                    "tool_name": event.get("tool_name", "unknown"),
                    "is_error": bool(event.get("is_error")),
                },
            )
        elif event_type == "status":
            add_timeline_entry("status", "Status", str(event.get("message", "")))
        elif event_type == "retry":
            add_timeline_entry(
                "retry",
                f"Retry {event.get('attempt', 0)}/{event.get('max_attempts', 0)}",
                str(event.get("message", "")),
                status="warning",
            )
        elif event_type == "usage":
            st.session_state["latest_usage"] = event
            add_timeline_entry(
                "usage",
                "Usage updated",
                (
                    f"input={event.get('input_tokens', 0)} "
                    f"output={event.get('output_tokens', 0)} "
                    f"cost={event.get('estimated_cost', 0)}"
                ),
                status="success",
                meta=event,
            )
        elif event_type == "approval_required":
            approval_event = event
            st.session_state["pending_approval"] = event
            add_timeline_entry(
                "approval",
                "Approval required",
                str(event.get("reason", "")),
                status="warning",
                meta=event,
            )
        elif event_type == "approval_decision":
            decision = str(event.get("decision", ""))
            add_timeline_entry(
                "approval",
                f"Approval {decision}",
                event.get("approval_id", ""),
                status="success" if decision == "approve" else "warning",
                meta=event,
            )
            track_approval_history(decision, event.get("approval_id", ""))
        elif event_type == "error":
            error_message = str(event.get("message", "Unknown error"))
            st.session_state["error_message"] = error_message
            add_timeline_entry("error", "Error", error_message, status="error")
            if assistant_placeholder is not None and not assistant_chunks and not assistant_complete:
                assistant_placeholder.error(error_message)

    final_text = assistant_complete or "".join(assistant_chunks).strip()
    if final_text:
        append_message("assistant", final_text)
    elif approval_event:
        notice = "Approval is required before the assistant can continue."
        if assistant_placeholder is not None:
            assistant_placeholder.info(notice)
    return final_text


def submit_approval(decision: str) -> None:
    approval = st.session_state.get("pending_approval")
    if not approval:
        return

    try:
        response = requests.post(
            f"{API_BASE_URL}/v1/approvals/{approval['approval_id']}",
            json={"decision": decision},
            headers=build_headers(),
            timeout=60,
        )
        response.raise_for_status()
        st.session_state["pending_approval"] = None
        st.session_state["resume_requested"] = True
        st.session_state["error_message"] = ""
        add_timeline_entry(
            "approval",
            f"Approval submitted: {decision}",
            approval["approval_id"],
            status="success" if decision == "approve" else "warning",
            meta=approval,
        )
        track_approval_history(decision, approval["approval_id"], approval.get("reason", ""))
    except Exception as exc:
        st.session_state["error_message"] = f"Failed to submit approval: {exc}"


@st.dialog("Approval Required")
def approval_dialog() -> None:
    approval = st.session_state.get("pending_approval")
    if not approval:
        return

    st.write("The assistant wants to use one or more tools before it can continue.")
    st.caption(str(approval.get("reason", "")))

    for tool in approval.get("tools", []):
        with st.container(border=True):
            st.markdown(f"**{tool.get('name', 'unknown')}**")
            reason = str(tool.get("reason", "")).strip()
            if reason:
                st.caption(reason)
            st.code(json.dumps(tool.get("arguments", {}), ensure_ascii=False, indent=2), language="json")

    approve_col, deny_col = st.columns(2)
    if approve_col.button("Approve", type="primary", use_container_width=True):
        submit_approval("approve")
        st.rerun()
    if deny_col.button("Deny", use_container_width=True):
        submit_approval("deny")
        st.rerun()


def render_sidebar() -> None:
    stats = session_stats()
    usage = st.session_state.get("latest_usage")
    pending_approval = st.session_state.get("pending_approval")
    approval_history = st.session_state.get("approval_history", [])
    recent_tools = [
        item
        for item in st.session_state.get("timeline", [])
        if item["kind"] == "tool"
    ][:6]

    with st.sidebar:
        st.subheader("Session Overview")
        st.code(st.session_state["session_id"] or "(new session)")
        top_left, top_right = st.columns(2)
        top_left.metric("Messages", stats["message_count"])
        top_right.metric("Assistant", stats["assistant_count"])
        bottom_left, bottom_right = st.columns(2)
        bottom_left.metric("Tool events", stats["tool_events"])
        bottom_right.metric("Approvals", stats["approval_events"])

        if st.button("New Session", use_container_width=True):
            reset_chat()
            st.rerun()

        st.divider()
        st.subheader("Approval State")
        if pending_approval:
            st.warning("Waiting for approval")
            st.caption(pending_approval.get("reason", ""))
            for tool in pending_approval.get("tools", []):
                st.markdown(f"- `{tool.get('name', 'unknown')}`")
        else:
            st.success("No pending approval")

        if approval_history:
            with st.expander("Recent approval decisions", expanded=False):
                for item in approval_history:
                    st.markdown(
                        f"**{item['timestamp']}**  `{item['decision']}`  `{item['approval_id'][:8]}`"
                    )
                    if item["reason"]:
                        st.caption(item["reason"])

        st.divider()
        st.subheader("Usage and Cost")
        if usage:
            st.metric("Input tokens", usage.get("input_tokens", 0))
            st.metric("Output tokens", usage.get("output_tokens", 0))
            st.metric("Estimated cost", usage.get("estimated_cost", 0))
            st.caption(f"Model: {usage.get('model_name', '-')}")
        else:
            st.caption("No usage data yet.")

        st.divider()
        st.subheader("Recent Tool Activity")
        if recent_tools:
            for item in recent_tools:
                st.markdown(f"**{item['timestamp']}**  {item['title']}")
                if item["detail"]:
                    st.caption(item["detail"][:180])
        else:
            st.caption("No tool activity yet.")


def timeline_style(status: str) -> tuple[str, str]:
    if status == "success":
        return "success", "Success"
    if status == "warning":
        return "warning", "Attention"
    if status == "error":
        return "error", "Error"
    return "info", "Info"


def render_timeline() -> None:
    st.subheader("Run Timeline")
    timeline = st.session_state.get("timeline", [])
    if not timeline:
        st.caption("Events from tool execution, approvals, retries, and usage will appear here.")
        return

    for item in timeline:
        status_type, label = timeline_style(item["status"])
        with st.container(border=True):
            header_left, header_right = st.columns([4, 1])
            header_left.markdown(f"**{item['title']}**")
            header_right.caption(item["timestamp"])
            st.caption(f"{item['kind'].upper()}  |  {label}")
            if item["detail"]:
                if item["kind"] in {"tool", "approval"} and ("{" in item["detail"] or "\n" in item["detail"]):
                    st.code(item["detail"], language="json" if item["detail"].lstrip().startswith("{") else None)
                else:
                    getattr(st, status_type)(item["detail"])


def render_messages() -> None:
    for message in st.session_state["messages"]:
        st.chat_message(message["role"]).write(message["content"])


def maybe_resume_after_approval() -> None:
    if not st.session_state.get("resume_requested") or not st.session_state.get("session_id"):
        return

    st.session_state["resume_requested"] = False
    st.session_state["error_message"] = ""
    try:
        with st.spinner("Resuming conversation..."):
            handle_stream(
                "/v1/chat/resume",
                {"session_id": st.session_state["session_id"]},
                render_in_chat=True,
            )
    except Exception as exc:
        st.session_state["error_message"] = f"Failed to resume conversation: {exc}"
    st.rerun()


def submit_user_prompt(prompt: str) -> None:
    st.session_state["error_message"] = ""
    append_message("user", prompt)
    st.chat_message("user").write(prompt)
    try:
        with st.spinner("Assistant is thinking..."):
            handle_stream(
                "/v1/chat/stream",
                {"message": prompt, "session_id": current_session_id()},
                render_in_chat=True,
            )
    except Exception as exc:
        st.session_state["error_message"] = f"Failed to send message: {exc}"
    st.rerun()


def main() -> None:
    ensure_state()
    st.title("Agent Console")
    st.caption("Streaming chat with approvals, tool activity, usage tracking, and a live run timeline.")
    render_sidebar()
    chat_col, timeline_col = st.columns([1.7, 1], gap="large")

    with chat_col:
        render_messages()

        if st.session_state.get("error_message"):
            st.error(st.session_state["error_message"])

        if st.session_state.get("pending_approval"):
            st.warning("Approval is required before the assistant can continue.")
            approval_dialog()

        maybe_resume_after_approval()

        prompt = st.chat_input(
            "Send a message",
            disabled=bool(st.session_state.get("pending_approval")) or bool(st.session_state.get("resume_requested")),
        )
        if prompt:
            submit_user_prompt(prompt)

    with timeline_col:
        render_timeline()


main()
