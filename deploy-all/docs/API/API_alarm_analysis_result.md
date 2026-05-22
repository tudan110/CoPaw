# 告警分析结果查询 API 文档

可通过告警 ID 查询 AI 已完成的分析结果，返回内容与 Portal 卡片展示一致。

## 概述

- **后端基础路径**: `http://127.0.0.1:8088`
- **接口路径**: `GET /api/portal/alarm-analyst/result/{alarm_id}`

## 设计说明

1. AI 对告警完成分析后，会将结构化分析结果持久化到本地 SQLite 数据库
2. 外部系统通过告警 ID 即可直接获取分析结果，无需解析会话或 Markdown
3. 返回字段与 Portal 前端卡片展示内容一一对应

---

## 接口详情

### 请求

```http
GET /api/portal/alarm-analyst/result/{alarm_id}
```

### 路径参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `alarm_id` | `string` | 是 | 告警唯一标识，如 `COMMON__1779384973992_2057515824412274688` |

### 环境地址

| 环境 | 基础地址 | 说明 |
|------|----------|------|
| 本地开发 | `http://192.168.130.50:8088` | 开发机直连 |
| 生产环境（同命名空间） | `http://qwenpaw:8088` | k3s 集群内 Service 名称访问 |
| 生产环境（NodePort） | `http://<节点IP>:30088` | k3s 集群外通过 NodePort 访问 |

### 请求示例

```bash
# 本地开发环境
curl http://192.168.130.50:8088/api/portal/alarm-analyst/result/COMMON__1779384973992_2057515824412274688

# 生产环境（同命名空间内的 Pod 调用）
curl http://qwenpaw:8088/api/portal/alarm-analyst/result/COMMON__1779384973992_2057515824412274688

# 生产环境（NodePort 调用）
curl http://<节点IP>:30088/api/portal/alarm-analyst/result/COMMON__1779384973992_2057515824412274688
```

---

### 响应

#### 成功响应（已有分析结果）

**HTTP 200**

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "title": "内存碎片率（SYRedis03）",
    "anchorObject": "SYRedis03",
    "faultNature": "Redis 集群内存碎片率集群性升高，全部实例同时突破告警阈值",
    "rootCauseDirection": "批量内存释放/重分配操作导致碎片率飙升",
    "impactScope": "全局（天翼智观平台全部 Redis 实例）",
    "priorityAction": "立即执行 MEMORY PURGE 回收碎片；若碎片率仍高于 1.5 则安排滚动重启",
    "relatedAlarmQueryStatus": "✅ 已完成全部关联资源告警查询，共发现 5 条同类告警",
    "confidence": "78%",
    "rootCauseType": "Redis 集群内存碎片率集群性升高",
    "rootCauseObject": "SYRedis03",
    "faultReason": "批量内存释放/重分配操作导致碎片率飙升"
  }
}
```

#### 暂无分析结果

**HTTP 200**

```json
{
  "code": 1,
  "message": "暂无分析结果",
  "data": null
}
```

可能原因：
- 该告警尚未完成 AI 分析（状态为 `analyzing`）
- 告警 ID 不存在或尚未被系统采集
- 分析过程中出现异常未产出结果

---

## 响应字段说明

### data 对象

| 字段名称 | 字段编码 | 类型 | 说明 |
|----------|----------|------|------|
| 根因分析总结 | `title` | `string` | 告警标题（含设备名） |
| 锚定对象 | `anchorObject` | `string` | 告警关联的核心设备/实例 |
| 故障性质 | `faultNature` | `string` | 故障性质描述 |
| 根因方向 | `rootCauseDirection` | `string` | 根因方向分析 |
| 影响范围 | `impactScope` | `string` | 影响范围评估 |
| 优先动作 | `priorityAction` | `string` | 优先处置动作建议 |
| 关联资源告警查询状态 | `relatedAlarmQueryStatus` | `string` | 关联资源告警查询状态 |
| 定位置信度 | `confidence` | `string` | AI 定位置信度（百分比） |
| 根因类型 | `rootCauseType` | `string` | 根因类型 |
| 根因对象 | `rootCauseObject` | `string` | 根因对象 |
| 故障原因 | `faultReason` | `string` | 故障原因 |

> **注意**：部分字段可能为空字符串 `""`，表示 AI 分析报告中未包含该项信息。

---

## 数据流说明

```
告警产生 → 自动轮询采集 → AI 分析（流式） → 分析完成
                                                  ↓
                                        提取结构化字段
                                                  ↓
                                  持久化到 SQLite (alarm_records.analysis_result)
                                                  ↓
                              外部系统调用 GET /result/{alarm_id} 获取
```

## 注意事项

1. **时效性**：只有 AI 分析完成（状态变为 `analyzed`）后，才会有分析结果可查
2. **幂等性**：接口为只读查询，多次调用返回相同结果
3. **数据更新**：若同一告警被重新分析，结果会被覆盖为最新分析内容
4. **认证**：遵循系统全局认证配置，详见 [API_base.md](./API_base.md)
