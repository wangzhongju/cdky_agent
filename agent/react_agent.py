import uuid
import os
import requests


class ReactAgent:
    def __init__(self):
        self.api_base_url = os.getenv("AGENT_API_BASE_URL", "http://127.0.0.1:8000")

    def execute_stream(self, query: str):
        session_id = str(uuid.uuid4())
        trace_id = str(uuid.uuid4())
        resp = requests.post(
            f"{self.api_base_url}/v1/chat/stream",
            json={"message": query, "session_id": session_id, "trace_id": trace_id},
            stream=True,
            timeout=120,
        )
        resp.raise_for_status()
        for chunk in resp.iter_content(chunk_size=1, decode_unicode=True):
            if chunk:
                yield chunk


if __name__ == '__main__':
    agent = ReactAgent()

    for chunk in agent.execute_stream("给我生成我的使用报告"):
        print(chunk, end="", flush=True)
