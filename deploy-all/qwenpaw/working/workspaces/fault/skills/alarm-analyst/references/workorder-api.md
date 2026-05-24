# 分析报告推送 API 与脚本参考

## 脚本入口

```bash
cd skills/alarm-analyst && python scripts/send_analysis_report.py \
  --alarm-id <alarmId> \
  --alarm-title "<告警标题>" \
  --visible-content "<用户可见告警摘要>" \
  --device-name <deviceName> \
  --manage-ip <manageIp> \
  --asset-id <assetId> \
  --level <alarmLevel> \
  --status <alarmStatus> \
  --event-time "<eventTime>" \
  --analysis-summary "AI 已完成根因分析" \
  --root-cause "<根因方向>" \
  --suggestion "<处置建议1>" \
  --suggestion "<处置建议2>" \
  --output markdown
```

## 字段要求

- 必须提交**告警流水号**，映射到 `alarm.alarmId`
- 告警标题末尾用括号标注，如 `数据库锁异常（AI创建）`
- 请求体里必须带处置建议
- `--chat-id` 和 `--res-id` 为可选参数，用于内部记录关联

## 推送前提

必须先形成：
1. 根因总结
2. 影响范围
3. 至少 1 条处置建议

## 失败处理

- 通知推送失败：明确写出失败渠道和原因
- 即使推送失败，RCA 结论仍保留供人工查看

## 推送后链路

1. 推送分析报告通知（见 `references/notification-protocol.md`）
2. 收到回调后执行恢复验证 → 更新告警状态
