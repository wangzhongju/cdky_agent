from __future__ import annotations

import json
from datetime import datetime

from enterprise.storage.db import SessionLocal
from enterprise.governance.prometheus_metrics import estimated_cost_total
from enterprise.storage.models import CostRecord
from enterprise.storage.redis_client import get_redis_client
from utils.config_handler import enterprise_conf


class CostService:
    def __init__(self):
        self.redis = get_redis_client()
        self.cost_conf = enterprise_conf.get("cost", {})
        self.ratio_in = int(self.cost_conf.get("input_token_ratio", 4))
        self.ratio_out = int(self.cost_conf.get("output_token_ratio", 4))
        self.prices = self.cost_conf.get("model_prices", {})

    def estimate_tokens(self, input_text: str, output_text: str) -> tuple[int, int]:
        in_tokens = max(1, len(input_text) // max(1, self.ratio_in))
        out_tokens = max(1, len(output_text) // max(1, self.ratio_out))
        return in_tokens, out_tokens

    def estimate_cost(self, model_name: str, input_tokens: int, output_tokens: int) -> float:
        price = self.prices.get(model_name, {"input_per_1k": 0.0, "output_per_1k": 0.0})
        in_cost = (input_tokens / 1000.0) * float(price.get("input_per_1k", 0.0))
        out_cost = (output_tokens / 1000.0) * float(price.get("output_per_1k", 0.0))
        return in_cost + out_cost

    def record(self, trace_id: str, actor: str, model_name: str, input_text: str, output_text: str) -> dict:
        in_tokens, out_tokens = self.estimate_tokens(input_text, output_text)
        cost = self.estimate_cost(model_name, in_tokens, out_tokens)

        with SessionLocal() as session:
            row = CostRecord(
                trace_id=trace_id,
                actor=actor,
                model_name=model_name,
                input_tokens=in_tokens,
                output_tokens=out_tokens,
                estimated_cost=f"{cost:.6f}",
                created_at=datetime.utcnow(),
            )
            session.add(row)
            session.commit()

        self.redis.incrbyfloat("metrics:cost:total", cost)
        self.redis.hincrby("metrics:cost:model_calls", model_name, 1)
        estimated_cost_total.labels(model_name=model_name).inc(cost)

        return {
            "trace_id": trace_id,
            "actor": actor,
            "model_name": model_name,
            "input_tokens": in_tokens,
            "output_tokens": out_tokens,
            "estimated_cost": float(f"{cost:.6f}"),
        }
