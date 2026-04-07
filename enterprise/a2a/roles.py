"""A2A 任务流中使用的标准角色名集合。

角色用途
- ``planner-agent``: 任务拆解与计划生成
- ``worker-rag``: 通用检索/问答执行
- ``worker-report``: 报告类任务执行
- ``reviewer-agent``: 结果复核与质量把关

说明
- 当前 ``A2ARuntime`` 的审计 actor 仅直接使用 ``worker-rag`` 与 ``worker-report``。
- 其余角色用于统一命名与后续扩展，避免角色字符串分散在多个模块中。
"""

A2A_ROLES = [
    "planner-agent",
    "worker-rag",
    "worker-report",
    "reviewer-agent",
]
