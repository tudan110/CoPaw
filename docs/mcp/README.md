# MCP Server 参考手册

## 概述

MCP（Model Context Protocol）是一种标准化的工具调用协议。我们的 QwenPaw 平台部署了 6 个 MCP Server，Agent 可以通过调用这些 Server 提供的 Tool 来查询/操作业务系统，无需编写脚本或手动配置 API 凭证。

### 为什么用 MCP？

- **零配置**：Agent 直接调用 MCP Tool，无需 `.env` 文件或手动管理 Token
- **安全**：增删改操作（cmdb-edit）只在特定智能体启用，权限可控
- **统一**：所有查询走同一个入口，不再需要记住不同的脚本命令

---

## MCP Server 清单

### 1. cmdb-query（CMDB 查询）

> 16 个工具，只读查询

| 工具名 | 用途 | 参数 |
| --- | --- | --- |
| `listCiTypes` | 查询 CI 类型列表 | page, per_page |
| `searchCiInstances` | 搜索 CI 实例 | q（查询条件）, page, count |
| `getCiInstance` | 查询 CI 实例详情 | id（CI ID） |
| `getCiRelations` | 查询 CI 关系拓扑 | root_id, level, count |
| `getCiTypeAttributes` | 查询 CI 类型属性 | id |
| `listCiTypeRelations` | 查询 CI 类型之间的关系 | ci_type_id |
| `listCiTypeGroups` | 查看 CI 类型分组目录 | — |
| `listRelationTypes` | 查询所有关系类型 | — |
| `listCmdbTypes` | 查看 CMDB 类型列表 | — |
| `getCmdbUserInfo` | 查询当前用户信息 | — |
| `cmdbLogin` | CMDB 登录 | — |
| `countCi` | CI 数量统计 | type（分组 ID） |
| `countCiByGroup` | CI 按分组统计 | type |
| `countCiByAttribute` | CI 按属性分组统计 | type, attr |
| `countChildCi` | CI 子类型统计 | type |
| `countChildCiByGroup` | CI 子类型分组统计 | type, attr |

**适用场景**：查 CMDB 资源、拓扑、模型、统计分布。

**示例**：
```
查 MySQL 实例 → cmdb-query__searchCiInstances(q="_type:mysql")
查 CI 详情    → cmdb-query__getCiInstance(id=3034)
查拓扑关系    → cmdb-query__getCiRelations(root_id=3034)
```

---

### 2. cmdb-edit（CMDB 编辑）

> 10 个工具，增删改。**仅在 resource 智能体启用**。

| 工具名 | 用途 |
| --- | --- |
| `createCiTypeGroup` | 创建 CI 类型分组 |
| `updateCiTypeGroup` | 更新 CI 类型分组 |
| `createCiType` | 创建 CI 类型 |
| `createCiTypeInheritance` | 创建 CI 类型继承关系 |
| `createCiTypeRelation` | 创建 CI 类型之间的关系 |
| `createCi` | 创建 CI 实例 |
| `updateCi` | 更新 CI 实例 |
| `deleteCi` | 删除 CI 实例 |
| `createCiRelation` | 创建 CI 关系 |
| `deleteCiRelation` | 删除 CI 关系 |

**适用场景**：资源导入、纳管、批量录入。

---

### 3. alarm（告警查询）

> 1 个工具

| 工具名 | 用途 | 参数 |
| --- | --- | --- |
| `queryHistoricalAlarms` | 查询告警列表 | beginTime, endTime, isClear, alarmSeverity, pageNum, pageSize, queryKey, neIp, alarmClassType |

**适用场景**：查询活跃告警、告警列表、按级别/设备/IP 筛选。

**示例**：
```
查活跃告警   → alarm__queryHistoricalAlarms(isClear="0", beginTime="...", endTime="...")
查数据库告警  → alarm__queryHistoricalAlarms(alarmClassType="数据库", isClear="0")
```

---

### 4. inspection（巡检指标）

> 4 个工具

