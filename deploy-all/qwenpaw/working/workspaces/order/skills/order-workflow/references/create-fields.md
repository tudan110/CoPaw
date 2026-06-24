# 处置工单创建 · 字段契约

本文件是「故障处置」(`faultManualWorkorders`) 建单的**唯一字段契约**：技能按这里的 key 收集/归一化并下发，ferry「故障处置」流程绑定的**表单模板字段 `model` 名必须和这里的 key 一字不差**，前端表单才能正常回显（详情技能也按 `model` 取中文标签）。换环境、重配模板时，照这张表对齐即可。

## 设计原则

- **必填卡到最少**：只有「问题描述」+「设备标识(三选一)」是必填，齐了就能建单。
- **其余全部可选**：用户给了就透传写入，没给由技能自动补默认——不要为凑字段逐个追问。
- 模板里**只把必填项标 `required`**，其它全部 optional（现状把 `alarmSeq/neTime/sendTim/alarmSeverity` 都设成 required，过于死板，对齐时要去掉）。

## 字段表

> `model` = 下发 form_data 的 key = 模板字段 model，三者必须一致。

### 必填

| `model` | 中文标签 | 类型 | 说明 / 技能接受的输入别名 |
|---|---|---|---|
| `title` | 告警标题 / 工单标题 | input | 问题描述/处置意见 → 作为工单标题。别名：`title`，或从问题描述/`visibleContent` 推导 |
| `deviceName` | 设备名称 | input | 设备标识三选一。别名：`deviceName`/`resourceName`/`assetName`/`instanceName`/`name` |
| `manageIp` | 管理 IP | input | 设备标识三选一。别名：`manageIp`/`deviceIp`/`ip`/`hostIp`（也会从描述里抓 IP） |
| `assetId` | 资产编号 | input | 设备标识三选一。别名：`assetId`/`resource`/`resourceId`/`resId` |

> 「三选一」指 `deviceName`/`manageIp`/`assetId` 至少给一个；缺的那些技能会相互回填。

### 可选（用户给就透传，不给补默认）

| `model` | 中文标签 | 类型 | 默认/说明 |
|---|---|---|---|
| `level` | 告警级别 | input（见下）| 英文枚举 `critical`/`major`/`minor`；不给默认 `major`。别名：`level`/`priority` |
| `status` | 告警状态 | input（见下）| 英文枚举 `active`/`clear`；不给默认 `active` |
| `eventTime` | 告警时间 | input | 不给默认取当前时间。别名：`eventTime`/`alarmTime`/`occurTime` |
| `visibleContent` | 告警摘要 | textarea | 不给由标题+设备自动拼。别名：`visibleContent`/`issue`/`description`/`alarmContent` |
| `suggestions` | 处置建议 | textarea | 不给默认「请人工处理：<标题>」。别名：`suggestions`/`advice`/`comment` |
| `metricType` | 资源类型 | input | 不给按内容推断（`mysql`/`server`/`network`/`generic`…）。别名：`metricType`/`resourceType`/`ciType` |
| `alarmId` | 告警 ID | input | 不给自动生成 `alarm-xxxx` |
| `resId` | 资源 ID(CMDB) | input | 不给回退用 `assetId`/`manageIp`/`deviceName`。别名：`resId`/`resourceId` |
| `chatId` | 会话 ID | input（可隐藏）| 不给自动生成 UUID，用于回写会话 |

## ⚠️ `level` / `status` 不要用中文下拉

技能下发的 `level`、`status` 是**英文枚举**（`critical/major/minor`、`active/clear`）。模板里这两个字段：

- 用**文本框**直接显示英文值；**或**
- 用 select，但**选项 value 必须是英文**（`critical`/`major`/`minor`、`active`/`clear`）。

若沿用中文下拉（严重/主要/普通、活跃告警/清除告警），下发的英文值匹配不到选项 → 显示空。（若确实想要表单显示中文，则需要让技能改下发中文，属另一种方案，本契约按英文枚举对齐。）

## 备注

- 这 13 个 key 是 `faultManualWorkorders` 把报文平铺成 `form_data` 后落库的字段，与接口文档一致。
- 优先级映射：`level` → `ticket.priority`（`critical→P1`/`major→P2`/`minor→P3`），ferry 再映射成数字优先级。
- 技能侧实现见 `runtime/client.py` 的 `_normalize_create_payload`；要新增可选字段（如告警那套 `neAlias`/`vendor`/`alarmLocation`/`alarmSeq`），在该函数里加透传即可，并同步更新本表。
