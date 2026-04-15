# Report Skill

Use this skill when the user asks for a personal usage report, monthly report, usage statistics, or maintenance suggestions based on their own robot usage data.

Rules:
- Prefer the `session.metadata.user_id` value as the report subject.
- If the user explicitly asks for a month, use that month; otherwise call `get_available_report_months` first and select the latest available month.
- Then call `get_usage_report_data` with `user_id` and `month`.
- Generate a direct report with:
  1. Summary of the month's usage
  2. Cleaning efficiency and consumables status
  3. Comparison insight
  4. Practical maintenance suggestions
- Do not ask to call old tools or RAG modules.
