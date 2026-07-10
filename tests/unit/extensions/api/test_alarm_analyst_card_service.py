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


def test_alarm_analyst_card_protocol_keeps_all_report_sections_across_separators() -> None:
    report_markdown = (
        "工单已创建成功！现在组织完整的 Portal 告警分析报告：\n\n"
        f"{PORTAL_ALARM_ANALYST_CARD_MARKER}\n\n"
        "---\n\n"
        "## 告警分析报告：数据库锁异常\n\n"
        "---\n\n"
        "## 告警基础信息\n\n"
        "| 字段 | 值 |\n"
        "|---|---|\n"
        "| 资源 ID（CI ID） | 3094 |\n"
        "| 资源名称 | db_mysql_001 |\n\n"
        "---\n\n"
        "## 根因判断\n\n"
        "- MySQL 锁等待放大，导致写入链路受阻。\n\n"
        "---\n\n"
        "## 影响范围\n\n"
        "- 受影响应用：CMDB\n"
        "- 受影响资源：3094\n\n"
        "---\n\n"
        "## 处置建议\n\n"
        "- P0：终止异常慢 SQL 会话。\n\n"
        "---\n\n"
        "## 📊 总结\n\n"
        "- 置信度：86%\n"
    )

    assert is_alarm_analyst_card_candidate(
        employee_id="fault",
        report_markdown=report_markdown,
        process_blocks=[],
    ) is True

    card = build_alarm_analyst_card(
        chat_id="chat-6",
        message_id="assistant-6",
        employee_id="fault",
        report_markdown=report_markdown,
        process_blocks=[],
    )

    assert "锁等待放大" in card.summary.conclusion
    assert card.impact.affected_applications[0].name == "CMDB"
    assert card.recommendations[0].priority == "p0"


def test_build_alarm_analyst_card_extracts_root_cause_candidates() -> None:
    card = build_alarm_analyst_card(
        chat_id="chat-7",
        message_id="assistant-7",
        employee_id="fault",
        report_markdown=(
            "🔴 数据库锁异常 — 完整故障分析报告\n"
            "## 根因判断\n"
            "- 根因：InnoDB 行锁竞争阻塞链。\n"
            "\n"
            "### 候选根因\n"
            "| 排名 | 候选根因 | 关联资源 | 置信度 | 关键证据 |\n"
            "|---|---|---|---|---|\n"
            "| 1 | InnoDB 行锁竞争阻塞链 | db_mysql_001（3094） | 86% "
            "| 锁等待告警 12 条；时序先于应用异常 |\n"
            "| 2 | 慢 SQL 导致连接池耗尽 | db_mysql_001（3094） | 45% "
            "| 慢查询数上升；无变更命中 |\n"
            "\n"
            "## 影响范围\n"
            "- 受影响应用：CMDB\n"
            "## 处置建议\n"
            "- P0：终止异常慢 SQL 会话。\n"
        ),
        process_blocks=[],
    )

    candidates = card.root_cause.candidates
    assert len(candidates) == 2
    assert candidates[0].rank == 1
    assert candidates[0].reason == "InnoDB 行锁竞争阻塞链"
    assert candidates[0].resource_name == "db_mysql_001（3094）"
    assert candidates[0].confidence == "86%"
    assert candidates[0].evidence == "锁等待告警 12 条；时序先于应用异常"
    assert candidates[1].rank == 2
    assert candidates[1].confidence == "45%"

    serialized = card.model_dump(by_alias=True)
    assert serialized["rootCause"]["candidates"][0]["resourceName"] == (
        "db_mysql_001（3094）"
    )


def test_build_alarm_analyst_card_without_candidates_subsection() -> None:
    card = build_alarm_analyst_card(
        chat_id="chat-8",
        message_id="assistant-8",
        employee_id="fault",
        report_markdown=(
            "🔴 数据库锁异常 — 完整故障分析报告\n"
            "## 根因分析结论\n"
            "- 根因：MySQL 资源 3094 存在锁等待放大。\n"
            "## 处置建议\n"
            "- P0：终止异常慢 SQL 会话。\n"
        ),
        process_blocks=[],
    )

    assert card.root_cause.candidates == []


def test_extract_root_cause_candidates_tolerates_messy_table() -> None:
    from qwenpaw.extensions.api.alarm_analyst_card_service import (
        _extract_root_cause_candidates,
    )

    # Reordered columns, a row with no reason, and a separator row.
    candidates = _extract_root_cause_candidates(
        "### 候选根因\n"
        "| 候选根因 | 置信度 | 排名 |\n"
        "|---|---|---|\n"
        "| 仅有根因列 | | 1 |\n"
        "| | 50% | 2 |\n"
        "| 第三条 | 30% | 3 |\n"
    )

    assert [item.reason for item in candidates] == ["仅有根因列", "第三条"]
    assert candidates[0].rank == 1
    assert candidates[0].confidence == ""
    assert candidates[1].rank == 3
    assert candidates[1].confidence == "30%"


