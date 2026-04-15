from __future__ import annotations

import json
import os
import uuid
from typing import Iterator

import requests


class ReactAgent:
    def __init__(self) -> None:
        self.api_base_url = os.getenv("AGENT_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
        self.api_key = os.getenv("AGENT_API_KEY", "react-agent")

    def execute_stream(self, query: str) -> Iterator[str]:
        session_id = str(uuid.uuid4())
        trace_id = str(uuid.uuid4())
        response = requests.post(
            f"{self.api_base_url}/v1/chat/stream",
            json={"message": query, "session_id": session_id, "trace_id": trace_id},
            headers={"x-api-key": self.api_key, "x-trace-id": trace_id},
            stream=True,
            timeout=120,
        )
        response.raise_for_status()
        response.encoding = "utf-8"

        for line in response.iter_lines(decode_unicode=True):
            if not line or not line.strip():
                continue
            event = json.loads(line)
            event_type = event.get("type", "")
            if event_type == "assistant_delta":
                yield str(event.get("text", ""))
            elif event_type == "assistant_complete":
                message = event.get("message", {}) or {}
                content = str(message.get("content", "") or "")
                if content:
                    yield content
            elif event_type == "approval_required":
                yield f"\n[approval required] {event.get('reason', '')}\n"
            elif event_type == "error":
                yield f"\n[error] {event.get('message', '')}\n"


if __name__ == "__main__":
    agent = ReactAgent()
    for chunk in agent.execute_stream("Generate my usage report"):
        print(chunk, end="", flush=True)
