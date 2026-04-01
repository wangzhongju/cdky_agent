import time
import requests

BASE = "http://127.0.0.1:8000"
HEADERS = {"x-api-key": "test-key", "x-trace-id": "trace-functional"}


def test_health_deep():
    resp = requests.get(f"{BASE}/healthz?deep=true", timeout=10)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["components"]["redis"] == "ok"
    assert data["components"]["postgres"] == "ok"


def test_capabilities_and_skills():
    resp = requests.get(f"{BASE}/v1/capabilities", headers=HEADERS, timeout=10)
    assert resp.status_code == 200
    caps = resp.json()
    assert any(c["fqdn"] == "knowledge.rag_summarize" for c in caps)

    resp2 = requests.get(f"{BASE}/v1/skills", headers=HEADERS, timeout=10)
    assert resp2.status_code == 200
    assert isinstance(resp2.json(), list)


def test_chat_stream():
    payload = {"message": "请帮我生成一段扫地机器人维护建议"}
    resp = requests.post(f"{BASE}/v1/chat/stream", json=payload, headers=HEADERS, stream=True, timeout=30)
    assert resp.status_code == 200
    text = "".join(chunk.decode("utf-8") for chunk in resp.iter_content(chunk_size=16) if chunk)
    assert len(text.strip()) > 0
    assert resp.headers.get("x-trace-id")


def test_task_lifecycle():
    payload = {
        "goal": "给我生成我的使用报告",
        "constraints": {},
        "context_ref": {"session_id": "s-functional"},
        "input": {},
    }
    resp = requests.post(f"{BASE}/v1/tasks", json=payload, headers=HEADERS, timeout=10)
    assert resp.status_code == 200
    task_id = resp.json()["task_id"]

    final_status = None
    for _ in range(30):
        time.sleep(1)
        query = requests.get(f"{BASE}/v1/tasks/{task_id}", headers=HEADERS, timeout=10)
        assert query.status_code == 200
        body = query.json()
        final_status = body["status"]
        if final_status in {"COMPLETED", "FAILED"}:
            break

    assert final_status == "COMPLETED"


def test_metrics_snapshot():
    resp = requests.get(f"{BASE}/v1/metrics", timeout=10)
    assert resp.status_code == 200
    data = resp.json()
    assert "requests_total" in data or "tasks_submitted" in data


def test_prometheus_metrics_endpoint():
    resp = requests.get(f"{BASE}/metrics", timeout=10)
    assert resp.status_code == 200
    body = resp.text
    assert "enterprise_api_requests_total" in body
    assert "enterprise_a2a_tasks_total" in body
