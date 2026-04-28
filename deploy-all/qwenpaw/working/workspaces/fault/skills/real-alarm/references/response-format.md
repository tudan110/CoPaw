# 响应格式

本文档描述告警列表接口的响应数据结构和字段说明。

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
  "alarmuniqueid": "COMMON_IPF_1773392530396_2032381694267797504",
  "alarmclass": "sys_log",
  "alarmseverity": 1,
  "alarmtitle": "端口DOWN",
  "vendor": "",
  "devName": "SN-XA-LHL-A.Leaf-4.MCN.CX600",
  "devId": 18,
  "manageIp": "4.155.10.35",
  "locatenename": "BindIfName=-",
  "alarmregion": "XA",
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

| 字段 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `alarmuniqueid` | string | 告警唯一标识 | `COMMON_IPF_1773392530396_2032381694267797504` |
| `alarmclass` | string | 告警类别（sys_log-设备告警，threshold-性能告警，derivative-衍生告警） | `sys_log` |

### 告警信息

| 字段 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `alarmtitle` | string | 告警标题 | `端口DOWN` |
| `alarmseverity` | int | 告警级别（1-严重，2-重要，3-一般，4-提示） | `1` |
| `alarmtext` | string | 告警文本描述 | - |
| `alarmstatus` | int | 告警状态（0-自动清除，1-活跃，2-同步清除，3-手工清除） | `1` |

### 设备信息

| 字段 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `devName` | string | 设备名称 | `SN-XA-LHL-A.Leaf-4.MCN.CX600` |
| `devId` | int/string | 当前告警对应的资源 ID，即 `resId/ci id` | `18` |
| `manageIp` | string | 管理IP | `4.155.10.35` |
| `vendor` | string | 厂商 | `HW` |
| `locatenename` | string | 位置名称 | `BindIfName=-` |

### 时间信息

| 字段 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `eventtime` | string | 告警发生时间 | `2026-03-16 09:38:28` |
| `daltime` | string | 发现时间 | `2026-03-13 09:38:28` |
| `eventlasttime` | string | 相同告警压缩后最后发生时间 | `2026-03-13 09:38:28` |
| `canceltime` | string | 清除时间 | `null` |

### 分类信息

| 字段 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `speciality` | string | 专业分类 | `IPM` |
| `alarmregion` | string | 告警区域 | `XA` |
| `alarmcounty` | string | 告警区县 | - |

### 状态信息

| 字段 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `alarmactcount` | int | 告警动作次数 | `0` |
| `ackflag` | string | 确认标志 | - |
| `acktime` | string | 确认时间 | - |
| `ackuser` | string | 确认用户 | - |
| `clearuser` | string | 清除用户 | - |

### 其他字段

| 字段 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `vendorserialno` | string | 厂商序列号 | - |
| `vendorclearno` | string | 厂商清除号 | - |
| `alarmlogicclass` | string | 告警逻辑类别 | - |
| `alarmlogicsubclass` | string | 告警逻辑子类别 | - |
| `relatedflag` | string | 关联标志 | - |
| `alarmprovince` | string | 告警省份 | - |
| `projectno` | string | 项目编号 | - |
| `nettypeName` | string | 网络类型名称 | - |
| `autodealstatus` | string | 自动处理状态 | - |
| `addInfo9` | string | 附加信息9 | - |
| `parentflag` | string | 父标志 | - |
| `linkName` | string | 链路名称 | - |
| `circName` | string | 电路名称 | - |
| `linkId` | string | 链路ID | - |
| `circId` | string | 电路ID | - |
| `isOrder` | string | 排序标志 | `0` |

## 字段映射

### 告警级别映射

| 原始值 | 显示值 |
|--------|--------|
| `1` | 严重 |
| `2` | 重要 |
| `3` | 一般 |
| `4` | 提示 |

### 告警状态映射

| 原始值 | 显示值 |
|--------|--------|
| `0` | 自动清除 |
| `1` | 活跃 |
| `2` | 同步清除 |
| `3` | 手工清除 |

### 告警类别映射

| 原始值 | 显示值 |
|--------|--------|
| `sys_log` | 设备告警 |
| `threshold` | 性能告警 |
| `derivative` | 衍生告警 |

## 使用建议

### 查询场景

1. **简单列表**：优先展示 `alarmtitle`、`alarmseverity`、`alarmclass`、`devName`、`eventtime`
2. **详细信息**：补充 `manageIp`、`devId`、`speciality`、`alarmstatus`、`alarmregion`
3. **分析统计**：按 `alarmseverity`、`alarmclass`、`speciality`、`devName`、`alarmregion` 分组

### 排序建议

- 按时间排序：优先使用 `eventtime`（告警发生时间）或 `eventlasttime`（最后发生时间）
- 按级别排序：优先展示 `alarmseverity` 值小的（严重告警）
- 按状态排序：优先展示 `alarmstatus = 1` 的活跃告警

### 过滤建议

- 严重告警：`alarmseverity = 1`
- 活跃告警：`alarmstatus = 1`
- 设备告警：`alarmclass = "sys_log"`
- 性能告警：`alarmclass = "threshold"`
- 衍生告警：`alarmclass = "derivative"`
- 时间范围：使用 `eventtime`（告警发生时间）或 `params.beginEventtime` / `params.endEventtime` 进行时间范围筛选
- 设备筛选：`devName` 或 `manageIp`
- 区域筛选：`alarmregion` 或 `alarmcounty`
- CI ID 展示与本地筛选：优先使用 `neId/ciId`，若接口仅返回 `devId`，则将 `devId` 视为当前告警的 `resId/CI ID`
