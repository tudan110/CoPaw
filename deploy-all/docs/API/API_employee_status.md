# 数字员工运行状态 API 文档

本文档描述 Portal 使用的数字员工运行状态接口，用于获取各数字员工当前是否运行中、是否存在紧急告警、最近会话等信息。

## 概述

- **QwenPaw 后端基础路径**: `http://127.0.0.1:8088`
- **接口路径**:
  - 后端原始路径: `GET /api/portal/employee-status`

## 认证说明

该接口位于 `/api/portal` 路径下，遵循项目统一认证规则：

- 未启用认证时，可直接访问
- 启用认证后，外部请求需在 header 中携带 `Authorization: Bearer <token>`

## Helm 部署访问说明

如果系统通过 Helm 部署到 Kubernetes，且调用方与 QwenPaw / Portal 部署在**同一个 namespace** 下，建议直接通过 Service 名称访问。

### 同 namespace 调用

#### 1. 直接调用 QwenPaw 原始后端接口

```text
http://qwenpaw:8088/api/portal/employee-status
```

### 跨 namespace 调用

若调用方与服务不在同一个 namespace，可使用 Kubernetes 集群内完整域名：

#### 1. 直接调用 QwenPaw 原始后端接口

```text
http://qwenpaw.<namespace>.svc.cluster.local:8088/api/portal/employee-status
```

### 建议

- **后端系统/服务间调用**：优先使用 `http://qwenpaw:8088/api/portal/employee-status`

## 接口说明

### 获取数字员工运行状态

返回 Portal 中各数字员工的聚合运行状态，包括：

- 是否可用
- 是否正在运行
- 是否处于紧急任务状态
- 当前任务描述
- 历史对话概况
- 告警数量

**请求**

```http
GET /api/portal/employee-status
```

### 查询参数

无

## 响应结构

### 顶层结构

```json
{
  "employees": [
    {
      "employeeId": "query",
      "employeeName": "数据分析专家",
      "available": true,
      "status": "idle",
      "urgent": false,
      "stateLabel": "待机",
      "workStatus": "待机",
      "progress": "100%",
      "currentJob": "最近会话：CPU 使用率分析",
      "hasConversation": true,
      "totalChatCount": 3,
      "activeTaskCount": 0,
      "activeChatCount": 0,
      "alertCount": 0,
      "latestSessionTitle": "CPU 使用率分析",
      "updatedAt": "2026-04-15T11:30:00+00:00"
    },
    {
      "employeeId": "fault",
      "employeeName": "故障分析专家",
      "available": true,
      "status": "idle",
      "urgent": true,
      "stateLabel": "紧急任务",
      "workStatus": "紧急任务",
      "progress": "0%",
      "currentJob": "待处理告警 2 条",
      "hasConversation": true,
      "totalChatCount": 5,
      "activeTaskCount": 0,
      "activeChatCount": 0,
      "alertCount": 2,
      "latestSessionTitle": "端口 down 定位",
      "updatedAt": "2026-04-15T11:28:00+00:00"
    }
  ],
  "updatedAt": "2026-04-15T11:30:05+00:00"
}
```

### 字段说明

#### 顶层字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `employees` | `array` | 数字员工状态列表 |
| `updatedAt` | `string` | 本次接口响应生成时间，ISO 8601 格式 |

#### employees[] 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `employeeId` | `string` | 数字员工 ID |
| `employeeName` | `string` | 数字员工名称 |
| `available` | `boolean` | 后端是否成功找到该员工对应 workspace |
| `status` | `string` | 运行状态，取值：`running` / `idle` |
| `urgent` | `boolean` | 是否处于紧急状态 |
| `stateLabel` | `string` | 展示用状态文案，如 `运行中` / `待机` / `紧急任务` |
| `workStatus` | `string` | 展示用工作状态文案 |
| `progress` | `string` | 当前进度展示值，取值：`0%` / `50%` / `100%` / `--` |
| `currentJob` | `string` | 当前任务描述 |
| `hasConversation` | `boolean` | 是否存在历史会话 |
| `totalChatCount` | `number` | 总会话数 |
| `activeTaskCount` | `number` | 当前活动任务数 |
| `activeChatCount` | `number` | 当前活动对话数 |
| `alertCount` | `number` | 当前告警数 |
| `latestSessionTitle` | `string` | 最近一次会话标题 |
| `updatedAt` | `string` | 当前员工状态更新时间，ISO 8601 格式 |

## 当前覆盖的员工

当前接口会返回以下数字员工状态：

- `query`
- `fault`
- `knowledge`
- `resource`
- `inspection`
- `order`

## 状态判定规则

### 1. 紧急任务

当 `alertCount > 0` 时：

- `urgent = true`
- `stateLabel = "紧急任务"`
- `workStatus = "紧急任务"`
- `progress = "0%"`

### 2. 运行中

当 `activeTaskCount > 0` 且 `alertCount = 0` 时：

- `status = "running"`
- `urgent = false`
- `stateLabel = "运行中"`
- `progress = "50%"`

### 3. 待机

当没有活动任务且没有告警时：

- `status = "idle"`
- `urgent = false`
- `stateLabel = "待机"`

若有历史会话，则：

- `currentJob` 会显示最近会话标题
- `progress = "100%"`

若没有历史会话，则：

- `currentJob = "暂无对话"`
- `progress = "--"`

## 当前告警来源说明

目前只有 **故障分析专家** (`fault`) 接入了真实告警源：

- 告警来源：`query_alarm_workorders()`
- 判定方式：查询待处理告警/工单数量，数量大于 0 即认为是紧急任务

其他员工当前未接入后端真实告警源，因此：

- `alertCount = 0`
- `urgent = false`

## 示例

### 1. 直接访问 QwenPaw 后端接口

```bash
curl "http://127.0.0.1:8088/api/portal/employee-status"
```

### 2. 启用认证时访问

```bash
curl "http://127.0.0.1:8088/api/portal/employee-status" \
  -H "Authorization: Bearer <token>"
```
