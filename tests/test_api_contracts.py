from enterprise.api.schemas import (
    ApprovalDecisionRequest,
    SessionCreateRequest,
    SessionMessageRequest,
    UserCreateRequest,
    UserUpdateRequest,
)


def test_session_create_schema():
    req = SessionCreateRequest(title="demo", user_id="1001", metadata={"user_id": "1001"})
    assert req.title == "demo"
    assert req.user_id == "1001"
    assert req.metadata["user_id"] == "1001"


def test_session_message_schema():
    req = SessionMessageRequest(message="hello", resume=False)
    assert req.message == "hello"
    assert req.resume is False


def test_approval_decision_schema():
    req = ApprovalDecisionRequest(approved=True)
    assert req.approved is True


def test_user_create_schema():
    req = UserCreateRequest(username="demo", display_name="Demo User", preferences={"theme": "light"})
    assert req.username == "demo"
    assert req.display_name == "Demo User"
    assert req.preferences["theme"] == "light"


def test_user_update_schema():
    req = UserUpdateRequest(display_name="Renamed")
    assert req.display_name == "Renamed"
