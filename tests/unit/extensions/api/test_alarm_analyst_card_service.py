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


def test_build_alarm_analyst_card_extracts_monitor_object_and_host_labels() -> None:
    card = build_alarm_analyst_card(
        chat_id="chat-anchor-1",
        message_id="assistant-anchor-1",
        employee_id="fault",
        report_markdown=(
            "## 告警分析报告：数据库锁异常\n"
            "## 告警基础信息\n"
            "| 字段 | 值 |\n"
            "|---|---|\n"
            "| 监控对象 | db_mysql_prod_01 |\n"
            "| 主机 | 10.43.150.186 |\n"
            "## 根因判断\n"
            "- MySQL 锁等待放大，导致写入链路受阻。\n"
            "## 处置建议\n"
            "- P0：终止异常慢 SQL 会话。\n"
        ),
        process_blocks=[],
    )

    assert card.root_cause.resource_name == "db_mysql_prod_01"
    assert card.workorder_proposal is not None
    assert card.workorder_proposal.device_name == "db_mysql_prod_01"
    assert card.workorder_proposal.manage_ip == "10.43.150.186"



def test_extract_display_fields_falls_back_to_monitor_object_and_host_labels() -> None:
    card = build_alarm_analyst_card(
        chat_id="chat-anchor-2",
        message_id="assistant-anchor-2",
        employee_id="fault",
        report_markdown=(
            "## 告警分析报告：数据库锁异常\n"
            "## 告警基础信息\n"
            "- 监控对象：db_mysql_prod_01\n"
            "- 主机：10.43.150.186\n"
            "## 根因判断\n"
            "- MySQL 锁等待放大，导致写入链路受阻。\n"
            "## 处置建议\n"
            "- P0：终止异常慢 SQL 会话。\n"
        ),
        process_blocks=[],
    )

    from qwenpaw.extensions.api.alarm_analyst_card_service import extract_display_fields

    display = extract_display_fields(card.model_dump(by_alias=True))

    assert display["anchorObject"] == "db_mysql_prod_01"
    assert display["rootCauseObject"] == "db_mysql_prod_01"



def test_build_alarm_analyst_card_generates_workorder_proposal_from_report_context() -> None:
    card = build_alarm_analyst_card(
        chat_id="chat-wo-1",
        message_id="assistant-wo-1",
        employee_id="fault",
        report_markdown=(
            "## 告警分析报告：数据库锁异常\n"
            "## 告警基础信息\n"
            "| 字段 | 值 |\n"
            "|---|---|\n"
            "| 设备名称 | db_mysql_001 |\n"
            "| 设备IP | 10.1.1.8 |\n"
            "| 告警时间 | 2026-07-22 10:00:00 |\n"
            "## 根因判断\n"
            "- MySQL 锁等待放大，导致写入链路阻塞。\n"
            "## 处置建议\n"
            "- P0：先切换到备用实例恢复访问。\n"
        ),
        process_blocks=[],
    )

    assert card.workorder_proposal is not None
    assert card.workorder_proposal.device_name == "db_mysql_001"
    assert card.workorder_proposal.manage_ip == "10.1.1.8"
    assert card.workorder_proposal.event_time == "2026-07-22 10:00:00"
    assert card.workorder_proposal.suggestions == ["P0：先切换到备用实例恢复访问。"]
    assert card.workorder_status is not None
    assert card.workorder_status.state == "idle"



