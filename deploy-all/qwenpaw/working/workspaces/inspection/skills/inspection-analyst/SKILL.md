---
name: inspection-analyst
category: inspection
tags: [inspection, health-check, cmdb, topology, metrics, database, middleware, resource]
triggers: [巡检, 资源巡检, 健康检查, 数据库巡检, 帮我巡检一下数据库, 帮我巡检一下中间件]
description: 资源巡检技能。当用户要求巡检、健康检查、查看指标数据时使用。覆盖 CMDB 拓扑确认、全量指标批量查询、阈值判定、多渠道通知推送（飞书/钉钉/应用）。即使用户只说"看看数据库状态"也应触发此技能。
bigscreen:
  name: 资源巡检指标
  domain: inspection
  script: scripts/inspect_resource_metrics.py
  args: ["--output", "json", "--no-notify"]
  rowsPath: metricDataBatch.metricResults
  unit: 项
  params:
    - {name: metric-type, label: 资源类型(ciType，如 mysql), required: true}
    - {name: res-id, label: CI ID(CMDB 资源ID), required: true}
  examplePrompts: ["巡检 res-id=3094 metric-type=mysql 的指标", "看 CI 3094 的巡检指标"]
---

# Inspection Analyst

完成一条真实巡检链路：识别巡检对象 → CMDB 确认拓扑 → 批量查询指标 → 阈值判定 → 输出结果 → 通知推送。

## 执行流程

1. **识别巡检对象**：用户指定的资源（数据库、中间件、主机等）
2. **CMDB 确认**：`zgops-cmdb` 是**同工作区下的兄弟 skill**（不是 inspection-analyst 内部脚本），从 inspection-analyst 目录用相对路径 `../zgops-cmdb/scripts/zgops-cmdb.sh` 调用，完成以下链路：
   - `../zgops-cmdb/scripts/zgops-cmdb.sh list-models` → 确认目标类型的 `name`（如 `redis`、`mysql`）
   - `../zgops-cmdb/scripts/zgops-cmdb.sh fetch "/api/v0.1/ci/s?q=_type:<name>&page=1&count=100"` → 获取实例列表
   - 多实例时列出候选让用户选择
   - 从选中实例取 `_id` 作为 resId；ciType 使用 `list-models` 查出的模型名称（如 `mysql`），也可直接传实例的 `_type` 数字 ID（脚本会自动转换）
3. **查询指标**：优先直接调用已注册的 `inspection` MCP Server，按“指标 MCP 调用”章节获取指标定义、指标值、阈值规则与操作符字典。
4. **输出结果**：按既有规则完成阈值判定，包含拓扑关系、指标数据表、巡检结论。
5. **通知推送**：只读 MCP Tools 不发送通知；仅在执行现有脚本回退路径时，才保留脚本按配置推送的行为。

## 指标 MCP 调用

本工作区已启用 `inspection` MCP Server。完成 CMDB 确认后，必须优先直接调用以下 MCP Tools；不要自行使用 `curl`、`requests`、SSE 或 JSON-RPC 访问接口，也不要为此编写额外 MCP 客户端。

### 调用顺序

1. 调用 `inspection__getMetricDefinitions`：

   ```json
   {
     "metricType": "<CMDB 确认的模型名称，例如 mysql>",
     "pageNum": 1,
     "pageSize": 100
   }
   ```

   - `metricType` 必须使用 CMDB `list-models` 确认后的模型名称，不能传空值。
   - CMDB 返回数字 `_type` 时，先按既有 CMDB 流程解析为模型名称，不能直接把数字传给 MCP Tool。
   - 逐页读取至全部指标定义完成，并按指标编码去重。

2. 从指标定义中提取全部有效指标编码，单次调用 `inspection__getMetricData`：

   ```json
   {
     "mulRes": [{"resId": "<CMDB 确认的真实 CI ID>"}],
     "queryKeys": ["<全部指标编码>"],
     "queryType": "0"
   }
   ```

   - `resId` 必须是 CMDB 确认的真实值，不能猜测或使用示例值。
   - `queryKeys` 必须一次传入全部有效指标编码；不要无必要拆成单指标多次查询。
   - 历史查询的 `queryType` 不等于 `"0"` 时，必须同时传 `startTime` 和 `endTime`。

3. 调用 `inspection__listInspectionConfigs`，以分页方式读取完整巡检规则；只使用与当前资源类型和指标编码匹配的规则。

4. 调用 `inspection__listDictionaryData`：

   ```json
   {"dictType": "verification_rules_new"}
   ```

   仅使用该字典解码规则 `operator`，不能传空 `dictType` 或用无关全量字典替代。

### 判定与回退

