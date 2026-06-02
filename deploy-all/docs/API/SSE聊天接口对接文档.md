# QwenPaw SSE 聊天接口对接文档

> 适用场景：第三方系统（如网管系统）自行实现聊天 UI，通过本接口与 QwenPaw 智能体进行流式对话。

---

## 1. 核心接口

### `POST /api/console/chat`

SSE（Server-Sent Events）流式聊天接口，返回 `text/event-stream`。

---

## 2. 请求格式

```http
POST /api/console/chat
Content-Type: application/json
X-Agent-Id: default
```

> `X-Agent-Id` 为可选 header，用于指定目标智能体，默认为 `"default"`。

### 请求体

```json
{
  "channel": "console",
  "user_id": "nms-user-001",
  "session_id": "session_20260602_140000",
  "input": [
    {
      "content": [
        { "type": "text", "text": "帮我查一下核心交换机状态" }
      ]
    }
  ]
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `channel` | string | 是 | 固定填 `"console"` |
| `user_id` | string | 是 | 用户唯一标识 |
| `session_id` | string | 是 | 会话标识，同一 session_id 保持上下文连续 |
| `input` | array | 是 | 消息内容数组 |
| `input[].content[]` | array | 是 | 内容块数组，支持多种类型 |
| `reconnect` | boolean | 否 | 设为 `true` 时重连已有流（断线重连用） |

### content 类型

```json
// 文本
{ "type": "text", "text": "你的问题" }

// 图片
{ "type": "image", "url": "https://..." }

// 文件（需先通过 /api/console/upload 上传）
{ "type": "file", "url": "/uploads/xxx.pdf", "name": "报告.pdf" }
```

---

## 3. SSE 响应格式

响应 Content-Type 为 `text/event-stream`，每条事件格式：

```
data: {JSON对象}\n\n
```

### 3.1 Progress 事件（等待心跳）

Agent 处理过程中定期发送，用于前端展示加载状态。

```json
{
  "object": "progress",
  "type": "progress",
  "stage": "request_received",
  "message": "后端已收到请求，正在准备调用 Agent。",
  "session_id": "session_20260602_140000",
  "elapsed_ms": 0,
  "retry_count": 0,
  "ts": "2026-06-02T14:00:00.000Z"
}
```

| stage 值 | 含义 |
|----------|------|
| `request_received` | 后端已收到请求 |
| `agent_started` | Agent 已开始处理 |
| `waiting_first_event` | 等待模型/工具产出首个事件 |
| `waiting_next_event` | 等待下一条事件 |

### 3.2 Message 事件（中间消息）

Agent 产出的中间消息（如工具调用结果、思考过程）。

```json
{
  "object": "message",
  "type": "assistant",
  "id": "msg-uuid-xxxx",
  "status": "Completed",
  "content": [
    { "type": "text", "text": "正在查询交换机状态..." }
  ]
}
```

### 3.3 Response 事件（最终回复）

Agent 完成处理后的最终响应，**收到此事件表示本轮对话结束**。

```json
{
  "object": "response",
  "type": "response",
  "id": "resp-uuid-xxxx",
  "status": "Completed",
  "output": [
    {
      "object": "message",
      "type": "assistant",
      "content": [
        { "type": "text", "text": "核心交换机运行正常，CPU 使用率 32%，内存占用 58%。" }
      ]
    }
  ],
  "usage": {
    "prompt_tokens": 120,
    "completion_tokens": 85,
    "total_tokens": 205
  }
}
```

### 3.4 Error 事件

```json
{ "error": "错误描述信息" }
```

### 事件时序

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  progress   │───▶│  progress   │───▶│  message    │───▶│  response   │
│ (received)  │    │ (waiting)   │    │ (中间消息)   │    │ (最终回复)   │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
                        ▲    │              ▲    │
                        └────┘              └────┘
                      (可能多次)           (可能多条)
```

---

## 4. 辅助接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/console/chat/stop?chat_id={id}` | POST | 中止正在运行的聊天 |
| `/api/chats` | GET | 获取聊天列表 |
| `/api/chats/{chat_id}` | GET | 获取指定聊天的历史消息 |
| `/api/chats/{chat_id}` | DELETE | 删除聊天记录 |
| `/api/chats/batch-delete` | POST | 批量删除聊天 |
| `/api/console/upload` | POST | 上传文件（multipart/form-data） |

> 以上接口均支持 `X-Agent-Id` header 指定智能体。

---

## 5. 会话管理

