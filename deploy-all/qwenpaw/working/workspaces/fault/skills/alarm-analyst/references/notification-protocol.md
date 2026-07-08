# 通知推送协议

分析报告推送完成后，必须执行 webhook 通知推送。通知由 `scripts/send_analysis_report.py` 内部自动完成。

## 推送渠道

可按 `.env` 配置同时推送到：
- 应用推送接口（可配置为量子密信）：`POST /api/push/{token}`，请求体 `{title, content, type}`
- 钉钉：发送 `markdown` 消息，指标值使用逐条列表（移动端不支持表格）
- 飞书：优先发送 `interactive` 卡片，明确展示状态、全量指标和结论

## 配置优先级

1. 优先读取 Portal「高级功能 → 设置 → 通知」中的 `alarm-analyst 建单推送` 配置
2. 未设置时回退到 `.env` 中的 `ORDER_CREATE_NOTIFY_*` 变量

## .env 配置项

```bash
ORDER_CREATE_NOTIFY_PUSH_URL=
ORDER_CREATE_NOTIFY_DINGTALK_WEBHOOK_URL=
ORDER_CREATE_NOTIFY_DINGTALK_SECRET=
ORDER_CREATE_NOTIFY_FEISHU_WEBHOOK_URL=
ORDER_CREATE_NOTIFY_FEISHU_SECRET=
ORDER_CREATE_NOTIFY_TIMEOUT_SECONDS=8
ORDER_CREATE_NOTIFY_MENTION_ALL=true
```

## 通知内容要求

至少包含：
- `AI 告警分析报告`
- 告警标题
- 告警编号 (alarmId)
- 资源 / 设备信息
- 根因方向
- 紧急预案（启用止血时必须体现，放在处置建议之前；通过 `--suggestions-json` 中 `stage:"emergency"` 的条目自动派生，未启用时省略）
- 处置建议
- 异常指标（如果有）

通知文案里必须明确这是 **AI 自动生成** 的分析报告。

## 推送结果展示规则

- 成功：`通知状态：✅ 已成功推送`（不需要逐渠道列出）
- 未配置：明确写出"通知未配置"
- 部分失败：明确写出"分析报告已生成，但部分通知发送失败"，列出失败渠道和原因
- 应用推送正文使用纯文本列表，不发送 `**`、`>` 等 Markdown 控制符

## 推荐通知模板

影响范围大、启用紧急预案时：

```
🔍 AI告警分析报告

- 告警标题：数据库锁异常
- 资源：db_mysql_001（10.43.150.186）
- 告警编号：alarm-001
- 根因方向：InnoDB 行锁竞争阻塞链 -> 死锁 -> 连接异常
- 🚑 紧急预案（止血，立即执行）：
  先将受影响业务切换至备用 MySQL 实例恢复访问（需人工确认审批后执行）
- 处置建议：
  1. 查看死锁记录
  2. 排查长事务和锁等待关系
  3. 分析慢 SQL 日志确认热点写入
  4. 检查连接池配置
- 异常指标：
  - 锁等待数：15（正常为 0，存在大量锁竞争）
  - 慢SQL数：8（近期突增，与阻塞高度相关）

此报告为 AI 自动生成，请尽快跟进处置。
```

影响范围可控、未启用紧急预案时省略"🚑 紧急预案"段，其余不变。