- MCP Tool 返回上游错误、协议错误或不可解析结果时，立即按失败处理，不要换参数反复重试；仅在 MCP Driver 未加载、不可用或返回协议无法解析时，才允许回退到下方旧脚本路径，并在过程说明中写明回退原因。
- 指标 Tool 成功但全部最近值为空，是“无实时监控数据”的合法结论；不要回退脚本、不要重复调用、不要转其他 Skill 验证。
- 使用 MCP 结果时，按本 Skill 的既有规则完成判定：满足阈值规则为正常，不满足为异常，无规则标注“需大模型判断”。
- MCP Tools 只负责取数，不自动发送通知。MCP 路径下应在报告中写明“通知未配置”；不要把只读巡检查询变成通知动作。

## 旧脚本回退路径

仅当 MCP Driver 未加载、工具不可用或 MCP 返回协议无法解析时，才执行以下命令。该脚本保留用于回退与结果基线，不作为默认指标查询方式：

```bash
cd skills/inspection-analyst && python scripts/inspect_resource_metrics.py \
  --res-id <CI_ID> --metric-type <ciType> \
  --inspection-object "<用户巡检对象>" --resource-name "<CMDB确认的资源名>" \
  --output markdown
```

### metric-type 参数说明

| 格式 | 示例 | 说明 |
|------|------|------|
| 模型名称（推荐） | `PostgreSQL`、`mysql`、`redis` | 直接匹配指标定义接口 |
| 数字 ID（自动转换） | `78`、`77`、`61` | CMDB 的 `_type` 字段值，脚本自动查询 ci_types 转换为模型名称 |

建议直接使用 CMDB 模型名称（即 `list-models` 输出的"模型名"列），避免额外查询开销。

## 本地优先原则

查 CMDB / 拓扑时默认先用 **inspection 本地的 `zgops-cmdb`**。只有以下情况才回退协作 query：

- inspection 工作区下没有 `zgops-cmdb`
- 本地 skill 配置缺失 / 接口未接通 / 执行失败
- 用户明确要求协作其他智能体

回退时必须在过程说明中写出回退原因。

## 关键规则

- **不能猜测 resId / ciType**：多个候选时列出清单让用户选择
- **不能假装查询成功**：接口失败直接报错，不返回假数据
- **Fail Fast，单次尝试即可下结论**：CMDB / MCP 指标查询接口失败（超时、401/403/404/5xx、连接错误）或返回不可解析结果时，按失败处理，不做二次三次重试，不切换参数硬凑结果；只有 MCP Driver 未加载、不可用或协议无法解析时，才按“旧脚本回退路径”执行一次回退。
- **指标值为空是合法结论**：MCP 指标查询成功但指标最近值全空（采集链路无数据 / `originalDatas: []`），**直接如实产出“无实时监控数据”报告即可**。不要为“证明真的没数据”绕去 alarm-analyst / resource-insight-query 等其他 skill 反复验证，也不要重复调用 MCP Tool 或回退脚本。
- **必须展示拓扑**：最终输出中显式展示 CMDB 拓扑关系，不能省略成"拓扑已确认"
- **阈值判定**：满足规则 = 正常，不满足 = 异常；无规则的标注"需大模型判断"
- **通知**：MCP 只读查询不发送通知，报告中明确写出“通知未配置”；只有旧脚本回退路径才按其现有配置处理通知。

## 输出结构

**每次输出完整巡检报告时，必须在最前面加上标志行和分隔线，否则 Portal 前端无法渲染卡片：**

> ⚠️ **正文章节之间禁止使用 `---` 水平分隔线。** `---` 只允许出现在标志行正下方那一处。Portal 按 `---` 切分内容来剥离标志行，正文里多写的每一条 `---` 都会把报告切碎、导致只剩 `## 巡检结果` 一段、基本信息/指标表全丢、摘要卡变成空白 `--`。章节之间一律用空行 + `##` 标题分隔。
>
> ⚠️ **基本信息表里状态字段名必须叫"状态"**，不要写成"资源状态""运行状态"，否则"在线状态"卡片取不到值。

```markdown
# PORTAL INSPECTION CARD MODE
---
## 巡检结果
（整体状态）

## 基本信息
| 项目 | 值 |
|------|-----|
| 巡检对象 | ... |
| 资源名称 | ... |
| 资源类型 | ... |
| 状态 | 正常/异常 |
| 指标总数 | ... |
| 数据来源 | live |
| 巡检时间 | ... |

## CMDB 拓扑关系
（根资源、上下游/关联资源）

## 指标数据
| 指标名 | 指标编码 | 最近值 | 状态 | 判定依据 |
|--------|----------|--------|------|----------|

## 巡检结论
（分析总结）
```

## 参考文档

按需查阅：

| 文件 | 何时查阅 |
|------|----------|
| `references/portal-card.md` | 需要 Portal 渲染巡检卡片时 |
| `references/notification.md` | 需要了解通知推送格式细节时 |
| `references/api-config.md` | 需要查看接口配置、阈值规则解码时 |
