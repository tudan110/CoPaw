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
3. **查询指标**：调用巡检脚本，批量查询全部指标定义与指标值
4. **输出结果**：包含拓扑关系、指标数据表、巡检结论
5. **通知推送**：脚本自动按配置推送到飞书/钉钉/应用

## 执行命令

拿到 resId 与 ciType 后立即执行，不要停在"计划调用""是否继续"：

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
- **Fail Fast，单次尝试即可下结论**：CMDB / 指标查询接口失败（超时、401/403/404/5xx、连接错误）或返回空，按失败/空直接处理，不做二次三次重试，不切换参数硬凑结果
- **指标值为空是合法结论**：脚本成功返回但指标最近值全空（采集链路无数据 / `originalDatas: []`），**直接如实产出"无实时监控数据"报告即可**。不要为"证明真的没数据"绕去 alarm-analyst / resource-insight-query 等其他 skill 反复验证，也不要重复重跑巡检脚本（单次约 12s）——一次拿到空值就可以下结论
- **必须展示拓扑**：最终输出中显式展示 CMDB 拓扑关系，不能省略成"拓扑已确认"
- **阈值判定**：满足规则 = 正常，不满足 = 异常；无规则的标注"需大模型判断"
- **通知未配置时**：明确写出"通知未配置"

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
