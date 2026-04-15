import asyncio
import importlib
import json
import uuid

from fastapi.testclient import TestClient

from enterprise.orchestrator.service import OrchestratorService
from harness.engine.cost_tracker import UsageSnapshot
from harness.engine.messages import ConversationMessage, ToolCall
from harness.providers.base import ProviderCompleteEvent, ProviderTextDeltaEvent


class FakeProvider:
    def __init__(self, scripted_messages: list[ConversationMessage]):
        self.scripted_messages = scripted_messages
        self.call_count = 0

    async def stream_message(self, request):
        del request
        message = self.scripted_messages[min(self.call_count, len(self.scripted_messages) - 1)]
        self.call_count += 1
        if message.content:
            for index in range(0, len(message.content), 8):
                yield ProviderTextDeltaEvent(text=message.content[index:index + 8])
        yield ProviderCompleteEvent(
            message=message,
            usage=UsageSnapshot(input_tokens=12, output_tokens=6),
            stop_reason="stop",
        )


def collect_stream(async_iterator):
    async def _collect():
        rows = []
        async for line in async_iterator:
            rows.append(json.loads(line))
        return rows

    return asyncio.run(_collect())


def test_orchestrator_service_streams_ndjson_and_persists_session():
    session_id = f"phase3-{uuid.uuid4()}"
    service = OrchestratorService(
        provider=FakeProvider([ConversationMessage(role="assistant", content="This is a new NDJSON session.")])
    )

    events = collect_stream(
        service.stream_chat(
            message="Summarize the current session.",
            session_id=session_id,
            trace_id=f"trace-{session_id}",
            actor="phase3-user",
        )
    )
    event_types = [item["type"] for item in events]
    assert "assistant_delta" in event_types
    assert "assistant_complete" in event_types
    assert "usage" in event_types
    assert event_types[-1] == "done"

    session = service.get_session(session_id)
    assert session is not None
    assert session["session_id"] == session_id

    messages = service.list_session_messages(session_id)
    assert [item["role"] for item in messages][-2:] == ["user", "assistant"]


def test_orchestrator_service_runs_tool_loop_and_persists_tool_messages():
    session_id = f"phase3-tool-{uuid.uuid4()}"
    scripted = [
        ConversationMessage(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="call-1", name="read_file", arguments={"path": "README.md", "max_chars": 80})],
        ),
        ConversationMessage(role="assistant", content="The tool finished and I read the file."),
    ]
    service = OrchestratorService(provider=FakeProvider(scripted))

    events = collect_stream(
        service.stream_chat(
            message="Read the first part of README.",
            session_id=session_id,
            trace_id=f"trace-{session_id}",
            actor="phase3-user",
        )
    )
    event_types = [item["type"] for item in events]
    assert "tool_start" in event_types
    assert "tool_result" in event_types

    messages = service.list_session_messages(session_id)
    assert [item["role"] for item in messages] == ["user", "assistant", "tool", "assistant"]


