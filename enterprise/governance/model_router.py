from __future__ import annotations

from langchain_community.chat_models.tongyi import ChatTongyi
from utils.config_handler import rag_conf, enterprise_conf


class ModelRouter:
    def __init__(self):
        self.main_model_name = rag_conf.get("chat_model_name", "qwen3-max")
        self.light_model_name = rag_conf.get("lightweight_chat_model_name", self.main_model_name)
        self.policy = enterprise_conf.get("orchestrator", {}).get("model_route_policy", "balanced")

    def pick(self, query: str, intent: str) -> tuple[str, ChatTongyi]:
        model_name = self.main_model_name

        if self.policy == "cost_preferred":
            model_name = self.light_model_name
        elif self.policy == "balanced":
            if intent == "chat" and len(query) < 80:
                model_name = self.light_model_name
        elif self.policy == "quality_preferred":
            model_name = self.main_model_name

        return model_name, ChatTongyi(model=model_name)
