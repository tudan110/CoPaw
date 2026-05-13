# 启明大模型 OpenAI 兼容性评估与接入方案

## 1. 背景

当前拿到的启明大模型调用样例如下：

```bash
curl --location 'http://10.130.154.233:30000/serviceAgent/rest/wsc/completions' \
--header 'X-APP-ID: dcoos订阅后生成' \
--header 'X-APP-KEY: dcoos订阅后生成' \
--header 'Authorization: Bearer xxxxx 订阅后提供' \
--header 'Content-Type: application/json' \
--data '{
  "model": "qiming25_72b_fc",
  "messages": [
    {
      "role": "system",
      "content": "你是由电信公司训练的，名字是“启明大模型”。你是属于电信领域大模型，你擅长直接回答电信公司的领域类的问题。电信领域包括无线、核心网、家庭宽带、移动终端、iTV、云K歌、天翼云等业务。"
    },
    {
      "role": "user",
      "content": "夸一夸中国电信"
    }
  ],
  "temperature": 0.6,
  "max_tokens": 8192,
  "stream": true
}'
```

用户关心的问题有两个：

1. 这个接口是否可以视为 OpenAI 兼容接口
2. 如果不能直接按 OpenAI provider 接入，QwenPaw 是否需要改代码

## 2. 结论

**结论：它不是“严格意义上的 OpenAI 兼容接口”，最多只能算“请求体近似 OpenAI Chat Completions 的类兼容接口”。**

原因不是消息体，而是**传输协议和接入契约不完全一致**。

### 2.1 相似的部分

这份请求体与 OpenAI Chat Completions 非常接近：

| 字段 | 启明样例 | OpenAI 常见接口 |
| --- | --- | --- |
| `model` | 有 | 有 |
| `messages` | 有 | 有 |
| `temperature` | 有 | 有 |
| `max_tokens` | 有 | 有 |
| `stream` | 有 | 有 |

因此从“业务参数形态”看，它很像 OpenAI 风格。

### 2.2 不兼容的部分

但从接入侧看，至少存在下面几个关键差异：

| 项目 | 启明样例 | OpenAI 兼容接口常见要求 | 影响 |
| --- | --- | --- | --- |
| 路径 | `/serviceAgent/rest/wsc/completions` | 通常是 `/v1/chat/completions` | 现有 OpenAI provider 不能直接命中该路径 |
| 鉴权 | `Authorization + X-APP-ID + X-APP-KEY` | 通常只需 `Authorization: Bearer ...` | 现有 provider 不能通用配置这两个额外 header |
| 模型发现 | 未体现 `/models` | OpenAI 兼容场景通常有 `/v1/models` | 当前模型发现/连通性检查会失败或不可用 |
| SDK 适配 | 未说明是否兼容 OpenAI SDK | 兼容接口通常可被 OpenAI SDK 直接调用 | 现有 `openai.AsyncOpenAI` 直连风险较高 |
| 流式返回 | 未确认 chunk 结构 | 常见为 SSE + `choices[].delta.content` | 若流式格式不同，需要额外解析适配 |

所以它**不是可直接替换为 OpenAI base_url 的严格兼容接口**。

## 3. 与 QwenPaw 当前实现的关系

当前 QwenPaw 的 OpenAI 系接入，依赖的是 OpenAI 风格的固定行为。

### 3.1 当前代码的关键假设

现状里，OpenAI provider 主要有这些假设：

1. **基于 `openai.AsyncOpenAI` 客户端调用**
   - 文件：`src/qwenpaw/providers/openai_provider.py`
2. **模型连通性检查使用 `client.chat.completions.create(...)`**
3. **连接检查与模型发现默认调用 `client.models.list()`**
4. **Provider 配置项只有 `base_url`、`api_key`、`generate_kwargs` 等通用字段**
   - 文件：`src/qwenpaw/app/routers/providers.py`
   - 文件：`portal/src/api/models.ts`
5. **前端模型设置页面没有暴露“自定义请求头”配置能力**

### 3.2 直接接入会遇到的问题

如果把启明接口直接当成 OpenAI 兼容地址来填，至少会遇到这些问题：

#### 问题 1：路径不匹配

当前 OpenAI provider 会走 OpenAI SDK 的 chat completions 路径，目标通常是：

```text
<base_url>/chat/completions
```

而启明样例给出的实际路径是：

```text
/serviceAgent/rest/wsc/completions
```

这不是同一个地址。

#### 问题 2：缺少额外请求头

启明接口要求：

- `X-APP-ID`
- `X-APP-KEY`
- `Authorization: Bearer ...`

而当前自定义 provider 的配置模型没有标准入口来保存并透传 `X-APP-ID`、`X-APP-KEY`。

#### 问题 3：`/models` 不一定存在

当前 provider 的连接检查与模型发现会尝试 `models.list()`。

