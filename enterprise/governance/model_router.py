from __future__ import annotations

from utils.config_handler import enterprise_conf


class ModelRouter:
    def __init__(self):
        model_conf = enterprise_conf.get("model", {})
        self.main_model_name = model_conf.get("default_model", "qwen3-max")
        self.light_model_name = model_conf.get("lightweight_model", self.main_model_name)
        self.policy = enterprise_conf.get("orchestrator", {}).get("model_route_policy", "balanced")

    def pick(self, query: str, intent: str) -> tuple[str, str]:
        del intent
        model_name = self.main_model_name
        if self.policy == "cost_preferred":
            model_name = self.light_model_name
        elif self.policy == "balanced" and len(query) < 80:
            model_name = self.light_model_name
        return model_name, model_name
