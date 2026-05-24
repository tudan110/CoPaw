# httpx.AsyncClient TCP 连接泄漏

## 发现时间

2026-05-24

## 现象

服务在服务器部署运行约一天后，接口响应变得非常卡顿。通过 `lsof` 检查发现进程积累了 **270+ 个 ESTABLISHED TCP 连接**，全部指向同一个模型服务端点（如 `172.28.75.4:30088`），FD 从 26 一路涨到 334，连接从未释放。

```
$ lsof -i:30088
COMMAND       PID USER   FD   TYPE     DEVICE SIZE/OFF NODE NAME
MainThrea 2857558 root   26u  IPv4 1162972552      0t0  TCP host01:60022->172.28.75.4:30088 (ESTABLISHED)
MainThrea 2857558 root   28u  IPv4 1162960750      0t0  TCP host01:37010->172.28.75.4:30088 (ESTABLISHED)
...（共 270+ 条）
MainThrea 2857558 root  334u  IPv4 1163557825      0t0  TCP host01:40848->172.28.75.4:30088 (ESTABLISHED)
```

## 根因分析

### 泄漏源头

`OpenAIProvider.get_chat_model_instance()`（`src/qwenpaw/providers/openai_provider.py`）每次调用都创建一个**新的 `httpx.AsyncClient`** 实例：

```python
# openai_provider.py - get_chat_model_instance()
client_kwargs["http_client"] = httpx.AsyncClient(
    timeout=httpx.Timeout(...),
    limits=httpx.Limits(
        max_keepalive_connections=20,
        keepalive_expiry=CHAT_CLIENT_KEEPALIVE_EXPIRY,
    ),
)
```

每个 `httpx.AsyncClient` 持有自己独立的 TCP 连接池。当 model 实例被丢弃时，AsyncClient 没有被显式关闭（`await client.aclose()`），导致底层 TCP 连接永远不会释放。

### 同样问题存在于

- `AnthropicProvider.get_chat_model_instance()`（`src/qwenpaw/providers/anthropic_provider.py`）在 `auth_mode == "auth_token"` 时也会每次 new 一个 `httpx.AsyncClient(transport=_StripApiKeyTransport())`。

### 触发路径

`create_model_and_formatter()` 在以下场景被反复调用，每次都会触发新的 AsyncClient 创建：

| 调用位置 | 触发频率 |
|---------|---------|
| `react_agent.py:178` — Agent 初始化 | 低（启动时一次） |
| `light_context_manager.py:625` — 上下文压缩 | 中（对话达到上下文限制时） |
| `reme_light_memory_manager.py:395` — 记忆总结 | 中（每次对话结束时） |
| `reme_light_memory_manager.py:600` — 记忆优化（dream） | 低（后台定期执行） |
| `title_generator.py:172` — 对话标题生成 | 高（每次新对话首条消息） |
| `skills_stream.py:30` — 技能调用 | 高（每次技能调用） |
| `proactive_responder.py:110` — 主动响应 | 中 |
| `knowledge_base.py:333` — 知识库查询 | 中 |
| `domain_guard/__init__.py:477` — 领域守卫 | 高（每次请求） |
| `natural_language_customization_service.py:250` — NL 定制 | 低 |

运行一天后，上述调用累积产生数百个未关闭的 AsyncClient，每个保持 keepalive 连接，导致 FD 耗尽和主线程阻塞。

## 修复方案

在 Provider 实例级别缓存 `httpx.AsyncClient`，所有 `get_chat_model_instance()` 调用复用同一个连接池。

### OpenAIProvider

```python
class OpenAIProvider(Provider):
    _chat_http_client: httpx.AsyncClient | None = None

    def _get_chat_http_client(self) -> httpx.AsyncClient:
        if self._chat_http_client is None:
            self._chat_http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=CHAT_CLIENT_CONNECT_TIMEOUT,
                    read=CHAT_CLIENT_READ_TIMEOUT,
                    write=CHAT_CLIENT_READ_TIMEOUT,
                    pool=CHAT_CLIENT_READ_TIMEOUT,
                ),
                limits=httpx.Limits(
                    max_keepalive_connections=20,
                    keepalive_expiry=CHAT_CLIENT_KEEPALIVE_EXPIRY,
                ),
            )
        return self._chat_http_client

    def get_chat_model_instance(self, model_id: str) -> ChatModelBase:
        ...
        # 替换：
        # client_kwargs["http_client"] = httpx.AsyncClient(...)
        # 为：
        client_kwargs["http_client"] = self._get_chat_http_client()
```

### AnthropicProvider

```python
# 在 get_chat_model_instance() 中，auth_token 模式复用已有缓存：
if self.auth_mode == "auth_token":
    # 替换：
    # client_kwargs["http_client"] = httpx.AsyncClient(transport=_StripApiKeyTransport())
    # 为：
    client_kwargs["http_client"] = self._get_strip_http_client()
```

> 注：`AnthropicProvider` 已有 `_get_strip_http_client()` 缓存方法，只是 `get_chat_model_instance()` 中没有使用它。

## 验证方法

部署修复后，监控连接数应稳定在连接池上限（20）以内：

```bash
# 监控连接数
watch -n 5 'lsof -p <PID> -i | grep ESTABLISHED | wc -l'

# 或针对特定端口
watch -n 5 'lsof -i:<PORT> | wc -l'
```

## 临时缓解措施

在修复代码部署前，可通过定期重启服务来缓解：

```bash
# 设置 crontab 每 12 小时重启一次
0 */12 * * * systemctl restart qwenpaw
```
