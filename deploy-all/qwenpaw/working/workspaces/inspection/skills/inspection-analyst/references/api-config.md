# 巡检指标 MCP 配置

本 Skill 的指标查询由当前智能体已注册的 `inspection` MCP Server 提供。Agent 直接调用 `inspection__*` Tools；Skill、脚本和文档中不得保存 MCP API Key、上游 token 或自行建立 SSE / JSON-RPC 连接。

## MCP Tools

| MCP Tool | 用途 | 调用约束 |
|---|---|---|
| `inspection__getMetricDefinitions` | 查询资源类型的全部指标定义 | `metricType` 必须传 CMDB 确认的模型名称；分页取全并按指标编码去重 |
| `inspection__getMetricData` | 批量查询指标值 | 使用真实 `resId`；将全部有效指标编码一次放入 `queryKeys`；`queryType != "0"` 时同时传时间范围 |
| `inspection__listInspectionConfigs` | 查询指标阈值规则 | 分页取全，仅使用当前资源类型和指标匹配的规则 |
| `inspection__listDictionaryData` | 查询规则操作符字典 | `dictType` 固定为 `verification_rules_new` |

## 调用顺序

1. CMDB 仍按 `zgops-cmdb` Skill 的既有流程确认资源、模型名称、真实 `resId` 和拓扑。
2. 调用 `inspection__getMetricDefinitions`，获取全部指标定义与指标编码。
3. 调用 `inspection__getMetricData`，批量获取全部指标的最近值或指定时间范围值。
4. 调用 `inspection__listInspectionConfigs` 和 `inspection__listDictionaryData`，完成规则匹配和操作符解码。
5. 按 Skill 规则生成巡检结论与 Portal 报告。

## 关键规则

- MCP Tool 返回上游错误、协议错误或不可解析结果时 fail-fast，不更换参数反复重试。
- 仅在 MCP Driver 未加载、工具不可用或协议无法解析时，才能使用 `scripts/inspect_resource_metrics.py` 作为旧直连回退；回退时需说明原因。
- 指标查询成功但最近值全空是合法的“无实时监控数据”结论，不重复调用或回退。
- `operator` 需要通过 `verification_rules_new` 字典解码。
- 命中规则配置时：**满足规则 = 正常，不满足规则 = 异常**。
- 没有对应规则配置的指标：标注“需结合上下文由大模型判断”，不要伪造阈值。
- 四个 MCP Tools 均为只读取数，不触发飞书、钉钉或应用通知。
