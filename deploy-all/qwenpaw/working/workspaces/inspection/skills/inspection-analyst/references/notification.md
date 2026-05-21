# 巡检通知推送约定

巡检结果生成后，`scripts/inspect_resource_metrics.py` 会根据配置自动推送通知。

## 支持的通知渠道

| 渠道 | 配置项 | 格式 |
|------|--------|------|
| 应用推送（量子密信等） | `INSPECTION_NOTIFY_PUSH_URL` | 纯文本列表，不使用 Markdown 控制符 |
| 钉钉 | `INSPECTION_NOTIFY_DINGTALK_WEBHOOK_URL` + `_SECRET` | Markdown 消息，指标用逐条列表（移动端不支持表格） |
| 飞书 | `INSPECTION_NOTIFY_FEISHU_WEBHOOK_URL` + `_SECRET` | Interactive 卡片，包含指标表格 |

## 通知内容要求

推送内容必须体现这是 **AI 巡检结果**，至少包含：

- 巡检对象、资源名称、资源 ID（CI ID）、资源类型
- 整体状态
- 指标总数
- 巡检时间
- 巡检结论
- 全量指标值（飞书用表格，其它渠道按各自能力展示）

## 各渠道格式细节

### 应用推送接口

- 使用 `POST /api/push/{token}`
- 请求体：`{title, content, type}`
- 正文使用纯文本列表，不发送 `**`、`>` 等 Markdown 控制符
- 至少体现状态、全量指标值、巡检结论

### 钉钉

- 发送 `markdown` 消息
- 自定义机器人移动端不支持 Markdown 表格，指标值使用逐条列表展示

### 飞书

- 优先发送 `interactive` 卡片
- 明确展示整体状态、全量指标表格、巡检结论

## 异常处理

- 未配置任何通知地址 → 明确写出"通知未配置"
- 部分渠道推送失败 → 明确写出"部分通知发送失败"
- 通知配置优先读取 Portal「高级功能 → 设置 → 通知」中的 `inspection` 配置；只有未设置时才回退 `.env` 中的 `INSPECTION_NOTIFY_*` / `ORDER_CREATE_NOTIFY_*`