如果启明接口没有对应模型列表接口，那么：

- 模型发现不可用
- 连接测试可能误报失败

#### 问题 4：流式返回结构待验证

即使请求成功，如果启明的流式返回不是 OpenAI 常见 SSE chunk 结构，当前流式解析链路也可能不兼容。

## 4. 结论落地

因此，**如果要“直接接入启明原始接口”，QwenPaw 需要改代码。**

但从工程实现角度看，不一定只有一种改法。

## 5. 推荐路线

建议分为两条路线评估：

### 路线 A：增加一个 OpenAI 适配网关（短期最省改动）

思路是：

1. 在启明接口前面再加一个轻量适配层
2. 把 QwenPaw 发来的 OpenAI 风格请求转换成启明接口格式
3. 适配层负责补充：
   - `X-APP-ID`
   - `X-APP-KEY`
   - `Authorization`
4. 把 OpenAI 风格路径映射到启明真实路径
5. 如有必要，补一个假的 `/v1/models`

### 路线 A 的优点

- **QwenPaw 核心代码几乎不用改**
- 可直接复用现有 OpenAI provider
- 对其他系统也能复用这层代理
- 后续如果启明接口升级，只改适配层即可

### 路线 A 的缺点

- 系统里多一层服务
- 需要单独维护适配网关
- 问题排查链路变长

### 路线 B：在 QwenPaw 内新增启明专用 provider（长期更清晰）

思路是：

1. 新增 `QimingProvider`
2. 直接使用 `httpx` 或定制客户端调用启明接口
3. 在 provider 内自行组装：
   - 请求路径
   - Bearer Token
   - `X-APP-ID`
   - `X-APP-KEY`
4. 根据启明实际返回格式做流式/非流式适配
5. 在 Portal 中新增启明 provider 的配置项

### 路线 B 的优点

- 职责更清晰
- 不需要额外部署一个代理服务
- 启明模型的特殊逻辑可以独立维护

### 路线 B 的缺点

- 需要改后端 provider 框架
- 需要改前端 provider 配置界面
- 需要补单元测试和接入测试

## 6. 不推荐路线

### 路线 C：在现有 OpenAI provider 里硬编码启明特判

例如：

- 某个 base_url 识别成启明
- 特殊拼接路径
- 特殊追加 headers
- 特殊跳过 `/models`

这类做法短期看起来快，但问题很多：

- OpenAI provider 会越来越臃肿
- 后续再接一个类似厂商会继续堆特判
- 前后端配置模型仍然不清晰

因此不建议把启明适配直接硬塞进 `OpenAIProvider`。

## 7. 推荐决策

建议按时间维度分两步：

### 7.1 短期建议

**优先选择路线 A：做一个启明到 OpenAI 的适配网关。**

原因：

- 风险最小
- 对 QwenPaw 改动最少
- 最快验证启明模型在实际业务里的效果

QwenPaw 侧只需要把它当成一个自定义 OpenAI provider：

```text
base_url = http://your-qiming-adapter/v1
api_key = <adapter token 或透传 token>
model = qiming25_72b_fc
```

### 7.2 中长期建议

如果启明将成为正式支持的企业级模型来源，建议落路线 B：

**在 QwenPaw 内新增原生 `QimingProvider`。**

这样更利于：

- 平台化管理
- UI 配置清晰化
- 后续支持多种电信内部模型

## 8. 若选择路线 B，需要改哪些代码

### 8.1 后端

建议涉及以下位置：

| 文件 | 建议改动 |
| --- | --- |
| `src/qwenpaw/providers/provider.py` | 扩展 provider 配置模型，支持额外认证字段或 header 配置 |
| `src/qwenpaw/providers/provider_manager.py` | 注册启明 provider，并支持其持久化 |
| `src/qwenpaw/providers/qiming_provider.py` | 新增启明 provider 实现 |
| `src/qwenpaw/app/routers/providers.py` | 扩展 provider 配置接口 |

### 8.2 前端

建议涉及以下位置：

| 文件 | 建议改动 |
| --- | --- |
| `portal/src/api/models.ts` | 扩展 provider 配置类型 |
| `portal/src/pages/digital-employee/usePortalModels.ts` | 提交启明专属配置字段 |
| `portal/src/pages/digital-employee/modelControls.tsx` | 增加 `APP ID / APP KEY / Token / Endpoint` 配置输入项 |

### 8.3 测试

建议补充：

- Provider 配置序列化/反序列化测试
- 请求头拼装测试
- 流式返回解析测试
- 连通性检查测试
- Portal 表单提交测试

## 9. 路线 B 的建议配置模型

如果做原生启明 provider，建议配置字段至少包含：

