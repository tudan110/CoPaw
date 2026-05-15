# Inspection Analyst 定时自动巡检配置说明

## 1. 文档目的

本文档用于说明：在当前 QwenPaw / Portal 实现下，如何为 `inspection` 智能体配置 **定时自动巡检**。

重点回答三个问题：

1. 当前是否已经有“巡检触发接口”
2. 为什么更推荐使用 **QwenPaw 内置 cron**
3. 如何实际配置“每小时巡检核心数据库”

---

## 2. 当前现状

### 2.1 已有巡检触发接口

后端已经提供了 Portal 场景下的巡检触发接口：

- `POST /api/portal/inspection/trigger-sessions`

代码位置：

- `src/qwenpaw/extensions/api/portal_backend.py`

该接口支持以下入参：

- `inspectionObject`
- `inspection_object`
- `target`
- `sessionId`（可选）

接口会做的事情不是“直接返回巡检结果”，而是：

1. 确保 inspection 会话存在
2. 在没有历史时启动一次巡检任务
3. 返回 `chatId / sessionId / started / skipped` 等结果

---

## 3. 为什么不建议定时去调用这个接口

虽然有这个接口，但**不建议把它当成长期自动巡检的主入口**。原因有两个：

### 3.1 QwenPaw 内置 cron 不是 HTTP 定时器

QwenPaw 当前内置 cron 支持的是：

1. `text`：定时发送固定文本
2. `agent`：定时向某个智能体发起一次请求

它的执行模型是：

- `cron -> runner.stream_query(...) -> channel dispatch`

而不是：

- `cron -> curl 某个 HTTP 接口`

也就是说，**内置 cron 当前不能直接作为任意 HTTP POST 调度器来使用**。

### 3.2 `trigger-sessions` 接口会“跳过已有历史会话”

当前 inspection trigger 的实现里，会先检查对应 `sessionId` 是否已有历史。

如果这个 session 已经跑过，并且已有会话历史，那么后续再次调用时通常会：

- `skipped = 1`
- 不会重新启动新的完整巡检

因此，如果想长期定时跑同一个巡检对象，直接重复调用同一个 trigger 接口并不稳妥。

---

## 4. 推荐方案

### 4.1 推荐思路

推荐使用 **QwenPaw 内置 cron 直接给 `inspection` 智能体发巡检请求**。

这句话的真实含义是：

1. 创建一个 cron job
2. 指定它运行在 `inspection` agent 上
3. 到时间后，系统自动像用户一样给巡检智能体发一条 prompt
4. inspection 智能体按当前已有链路执行：
   - 协作 `query` 智能体查 CMDB
   - 确认巡检对象
   - 查询指标定义
   - 拉取指标数据
   - 输出巡检报告与健康评估

也就是说，推荐链路是：

- `cron -> inspection 智能体 -> 完整巡检流程`

而不是：

- `cron -> /portal-api/inspection/trigger-sessions`

---

## 5. 适用场景

这种方式适合以下场景：

1. 每小时巡检核心数据库
2. 每天固定时间巡检某台关键主机
3. 每周巡检一组固定对象
4. 定时输出巡检结果到固定会话

---

## 6. 示例：每小时巡检核心数据库

以下示例用于配置：

- **对象**：`db_mysql_001`
- **频率**：每小时整点
- **执行智能体**：`inspection`
- **输出方式**：仅保留最终结果

### 6.1 Cron Job JSON

```json
{
  "id": "",
  "name": "每小时巡检核心数据库",
  "enabled": true,
  "schedule": {
    "type": "cron",
    "cron": "0 * * * *",
    "timezone": "Asia/Shanghai"
  },
  "task_type": "agent",
  "request": {
    "input": [
      {
        "role": "user",
        "type": "message",
        "content": [
          {
            "type": "text",
            "text": "请帮我巡检一下核心数据库 db_mysql_001。\n要求：\n1. 先协作 query 智能体使用 zgops-cmdb 确认巡检对象的拓扑、资源名称、resId/CI ID 和 ciType。\n2. 如果存在多个候选资源，先明确列出候选项，不要默认任选一个。\n3. 一旦确认 resId 和 ciType，查询该资源类型的全部指标定义，提取全部指标编码。\n4. 调用指标数据接口，使用 resId + 全部指标编码数组完成巡检。\n5. 最后输出巡检结果、拓扑确认摘要、健康状态评估和指标数据表。"
          }
        ]
      }
    ],
    "user_id": "cron",
    "session_id": "portal-cron-inspection-core-db"
  },
  "dispatch": {
    "type": "channel",
    "channel": "console",
    "target": {
      "user_id": "cron",
      "session_id": "portal-cron-inspection-core-db"
    },
    "mode": "final",
    "meta": {}
  },
  "runtime": {
    "max_concurrency": 1,
    "timeout_seconds": 600,
    "misfire_grace_seconds": 300
  },
  "meta": {
    "scene": "hourly-inspection",
    "object": "db_mysql_001"
  }
}
```