| 工具名 | 用途 | 参数 |
| --- | --- | --- |
| `getMetricDefinitions` | 查询资源指标定义 | metricType（模型名）, pageNum, pageSize |
| `getMetricData` | 批量查询指标值 | mulRes, queryKeys, queryType |
| `listInspectionConfigs` | 查询巡检规则（阈值） | pageNum, pageSize |
| `listDictionaryData` | 查询操作符字典 | dictType（固定 `verification_rules_new`） |

**适用场景**：资源巡检、健康检查、指标阈值判定。

---

### 5. order（工单）

> 4 个工具

| 工具名 | 用途 | 参数 |
| --- | --- | --- |
| `getWorkOrderStats` | 工单统计 | startTime, endTime |
| `listWorkOrders` | 查询工单列表 | classify（1=待办，5=已办）, page, per_page |
| `getWorkOrderDetail` | 查询工单详情 | processId, workOrderId |
| `createWorkOrder` | 创建工单 | alarm（告警信息）, analysis（分析结论）, ticket（工单属性） |

**适用场景**：工单查询、统计、创建。

---

### 6. resource（资源状态与监控）

> 7 个工具

| 工具名 | 用途 | 参数 |
| --- | --- | --- |
| `getDatabaseResourceStatusOverview` | 数据库状态总览 | — |
| `getTopMetricData` | 页面性能 Top 数据 | orderCode, topNum, type |
| `getTopResourceMetricData` | 资源性能 Top 数据 | orderKey, topNum, type |
| `queryDatabasePerformanceMetrics` | 数据库性能指标分页 | keyWord, pageNum, pageSize |
| `queryAlarmResourceTop` | 告警对象 Top 统计 | alarmClassType, alarmSeverity, type |
| `queryAssetOverview` | 资产总览 | — |
| `queryMonitoringTopology` | 监控总览拓扑 | — |

**适用场景**：资源状态总览、性能排行、监控大屏。

---

## 在 Skill 中调用 MCP

### 命名规范

在 SKILL.md 中引用 MCP Tool 时，格式为：

```
<MCP Server 名>__<工具名>
```

例如：
- `cmdb-query__searchCiInstances`
- `alarm__queryHistoricalAlarms`
- `inspection__getMetricData`

### 关键原则

1. **MCP 优先**：Agent 优先调用 MCP Tool，仅在 MCP Driver 不可用时回退脚本
2. **Fail-fast**：MCP 返回业务错误（4xx/5xx）不回退脚本，直接报错
3. **零配置**：不需要在 Skill 中写 `.env` 配置，MCP 自带认证

### 如何判断 MCP 是否可用

在 SKILL.md 中写入以下引导：

```markdown
## MCP 优先级

本工作区已启用 `<MCP Server 名>` MCP Server。Agent 必须优先直接调用
`<前缀>__<工具名>` 获取数据；不要自行使用 curl、requests、SSE 或 JSON-RPC。

仅在 MCP Driver 未加载、客户端/工具不可用或协议响应无法解析时，
才允许回退到旧脚本路径。
```

---

## 完整示例：一个简单的查询类 Skill

假设我们要做一个"数据库状态查询"的 Skill，只需查询资源状态总览和性能 Top。

### SKILL.md

```markdown
---
name: database-status
description: 查询数据库资源状态和性能排行。当用户询问数据库状态、性能 Top 时使用。
---

# Database Status

## MCP 优先级

本工作区已启用 `resource` MCP Server。Agent 必须优先直接调用以下 MCP Tools。

## 能力

| 操作 | MCP Tool |
| --- | --- |
| 数据库状态总览 | `resource__getDatabaseResourceStatusOverview` |
| 数据库性能 Top | `resource__getTopMetricData` |
| 资源性能 Top | `resource__getTopResourceMetricData` |

## 自然语言映射

- "数据库状态" → `resource__getDatabaseResourceStatusOverview`
- "数据库磁盘 Top 5" → `resource__getTopMetricData(orderCode="diskRate", topNum=5)`
- "网络设备 CPU 排行" → `resource__getTopResourceMetricData(orderKey="cpuRate", topNum=5)`

## 旧脚本回退

仅在 resource MCP Driver 不可用时，才执行脚本。
```

更多完整示例见 `demos/` 目录。