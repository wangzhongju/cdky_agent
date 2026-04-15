---
id: report
name: report
description: 为用户生成扫地机器人使用报告与保养建议。
enabled: true
tags:
  - report
  - monthly
  - analytics
triggers:
  - 报告
  - 月报
  - 使用记录
  - 统计
allowed_tools:
  - fetch_external_report_data
---

当用户请求生成、分析或总结个人使用报告时，使用该技能。

执行规则：

1. 优先调用 `fetch_external_report_data` 获取报告数据。
2. 如果用户没有明确给出月份，优先使用工具内置的默认最新月份。
3. 生成报告时至少覆盖：
   - 使用概况
   - 清洁/覆盖表现
   - 耗材或保养风险
   - 下一步建议
4. 输出应面向普通用户，语言清晰，不要堆砌术语。
