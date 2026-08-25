---
name: cmdb-lookup
description: CMDB 资源查询示例技能。当用户询问"查一下 MySQL 实例""列出所有 Redis""查 CI 3034 的拓扑""统计数据库资源数量""CMDB 管理了哪些应用"时使用。本技能演示如何通过 MCP 调用 cmdb-query 完成常见 CMDB 查询。
tags: [cmdb, example, demo]
---

# CMDB 查询示例

这是一个最小可用的 CMDB 查询技能，演示如何通过 MCP 完成常见查询。

## MCP 优先级

本工作区已启用 `cmdb-query` MCP Server。Agent 必须优先直接调用 `cmdb-query__*` 工具获取数据；不要使用 curl、requests 或脚本。

## 常见场景

### 查实例

用户说"查 MySQL 实例"时：

1. 调 `cmdb-query__listCiTypes` 分页找到目标模型的 `name`（如 `mysql`）
2. 调 `cmdb-query__searchCiInstances(q="_type:mysql", page=1, count=100)`
3. 多实例时列出候选让用户选择，禁止自动任选

### 查应用列表

用户说"CMDB 管理了哪些应用"时：

调 `cmdb-query__searchCiInstances(q="_type:project", page=1, count=100)`

`project` 在 CMDB 中对应"应用"模型。返回结果中列出应用名称，表格展示。

### 查拓扑

用户说"查 CI 3034 的拓扑"时：

调 `cmdb-query__getCiRelations(root_id="3034", level=1, count=10000)`

输出 ECharts 树状图（`series.type='tree'`，从左到右展开）。

### 查统计

用户说"统计数据库资源类型分布"时：

调 `cmdb-query__countCiByGroup(type=5)`（`5` 是数据库分组 ID）

输出饼图或表格。

## 自然语言映射

| 用户说法 | MCP 调用 |
| --- | --- |
| "查 MySQL 实例" | `cmdb-query__listCiTypes` → `cmdb-query__searchCiInstances(q="_type:mysql")` |
| "CMDB 管理了哪些应用" | `cmdb-query__searchCiInstances(q="_type:project")` |
| "查 CI 3034 详情" | `cmdb-query__getCiInstance(id="3034")` |
| "查 CI 3034 拓扑" | `cmdb-query__getCiRelations(root_id="3034")` |
| "列出所有 CMDB 模型" | `cmdb-query__listCiTypes` |
| "统计数据库资源数量" | `cmdb-query__countCiByGroup(type=5)` |
| "查看关系类型" | `cmdb-query__listRelationTypes` |

## 返回要求

- 列表类：表格展示关键字段，不要原样塞 JSON
- 拓扑类：输出 ```echarts 代码块
- 统计类：1~3 句结论 + 图表
- 多实例时列出候选，不要默认任选