from __future__ import annotations

from qwenpaw.extensions.api.alarm_analyst_card_service import (
    build_alarm_analyst_card,
    is_alarm_analyst_card_candidate,
)


PORTAL_ALARM_ANALYST_CARD_MARKER = "# PORTAL ALARM ANALYST CARD MODE"


def test_is_alarm_analyst_card_candidate_matches_report_with_rca_markers() -> None:
    matched = is_alarm_analyst_card_candidate(
        employee_id="fault",
        report_markdown=(
            "🔴 数据库锁异常 — 完整故障分析报告\n"
            "## 根因分析结论\n"
            "- 根资源 MySQL（CI ID 3094）出现锁等待放大\n"
            "## 处置建议\n"
            "- 优先终止异常会话并观察告警收敛\n"
        ),
        process_blocks=[
            {
                "kind": "tool",
                "toolName": "read_file",
                "outputContent": (
                    "{\"title\":{\"text\":\"CMDB 应用关系拓扑\"},"
                    "\"series\":[{\"type\":\"graph\",\"data\":[],\"links\":[]}]}"
                ),
            }
        ],
    )

    assert matched is True


def test_build_alarm_analyst_card_extracts_summary_recommendations_and_hash() -> None:
    card = build_alarm_analyst_card(
        chat_id="chat-1",
        message_id="assistant-1",
        employee_id="fault",
        report_markdown=(
            "🔴 数据库锁异常 — 完整故障分析报告\n"
            "## 根因分析结论\n"
            "- 根因：MySQL 资源 3094 存在锁等待放大，导致 CMDB 写入失败。\n"
            "## 影响范围\n"
            "- 受影响应用：CMDB\n"
            "- 受影响资源：3094、3092\n"
            "## 处置建议\n"
            "- P0：终止异常慢 SQL 会话。\n"
            "- P1：继续观察最近 10 分钟告警是否收敛。\n"
        ),
        process_blocks=[
            {
                "kind": "tool",
                "toolName": "read_file",
                "outputContent": (
                    "```json\n"
                    "{\"title\":{\"text\":\"CMDB 应用关系拓扑\"},"
                    "\"series\":[{\"type\":\"graph\",\"data\":[{\"id\":\"3094\",\"name\":\"MySQL\"}],"
                    "\"links\":[{\"source\":\"3094\",\"target\":\"3092\"}]}]}\n"
                    "```"
                ),
            }
        ],
    )

    assert card.type == "alarm-analyst-card"
    assert card.summary.title == "数据库锁异常"
    assert "MySQL" in card.summary.conclusion
    assert card.source.content_hash
    assert card.source.chat_id == "chat-1"
    assert card.root_cause.ci_id == "3094"
    assert card.impact.affected_applications[0].name == "CMDB"
    assert card.impact.affected_resources[0].id == "3094"
    assert card.topology.nodes[0]["id"] == "3094"
    assert card.recommendations[0].priority == "p0"
    assert card.recommendations[1].action_type == "observe"
    assert card.evidence[-1].kind == "tool"


def test_build_alarm_analyst_card_filters_noisy_impact_and_sanitizes_titles() -> None:
    card = build_alarm_analyst_card(
        chat_id="chat-2",
        message_id="assistant-2",
        employee_id="fault",
        report_markdown=(
            "数据库锁异常 — 完整故障分析报告\n"
            "## 根因分析结论\n"
            "- 根因：MySQL 资源 3094 存在锁竞争。\n"
            "## 影响范围\n"
            "### 受影响应用\n"
            "- CMDB\n"
            "- 应用拓扑确认（query -> zgops-cmdb）\n"
            "- 天翼智观应用中依赖 MySQL 的写入链路\n"
            "### 受影响资源\n"
            "- 3094\n"
            "- Redis-01\n"
            "- | 2980 | 天翼智观（应用） | ✅ 0条 |\n"
            "## 处置建议\n"
            "- P0：`数据库死锁 + 数据库锁异常 + 连接异常` 三告警同一时间点出现 → 锁竞争已激化到死锁级别。\n"
        ),
        process_blocks=[],
    )

    assert [item.name for item in card.impact.affected_applications] == ["CMDB"]
    assert [item.name for item in card.impact.affected_resources] == ["3094", "Redis-01"]
    assert card.impact.blast_radius_text == "影响 1 个应用、2 个资源"
    assert card.recommendations[0].title == "数据库死锁 + 数据库锁异常 + 连接异常 三告警同一时间点出现"