| 字段 | 说明 |
| --- | --- |
| `base_url` | 服务地址，例如 `http://10.130.154.233:30000` |
| `completion_path` | 默认 `/serviceAgent/rest/wsc/completions` |
| `app_id` | `X-APP-ID` |
| `app_key` | `X-APP-KEY` |
| `bearer_token` | `Authorization` 使用的 token |
| `models` | 可手工维护的模型列表 |
| `support_model_discovery` | 默认关闭 |
| `support_connection_check` | 可保留，但采用 completion ping，而不是 `/models` |

## 10. 路线 B 的运行逻辑建议

### 10.1 连接检查

不要再走 `/models`，改为发一个最小 completion 请求：

```json
{
  "model": "qiming25_72b_fc",
  "messages": [{"role": "user", "content": "ping"}],
  "max_tokens": 1,
  "stream": false
}
```

### 10.2 模型管理

初期建议：

- 手工添加模型
- 不做自动发现

因为当前没有看到启明提供标准模型发现接口。

### 10.3 聊天调用

provider 内部直接发 HTTP 请求到：

```text
POST /serviceAgent/rest/wsc/completions
```

并注入：

```text
X-APP-ID
X-APP-KEY
Authorization: Bearer ...
```

### 10.4 流式响应

要先确认启明返回是否为：

- 标准 SSE
- 标准 OpenAI chunk
- 或自定义 JSON 分片

如果不是标准 OpenAI chunk，需要在 provider 内实现专用流式适配器。

## 11. 建议先做的验证

在正式开发前，建议先确认四件事：

1. 启明是否存在等价的 `/models` 接口
2. 启明的 `stream=true` 返回是否是标准 SSE
3. 启明的非流式返回结构是否接近 OpenAI `chat.completion`
4. 是否允许通过代理层统一托管 `X-APP-ID` / `X-APP-KEY`

其中第 2、3 点最关键，决定是“轻适配”还是“专用 provider”。

## 12. 最终建议

基于当前信息，建议结论如下：

1. **启明接口不是严格 OpenAI 兼容接口**
2. **如果要直接接入原始启明接口，QwenPaw 需要改代码**
3. **短期最推荐：增加一层 OpenAI 适配网关**
4. **中长期最推荐：在 QwenPaw 内增加原生 `QimingProvider`**

换句话说：

> 从请求体看它“像 OpenAI”，但从实际接入契约看，它还不能直接当成标准 OpenAI provider 来用。

因此，不能只改配置；如果不加代理层，最终还是要做代码适配。

## 13. 当前仓库中的短期适配落地

当前已按“短期推荐”在 QwenPaw 内落了一层轻量适配路由，位置在：

- `src/qwenpaw/extensions/api/qiming_openai_adapter.py`

挂载后的访问入口是：

```text
/api/portal/qiming-adapter/v1
```

它对外提供两个 OpenAI 风格接口：

- `GET /api/portal/qiming-adapter/v1/models`
- `POST /api/portal/qiming-adapter/v1/chat/completions`

适配层当前主要做四件事：

1. 把 OpenAI 风格的 `/chat/completions` 转发到启明真实地址
2. 自动补充 `X-APP-ID` 和 `X-APP-KEY`
3. 透传调用方的 `Authorization: Bearer ...`
4. 把 OpenAI 文本数组格式的 `messages[].content` 归一成启明更常见的字符串格式

## 14. 启用方式

### 14.1 配置环境变量

至少需要配置：

```bash
QWENPAW_QIMING_BASE_URL=http://10.130.154.233:30000
QWENPAW_QIMING_APP_ID=你的APP_ID
QWENPAW_QIMING_APP_KEY=你的APP_KEY
QWENPAW_QIMING_MODELS=qiming25_72b_fc
```

可选配置：

```bash
QWENPAW_QIMING_COMPLETIONS_PATH=/serviceAgent/rest/wsc/completions
QWENPAW_QIMING_TIMEOUT_SECONDS=300
QWENPAW_QIMING_BEARER_TOKEN=你的BearerToken
```

说明：

- 如果调用方自己会带 `Authorization`，适配层会优先透传调用方请求头
- 只有调用方没带 `Authorization` 时，才会回退到 `QWENPAW_QIMING_BEARER_TOKEN`

### 14.2 在 QwenPaw 中配置模型提供商

由于这层适配已经暴露为 OpenAI 风格接口，因此可以直接在现有模型设置页面中新建一个自定义 provider：

| 字段 | 建议值 |
| --- | --- |
| 协议 | `OpenAIChatModel` |
| Base URL | `http://127.0.0.1:8088/api/portal/qiming-adapter/v1` |
| API Key | 启明 Bearer Token |
| Model ID | `qiming25_72b_fc` |

如果你的 QwenPaw 不是跑在 `8088`，把端口替换成实际监听端口即可。

在 Kubernetes / Helm 场景下，推荐仍然优先使用 **Pod 内回环地址** 或同容器本机地址，而不是通过外部网关再绕回自己，这样更稳，也不会额外受认证中间件和外部网络策略影响。
