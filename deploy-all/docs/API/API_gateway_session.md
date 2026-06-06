# Gateway 智能体 - 会话接口文档

本文档整理 **gateway** 智能体的两个核心接口：**新增会话**与**历史会话**。内容依据最新后端代码整理：

- 路由实现：`src/qwenpaw/app/runner/api.py`
- 数据模型：`src/qwenpaw/app/runner/models.py`

## 基础配置

- **默认地址**：`http://127.0.0.1:8088`
- **指定智能体（gateway）**，二选一：
  - **方式 1（Header）**：在请求头添加 `X-Agent-Id: gateway`，路径用 `/api/chats/...`
  - **方式 2（URL 路径）**：使用 `/api/agents/gateway/chats/...`，无需 Header

> `gateway` 是 Portal 入口智能体，其 Agent ID 可由环境变量 `QWENPAW_PORTAL_GATEWAY_AGENT_ID` 配置，默认值为 `gateway`。

## 核心概念

| 字段 | 说明 |
|------|------|
| `id`（chat.id） | 系统自动生成的 UUID，存储层唯一标识一条聊天记录，用于获取历史、更新、删除等操作 |
| `session_id` | 会话逻辑标识符，由用户定义，用于标识对话上下文、保持消息连续性 |
| `user_id` | 用户标识符，区分不同用户 |
| `channel` | 消息来源渠道，默认 `console` |
| `status` | 会话状态：`idle`（空闲）或 `running`（运行中） |

---

## 1. 新增会话

创建一条新的聊天记录。`chat.id`（UUID）由服务端自动生成，请求体中即使传入 `id` 也会被忽略。

**POST** `/api/agents/gateway/chats`

> 等价写法：`POST /api/chats` + Header `X-Agent-Id: gateway`

### 请求体（ChatSpec）

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `session_id` | string | 是 | - | 会话逻辑标识（建议用时间戳） |
| `user_id` | string | 是 | - | 用户标识 |
| `name` | string | 否 | `"New Chat"` | 会话名称 |
| `channel` | string | 否 | `"console"` | 渠道名称 |
| `meta` | object | 否 | `{}` | 附加元数据 |

> 说明：请求体仅取用 `name`、`session_id`、`user_id`、`channel`、`meta` 字段；`id`、`created_at`、`updated_at`、`status`、`pinned`、`source` 等由服务端管理，传入无效。

```json
{
  "name": "新对话",
  "session_id": "1742889998887",
  "user_id": "default",
  "channel": "console"
}
```

### 响应（ChatSpec）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 服务端生成的 chat UUID，后续获取历史用 |
| `name` | string | 会话名称 |
| `session_id` | string | 会话逻辑标识 |
| `user_id` | string | 用户标识 |
| `channel` | string | 渠道名称 |
| `created_at` | datetime | 创建时间（UTC） |
| `updated_at` | datetime | 更新时间（UTC） |
| `meta` | object | 附加元数据 |
| `status` | string | 会话状态，`idle` / `running`，新建为 `idle` |
| `pinned` | bool | 是否置顶，默认 `false` |
| `source` | string | 会话来源，`chat` / `cron`，默认 `chat` |

```json
{
  "id": "3283e974-49b0-4874-a92c-4776054e7b49",
  "name": "新对话",
  "session_id": "1742889998887",
  "user_id": "default",
  "channel": "console",
  "created_at": "2026-06-06T08:46:38.888505Z",
  "updated_at": "2026-06-06T08:46:38.888506Z",
  "meta": {},
  "status": "idle",
  "pinned": false,
  "source": "chat"
}
```

### curl 示例

```bash
# 方式 1：URL 路径指定 gateway
curl -X POST http://127.0.0.1:8088/api/agents/gateway/chats \
  -H "Content-Type: application/json" \
  -d '{"name": "新对话", "session_id": "1742889998887", "user_id": "default", "channel": "console"}'

# 方式 2：Header 指定 gateway
curl -X POST http://127.0.0.1:8088/api/chats \
  -H "Content-Type: application/json" \
  -H "X-Agent-Id: gateway" \
  -d '{"name": "新对话", "session_id": "1742889998887", "user_id": "default", "channel": "console"}'
```

> **简化做法**：也可以不预先创建会话，直接调用发送消息接口时后端会自动创建聊天。

---

## 2. 历史会话

根据 `chat.id`（UUID）获取该会话的完整历史消息及当前状态。

**GET** `/api/agents/gateway/chats/{chatId}`

> 等价写法：`GET /api/chats/{chatId}` + Header `X-Agent-Id: gateway`

### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `chatId` | string | 新增会话返回的 `id`（chat UUID） |

### 响应（ChatHistory）

| 字段 | 类型 | 说明 |
|------|------|------|
| `messages` | array | 历史消息列表，按时间顺序 |
| `status` | string | 当前会话状态：`idle` / `running` |

`messages` 中每条 `Message` 主要字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `role` | string | 角色：`user` / `assistant` 等 |
| `type` | string | 消息类型，如 `message` |
| `content` | array | 内容块列表，如 `[{ "type": "text", "text": "..." }]` |
| `id` | string | 消息 ID |
| `status` | string | 消息状态 |
| `sequence_number` | int | 序号 |

```json
{
  "messages": [
    {
      "role": "user",
      "type": "message",
      "content": [{ "type": "text", "text": "你好" }]
    },
    {
      "role": "assistant",
      "type": "message",
      "content": [{ "type": "text", "text": "你好！有什么可以帮助你的？" }]
    }
  ],
  "status": "idle"
}
```