def test_alarm_analyst_card_protocol_marker_matches_and_preserves_raw_report() -> None:
    report_markdown = (
        f"{PORTAL_ALARM_ANALYST_CARD_MARKER}\n\n"
        "---\n"
        "## 告警分析报告：数据库锁异常\n"
        "## 告警基础信息\n"
        "| 字段 | 值 |\n"
        "|---|---|\n"
        "| 资源 ID（CI ID） | 3094 |\n"
        "| 资源名称 | db_mysql_001 |\n"
        "## 根因判断\n"
        "- MySQL 锁等待放大，导致写入链路受阻。\n"
        "## 影响范围\n"
        "- 受影响应用：CMDB\n"
        "- 受影响资源：3094\n"
        "## 处置建议\n"
        "- P0：终止异常慢 SQL 会话。\n"
        "## 📊 总结\n"
        "- 置信度：86%\n"
    )

    assert is_alarm_analyst_card_candidate(
        employee_id="fault",
        report_markdown=report_markdown,
        process_blocks=[],
    ) is True

    card = build_alarm_analyst_card(
        chat_id="chat-3",
        message_id="assistant-3",
        employee_id="fault",
        report_markdown=report_markdown,
        process_blocks=[],
    )

    assert card.summary.title == "数据库锁异常"
    assert "锁等待放大" in card.summary.conclusion
    assert card.root_cause.ci_id == "3094"
    assert card.raw_report_markdown.startswith(PORTAL_ALARM_ANALYST_CARD_MARKER)


def test_alarm_analyst_card_protocol_marker_matches_with_preface_text() -> None:
    report_markdown = (
        "工单已成功创建，通知状态为部分推送成功。现在我已拥有完整的分析数据，可以输出最终报告了。\n\n"
        "---\n\n"
        f"{PORTAL_ALARM_ANALYST_CARD_MARKER}\n\n"
        "---\n\n"
        "## 告警分析报告：数据库锁异常\n\n"
        "## 告警基础信息\n\n"
        "| 字段 | 值 |\n"
        "|---|---|\n"
        "| 资源 ID（CI ID） | 3094 |\n"
        "| 资源名称 | db_mysql_001 |\n\n"
        "## 根因判断\n\n"
        "- MySQL 锁等待放大，导致写入链路受阻。\n\n"
        "## 影响范围\n\n"
        "- 受影响应用：CMDB\n"
        "- 受影响资源：3094\n\n"
        "## 处置建议\n\n"
        "- P0：终止异常慢 SQL 会话。\n\n"
        "## 📊 总结\n\n"
        "- 置信度：86%\n"
    )

    assert is_alarm_analyst_card_candidate(
        employee_id="fault",
        report_markdown=report_markdown,
        process_blocks=[],
    ) is True

    card = build_alarm_analyst_card(
        chat_id="chat-4",
        message_id="assistant-4",
        employee_id="fault",
        report_markdown=report_markdown,
        process_blocks=[],
    )

    assert card.summary.title == "数据库锁异常"
    assert card.root_cause.ci_id == "3094"
    assert card.raw_report_markdown.startswith("工单已成功创建")


def test_alarm_analyst_card_protocol_ignores_trailing_supplement_after_report() -> None:
    report_markdown = (
        "工单已创建成功，通知状态部分推送成功。\n\n"
        "---\n\n"
        f"{PORTAL_ALARM_ANALYST_CARD_MARKER}\n\n"
        "---\n\n"
        "## 告警分析报告：数据库锁异常\n\n"
        "## 告警基础信息\n\n"
        "| 字段 | 值 |\n"
        "|---|---|\n"
        "| 资源 ID（CI ID） | 3094 |\n"
        "| 资源名称 | db_mysql_001 |\n\n"
        "## 根因判断\n\n"
        "- MySQL 锁等待放大，导致写入链路受阻。\n\n"
        "## 影响范围\n\n"
        "- 受影响应用：CMDB\n"
        "- 受影响资源：3094\n\n"
        "## 处置建议\n\n"
        "- P0：终止异常慢 SQL 会话。\n\n"
        "## 📊 总结\n\n"
        "- 置信度：86%\n\n"
        "---\n\n"
        "> 💡 补充说明：这里是报告后的补充说明，不应覆盖主报告正文。\n"
    )

    assert is_alarm_analyst_card_candidate(
        employee_id="fault",
        report_markdown=report_markdown,
        process_blocks=[],
    ) is True

    card = build_alarm_analyst_card(
        chat_id="chat-5",
        message_id="assistant-5",
        employee_id="fault",
        report_markdown=report_markdown,
        process_blocks=[],
    )

    assert card.summary.title == "数据库锁异常"
    assert card.root_cause.ci_id == "3094"