def test_build_alarm_analyst_card_generates_workorder_proposal_from_table_recommendations() -> None:
    card = build_alarm_analyst_card(
        chat_id="chat-wo-table-1",
        message_id="assistant-wo-table-1",
        employee_id="fault",
        report_markdown=(
            "## 告警分析报告：进程监控内存超阈值\n"
            "## 告警基础信息\n"
            "| 字段 | 值 |\n"
            "|---|---|\n"
            "| 监控对象 | docker-zg-01 |\n"
            "| 主机 IP | 82.156.83.38 |\n"
            "| 告警时间 | 2026-07-28 10:00:00 |\n"
            "## 根因判断\n"
            "- k3s 进程内存持续增长，触发内存阈值告警。\n"
            "## 处置建议\n"
            "| 优先级 | 动作 | 说明 |\n"
            "|--------|------|------|\n"
            "| 🚑 **紧急** | 检查 k3s 进程当前内存占用趋势 | 在 82.156.83.38 上执行 top/htop 观察 k3s 进程 RES 内存，确认是否持续增长 |\n"
            "| 🔧 修复 | 检查集群 Pod 数量变化 | 排查是否有业务批量部署或调度异常导致 k3s 负载增加 |\n"
        ),
        process_blocks=[],
    )

    assert [item.priority for item in card.recommendations] == ["p0", "p1"]
    assert [item.stage for item in card.recommendations] == ["emergency", "repair"]
    assert card.recommendations[0].title == "检查 k3s 进程当前内存占用趋势"
    assert (
        card.recommendations[0].description
        == "检查 k3s 进程当前内存占用趋势：在 82.156.83.38 上执行 top/htop 观察 k3s 进程 RES 内存，确认是否持续增长"
    )
    assert card.workorder_proposal is not None
    assert card.workorder_proposal.device_name == "docker-zg-01"
    assert card.workorder_proposal.manage_ip == "82.156.83.38"
    assert card.workorder_proposal.suggestions == [
        "检查 k3s 进程当前内存占用趋势：在 82.156.83.38 上执行 top/htop 观察 k3s 进程 RES 内存，确认是否持续增长",
        "检查集群 Pod 数量变化：排查是否有业务批量部署或调度异常导致 k3s 负载增加",
    ]



def test_build_alarm_analyst_card_skips_table_header_as_title() -> None:
    card = build_alarm_analyst_card(
        chat_id="chat-wo-2",
        message_id="assistant-wo-2",
        employee_id="fault",
        report_markdown=(
            "| 项目 | 值 |\n"
            "|---|---|\n"
            "| 设备名称 | 172.28.75.4 |\n"
            "| 告警时间 | 2026-07-21 16:42:32 |\n"
            "## 根因判断\n"
            "- 正常逻辑：系统平均负载超过阈值（如 >80）才应告警。\n"
            "## 处置建议\n"
            "- P1：检查采集阈值与规则配置。\n"
        ),
        process_blocks=[],
    )

    assert card.workorder_proposal is not None
    assert card.workorder_proposal.title != "项目 | 值"
    assert card.summary.title != "项目 | 值"


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


def test_alarm_analyst_card_ignores_progress_chatter_as_impact_scope() -> None:
    card = build_alarm_analyst_card(
        chat_id="chat-progress",
        message_id="assistant-progress",
        employee_id="fault",
        report_markdown=(
            "## 告警分析报告：网卡带宽利用率过高\n"
            "## 影响范围\n"
            "报告推送成功！现在我来汇总完整的分析结论。\n"
            "## 处置建议\n"
            "- P1：核对网卡流量和 QoS 策略。\n"
        ),
        process_blocks=[],
    )

    assert card.impact.blast_radius_text is None
    assert not card.impact.affected_applications
    assert not card.impact.affected_resources
    assert not any(item.title == "影响范围" for item in card.evidence)


def test_extract_display_fields_ignores_progress_chatter_impact_scope() -> None:
    from qwenpaw.extensions.api.alarm_analyst_card_service import (
        extract_display_fields,
    )

    display = extract_display_fields(
        {
            "rawReportMarkdown": (
                "## 告警分析报告：网卡带宽利用率过高\n"
                "## 📊 总结\n"
                "- 影响范围：报告推送成功！现在我来汇总完整的分析结论。\n"
            ),
            "summary": {},
            "rootCause": {},
        }
    )

    assert "impactScope" not in display


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
