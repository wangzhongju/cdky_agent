from __future__ import annotations

"""编排层模型路由策略。

该模块负责把“策略配置”转为可执行的模型选择逻辑，供 ``OrchestratorEngine``
在最终响应阶段统一调用。当前关注点是“质量/成本平衡”，而不是复杂的在线学习路由。
"""

from langchain_community.chat_models.tongyi import ChatTongyi
from utils.config_handler import rag_conf, enterprise_conf


class ModelRouter:
    """用于选择最终响应模型的轻量策略对象。"""

    def __init__(self):
        """加载主模型、轻量模型与路由策略配置。"""
        self.main_model_name = rag_conf.get("chat_model_name", "qwen3-max")
        self.light_model_name = rag_conf.get("lightweight_chat_model_name", self.main_model_name)
        self.policy = enterprise_conf.get("orchestrator", {}).get("model_route_policy", "balanced")

    def pick(self, query: str, intent: str) -> tuple[str, ChatTongyi]:
        """根据策略返回模型名称与可调用模型实例。

        规则说明：
        - ``cost_preferred``: 优先轻量模型
        - ``balanced``: 聊天短问句优先轻量模型，其他走主模型
        - ``quality_preferred``: 始终主模型
        """
        model_name = self.main_model_name

        if self.policy == "cost_preferred":
            model_name = self.light_model_name
        elif self.policy == "balanced":
            if intent == "chat" and len(query) < 80:
                model_name = self.light_model_name
        elif self.policy == "quality_preferred":
            model_name = self.main_model_name

        return model_name, ChatTongyi(model=model_name)
