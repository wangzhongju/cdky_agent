import json

import pytest
from fastapi.testclient import TestClient

from enterprise.api.app import app
from enterprise.engine.messages import assistant_message_from_openai
from enterprise.model.client import ApiMessageCompleteEvent, ApiMessageRequest, ApiTextDeltaEvent
from enterprise.model.usage import UsageSnapshot
from enterprise.storage.approval_repository import ApprovalRepository
from enterprise.storage.memory_repository import MemoryRepository
from enterprise.storage.session_repository import SessionRepository
from enterprise.storage.user_repository import UserRepository
from utils.config_handler import enterprise_conf


class BasicMockClient:
    async def stream_message(self, request: ApiMessageRequest):
        last = request.messages[-1]
        text = f"echo:{last.text or 'resume'}"
        yield ApiTextDeltaEvent(text=text)
        yield ApiMessageCompleteEvent(
            message=assistant_message_from_openai({"content": text, "tool_calls": []}),
            usage=UsageSnapshot(input_tokens=5, output_tokens=5),
            stop_reason="stop",
        )

    async def complete_text(self, *, model: str, system_prompt: str, prompt: str, max_tokens: int = 1024) -> str:
        del model, max_tokens
        lower_prompt = prompt.lower()
        lower_system = system_prompt.lower()
        if "choose the most relevant skills" in lower_prompt:
            return '["product_knowledge"]'
        if "generate a concise conversation title" in lower_system:
            return "测试标题"
        return "short summary"


class ReportMockClient(BasicMockClient):
    async def stream_message(self, request: ApiMessageRequest):
        has_tool_result = any(
            any(block.get("type") == "tool_result" for block in message.model_dump(mode="json")["content"])
            for message in request.messages
        )
        if not has_tool_result:
            yield ApiMessageCompleteEvent(
                message=assistant_message_from_openai(
                    {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "tool-report",
                                "type": "function",
                                "function": {"name": "get_usage_report_data", "arguments": json.dumps({"user_id": "1001", "month": "2025-01"})},
                            }
                        ],
                    }
                ),
                usage=UsageSnapshot(input_tokens=10, output_tokens=2),
                stop_reason="tool_calls",
            )
            return
        yield ApiTextDeltaEvent(text="report ready")
        yield ApiMessageCompleteEvent(
            message=assistant_message_from_openai({"content": "report ready", "tool_calls": []}),
            usage=UsageSnapshot(input_tokens=5, output_tokens=5),
            stop_reason="stop",
        )

    async def complete_text(self, *, model: str, system_prompt: str, prompt: str, max_tokens: int = 1024) -> str:
        del model, max_tokens
        lower_prompt = prompt.lower()
        lower_system = system_prompt.lower()
        if "choose the most relevant skills" in lower_prompt:
            return '["report"]'
        if "generate a concise conversation title" in lower_system:
            return "报告对话"
        return "report summary"


class ApprovalMockClient(BasicMockClient):
    async def stream_message(self, request: ApiMessageRequest):
        has_tool_result = any(
            any(block.get("type") == "tool_result" for block in message.model_dump(mode="json")["content"])
            for message in request.messages
        )
        if not has_tool_result:
            yield ApiMessageCompleteEvent(
                message=assistant_message_from_openai(
                    {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "tool-write",
                                "type": "function",
                                "function": {"name": "write_file", "arguments": json.dumps({"path": "tmp_test.txt", "content": "ok"})},
                            }
                        ],
                    }
                ),
                usage=UsageSnapshot(input_tokens=10, output_tokens=2),
                stop_reason="tool_calls",
            )
            return
        yield ApiTextDeltaEvent(text="resume complete")
        yield ApiMessageCompleteEvent(
            message=assistant_message_from_openai({"content": "resume complete", "tool_calls": []}),
            usage=UsageSnapshot(input_tokens=5, output_tokens=5),
            stop_reason="stop",
        )


@pytest.fixture()
def client():
    enterprise_conf["model"]["provider"] = "mock"
    with TestClient(app) as test_client:
        SessionRepository().delete_all()
        ApprovalRepository().delete_all()
        MemoryRepository().delete_all()
        UserRepository().delete_all()
        app.state.session_service.model_client = BasicMockClient()
        app.state.session_service.skill_service.model_client = app.state.session_service.model_client
        yield test_client


def _stream_events(resp):
    events = []
    for line in resp.iter_lines():
        if not line:
            continue
        if isinstance(line, bytes):
            line = line.decode("utf-8")
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


