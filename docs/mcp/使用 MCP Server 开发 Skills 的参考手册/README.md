# MCP Server 参考手册

## 概述

MCP（Model Context Protocol）是一种标准化的工具调用协议。平台提供了 7 个 MCP Server，共 56 个 Tool。你只需要在 Skill 的 SKILL.md 中引用这些 Tool，Agent 就能自动调用，无需关心底层 API 地址、认证方式或网络细节。

### 如何导入

在平台配置中心 → MCP 管理 → 新增MCP，将下方各 Server 的导入 JSON 粘贴进去即可。现在已经导入过了，可以在 MCP 管理里面查看。每个 Server 只需导入一次，导入后该智能体即可使用其中的所有 Tool。

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
查应用列表    → cmdb-query__searchCiInstances(q="_type:project")
```

<details>
<summary>导入 JSON</summary>

```json
{
  "mcpServers": {
    "cmdb-query": {
      "url": "http://81.70.93.245:31080/mcp-servers/cmdb-query/sse",
      "type": "sse",
      "headers": {
        "X-API-Key": "<your-api-key>"
      }
    }
  }
}
```
</details>

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

<details>
<summary>导入 JSON</summary>

```json
{
  "mcpServers": {
    "cmdb-edit": {
      "url": "http://81.70.93.245:31080/mcp-servers/cmdb-edit/sse",
      "type": "sse",
      "headers": {
        "X-API-Key": "<your-api-key>"
      }
    }
  }
}
```
</details>

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

<details>
<summary>导入 JSON</summary>

```json
{
  "mcpServers": {
    "alarm": {
      "url": "http://81.70.93.245:31080/mcp-servers/alarm/sse",
      "type": "sse",
      "headers": {
        "X-API-Key": "<your-api-key>"
      }
    }
  }
}
```
</details>

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

<details>
<summary>导入 JSON</summary>

```json
{
  "mcpServers": {
    "inspection": {
      "url": "http://81.70.93.245:31080/mcp-servers/inspection/sse",
      "type": "sse",
      "headers": {
        "X-API-Key": "<your-api-key>"
      }
    }
  }
}
```
</details>

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

<details>
<summary>导入 JSON</summary>

```json
{
  "mcpServers": {
    "order": {
      "url": "http://81.70.93.245:31080/mcp-servers/order/sse",
      "type": "sse",
      "headers": {
        "X-API-Key": "<your-api-key>"
      }
    }
  }
}
```
</details>

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

<details>
<summary>导入 JSON</summary>

```json
{
  "mcpServers": {
    "resource": {
      "url": "http://81.70.93.245:31080/mcp-servers/resource/sse",
      "type": "sse",
      "headers": {
        "X-API-Key": "<your-api-key>"
      }
    }
  }
}
```
</details>

---

### 7. web-check-app（Web 拨测）

> 14 个工具

| 工具名 | 用途 |
| --- | --- |
| `getWebMonitorHealth` | 健康检查 |
| `getMonitorDashboard` | 查询监测看板 |
| `listMonitors` | 查询监测任务列表 |
| `getMonitor` | 查询监测任务详情 |
| `createMonitor` | 创建监测任务 |
| `updateMonitor` | 更新监测任务 |
| `deleteMonitor` | 删除监测任务 |
| `publishMonitor` | 发布监测任务 |
| `triggerMonitor` | 手工触发监测任务 |
| `listMonitorRuns` | 查询任务执行记录 |
| `getMonitorRun` | 查询单次执行详情 |
| `deleteMonitorRun` | 删除单次执行记录 |
| `batchDeleteMonitorRuns` | 批量删除执行记录 |
| `suggestSelectors` | 生成页面元素选择器建议 |

**适用场景**：网站可用性监测、拨测任务管理。

<details>
<summary>导入 JSON</summary>

```json
{
  "mcpServers": {
    "web-check-app": {
      "url": "http://81.70.93.245:31080/mcp-servers/web-check-app/sse",
      "type": "sse",
      "headers": {
        "X-API-Key": "<your-api-key>"
      }
    }
  }
}
```
</details>

---

## 在 Skill 中调用 MCP

### 命名规范

```
<MCP Server 名>__<工具名>
```

例如：
- `cmdb-query__searchCiInstances`
- `alarm__queryHistoricalAlarms`
- `inspection__getMetricData`
- `web-check-app__listMonitors`

### 编写 SKILL.md

一个完整的 Skill 只需包含以下内容：

```markdown
---
name: 技能名称
description: 技能描述，写明何时触发
---

## MCP 优先级

本工作区已启用 `<MCP Server 名>` MCP Server。Agent 必须优先直接调用
`<前缀>__<工具名>` 获取数据；不要使用 curl、requests 或脚本。

## 能力

| 操作 | MCP Tool |
| --- | --- |
| 场景一 | `<前缀>__<工具名>` |
| 场景二 | `<前缀>__<工具名>` |

## 自然语言映射

- "用户说法" → `<前缀>__<工具名>(参数)`
```

### 完整示例

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
```

更多完整示例见 `demos/` 目录。

---

## 调用规则

- **MCP 优先**：Agent 优先调用 MCP Tool，不要使用 curl、requests 或 SSE
- **零配置**：不需要在 Skill 中写 `.env` 或 API Key，MCP 自带认证
- **参数即文档**：每个 Tool 的参数由 MCP 自动描述，Agent 知道如何传参