def test_chat_stream_api_returns_ndjson_and_session_history(monkeypatch):
    app_module = importlib.import_module("enterprise.api.app")

    fake_service = OrchestratorService(
        provider=FakeProvider([ConversationMessage(role="assistant", content="The API now streams NDJSON.")])
    )
    monkeypatch.setattr(app_module, "OrchestratorService", lambda: fake_service)

    session_id = f"phase3-api-{uuid.uuid4()}"
    with TestClient(app_module.app) as client:
        response = client.post(
            "/v1/chat/stream",
            json={"message": "Confirm the current response format.", "session_id": session_id},
            headers={"x-api-key": "phase3-api-user"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/x-ndjson")

        events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
        assert events[-1]["type"] == "done"

        session_response = client.get(f"/v1/sessions/{session_id}", headers={"x-api-key": "phase3-api-user"})
        assert session_response.status_code == 200
        assert session_response.json()["session_id"] == session_id

        message_response = client.get(f"/v1/sessions/{session_id}/messages", headers={"x-api-key": "phase3-api-user"})
        assert message_response.status_code == 200
        assert any(item["role"] == "assistant" for item in message_response.json())


def test_orchestrator_service_supports_approval_and_resume():
    session_id = f"phase3-approval-{uuid.uuid4()}"
    scripted = [
        ConversationMessage(
            role="assistant",
            content="",
            tool_calls=[
                ToolCall(
                    id="approve-1",
                    name="shell_command",
                    arguments={"command": "python -c \"print('approved')\"", "timeout_seconds": 10},
                )
            ],
        ),
        ConversationMessage(role="assistant", content="The approved tool completed successfully."),
    ]
    service = OrchestratorService(provider=FakeProvider(scripted))

    initial_events = collect_stream(
        service.stream_chat(
            message="Run the shell command after approval.",
            session_id=session_id,
            trace_id=f"trace-{session_id}",
            actor="phase3-user",
        )
    )
    initial_types = [item["type"] for item in initial_events]
    assert "approval_required" in initial_types
    assert initial_types[-1] == "done"

    session = service.get_session(session_id)
    assert session is not None
    approval_id = session["latest_approval_id"]
    assert approval_id

    decision = service.decide_approval(approval_id, "approve")
    assert decision is not None
    assert decision["status"] == "APPROVED"

    resumed_events = collect_stream(
        service.resume_chat(
            session_id=session_id,
            trace_id=f"resume-{session_id}",
            actor="phase3-user",
        )
    )
    resumed_types = [item["type"] for item in resumed_events]
    assert "approval_decision" in resumed_types
    assert "tool_start" in resumed_types
    assert "tool_result" in resumed_types
    assert "assistant_complete" in resumed_types
    assert resumed_types[-1] == "done"

    messages = service.list_session_messages(session_id)
    assert [item["role"] for item in messages] == ["user", "assistant", "tool", "assistant"]


def test_chat_resume_api_supports_approval_round_trip(monkeypatch):
    app_module = importlib.import_module("enterprise.api.app")

    fake_service = OrchestratorService(
        provider=FakeProvider(
            [
                ConversationMessage(
                    role="assistant",
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="approve-api-1",
                            name="shell_command",
                            arguments={"command": "python -c \"print('approved-api')\"", "timeout_seconds": 10},
                        )
                    ],
                ),
                ConversationMessage(role="assistant", content="The approved API tool completed successfully."),
            ]
        )
    )
    monkeypatch.setattr(app_module, "OrchestratorService", lambda: fake_service)

    session_id = f"phase3-api-approval-{uuid.uuid4()}"
    with TestClient(app_module.app) as client:
        stream_response = client.post(
            "/v1/chat/stream",
            json={"message": "Run the command with approval.", "session_id": session_id},
            headers={"x-api-key": "phase3-api-user"},
        )
        assert stream_response.status_code == 200
        initial_events = [json.loads(line) for line in stream_response.text.splitlines() if line.strip()]
        approval_event = next(item for item in initial_events if item["type"] == "approval_required")

        approval_response = client.post(
            f"/v1/approvals/{approval_event['approval_id']}",
            json={"decision": "approve"},
            headers={"x-api-key": "phase3-api-user"},
        )
        assert approval_response.status_code == 200
        assert approval_response.json()["status"] == "APPROVED"

        resume_response = client.post(
            "/v1/chat/resume",
            json={"session_id": session_id},
            headers={"x-api-key": "phase3-api-user"},
        )
        assert resume_response.status_code == 200
        assert resume_response.headers["content-type"].startswith("application/x-ndjson")

        resumed_events = [json.loads(line) for line in resume_response.text.splitlines() if line.strip()]
        resumed_types = [item["type"] for item in resumed_events]
        assert "approval_decision" in resumed_types
        assert "tool_start" in resumed_types
        assert "tool_result" in resumed_types
        assert "assistant_complete" in resumed_types
        assert resumed_types[-1] == "done"