### 6.2 字段说明

#### `cron`

```json
"cron": "0 * * * *"
```

表示每小时整点执行一次。

#### `task_type`

```json
"task_type": "agent"
```

表示不是简单发文案，而是**让 inspection 智能体真正执行一次巡检任务**。

#### `request.input`

这里放的是“定时替你发给 inspection 智能体的话”。

你可以把它理解为：

> 每到整点，系统自动对巡检专家说一次：请帮我巡检核心数据库 db_mysql_001。

#### `dispatch`

```json
"channel": "console"
```

表示结果发送到 console 会话。

```json
"target": {
  "user_id": "cron",
  "session_id": "portal-cron-inspection-core-db"
}
```

表示所有定时巡检结果都会落在同一个 cron 会话中，便于集中查看。

#### `timeout_seconds`

```json
"timeout_seconds": 600
```

巡检通常会串联多个工具调用，默认 120 秒偏紧，建议提高到 600 秒。

---

## 7. 如何用 Postman 创建

### 7.1 请求信息

- **Method**: `POST`
- **URL**: `http://localhost:5173/copaw-api/api/cron/jobs`

### 7.2 Headers

```http
Content-Type: application/json
X-Agent-Id: inspection
```

### 7.3 Body

直接把上面的 Cron Job JSON 粘进去即可。

### 7.4 成功后的预期

成功后会返回一个完整的 job 定义，其中包含：

- `id`
- `name`
- `schedule`
- `dispatch`
- `runtime`

后续可以再调用：

- `GET /copaw-api/api/cron/jobs`
- `GET /copaw-api/api/cron/jobs/{jobId}/state`
- `POST /copaw-api/api/cron/jobs/{jobId}/run`

来查看状态和手动触发。

---

## 8. CLI 创建方式

如果使用 CLI，也可以这样创建：

```bash
qwenpaw cron create \
  --agent-id inspection \
  --type agent \
  --name "每小时巡检核心数据库" \
  --cron "0 * * * *" \
  --channel console \
  --target-user cron \
  --target-session portal-cron-inspection-core-db \
  --mode final \
  --text "请帮我巡检一下核心数据库 db_mysql_001。要求：1. 先协作 query 智能体使用 zgops-cmdb 确认巡检对象的拓扑、资源名称、resId/CI ID 和 ciType。2. 如果存在多个候选资源，先明确列出候选项，不要默认任选一个。3. 一旦确认 resId 和 ciType，查询该资源类型的全部指标定义，提取全部指标编码。4. 调用指标数据接口，使用 resId + 全部指标编码数组完成巡检。5. 最后输出巡检结果、拓扑确认摘要、健康状态评估和指标数据表。"
```

---

## 9. 与 `trigger-sessions` 接口的关系

两者并不是完全冲突，而是适合不同用途。

### 9.1 适合用 trigger 接口的场景

适合：

1. Portal 按钮点击触发一次巡检
2. 外部系统通过 API 临时发起一轮巡检
3. 需要快速拿到 chatId/sessionId，用于 Portal 会话联动

### 9.2 适合用 cron 的场景

适合：

1. 定时自动巡检
2. 每小时 / 每天 / 每周重复执行
3. 持续巡检固定对象
4. 形成长期稳定的自动化任务

---

## 10. 当前限制

### 10.1 不能让 cron 直接打任意 HTTP

当前内置 cron 不是通用 HTTP scheduler，因此不能直接配置成：

- 每小时 `POST /portal-api/inspection/trigger-sessions`

### 10.2 不能默认指望“对巡检智能体说一句话，它自动创建 cron”

当前 inspection 智能体主要负责**执行巡检**，还没有专门接上“创建定时任务”的工具链路。

所以现阶段：

- **一次性巡检**：可以直接聊天触发
- **长期定时巡检**：仍建议走 cron 配置

---

## 11. 推荐落地方式

如果现在要在生产或测试环境里稳定跑起来，建议按下面方式做：

1. 先为关键对象单独建 cron job
2. 每个关键对象使用独立 `targetSession`
3. 统一命名，例如：
   - `portal-cron-inspection-core-db`
   - `portal-cron-inspection-core-redis`
   - `portal-cron-inspection-core-network`
4. 先用 `run` 手动触发一次，确认输出正常
5. 再正式开启定时执行

---

## 12. 一句话结论

当前要做“定时自动巡检”，**最佳实践不是定时调用 inspection trigger 接口，而是用 QwenPaw 内置 cron 定时向 `inspection` 智能体发起一次完整巡检请求。**
