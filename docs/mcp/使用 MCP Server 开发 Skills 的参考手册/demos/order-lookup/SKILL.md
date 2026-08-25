---
name: order-lookup
description: 工单查询示例技能。当用户询问"待办工单""已办工单""工单统计""工单详情""创建工单"时使用。本技能演示如何通过 MCP 调用 order 完成工单查询与创建。
tags: [order, example, demo]
---

# 工单查询示例

最小可用的工单查询技能，演示通过 MCP 完成工单查询、统计与创建。

## MCP 优先级

本工作区已启用 `order` MCP Server。Agent 必须优先直接调用 `order__*` 工具；不要使用 curl、requests 或脚本。

## MCP Tools

| 工具 | 用途 | 关键参数 |
| --- | --- | --- |
| `order__getWorkOrderStats` | 工单统计 | startTime, endTime |
| `order__listWorkOrders` | 工单列表 | classify（1=待办，5=已办）, page, per_page |
| `order__getWorkOrderDetail` | 工单详情 | processId, workOrderId |
| `order__createWorkOrder` | 创建工单 | alarm, analysis, ticket |

## 常见场景

### 查待办列表

```json
{ "classify": 1, "page": 1, "per_page": 10 }
```

### 查已办列表

```json
{ "classify": 5, "page": 1, "per_page": 10 }
```

### 查详情

从列表结果中取该行的 `workOrderId` 和 `processId`，调用：

```json
{ "processId": "<从列表取>", "workOrderId": "<从列表取>" }
```

### 工单统计

调 `order__getWorkOrderStats`，返回 `todoCount`、`inProgressCount`、`finishedCount`。

### 创建工单

```json
{
  "alarm": {
    "alarmTitle": "<告警标题>",
    "neName": "<设备名称>",
    "neIp": "<设备IP>",
    "alarmSeverity": "主要",
    "isClear": "活跃告警"
  },
  "analysis": {
    "summary": "<分析摘要>",
    "rootCause": "<根因>",
    "suggestions": ["<建议1>", "<建议2>"]
  },
  "ticket": {
    "title": "<工单标题>",
    "priority": "P2",
    "source": "portal-order-agent"
  }
}
```

必填：`alarmTitle` + (`neName` 或 `neIp` 至少一个)。

## 自然语言映射

| 用户说法 | MCP 调用 |
| --- | --- |
| "待办工单" | `order__listWorkOrders(classify=1)` |
| "已办工单" | `order__listWorkOrders(classify=5)` |
| "工单统计" | `order__getWorkOrderStats` |
| "查看第 N 条详情" | `order__getWorkOrderDetail` |
| "创建工单" | `order__createWorkOrder` |

## 返回要求

- 列表类：带"序号"列的表格，"工单号""流程号"必须完整
- 创建工单：只补问缺失的必填字段