# 告警清除通知（恢复验证）API 文档

本文档描述 INOE 告警平台在**清除告警**后，通知 QwenPaw 执行恢复验证的接口。

相关后端代码位于：

- `src/qwenpaw/extensions/api/alarm_clear_models.py`
- `src/qwenpaw/extensions/api/recovery_verification_service.py`
- `src/qwenpaw/extensions/portal_alarm_clear_events.py`
- `src/qwenpaw/extensions/api/portal_backend.py`

## 概述

- **QwenPaw 后端基础路径**: `http://<host>:8088`
- **接口路径**: `POST /api/portal/real-alarms/clear-notifications`
- **鉴权**: 无（无需 Token）

## 设计目标

当 INOE 侧将一条告警标记为"已清除"后，通过本接口将清除事件推送给 QwenPaw。QwenPaw 不会立即做出判断，而是在延迟窗口（默认 120 秒）后启动**三阶段异步验证**：

1. **INOE 复核** — 回查 INOE 活跃告警列表，确认该告警是否已从活跃状态中消失
2. **指标验证** — 查询关联资源的监控指标，判断业务是否真正恢复
3. **观察窗口** — 若前两阶段均正常，继续观察一段时间（默认 30 分钟），确认未复发

验证完成后 QwenPaw 将通过企微/钉钉/飞书通知发送验证结论，并在 Portal 告警台账中更新告警状态。

---

## 接口详情

### POST /api/portal/real-alarms/clear-notifications

#### 请求头

| 字段           | 值                               |
|----------------|----------------------------------|
| Content-Type   | `application/json;charset=UTF-8` |

#### 请求体（JSON）

| 字段        | 别名                                           | 类型   | 必填 | 说明                                                       |
|-------------|------------------------------------------------|--------|------|------------------------------------------------------------|
| `alarmId`   | `alarmuniqueid` \| `id`                        | string | **是** | 告警唯一标识（与 INOE 活跃告警列表中的 `alarmuniqueid` 对应）|
| `resId`     | `devId`                                        | string | 否   | 资源 / 设备 ID，用于指标验证阶段的资源定位                 |
| `clearTime` | `cleartime` \| `canceltime`                    | string | 否   | 告警清除时间，格式 `YYYY-MM-DD HH:MM:SS` 或 ISO 8601       |
| `clearType` | —                                              | string | 否   | 清除方式：`"auto"`（自动清除）或 `"manual"`（人工清除）    |
| `operator`  | —                                              | string | 否   | 清除操作人（用于日志记录）                                 |
| `reason`    | —                                              | string | 否   | 清除原因描述                                               |
| `metricType`| —                                              | string | 否   | 关联指标类型（若有），供指标验证阶段参考                   |

> **字段别名说明**：INOE 侧可直接使用原生字段名（如 `alarmuniqueid`、`canceltime`、`devId`）推送，无需转换字段名。QwenPaw 会自动识别。

#### 请求体示例

```json
{
  "alarmuniqueid": "ALM-2025-00123456",
  "devId": "RES-001",
  "canceltime": "2025-06-12 14:30:00",
  "clearType": "manual",
  "operator": "张三",
  "reason": "重启设备后告警消失"
}
```

也可以使用规范化字段名：

```json
{
  "alarmId": "ALM-2025-00123456",
  "resId": "RES-001",
  "clearTime": "2025-06-12T14:30:00",
  "clearType": "auto"
}
```

#### 响应体（HTTP 200）

```json
{
  "status": "accepted",
  "eventId": 42,
  "alarmId": "ALM-2025-00123456",
  "tracked": true,
  "deduped": false,
  "nextVerifyAt": "2025-06-12T14:32:00+08:00",
  "verificationEnabled": true
}
```

| 字段                  | 类型    | 说明                                                                 |
|-----------------------|---------|----------------------------------------------------------------------|
| `status`              | string  | 固定为 `"accepted"`，表示通知已受理                                  |
| `eventId`             | integer | 本次清除事件在 QwenPaw 内部的记录 ID                                 |
| `alarmId`             | string  | 已接收的告警 ID（回显）                                              |
| `tracked`             | boolean | `true` 表示已进入验证队列；`false` 表示该告警台账中不存在，仅记录    |
| `deduped`             | boolean | `true` 表示该告警已有进行中的验证任务，本次通知被合并（幂等）        |
| `nextVerifyAt`        | string  | 预计首次执行验证的时间（ISO 8601）                                   |
| `verificationEnabled` | boolean | 当前恢复验证功能是否已启用（可在 Portal 设置页关闭）                 |