def _create_user(client: TestClient, username: str, display_name: str):
    response = client.post(
        "/v2/users",
        json={"username": username, "display_name": display_name, "note": "", "default_model": "", "preferences": {}},
    )
    assert response.status_code == 200
    return response.json()


def test_health_and_metrics(client):
    assert client.get("/healthz?deep=true").status_code == 200
    assert client.get("/metrics").status_code == 200
    assert client.get("/v1/metrics").status_code == 200


def test_user_crud(client):
    created = _create_user(client, "alice", "Alice")
    user_id = created["user_id"]

    listing = client.get("/v2/users")
    assert any(item["user_id"] == user_id for item in listing.json())

    fetched = client.get(f"/v2/users/{user_id}")
    assert fetched.status_code == 200
    assert fetched.json()["username"] == "alice"

    updated = client.patch(f"/v2/users/{user_id}", json={"display_name": "Alice Chen", "note": "owner"})
    assert updated.status_code == 200
    assert updated.json()["display_name"] == "Alice Chen"
    assert updated.json()["note"] == "owner"


def test_session_lifecycle_filtering_and_title_generation(client):
    user_a = _create_user(client, "alice", "Alice")
    user_b = _create_user(client, "bob", "Bob")

    session_a = client.post("/v2/sessions", json={"user_id": user_a["user_id"], "metadata": {}}).json()
    session_b = client.post("/v2/sessions", json={"user_id": user_b["user_id"], "metadata": {}}).json()

    stream = client.post(
        f"/v2/sessions/{session_a['session_id']}/messages/stream",
        json={"message": "hello from alice"},
    )
    assert stream.status_code == 200
    events = _stream_events(stream)
    assert any(event["type"] == "assistant_text_delta" for event in events)
    assert any(event["type"] == "assistant_turn_complete" for event in events)

    filtered = client.get(f"/v2/sessions?user_id={user_a['user_id']}")
    assert filtered.status_code == 200
    assert [item["session_id"] for item in filtered.json()] == [session_a["session_id"]]
    assert filtered.json()[0]["message_count"] >= 2
    assert filtered.json()[0]["last_message_preview"]

    session_detail = client.get(f"/v2/sessions/{session_a['session_id']}")
    assert session_detail.json()["title"] == "测试标题"
    assert session_detail.json()["user_id"] == user_a["user_id"]
    assert client.get(f"/v2/sessions?user_id={user_b['user_id']}").json()[0]["session_id"] == session_b["session_id"]


def test_report_tool_flow(client):
    _create_user(client, "reporter", "Reporter")
    app.state.session_service.model_client = ReportMockClient()
    app.state.session_service.skill_service.model_client = app.state.session_service.model_client
    session_id = client.post("/v2/sessions", json={"title": "report", "user_id": None, "metadata": {"user_id": "1001"}}).json()["session_id"]
    stream = client.post(f"/v2/sessions/{session_id}/messages/stream", json={"message": "report please"})
    events = _stream_events(stream)
    assert any(event["type"] == "tool_execution_started" and event["tool_name"] == "get_usage_report_data" for event in events)
    assert any(event["type"] == "assistant_turn_complete" for event in events)


def test_approval_flow_and_resume(client):
    app.state.session_service.model_client = ApprovalMockClient()
    app.state.session_service.skill_service.model_client = app.state.session_service.model_client
    session_id = client.post("/v2/sessions", json={"title": "approval", "metadata": {}}).json()["session_id"]

    events = _stream_events(client.post(f"/v2/sessions/{session_id}/messages/stream", json={"message": "write a file"}))
    approval = next(event for event in events if event["type"] == "approval_required")
    approval_id = approval["approval_id"]

    pending = client.get("/v2/approvals?status=pending")
    item = next(item for item in pending.json() if item["approval_id"] == approval_id)
    assert item["session_id"] == session_id
    assert item["status"] == "pending"

    decision = client.post(f"/v2/approvals/{approval_id}/decision", json={"approved": True})
    assert decision.status_code == 200

    resumed = client.post(f"/v2/sessions/{session_id}/messages/stream", json={"resume": True})
    resumed_events = _stream_events(resumed)
    assert any(event["type"] == "assistant_turn_complete" for event in resumed_events)


def test_skills_and_tools_listing(client):
    skills = client.get("/v2/skills")
    tools = client.get("/v2/tools")
    assert any(item["id"] == "report" for item in skills.json())
    assert any(item["name"] == "read_file" for item in tools.json())
