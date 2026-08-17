---
name: monitoring-overview-query
description: 查询监控总览/运维驾驶舱页面数据。适用于用户询问当前系统概览、智观系统运行状态、整体运行态势、监控概况、资产总览、应用健康概览、告警对象 Top5、全局/系统/监控/简易拓扑时使用。监控页中的实时告警时间范围查询继续使用 real-alarm；具体某个应用的 CMDB 关系拓扑继续使用 zgops-cmdb。
---

# Monitoring Overview Query

查询监控总览/运维驾驶舱数据。面向"全局监控总览"和"系统级概览"，不需要用户先选择某个 CMDB 应用。

## MCP 优先级

本工作区已启用 `resource` MCP Server（含监控总览工具）。Agent 必须优先直接调用以下 MCP Tools；不要自行使用 `curl`、`requests`、SSE 或 JSON-RPC。

仅在 resource MCP Driver 未加载或相关工具不可用时，才允许回退到旧脚本路径（见末尾"旧脚本回退路径"）。

## 边界

- 告警列表、实时告警、按时间范围查询告警：继续使用 `real-alarm`
- 数据库状态总览、资源性能 Top、数据库指标清单：继续使用 `resource-insight-query`
- CMDB count/group、模型分布、厂商分布：继续使用 `zgops-cmdb`
- 指定了具体应用名/项目名的应用关系拓扑：继续使用 `zgops-cmdb`
- 未指定具体应用的"简易拓扑 / 系统拓扑 / 全局拓扑 / 监控拓扑"：使用本技能的 `queryMonitoringTopology`

## MCP Tools

| 操作 | MCP Tool | 参数 |
| --- | --- | --- |
| 告警对象排行 | `resource__queryAlarmResourceTop` | `alarmClassType`, `alarmSeverity`, `type` |
| 监控拓扑 | `resource__queryMonitoringTopology` | 无 |
| 资产总览 | `resource__queryAssetOverview` | 无 |

## 自然语言映射

- "告警对象 top5 / 告警对象排行" → `resource__queryAlarmResourceTop`
- "系统概览 / 当前运行态势 / 监控概况 / 应用健康概览" → `resource__queryAssetOverview`
- "监控拓扑 / 简易拓扑 / 系统拓扑 / 全局拓扑 / 总览拓扑" → `resource__queryMonitoringTopology`，优先输出 `echarts` 代码块
- "资产总览 / 资源健康概览" → `resource__queryAssetOverview`
- "某某应用拓扑 / 指定应用依赖拓扑" → 不要用本技能，改用 `zgops-cmdb`
- "最近 24 小时实时告警" → 不要用本技能，改用 `real-alarm`

## 旧脚本回退路径

仅当 monitor-overview MCP Driver 不可用时，才执行以下命令。脚本自动从环境变量读取凭证。

```bash
cd skills/monitoring-overview-query
python3 scripts/monitoring_overview.py alarm-top5 --output markdown
python3 scripts/monitoring_overview.py topology --output markdown
python3 scripts/monitoring_overview.py asset-overview --output markdown
```

回退时必须在过程说明中写明回退原因（如 `resource-mcp-unavailable`）。