- **session_id**：由调用方自行生成和管理，推荐格式如 `nms_{userId}_{timestamp}`
- **上下文保持**：相同 `session_id` + `user_id` 的多次请求共享对话历史
- **新会话**：使用新的 `session_id` 即开启新的对话上下文
- **chat_id**：系统自动分配的内部 ID，可通过 `/api/chats` 接口查询

---

## 6. 断线重连

当客户端连接中断时，可使用 `reconnect` 参数重新连接到正在运行的流：

```json
{
  "channel": "console",
  "user_id": "nms-user-001",
  "session_id": "session_20260602_140000",
  "reconnect": true
}
```

**行为：**
- 回放已缓存的所有事件（不会丢失之前的输出）
- 继续接收新产生的事件
- **不会**触发新一轮 Agent 执行

---

## 7. 认证说明

| 模式 | 说明 |
|------|------|
| 默认（无认证） | 直接调用即可，无需 token |
| 启用认证 | 需先调用 `/api/auth/login` 获取 token，后续请求携带 `Authorization: Bearer <token>` |

认证开关由服务端环境变量 `QWENPAW_AUTH_ENABLED=true` 控制。

---

## 8. 前端对接示例

### JavaScript (fetch + ReadableStream)

```javascript
/**
 * 与 QwenPaw 智能体进行流式对话
 * @param {string} message - 用户消息
 * @param {string} sessionId - 会话标识
 * @param {string} userId - 用户标识
 * @param {object} callbacks - 回调函数
 */
async function chatWithAgent(message, sessionId, userId, callbacks = {}) {
  const { onProgress, onMessage, onResponse, onError } = callbacks;

  const response = await fetch('/api/console/chat', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Agent-Id': 'default',
    },
    body: JSON.stringify({
      channel: 'console',
      user_id: userId,
      session_id: sessionId,
      input: [{ content: [{ type: 'text', text: message }] }],
    }),
  });

  if (!response.ok) {
    onError?.(`HTTP ${response.status}: ${response.statusText}`);
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split('\n\n');
    buffer = parts.pop(); // 保留不完整部分

    for (const part of parts) {
      if (!part.startsWith('data: ')) continue;
      try {
        const event = JSON.parse(part.slice(6));

        if (event.error) {
          onError?.(event.error);
        } else if (event.object === 'progress') {
          onProgress?.(event);
        } else if (event.object === 'message') {
          onMessage?.(event);
        } else if (event.object === 'response') {
          onResponse?.(event);
        }
      } catch (e) {
        console.warn('Failed to parse SSE event:', part, e);
      }
    }
  }
}
```

### 使用示例

```javascript
await chatWithAgent(
  '核心交换机当前的 CPU 和内存使用率是多少？',
  'nms_admin_1717315200',
  'admin',
  {
    onProgress: (event) => {
      console.log(`[${event.stage}] ${event.message}`);
      // 可展示 loading 动画或进度文字
    },
    onMessage: (event) => {
      // 中间消息，如工具调用过程
      const text = event.content?.find(c => c.type === 'text')?.text;
      if (text) console.log('[中间]', text);
    },
    onResponse: (event) => {
      // 最终回复
      const reply = event.output?.[0]?.content?.find(c => c.type === 'text')?.text;
      console.log('[回复]', reply);
      // 渲染到聊天界面
    },
    onError: (err) => {
      console.error('[错误]', err);
    },
  }
);
```

### cURL 测试

```bash
curl -X POST "http://<host>:30088/api/console/chat" \
  -H "Content-Type: application/json" \
  -H "X-Agent-Id: default" \
  -d '{
    "channel": "console",
    "user_id": "test-user",
    "session_id": "test-session-001",
    "input": [{"content": [{"type": "text", "text": "你好"}]}]
  }' \
  --no-buffer
```

---

## 9. 注意事项

1. **SSE 长连接**：请确保客户端和中间代理（nginx 等）不会过早超时断开连接，建议设置超时 ≥ 300s
2. **并发限制**：同一 session_id 同时只能有一个正在运行的 Agent 任务，重复请求会加入已有流
3. **消息顺序**：SSE 事件按产生顺序推送，前端按序处理即可
4. **编码**：所有 JSON 均为 UTF-8 编码，`ensure_ascii=True`（中文会被转义为 `\uXXXX`）
5. **文件上传**：需先通过 `/api/console/upload` 上传，获取 URL 后放入 content 的 `file` 类型中
6. **Nginx 代理配置**（如有）：
   ```nginx
   location /api/ {
       proxy_pass http://127.0.0.1:30088;
       proxy_http_version 1.1;
       proxy_set_header Connection "";
       proxy_buffering off;           # 关键：关闭缓冲以支持 SSE
       proxy_read_timeout 300s;
   }
   ```
