---
name: alarm-lookup
description: 告警查询示例技能。当用户询问"最近有哪些活跃告警""有哪些严重告警""数据库当前告警""查端口 DOWN 告警""最近 24 小时告警"时使用。本技能演示如何通过 MCP 调用 alarm 完成告警查询。
tags: [alarm, example, demo]
---

# 告警查询示例

最小可用的告警查询技能，演示通过 MCP 完成告警查询与统计分析。

## MCP 优先级

本工作区已启用 `alarm` MCP Server。Agent 必须优先直接调用 `alarm__queryHistoricalAlarms` 获取数据；不要使用 curl、requests 或脚本。

## 唯一 MCP Tool

| 工具 | 用途 | 关键参数 |
| --- | --- | --- |
| `alarm__queryHistoricalAlarms` | 查询告警列表 | beginTime, endTime, isClear, alarmSeverity, pageNum, pageSize, queryKey, alarmClassType |

## 常见场景

### 查活跃告警

用户说"最近有哪些活跃告警"时：

```json
{
  "beginTime": "<24小时前>",
  "endTime": "<当前时间>",
  "isClear": "0",
  "pageNum": 1,
  "pageSize": 10
}
```

### 查严重告警

用户说"有哪些严重告警"时：

```json
{
  "beginTime": "<24小时前>",
  "endTime": "<当前时间>",
  "alarmSeverity": "1",
  "pageNum": 1,
  "pageSize": 10
}
```

### 查数据库告警

用户说"数据库当前告警"时：

```json
{
  "beginTime": "<24小时前>",
  "endTime": "<当前时间>",
  "isClear": "0",
  "alarmClassType": "数据库",
  "pageNum": 1,
  "pageSize": 10
}
```

### 统计分析

用户说"统计告警级别分布"时：

全量拉取后按 `alarmseverity` 字段分组计数，用环形图展示。

## 自然语言映射

| 用户说法 | 关键参数 |
| --- | --- |
| "最近活跃告警" | `isClear="0"` |
| "有哪些严重告警" | `alarmSeverity="1"` |
| "数据库当前告警" | `alarmClassType="数据库", isClear="0"` |
| "网络设备告警" | `alarmClassType="网络设备"` |
| "查端口 DOWN 告警" | `queryKey="端口"` |
| "最近 24 小时告警" | `beginTime` / `endTime` 填入 24 小时范围 |
| "统计告警级别分布" | 全量拉取 → 按 `alarmseverity` 分组 |

## 返回字段说明

| 字段 | 含义 |
| --- | --- |
| `alarmtitle` | 告警标题 |
| `alarmseverity` | 级别：1-紧急，2-严重，3-普通，4-预警 |
| `alarmstatus` | 状态：0-自动清除，1-活跃 |
| `devName` | 设备名称 |
| `manageIp` | 管理 IP |
| `eventtime` | 告警发生时间 |

## 返回要求

- 列表类：先给摘要，再给表格
- 统计类：先给结论，再给图表
- 默认展示前 20 条，说明总数

## 旧脚本回退

仅当 alarm MCP Driver 不可用时，才使用 `real-alarm` 脚本。