# 处置工单创建 · 字段契约（对齐「故障处置」模板）

技能建单时把字段平铺成 `form_data`，**key 必须与「故障处置」流程绑定的表单模板字段 `model` 一字不差**，前端表单才能正常回显（否则值会落不到对应框里，看起来像“只有处置建议有内容”）。本表就是这套 model 名。

## 模板字段（model）

> 技能会把用户给的中文/英文别名都归一化到这些 `model`，并按需做值转换。

### 关键字段（建议必给）

| `model` | 标签 | 类型 | 技能接受的别名 | 值处理 |
|---|---|---|---|---|
| `alarmTitle` | 告警标题 | input | `alarmTitle`/`title`/`标题`/`告警标题` | 作为工单标题；不给时从处置意见/设备兜底 |
| `neName` | 设备名称 | input | `neName`/`deviceName`/`设备名称`/`name` | 与 `neIp` 至少给一个 |
| `neIp` | 设备IP | input | `neIp`/`manageIp`/`ip`/`设备IP`/`deviceIp` | 与 `neName` 至少给一个；也会从文本里抓 IP |

### 可选字段（用户给就填，不给留空/补默认）

| `model` | 标签 | 类型 | 别名 | 默认 / 值转换 |
|---|---|---|---|---|
| `alarmSeq` | 告警流水 | input | `alarmSeq`/`告警流水`/`流水`/`seq` | 不给留空 |
| `alarmSeverity` | 告警级别 | select | `alarmSeverity`/`level`/`priority`/`优先级`/`级别` | **转中文**：严重/主要/普通/预警；不给默认「主要」 |
| `isClear` | 告警状态 | select | `isClear`/`status`/`告警状态` | **转中文**：活跃告警/清除告警；默认「活跃告警」 |
| `neTime` | 发生时间 | input | `neTime`/`eventTime`/`发生时间` | 「现在/now/空」→ 当前时间 |
| `sendTim` | 发现时间 | input | `sendTim`/`发现时间`/`sendTime` | 不给 → 取 `neTime` |
| `neAlias` | 设备别名 | input | `neAlias`/`设备别名`/`alias` | 留空 |
| `vendor` | 厂家 | input | `vendor`/`厂家`/`设备类型`/`厂商` | 留空 |
| `clearuser` | 告警清除人 | input | `clearuser`/`告警清除人` | 留空 |
| `clearanceCollectTime` | 告警清除时间 | input | `clearanceCollectTime`/`告警清除时间` | 留空 |
| `additionalText` | 告警原始报文 | textarea | `additionalText`/`告警原始报文`/`原始报文` | 留空 |
| `alarmLocation` | 定位信息 | textarea | `alarmLocation`/`定位信息`/`location` | 留空 |
| `suggestions` | 处置建议 | textarea | `suggestions`/`处置建议`/`处置意见`/`advice` | **只放用户明确给的处置建议**，不给留空（别把其它信息塞这里） |

## 值转换规则

- **告警级别 `alarmSeverity`（必须是模板下拉的中文）**：

  | 输入 | → alarmSeverity | → 工单优先级 |
  |---|---|---|
  | P1 / critical / 严重 / 紧急 / 一级 | 严重 | P1 |
  | P2 / major / 主要 / 重要 / 二级 | 主要 | P2 |
  | P3 / minor / 普通 / 一般 / 三级 | 普通 | P3 |
  | P4 / warning / 预警 / 四级 | 预警 | P3 |
  | （不给） | 主要 | P2 |

- **告警状态 `isClear`**：含「清除/恢复/clear/resolved」→「清除告警」，否则「活跃告警」。
- **时间**：`现在/now/当前/空` → 服务器当前时间；`sendTim` 不给取 `neTime`。

## 注意

- `alarmSeverity`、`isClear` 是模板里的**中文下拉**，所以技能下发中文（严重/活跃告警），不是英文枚举——这点和早期文档不同。
- `suggestions` 由 `analysis.suggestions` 以 JSON 字符串落库（前端可能显示成 `["..."]`），属接口行为。
- 技能侧实现：`runtime/client.py` 的 `_normalize_create_payload` + `_to_alarm_severity`/`_to_is_clear`/`_resolve_event_time`。新增/调整字段后同步更新本表。
- 非模板字段（`chatId`/`resId`/`metricType`/`alarmId`）也会进 form_data，但模板没有对应框，不显示，不影响。
