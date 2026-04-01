from enterprise.api.schemas import ChatStreamRequest, TaskCreateRequest, SkillPatchRequest
from enterprise.a2a.protocol import A2ATaskPayload


def test_chat_stream_request_schema():
    req = ChatStreamRequest(message="你好")
    assert req.message == "你好"


def test_task_create_request_schema():
    req = TaskCreateRequest(goal="生成报告")
    assert req.goal == "生成报告"


def test_skill_patch_request_schema():
    req = SkillPatchRequest(enabled=False)
    assert req.enabled is False


def test_a2a_payload_required_fields():
    payload = A2ATaskPayload(task_id="t1", goal="g", trace_id="trace")
    assert payload.status.value == "PENDING"
