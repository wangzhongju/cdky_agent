# Refactor Roadmap

## Completed

- Removed the legacy `agent.tools`, `rag`, `orchestrator`, `capability`, and `a2a` runtime paths from the active architecture.
- Introduced the `v2` session-based API with users, sessions, streaming chat, approvals, skills, and tools.
- Added the query engine with streaming tool-use loops, retry-aware model client plumbing, cost tracking, and structured stream events.
- Rebuilt the tool system with core file/web/user tools, Gaode weather/location tools, and report data tools.
- Replaced generic RAG with lazy-loaded skills, including `report` and `product_knowledge`.
- Added persistent sessions, session message history, approvals, and memory storage.
- Replaced the Streamlit UI with an independent Next.js Web app under `frontend/`.
- Added frontend interaction regression tests for user creation, session rendering, streaming send, approval resume, and SSE parsing.

## Next

- Add end-to-end browser tests once a browser test runner is introduced.
- Add session rename/delete actions in the Web UI.
- Add richer user preference editing and model selection in the side panel.
- Expand approval audit views and tool result inspection in the UI.
- Upgrade Next.js to a patched release after dependency compatibility is confirmed.
