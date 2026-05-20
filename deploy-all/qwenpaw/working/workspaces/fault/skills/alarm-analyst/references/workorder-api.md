# 工单创建 API 与脚本参考

## 脚本入口

```bash
cd skills/alarm-analyst && python scripts/create_manual_workorder.py \
  --chat-id <当前会话ID> \
  --res-id <当前告警对应的CI_ID> \
  --metric-type <ciType或mysql> \
  --alarm-id <alarmId> \
  --alarm-title "<告警标题>" \
  --visible-content "<用户可见告警摘要>" \
  --device-name <deviceName> \
  --manage-ip <manageIp> \
  --asset-id <assetId> \
  --level <alarmLevel> \
  --status <alarmStatus> \
  --event-time "<eventTime>" \
  --analysis-summary "AI 已完成根因分析，自动创建人工处置工单" \
  --root-cause "<根因方向>" \
  --suggestion "<处置建议1>" \
  --suggestion "<处置建议2>" \
  --output markdown
```

## 工单字段要求

- 必须提交**告警流水号**，映射到请求体 `alarm.alarmId`
- `ticket.source` 默认使用 `portal-fault-disposal-ai`
- 工单标题应体现 `AI创建`
- 告警标题末尾用括号标注，如 `数据库锁异常（AI创建）`
- 请求体里必须带处置建议

## 创建前提

必须先形成：
1. 根因总结
2. 影响范围
3. 至少 1 条处置建议

## 失败处理

- 接口失败：明确写出失败原因，不能谎称"已创建工单"，仍保留 RCA 结论供人工补建
- 通知失败：与建单失败分开说明，写清失败渠道和原因

## 创建后链路

1. 自动创建工单
2. 执行通知推送（见 `references/notification-protocol.md`）
3. 如果可自动处置 → 执行处置 → 恢复验证 → 清除告警 → 更新工单状态
4. 如果不可闭环 → 等待恢复告警或人工处理 → 再做恢复验证