#### 错误响应

| HTTP 状态码 | 含义                                      | 示例响应体                                                        |
|-------------|-------------------------------------------|-------------------------------------------------------------------|
| 422         | 请求参数校验失败，通常为 `alarmId` 缺失   | `{"detail": [{"loc": ["body", "alarmId"], "msg": "Field required"}]}` |
| 500         | 服务内部错误                              | `{"detail": "Internal server error"}`                             |

---

## 幂等性说明

- 同一 `alarmId` 在已有**进行中**（`pending` / `verifying` / `observing`）的验证任务时，重复推送不会新建任务，响应中 `deduped` 为 `true`。
- 对已完成（`recovered` / `unrecovered` / `unknown`）的告警重新推送，会开启新一轮验证。
- 推荐 INOE 侧在清除告警后**仅推送一次**，QwenPaw 内部有重试机制，无需在 INOE 侧轮询重推。

---

## 验证流程说明

接口返回 `accepted` 后，验证在后台异步进行，分为以下阶段：

```
推送清除通知
     ↓
等待延迟窗口（默认 120 秒）
     ↓
阶段一：INOE 活跃告警复核
  ├─ 仍在活跃列表 → recovery_failed（清除未恢复）
  └─ 已不在活跃列表 ↓
阶段二：指标验证
  ├─ 指标仍异常 → 重试（最多 3 次，间隔 300 秒）
  ├─ 指标恢复 ↓
  └─ 指标不可查 → recovery_unknown（恢复待确认）
阶段三：观察窗口（默认 30 分钟）
  ├─ 窗口内再次出现 → recurred（已复发）
  └─ 窗口结束无复发 → recovered（已恢复）
```

验证完成后：
- Portal 告警台账中的告警状态会更新为对应结论
- 若配置了推送通知，会向钉钉 / 飞书 / Webhook 发送验证结论消息

---

## 验证参数配置

以下参数可在 **Portal → 设置 → 诊断 → 恢复验证** 中调整：

| 参数                               | 默认值   | 说明                                         |
|------------------------------------|----------|----------------------------------------------|
| 恢复验证功能开关                   | 开启     | 关闭后接口仍接受推送，但不触发验证           |
| 验证延迟（秒）                     | 120      | 收到清除通知后等待多久再开始第一次验证       |
| 最大重试次数                       | 3        | 验证失败时的最大重试次数                     |
| 重试间隔（秒）                     | 300      | 两次重试之间的等待时间                       |
| 观察窗口（分钟）                   | 30       | 指标恢复后继续观察多久以确认未复发           |

---

## curl 示例

```bash
curl -X POST http://<host>:8088/api/portal/real-alarms/clear-notifications \
  -H "Content-Type: application/json;charset=UTF-8" \
  -d '{
    "alarmuniqueid": "ALM-2025-00123456",
    "devId": "RES-001",
    "canceltime": "2025-06-12 14:30:00",
    "clearType": "manual",
    "operator": "张三",
    "reason": "重启设备后告警消失"
  }'
```

预期响应：

```json
{
  "status": "accepted",
  "eventId": 42,
  "alarmId": "ALM-2025-00123456",
  "tracked": true,
  "deduped": false,
  "nextVerifyAt": "2025-06-12T14:32:00+08:00",
  "verificationEnabled": true
}
```

---

## 查询清除事件列表（可选）

QwenPaw 也提供一条只读接口，可查询历史清除通知及验证状态：

```
GET /api/portal/real-alarms/clear-events?limit=20&status=verifying
```

| 查询参数 | 类型    | 说明                                                      |
|----------|---------|-----------------------------------------------------------|
| `limit`  | integer | 返回条数，默认 50，最大 200                               |
| `status` | string  | 按验证状态过滤：`pending` / `verifying` / `observing` / `recovered` / `unrecovered` / `unknown` / `recurred` |
