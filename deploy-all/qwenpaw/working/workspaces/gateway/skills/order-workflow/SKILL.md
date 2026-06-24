---
name: order-workflow
category: workflow
tags: [order, workorder, workflow, ticket]
triggers: [工单, 工单统计, 待办工单, 已办工单, 工单详情, 创建工单, 处置工单]
description: inoe-ferry 工单技能：工单统计、待办/已办列表、工单详情、创建处置工单。
---

# Order Workflow

对接 inoe-ferry 工单接口（`/api/v1/work-order/*`）。**配置由脚本自动从共享 `secrets/inoe.env` 读取**（含 `ORDER_API_BASE_URL` 与鉴权）——直接跑脚本即可，无需传环境变量、无需技能目录 `.env`、也无需转交其他智能体。脚本报 `404 NOT_FOUND` / `服务未找到` / `获取流程失败` 是上游网关/服务的问题，按原文转述即可。回答里不要泄露 token。

## 能力

| 命令 | 说明 |
|---|---|
| `stats` | 工单统计 |
| `todo-list` | 待办列表（classify=1） |
| `finished-list` | 已办列表（classify=5） |
| `detail --process-id <pid> --work-order-id <wid>` | 工单详情 |
| `create --payload-file <path>` | 创建处置工单（故障处置派单） |

待办/已办共用 `list` 接口靠 `classify` 区分；告警派单、审批/流转等暂未接入，不要联动 `fault` skill。

## 命令

```bash
cd skills/order-workflow
python3 scripts/order_workflow.py stats --output markdown
python3 scripts/order_workflow.py todo-list --output markdown
python3 scripts/order_workflow.py finished-list --output markdown
python3 scripts/order_workflow.py detail --process-id <processId> --work-order-id <workOrderId> --output markdown
python3 scripts/order_workflow.py create --payload-file /tmp/order_create_payload.json --output markdown
```

聊天入口：`python3 scripts/chat_skill_bridge.py --context-file <ctx.json>`。

## 创建工单：按「故障处置」模板字段各归各位

把用户每个输入**放到对应字段，绝不要一股脑塞进 `suggestions`**。完整字段/别名/值转换见 `references/create-fields.md`。

```json
{
  "alarmSeq": "test001", "alarmTitle": "端口down告警",
  "neName": "HW-hs318", "neIp": "192.168.1.32", "vendor": "华为",
  "neTime": "现在", "alarmSeverity": "P2", "isClear": "活跃告警",
  "suggestions": "端口异常，需人工排查"
}
```

- **必填**：告警标题 `alarmTitle` + 设备名称 `neName` / 设备IP `neIp` 至少一个。其余可选，不给留空，**别为凑字段逐个追问**。
- 值转换 skill 自动做：`alarmSeverity` P2→`主要`、`neTime` 现在→当前时间、`sendTim` 不给→取 `neTime`；并自动补 `chatId/alarmId/resId/ticket.*`。
- 兼容旧别名：`deviceName→neName`、`manageIp`/`ip`→`neIp`、`title→alarmTitle`、`level`/`priority`→`alarmSeverity`。

## 自然语言映射

- “待办/已办工单”：默认 `todo-list`/`finished-list` 第 1 页 10 条预览；说“全部/全量”才全量查。
- “看详情 / 第 N 条详情”：从上一条列表取该行「工单号」(workOrderId) 和「流程号」(processId)，执行 `detail`。
- “创建工单”：按上面的字段映射整理 JSON 后 `create`。

## 返回要求

- 只走 markdown（列表 10 条预览表带“序号”列、详情 markdown），不输出 `portal-visualization`。
- 脚本已生成的 markdown 表格/分段**逐字保留**，不要重写成另一版摘要、不要压平成一段。
- 列表里的「工单号」「流程号」必须完整，禁止省略号缩写（查详情要用）。
- 创建时只补问缺失的**必填**，别把内部 JSON 字段清单整段抛给用户。

## 已封装接口

均在 `/api/v1/work-order/` 前缀下：`getWorkOrder`（统计）· `faultManualWorkorders`（创建）· `list`（classify 待办/已办）· `process-structure`（详情）。
