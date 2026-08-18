# 巡检 MCP 配置

本 Skill 的资源确认由当前智能体已注册的 `cmdb-query` MCP Server 提供，指标查询由已注册的 `inspection` MCP Server 提供。Agent 直接调用 `cmdb-query__*` 与 `inspection__*` Tools；Skill、脚本和文档中不得保存 MCP API Key、上游 token 或自行建立 SSE / JSON-RPC 连接。

## CMDB MCP Tools

| MCP Tool | 用途 | 调用约束 |
|---|---|---|
| `cmdb-query__listCiTypes` | 查询 CI 类型/模型 | 分页取全；模型 `name` 是唯一可用于 `metricType` 的真实来源，不能猜测或直接使用数字类型 ID |
| `cmdb-query__searchCiInstances` | 搜索 CI 实例 | 使用 `_type:<模型 name>`；完整处理分页；多候选必须让用户选择 |
| `cmdb-query__getCiInstance` | 确认单个 CI 详情 | `id` 必须为选中候选的真实 `_id`；确认后的 `_id` 才能作为 `resId` |
| `cmdb-query__getCiRelations` | 查询 CI 关系拓扑 | 仅用户需要依赖/影响面/拓扑或异常分析需要时，以确认 `_id` 作为 `root_id` 查询；空关系是合法结论 |

## MCP Tools

| MCP Tool | 用途 | 调用约束 |
|---|---|---|
| `inspection__getMetricDefinitions` | 查询资源类型的全部指标定义 | `metricType` 必须传 CMDB 确认的模型名称；分页取全并按指标编码去重 |
| `inspection__getMetricData` | 批量查询指标值 | 使用真实 `resId`；将全部有效指标编码一次放入 `queryKeys`；`queryType != "0"` 时同时传时间范围 |
| `inspection__listInspectionConfigs` | 查询指标阈值规则 | 分页取全，仅使用当前资源类型和指标匹配的规则 |
| `inspection__listDictionaryData` | 查询规则操作符字典 | `dictType` 固定为 `verification_rules_new` |

## 调用顺序

1. 调用 `cmdb-query__listCiTypes`，分页确认目标模型的真实 `name`。
2. 以该模型 `name` 调用 `cmdb-query__searchCiInstances`，完整处理分页；零候选直接说明无法确认资源，多候选等待用户选择。
3. 对选中候选调用 `cmdb-query__getCiInstance`，确认真实 `_id`、展示名和类型；使用确认后的 `_id` 作为 `resId`，模型 `name` 作为 `metricType`。
4. 仅在需要依赖、影响面或拓扑时调用 `cmdb-query__getCiRelations(root_id=<确认的 _id>)`；最终报告展示真实关系或“无关系”。
5. 调用 `inspection__getMetricDefinitions`，获取全部指标定义与指标编码。
6. 调用 `inspection__getMetricData`，批量获取全部指标的最近值或指定时间范围值。
7. 调用 `inspection__listInspectionConfigs` 和 `inspection__listDictionaryData`，完成规则匹配和操作符解码。
8. 按 Skill 规则生成巡检结论与 Portal 报告。

## 关键规则

- CMDB 与指标 MCP Tool 返回上游错误、协议错误或不可解析结果时 fail-fast，不更换参数反复重试。
- 仅当对应 MCP Driver 未加载、客户端/工具不可用或协议无法解析时，才能使用脚本回退；CMDB 回退只允许一次调用 `zgops-cmdb`，并记录 `zgops-cmdb-script-fallback` 与原因。
- 指标查询成功但最近值全空是合法的“无实时监控数据”结论，不重复调用或回退。
- `operator` 需要通过 `verification_rules_new` 字典解码。
- 命中规则配置时：**满足规则 = 正常，不满足规则 = 异常**。
- 没有对应规则配置的指标：标注“需结合上下文由大模型判断”，不要伪造阈值。
- 四个 MCP Tools 均为只读取数，不触发飞书、钉钉或应用通知。
