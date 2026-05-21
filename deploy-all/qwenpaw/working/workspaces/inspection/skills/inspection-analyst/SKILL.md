---
name: inspection-analyst
category: inspection
tags: [inspection, health-check, cmdb, topology, metrics, database, middleware, resource]
triggers: [巡检, 资源巡检, 健康检查, 数据库巡检, 帮我巡检一下数据库, 帮我巡检一下中间件]
description: 资源巡检技能。当用户要求巡检、健康检查、查看指标数据时使用。覆盖 CMDB 拓扑确认、全量指标批量查询、阈值判定、多渠道通知推送（飞书/钉钉/应用）。即使用户只说"看看数据库状态"也应触发此技能。
---

# Inspection Analyst

完成一条真实巡检链路：识别巡检对象 → CMDB 确认拓扑 → 批量查询指标 → 阈值判定 → 输出结果 → 通知推送。

## 执行流程

1. **识别巡检对象**：用户指定的资源（数据库、中间件、主机等）
2. **CMDB 确认**：使用 inspection 本地 `zgops-cmdb` 完成以下链路：
   - `scripts/zgops-cmdb.sh list-models` → 确认目标类型的 `name`（如 `redis`、`mysql`）
   - `scripts/zgops-cmdb.sh fetch "/api/v0.1/ci/s?q=_type:<name>&page=1&count=100"` → 获取实例列表
   - 多实例时列出候选让用户选择
   - 从选中实例取 `_id` 作为 resId、`_type` 作为 ciType
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

## 本地优先原则

查 CMDB / 拓扑时默认先用 **inspection 本地的 `zgops-cmdb`**。只有以下情况才回退协作 query：

- inspection 工作区下没有 `zgops-cmdb`
- 本地 skill 配置缺失 / 接口未接通 / 执行失败
- 用户明确要求协作其他智能体

回退时必须在过程说明中写出回退原因。

## 关键规则

- **不能猜测 resId / ciType**：多个候选时列出清单让用户选择
- **不能假装查询成功**：接口失败直接报错，不返回假数据
- **必须展示拓扑**：最终输出中显式展示 CMDB 拓扑关系，不能省略成"拓扑已确认"
- **阈值判定**：满足规则 = 正常，不满足 = 异常；无规则的标注"需大模型判断"
- **通知未配置时**：明确写出"通知未配置"

## 输出结构

```markdown
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