> 若会话不存在，返回 **404**：`{"detail": "Chat not found: {chatId}"}`。
> 若会话存在但尚无消息，返回 `{"messages": [], "status": "idle"}`。

### curl 示例

```bash
# 方式 1：URL 路径指定 gateway
curl http://127.0.0.1:8088/api/agents/gateway/chats/3283e974-49b0-4874-a92c-4776054e7b49

# 方式 2：Header 指定 gateway
curl http://127.0.0.1:8088/api/chats/3283e974-49b0-4874-a92c-4776054e7b49 \
  -H "X-Agent-Id: gateway"
```

---

## 3. 发送消息（SSE 流式）

向 gateway 智能体发送消息，以 SSE（`text/event-stream`）流式返回回复。可不预先调用「新增会话」，后端会按 `session_id + user_id + channel` 自动创建/复用聊天。

**POST** `/api/agents/gateway/console/chat`

> 等价写法：`POST /api/console/chat` + Header `X-Agent-Id: gateway`

### 请求体（AgentRequest）

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `input` | array | 是 | - | 消息列表，见下方结构 |
| `session_id` | string | 否 | `null` | 会话逻辑标识，需与新增会话时保持一致 |
| `user_id` | string | 否 | `null` | 用户标识 |
| `channel` | string | 否 | `"console"` | 渠道名称 |
| `stream` | bool | 否 | `true` | 是否流式返回 |
| `reconnect` | bool | 否 | `false` | 为 `true` 时重连到已在运行的流，而非新建对话 |

> `AgentRequest` 允许额外字段，还支持模型采样参数（`model`、`temperature`、`top_p`、`max_tokens`、`stop`、`seed`、`tools` 等），一般无需传入。

`input` 中每条消息结构：

```json
{
  "role": "user",
  "type": "message",
  "content": [
    { "type": "text", "text": "现在几点了", "status": "created" }
  ]
}
```

完整请求体示例：

```json
{
  "session_id": "1742889998887",
  "user_id": "default",
  "channel": "console",
  "stream": true,
  "input": [
    {
      "role": "user",
      "type": "message",
      "content": [{ "type": "text", "text": "现在几点了", "status": "created" }]
    }
  ]
}
```

### 响应：SSE 流（`text/event-stream`）

响应头：

```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
```

每个事件为一行 `data: <JSON>\n\n`。主要事件类型（按 `object` 字段区分）：

| object | 说明 |
|--------|------|
| `portal_progress` | 进度提示（`request_received` / `agent_started` / `waiting_first_event` / `waiting_next_event` 等阶段） |
| `message` | 消息事件，含 `type`、`status`、`role`、`content`、`sequence_number` 等，文本片段在 `content[].text` |
| `response` | 整体响应状态，完成时含 `output`、`usage`（`input_tokens` / `output_tokens`） |
| `error` | 错误信息，形如 `{"error": "..."}` |

`message` 事件示例：

```
data: {"object":"message","type":"message","status":"in_progress","role":"assistant","content":[{"type":"text","text":"现在"}],"sequence_number":1}
data: {"object":"message","type":"message","status":"completed","role":"assistant","content":[{"type":"text","text":"现在是 10:30。"}],"sequence_number":2}
data: {"object":"response","status":"completed","usage":{"input_tokens":12,"output_tokens":8}}
```

### curl 示例

```bash
# 方式 1：URL 路径指定 gateway
curl 'http://127.0.0.1:8088/api/agents/gateway/console/chat' \
  -H 'Content-Type: application/json' \
  --data-raw '{"input":[{"role":"user","type":"message","content":[{"type":"text","text":"现在几点了","status":"created"}]}],"session_id":"1742889998887","user_id":"default","channel":"console","stream":true}'

# 方式 2：Header 指定 gateway
curl 'http://127.0.0.1:8088/api/console/chat' \
  -H 'Content-Type: application/json' \
  -H 'X-Agent-Id: gateway' \
  --data-raw '{"input":[{"role":"user","type":"message","content":[{"type":"text","text":"现在几点了","status":"created"}]}],"session_id":"1742889998887","user_id":"default","channel":"console","stream":true}'
```

---

## 4. 停止对话

中断正在进行（`running`）的对话。

**POST** `/api/agents/gateway/console/chat/stop?chat_id={chatId}`

> 等价写法：`POST /api/console/chat/stop?chat_id={chatId}` + Header `X-Agent-Id: gateway`

### 查询参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `chat_id` | string | 是 | chat UUID（`ChatSpec.id`）或 `session_id`，服务端会自动解析 |

### 响应

```json
{ "stopped": true }
```

成功停止返回 `true`，无运行中任务返回 `false`。

### curl 示例

```bash
curl -X POST "http://127.0.0.1:8088/api/agents/gateway/console/chat/stop?chat_id=3283e974-49b0-4874-a92c-4776054e7b49"
```

---

## 完整对话流程

```
1. 新增会话      POST /api/agents/gateway/chats            → 拿到 chat.id 与 session_id
2. 发送消息      POST /api/agents/gateway/console/chat     → SSE 流式接收回复
3. 停止对话(可选) POST /api/agents/gateway/console/chat/stop → 中断进行中的对话
4. 历史会话      GET  /api/agents/gateway/chats/{chatId}   → 回显历史消息
```

> 步骤 1 可省略：直接发送消息时后端会按 `session_id + user_id + channel` 自动创建会话。

---

## 关键字段对照

| 场景 | 使用字段 |
|------|----------|
| 新增会话 | `session_id`（用户定义）+ `user_id` |
| 获取历史会话 | `chat.id`（新增会话返回的 UUID） |
| 指定智能体 | URL `/api/agents/gateway/...` 或 Header `X-Agent-Id: gateway` |
