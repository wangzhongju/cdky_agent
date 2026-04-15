from harness.knowledge.service import ReportDataService
from harness.tools.registry import build_default_tool_registry
from harness.skills.service import SkillSyncService
from harness.memory.service import MemoryService


def test_report_data_service_latest_month():
    service = ReportDataService()
    month = service.latest_month()
    assert month
    payload = service.fetch(user_id="1001", month=month)
    assert payload["user_id"] == "1001"
    assert payload["month"] == month


def test_skill_sync_service_loads_markdown_skill():
    service = SkillSyncService()
    skills = service.sync(persist=False)
    assert any(skill.id == "report" for skill in skills)
    selected = service.select_for_query("帮我生成使用报告")
    assert any(skill.id == "report" for skill in selected)


def test_memory_service_extracts_identity():
    service = MemoryService()
    entries = service._extract_entries("我叫小王，我喜欢安静模式")
    assert any("用户名字是小王" == entry["content"] for entry in entries)
    assert any("用户偏好安静模式" == entry["content"] for entry in entries)


def test_default_tool_registry_contains_phase2_tools():
    class _FakeKnowledgeService:
        def search(self, query: str) -> str:
            return query

    class _FakeReportDataService:
        def fetch(self, user_id=None, month=None):
            return {"user_id": user_id, "month": month}

    registry = build_default_tool_registry(
        knowledge_service=_FakeKnowledgeService(),
        report_service=_FakeReportDataService(),
    )
    names = {tool.name for tool in registry.list_tools()}
    assert "knowledge_search" in names
    assert "fetch_external_report_data" in names
    assert "gaode_get_weather" in names
