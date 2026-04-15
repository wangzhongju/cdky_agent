from __future__ import annotations

import asyncio
from urllib.parse import urlencode
from urllib.request import urlopen

from pydantic import BaseModel, Field

from harness.knowledge.service import KnowledgeService, ReportDataService
from harness.tools.base import BaseTool, ToolExecutionContext, ToolResult
from utils.config_handler import agent_conf


def _gaode_get(path: str, params: dict) -> dict:
    query = dict(params)
    query["key"] = (agent_conf.get("gaodekey") or "").strip()
    if not query["key"]:
        raise ValueError("GAODE_MCP_KEY is not configured")
    url = f"{agent_conf.get('gaode_base_url', 'https://restapi.amap.com')}{path}?{urlencode(query)}"
    with urlopen(url, timeout=float(agent_conf.get("gaode_timeout", 5))) as resp:
        import json

        return json.loads(resp.read().decode("utf-8"))


class KnowledgeSearchInput(BaseModel):
    query: str


class KnowledgeSearchTool(BaseTool):
    name = "knowledge_search"
    description = "Search the local robotics knowledge base."
    input_model = KnowledgeSearchInput

    def __init__(self, service: KnowledgeService):
        self.service = service

    def is_read_only(self, arguments: KnowledgeSearchInput) -> bool:
        return True

    async def execute(self, arguments: KnowledgeSearchInput, context: ToolExecutionContext) -> ToolResult:
        del context
        try:
            output = await asyncio.to_thread(self.service.search, arguments.query)
            return ToolResult(output=output)
        except Exception as exc:
            return ToolResult(output=str(exc), is_error=True)


class FetchExternalReportDataInput(BaseModel):
    user_id: str | None = None
    month: str | None = None


class FetchExternalReportDataTool(BaseTool):
    name = "fetch_external_report_data"
    description = "Fetch structured monthly report data for a user."
    input_model = FetchExternalReportDataInput

    def __init__(self, service: ReportDataService):
        self.service = service

    def is_read_only(self, arguments: FetchExternalReportDataInput) -> bool:
        return True

    async def execute(self, arguments: FetchExternalReportDataInput, context: ToolExecutionContext) -> ToolResult:
        del context
        payload = await asyncio.to_thread(self.service.fetch, arguments.user_id, arguments.month)
        import json

        return ToolResult(output=json.dumps(payload, ensure_ascii=False))


class GaodeGetWeatherInput(BaseModel):
    city: str


class GaodeGetWeatherTool(BaseTool):
    name = "gaode_get_weather"
    description = "Query real-time weather for a city via Gaode."
    input_model = GaodeGetWeatherInput

    def is_read_only(self, arguments: GaodeGetWeatherInput) -> bool:
        return True

    async def execute(self, arguments: GaodeGetWeatherInput, context: ToolExecutionContext) -> ToolResult:
        del context
        try:
            geocode = await asyncio.to_thread(_gaode_get, "/v3/geocode/geo", {"address": arguments.city})
            if geocode.get("status") != "1" or not geocode.get("geocodes"):
                return ToolResult(output=f"城市解析失败: {geocode.get('info', 'unknown')}", is_error=True)
            first = geocode["geocodes"][0]
            adcode = first.get("adcode")
            weather = await asyncio.to_thread(_gaode_get, "/v3/weather/weatherInfo", {"city": adcode, "extensions": "base"})
            if weather.get("status") != "1" or not weather.get("lives"):
                return ToolResult(output=f"天气查询失败: {weather.get('info', 'unknown')}", is_error=True)
            live = weather["lives"][0]
            output = (
                f"城市{arguments.city}天气: {live.get('weather', '未知')}，温度{live.get('temperature', '未知')}°C，"
                f"湿度{live.get('humidity', '未知')}%，风向{live.get('winddirection', '未知')}，风力{live.get('windpower', '未知')}级。"
            )
            return ToolResult(output=output)
        except Exception as exc:
            return ToolResult(output=str(exc), is_error=True)


class GaodeGetLocationInput(BaseModel):
    ip: str | None = Field(default=None, description="Optional public IPv4 address.")


class GaodeGetLocationTool(BaseTool):
    name = "gaode_get_location"
    description = "Resolve current city via Gaode IP geolocation."
    input_model = GaodeGetLocationInput

    def is_read_only(self, arguments: GaodeGetLocationInput) -> bool:
        return True

    async def execute(self, arguments: GaodeGetLocationInput, context: ToolExecutionContext) -> ToolResult:
        del context
        try:
            payload = {"ip": arguments.ip} if arguments.ip else {}
            ip_info = await asyncio.to_thread(_gaode_get, "/v3/ip", payload)
            if ip_info.get("status") != "1":
                return ToolResult(output=f"定位失败: {ip_info.get('info', 'unknown')}", is_error=True)
            city = str(ip_info.get("city") or ip_info.get("province") or "未知城市").strip()
            return ToolResult(output=city)
        except Exception as exc:
            return ToolResult(output=str(exc), is_error=True)
