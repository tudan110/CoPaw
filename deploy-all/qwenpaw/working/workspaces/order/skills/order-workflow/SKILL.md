---
name: order-workflow
category: workflow
tags: [order, workorder, workflow, ticket]
triggers: [工单, 工单统计, 待办工单, 已办工单, 工单详情, 创建工单, 处置工单]
description: 传统工单系统中的处置类工单技能。适用于查看今日工单统计、查询待办工单、查询已办工单、查看工单详情、创建处置工单。当前阶段不要与 fault 故障处置闭环联动。
---

# Order Workflow

这是 `order` 数字员工的第一版真实工单技能。

## 重要：调用方式（务必遵守）

- 本技能的接口配置由**后端自动从共享 `secrets/`（INOE 网关）注入**，运行时已具备 `ORDER_API_BASE_URL` / 鉴权信息。
- **技能目录下没有 `.env` 是正常的、预期的**——配置不放在 `.env`。看到只有 `.env.example`、没有 `.env`，**不代表缺少配置**，**不要据此判定“无法调用”**。
- 工单查询/创建请**直接用本技能脚本调用**完成，**不要因为“没有 .env”就转交、协同（chat_with_agent）给其他智能体**——`gateway` 与 `order` 同进程、同配置，本地直接调即可。
- 如果脚本返回报错（如 `404 NOT_FOUND`、`服务未找到`、`获取流程失败`），那是**上游网关/工单服务**的问题（地址或服务未就绪），**不是本地缺配置**；请把报错原文如实转述，不要改口说“缺少 .env 配置”。

## 边界

- 当前对接 inoe-ferry 工单接口，封装 5 类能力：
  - 工单统计
  - 处置工单创建（故障处置派单）
  - 待办工单列表（list classify=1）
  - 已办工单列表（list classify=5）
  - 工单详情（process-structure）
- 待办/已办共用同一个 `list` 接口，靠 `classify` 区分。
- 告警派单（`alarm-create`）当前未接入。
- 当前阶段不要调用 `fault` 的故障处置 skill。
- 当前阶段不要自行扩展到审批、批量流转、自动关闭等未接通能力。

## 配置

接口配置优先从共享 `secrets/`（ZGOPS/INOE）读取，未配置时回退本技能目录 `.env` 或同名环境变量；通知推送配置优先从 Portal「高级功能 → 设置 → 通知」读取，未设置时再回退到 `.env` 或同名环境变量：

```bash
ORDER_API_BASE_URL=http://<inoe-ferry-gateway-host>:<port>
ORDER_AUTHORIZATION=your_authorization_token
ORDER_COOKIE=
ORDER_SERIAL_NO=
ORDER_TIMEOUT_SECONDS=20
ORDER_VERIFY_SSL=true
ORDER_ENABLE_CURL_FALLBACK=false
ORDER_EXTRA_HEADERS={}
```

- `ORDER_API_BASE_URL` 指 inoe-ferry 工单网关根地址；脚本内固定路径前缀 `/api/v1/work-order`，base 只配到网关根（不要带前缀）。
- `ORDER_AUTHORIZATION` 对应接口文档中的 `Authorization` 请求头。
- `ORDER_SERIAL_NO` 可留空，脚本会自动生成。
- `ORDER_EXTRA_HEADERS` 用 JSON 传额外请求头。
- 建单通知会优先读取工作空间 `extensions/notifications/settings.json` 里的 `order_workflow` 配置；只有未配置时才回退 `ORDER_CREATE_NOTIFY_*`。

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
python3 scripts/order_workflow.py detail --process-id <processId> --work-order-id <workOrderId> --output markdown
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
- “看这张工单详情”：执行 `detail`，需要该工单的「工单号」(workOrderId) 和「流程号」(processId)
- “看第 3 条 / 第 3 条详情”：按上一条待办/已办列表里的序号定位对应行，取该行的「工单号」「流程号」，再执行 `detail --process-id <流程号> --work-order-id <工单号>`
- “帮我创建一张处置工单”：整理结构化 JSON 后执行 `create`
- **必填（只问这两类，齐了就建单，别再追问）**：问题描述/处置意见，以及 `manageIp`、`deviceName`、`assetId` 三者中的至少一个。
- **可选（用户主动给就收下、透传进载荷，绝不丢弃）**：级别/优先级 `level`、告警状态 `status`、发生时间 `eventTime`、资产编号 `assetId`、资源类型 `metricType`、告警摘要 `visibleContent`、处置建议 `suggestions` 等。用户没提的，由 skill 自动补默认；**不要为了凑字段逐个追问**。
- 可以顺带提醒用户一句“还能补充级别/时间/资产编号等，不填我来补默认”，但只说一次、不强制。
- 完整的可填字段（必填/可选 + 字段名）见 `references/create-fields.md`。

## 返回要求

- 默认走轻量输出：列表给 10 条纯 markdown 预览表格，详情给 markdown 预览。
- 列表 markdown 必须带“序号”列，便于后续直接按“第 N 条”继续查询详情。
- 用户明确要求“完整”“全部”时，返回更完整的 markdown 明细，但仍然只走 markdown，不输出 `portal-visualization`。
- gateway / agent 层如果要补充一句说明，也只能追加在结果前后，不能替换掉结果本体。
- 如果脚本输出中已经包含 markdown 表格或详情分段，agent 层必须逐字保留，不要重写成另一版摘要，不要压平为一整段文字。
- 列表中的「工单号」(workOrderId) 和「流程号」(processId) 必须保持完整，禁止任何省略号缩写（后续查详情要用）。
- 创建工单时不要把内部 JSON 字段清单整段抛给用户；只补问缺失的**必填**信息。用户主动提供的可选字段要收下并写入载荷，不要丢弃，也不要用自动补默认去覆盖用户已给的值。
- `order-workflow` 不再输出任何 `portal-visualization` 代码块。

## 已封装接口

- `GET /api/v1/work-order/getWorkOrder`（工单统计）
- `POST /api/v1/work-order/faultManualWorkorders`（创建处置工单）
- `GET /api/v1/work-order/list`（工单列表，classify=1 待办 / 5 已办理）
- `GET /api/v1/work-order/process-structure`（工单详情，processId+workOrderId）
