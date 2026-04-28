---
name: order-workflow
category: workflow
tags: [order, workorder, workflow, ticket]
triggers: [工单, 工单统计, 待办工单, 已办工单, 工单详情, 创建工单, 处置工单]
description: 传统工单系统中的处置类工单技能。适用于查看今日工单统计、查询待办工单、查询已办工单、查看工单详情、创建处置工单。当前阶段不要与 fault 故障处置闭环联动。
---

# Order Workflow

这是 `order` 数字员工的第一版真实工单技能。

## 边界

- 当前只封装传统工单系统的 5 个接口：
  - 今日工单统计
  - 处置工单创建
  - 待办工单列表
  - 已办工单列表
  - 工单详情
- 当前阶段不要调用 `fault` 的故障处置 skill。
- 当前阶段不要自行扩展到审批、批量流转、自动关闭等未接通能力。

## 配置

配置优先从本技能目录的 `.env` 读取，也支持同名环境变量：

```bash
ORDER_API_BASE_URL=http://192.168.130.51:30081
ORDER_AUTHORIZATION=your_authorization_token
ORDER_COOKIE=
ORDER_SERIAL_NO=
ORDER_TIMEOUT_SECONDS=20
ORDER_VERIFY_SSL=true
ORDER_ENABLE_CURL_FALLBACK=false
ORDER_EXTRA_HEADERS={}
```

- `ORDER_API_BASE_URL` 指传统工单系统根地址。
- `ORDER_AUTHORIZATION` 对应接口文档中的 `Authorization` 请求头。
- `ORDER_SERIAL_NO` 可留空，脚本会自动生成。
- `ORDER_EXTRA_HEADERS` 用 JSON 传额外请求头。

不要在回答中泄露 token、cookie 或请求头明文。

## 常用命令

查看今日工单统计：

```bash
cd skills/order-workflow
python3 scripts/order_workflow.py stats --output markdown
```

查看待办工单：

```bash
cd skills/order-workflow
python3 scripts/order_workflow.py todo-list --output markdown
```

查看已办工单：

```bash
cd skills/order-workflow
python3 scripts/order_workflow.py finished-list --output markdown
```

查看工单详情：

```bash
cd skills/order-workflow
python3 scripts/order_workflow.py detail --proc-ins-id <procInsId> --task-id <taskId> --output markdown
```

创建处置工单：

```bash
cd skills/order-workflow
python3 scripts/order_workflow.py create --payload-file /tmp/order_create_payload.json --output markdown
```

创建接口支持两类输入：

1. 完整旧版结构化载荷：

```json
{
  "chatId": "auto-or-user-provided",
  "resId": "3094",
  "metricType": "mysql",
  "alarm": {
    "alarmId": "alarm-001",
    "title": "数据库锁异常",
    "visibleContent": "数据库锁异常（db_mysql_001 10.43.150.186）",
    "deviceName": "db_mysql_001",
    "manageIp": "10.43.150.186",
    "assetId": "db_mysql_001",
    "level": "critical",
    "status": "active",
    "eventTime": "2026-04-20 15:00:00"
  },
  "analysis": {
    "summary": "AI 无法直接止血，转人工处理",
    "suggestions": ["排查长事务"]
  },
  "ticket": {
    "title": "数据库锁异常人工处置"
  }
}
```

2. 贴近页面的轻量表单载荷：

```json
{
  "deviceName": "db_mysql_001",
  "manageIp": "10.43.150.186",
  "assetId": "3094",
  "suggestions": "数据库锁异常，需要人工排查长事务和阻塞链"
}
```

第二种轻量输入会由 skill 自动补齐 `chatId`、`alarmId`、`resId`、`metricType`、`title`、`visibleContent`、`eventTime`、`ticket.priority` 等字段。

标准聊天入口：

```bash
cd skills/order-workflow
python3 scripts/chat_skill_bridge.py --context-file /tmp/order_context.json
```

## 自然语言映射

- “今天工单有多少 / 今日工单统计”：执行 `stats`
- “查看待办工单 / 待处理工单”：默认执行 `todo-list` 第 1 页 10 条预览；只有明确要求“全部/全量”时才全量查
- “查看已办工单 / 已处理工单”：默认执行 `finished-list` 第 1 页 10 条预览；只有明确要求“全部/全量”时才全量查
- “看这张工单详情”：执行 `detail`
- “看第 3 条 / 第 3 条详情”：优先按上一条待办/已办列表里的序号定位对应记录，再执行 `detail`
- “帮我创建一张处置工单”：整理结构化 JSON 后执行 `create`
- 创建时优先收集最少业务字段：问题描述/处置意见，以及 `manageIp`、`deviceName`、`assetId` 三者中的至少一个；其余字段优先自动补齐。

## 返回要求

- 默认走轻量输出：列表给 10 条纯 markdown 预览表格，详情给 markdown 预览。
- 列表 markdown 必须带“序号”列，便于后续直接按“第 N 条”继续查询详情。
- 用户明确要求“完整”“全部”时，返回更完整的 markdown 明细，但仍然只走 markdown，不输出 `portal-visualization`。
- gateway / agent 层如果要补充一句说明，也只能追加在结果前后，不能替换掉结果本体。
- 如果脚本输出中已经包含 markdown 表格或详情分段，agent 层必须逐字保留，不要重写成另一版摘要，不要压平为一整段文字。
- 列表中的 `taskId`、`procInsId` 必须保持完整，禁止任何省略号缩写。
- 创建工单时不要把内部 JSON 字段清单整段抛给用户。除非用户主动要求看 JSON，否则只补问最少缺失业务信息。
- `order-workflow` 不再输出任何 `portal-visualization` 代码块。

## 已封装接口

- `GET /flowable/workflow/workOrder/getWorkOrder`
- `POST /flowable/workflow/workOrder/faultManualWorkorders`
- `GET /flowable/workflow/process/todoList`
- `GET /flowable/workflow/process/finishedList`
- `GET /flowable/workflow/process/detail`