def test_extract_topology_payload_flattens_tree_series() -> None:
    from qwenpaw.extensions.api.alarm_analyst_card_service import (
        _extract_topology_payload,
    )

    process_blocks = [
        {
            "kind": "tool",
            "toolName": "cmdb_topology",
            "outputContent": (
                "{\"series\":[{\"type\":\"tree\",\"orient\":\"LR\","
                "\"data\":[{\"name\":\"天翼智观\",\"children\":["
                "{\"name\":\"k3s-SYM01\",\"children\":["
                "{\"name\":\"天翼智观部署虚机\"}]}]}]}]}"
            ),
        }
    ]

    nodes, edges = _extract_topology_payload(process_blocks)

    names = {node["name"] for node in nodes}
    assert names == {"天翼智观", "k3s-SYM01", "天翼智观部署虚机"}
    assert len(edges) == 2
    root_id = next(node["id"] for node in nodes if node["name"] == "天翼智观")
    mid_id = next(node["id"] for node in nodes if node["name"] == "k3s-SYM01")
    assert {"source": root_id, "target": mid_id} in edges


def test_extract_topology_payload_still_supports_graph_series() -> None:
    from qwenpaw.extensions.api.alarm_analyst_card_service import (
        _extract_topology_payload,
    )

    process_blocks = [
        {
            "kind": "tool",
            "toolName": "cmdb_topology",
            "outputContent": (
                "{\"series\":[{\"type\":\"graph\","
                "\"data\":[{\"id\":\"a\",\"name\":\"A\"},{\"id\":\"b\",\"name\":\"B\"}],"
                "\"links\":[{\"source\":\"a\",\"target\":\"b\"}]}]}"
            ),
        }
    ]

    nodes, edges = _extract_topology_payload(process_blocks)

    assert nodes == [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}]
    assert edges == [{"source": "a", "target": "b"}]


def test_build_alarm_analyst_card_extracts_staged_recommendations() -> None:
    card = build_alarm_analyst_card(
        chat_id="chat-1",
        message_id="assistant-1",
        employee_id="fault",
        report_markdown=(
            "🔴 端口 LinkDown — 完整故障分析报告\n"
            "## 根因分析结论\n"
            "- 根因：核心链路光模块故障（CI ID 3094）。\n"
            "## 影响范围\n"
            "- 受影响资源：3094\n"
            "## 处置建议\n"
            "### 🚑 紧急预案（止血，立即执行）\n"
            "1. 将受影响用户切换至备用链路恢复访问（需人工确认审批后执行）\n"
            "### 🔧 根因处置（修复，可择机安排）\n"
            "1. 更换故障光模块，安排业务低峰窗口\n"
            "2. 观察告警是否收敛\n"
        ),
        process_blocks=[],
    )

    stages = [item.stage for item in card.recommendations]
    assert stages == ["emergency", "repair", "repair"]
    assert card.recommendations[0].priority == "p0"
    assert "备用链路" in card.recommendations[0].description


def test_extract_recommendations_without_subsections_keeps_stage_none() -> None:
    card = build_alarm_analyst_card(
        chat_id="chat-1",
        message_id="assistant-1",
        employee_id="fault",
        report_markdown=(
            "🔴 单用户光猫故障 — 完整故障分析报告\n"
            "## 根因分析结论\n"
            "- 根因：用户光猫光模块老化（CI ID 12）。\n"
            "## 影响范围\n"
            "- 仅该用户\n"
            "## 处置建议\n"
            "- 上门更换光猫，常规工单排期\n"
        ),
        process_blocks=[],
    )

    assert card.recommendations
    assert all(item.stage is None for item in card.recommendations)


def test_extract_display_fields_includes_emergency_plan_row() -> None:
    from qwenpaw.extensions.api.alarm_analyst_card_service import (
        extract_display_fields,
    )

    display = extract_display_fields(
        {
            "rawReportMarkdown": (
                "## 告警分析报告：端口 LinkDown\n"
                "## 📊 总结\n"
                "- 置信度：86%\n"
                "- 故障性质：核心链路光模块故障\n"
                "- 影响范围：A 片区 3 栋楼\n"
                "- 紧急预案：先将受影响用户切换至备用链路恢复访问\n"
                "- 优先动作：切换备用链路止血后更换光模块\n"
            ),
            "summary": {},
            "rootCause": {},
        }
    )

    assert display["emergencyPlan"] == "先将受影响用户切换至备用链路恢复访问"


def test_extract_display_fields_includes_numbered_disposal_suggestions() -> None:
    from qwenpaw.extensions.api.alarm_analyst_card_service import (
        extract_display_fields,
    )

    display = extract_display_fields(
        {
            "rawReportMarkdown": "## 告警分析报告：端口 LinkDown\n",
            "summary": {},
            "rootCause": {},
            "recommendations": [
                {"title": "建议 1", "description": "🚑 切换至备用链路"},
                {"title": "建议 2", "description": "更换故障光模块"},
                {"title": "建议 3", "description": ""},
            ],
        }
    )

    assert display["disposalSuggestions"] == [
        "1. 🚑 切换至备用链路",
        "2. 更换故障光模块",
        "3. 建议 3",
    ]


def test_extract_display_fields_omits_empty_disposal_suggestions() -> None:
    from qwenpaw.extensions.api.alarm_analyst_card_service import (
        extract_display_fields,
    )

    display = extract_display_fields(
        {
            "rawReportMarkdown": "## 告警分析报告：端口 LinkDown\n",
            "summary": {},
            "rootCause": {},
        }
    )

    assert "disposalSuggestions" not in display
