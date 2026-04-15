from enterprise.capability.builtin_skills import register_rag_capability, register_report_capabilities
from enterprise.capability.skills.runtime import SkillRuntime


def test_legacy_capability_aliases_exist():
    capability_names = {cap.fqdn for cap in register_rag_capability()}
    capability_names.update(cap.fqdn for cap in register_report_capabilities())

    assert "knowledge.rag_summarize" in capability_names
    assert "enterprise.fetch_external_data" in capability_names
    assert "report.report_writer" in capability_names


def test_skill_runtime_discovers_markdown_skills():
    runtime = SkillRuntime()
    skills = {item["id"]: item for item in runtime.discover_markdown_skills()}
    assert "report" in skills
    assert skills["report"]["source"] == "markdown"
