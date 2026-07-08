# 响应格式

本文档描述告警列表接口的响应数据结构和字段说明。

> **请求与响应字段不对称**：请求 `hisAlarmList` 时传的是 `isClear`（见
> `api-specification.md`），但接口返回的每条告警对象里，状态字段仍然叫
> `alarmstatus`（本文档里的字段名）。解析响应时不要去找 `isClear` 字段。

## 标准响应结构

```json
{
  "msg": "操作成功",
  "total": 17,
  "code": 200,
  "rows": [...]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | int | 响应码，`200` 表示成功 |
| `msg` | string | 响应消息 |
| `total` | int | 告警总数 |
| `rows` | array | 告警列表数据 |

## 告警对象结构

```json
{
  "alarmuniqueid": "ALARM_2026031609382801_0000000000000001",
  "alarmclass": "sys_log",
  "alarmseverity": 1,
  "alarmtitle": "端口DOWN",
  "vendor": "HW",
  "devName": "device-core-01.rack-a",
  "devId": 18,
  "manageIp": "<device-ip>",
  "locatenename": "BindIfName=-",
  "alarmregion": "区域A",
  "eventtime": "2026-03-16 09:38:28",
  "daltime": "2026-03-13 09:38:28",
  "alarmactcount": 0,
  "eventlasttime": "2026-03-13 09:38:28",
  "canceltime": null,
  "alarmstatus": 1,
  "speciality": "IPM",
  "isOrder": "0"
}
```

## 核心字段说明

### 告警标识

| 字段 | 类型 | 说明 |
|------|------|------|
| `alarmuniqueid` | string | 告警唯一标识 |
| `alarmclass` | string | 告警类别（sys_log / threshold / derivative） |

### 告警信息

| 字段 | 类型 | 说明 |
|------|------|------|
| `alarmtitle` | string | 告警标题，如 `端口DOWN` |
| `alarmseverity` | int | 告警级别（1-紧急，2-严重，3-普通，4-预警） |
| `alarmstatus` | int | 告警状态（0-自动清除，1-活跃，2-同步清除，3-手工清除） |
| `alarmtext` | string | 告警文本描述 |

### 设备信息

| 字段 | 类型 | 说明 |
|------|------|------|
| `devName` | string | 设备名称 |
| `devId` | int/string | 当前告警对应的资源 ID（resId/CI ID） |
| `manageIp` | string | 管理IP |
| `vendor` | string | 厂商 |
| `locatenename` | string | 位置名称 |

### 时间信息

| 字段 | 类型 | 说明 |
|------|------|------|
| `eventtime` | string | 告警发生时间 |
| `daltime` | string | 发现时间 |
| `eventlasttime` | string | 相同告警压缩后最后发生时间 |
| `canceltime` | string | 清除时间（活跃告警为 null） |

### 分类信息

| 字段 | 类型 | 说明 |
|------|------|------|
| `speciality` | string | 专业分类，如 `IPM` |
| `alarmregion` | string | 告警区域 |
| `alarmcounty` | string | 告警区县 |

## 字段映射

### 告警级别

| 原始值 | 显示值 |
|--------|--------|
| `1` | 紧急 |
| `2` | 严重 |
| `3` | 普通 |
| `4` | 预警 |

### 告警状态

| 原始值 | 显示值 |
|--------|--------|
| `0` | 自动清除 |
| `1` | 活跃 |
| `2` | 同步清除 |
| `3` | 手工清除 |

### 告警类别

| 原始值 | 显示值 |
|--------|--------|
| `sys_log` | 设备告警 |
| `threshold` | 性能告警 |
| `derivative` | 衍生告警 |

## 使用建议

- **简单列表**：优先展示 `alarmtitle`、`alarmseverity`、`devName`、`eventtime`
- **详细信息**：补充 `manageIp`、`devId`、`speciality`、`alarmstatus`、`alarmregion`
- **统计分析**：按 `alarmseverity`、`speciality`、`devName`、`alarmregion` 分组
- **CI ID 展示**：优先 `neId/ciId`，若接口只返回 `devId`，则将 `devId` 视为 CI ID
- **排序建议**：按 `eventtime` 降序，或按 `alarmseverity` 升序（紧急告警优先）
