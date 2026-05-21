---
name: alarm-analyst
category: root-cause
tags: [fault, alarm, diagnosis, cmdb, mysql, metrics, deadlock, analysis-report, collaboration, portal, topology, application]
triggers: [告警分析, 故障分析, 数据库锁异常, 数据库死锁分析, 告警处置分析, 告警根因分析, 活动告警处置, 告警闭环, 应用新增数据失败, CMDB 插入失败]
description: 面向单条活动告警或单个应用故障现象驱动的故障分析与闭环处置技能。适用于 Portal 中用户点击右上角铃铛告警后，或直接描述"某应用新增数据失败 / CMDB 插入数据失败"等现象后，由故障分析专家数字员工接管，并向用户展示从智观活动告警、CMDB 资源确认、应用拓扑拆解、指标分析、影响范围判断、处置建议、恢复验证到清除告警/推送分析报告的完整过程。若当前工作区已具备 shell、跨智能体和指标接口能力，应优先执行真实查询，不要只复述流程模板。
---

# Alarm Analyst

围绕单条活动告警完成根因分析与处置闭环。不是单纯的告警查询技能，也不是只输出诊断结论的模板。

## 何时使用

- 用户给出了一条具体告警，或上下文中已选中一条活动告警
- 用户希望分析故障根因、影响范围和处置建议
- 用户需要推进闭环：推送分析报告 / 恢复验证 / 清除告警 / 更新状态
- 告警与数据库、MySQL、锁异常、死锁、性能异常、服务异常等主题相关
- 用户描述"某应用新增数据失败""CMDB 插入数据失败"等故障现象

## 何时不使用

- 只看告警列表/数量/分布 → 用 `real-alarm`
- 已有工单上下文继续处置 → 用 `fault-disposal`

---

## 核心原则

### 执行优先，不要停在"计划调用"

只要当前工作区具备可用工具（shell、chat_with_agent），就必须先执行真实动作再汇报结果。不需要问"是否继续"，直接做。只有在工具不可用、参数不明确或用户明确要求"先不要执行"时才允许只展示计划。

### 本地 skill 优先

1. CMDB 查询 → 优先使用 fault 本地的 `zgops-cmdb`
2. 活动告警查询 → 优先使用 fault 本地的 `real-alarm`
3. 只有本地 skill 不可用时才回退到跨智能体协作（chat_with_agent → query）
4. 回退时必须说明原因

### 拓扑驱动分析

不只处理"单个资源告警"，也处理"应用功能失败"：
- 先查应用拓扑，拆出依赖组件链（数据库、中间件、网络、应用、基础资源）
- 再对各组件分层进入故障分析

---

## 完整执行链路（不允许跳步）

```
1. 接收告警 → 提取告警标题、resId/CI ID、告警时间、设备名/IP
2. 查智观活动告警上下文（活跃状态、近7日历史）
3. CMDB 资源确认 → 根资源详情 + ciType + 拓扑关系
4. 变更关联 → 查询故障前24h内相关配置变更/版本升级/割接记录（变更命中=高置信线索）
5. 拓扑关联资源告警查询（硬约束）
6. 指标定义查询 → AI 筛选关键指标 → 查指标值（含动态基线偏离分析）
7. AI 综合分析 → 故障类型识别 + 根因判断（六步分析法）
8. 影响范围分析
9. 推送分析报告 + 通知推送
10. 恢复验证 → 清除告警 → 更新状态
```

---

## 关键步骤详解

### 拓扑关联资源告警查询（硬约束）

这是 RCA 完成的**必要条件**，不是可选步骤：

1. 拿到根资源 resId 后，通过 zgops-cmdb 查询 CMDB 拓扑关系
2. 从拓扑中提取**全部**关联资源 ID（根资源、节点 `_id/ci_id`、关系边 `src_ci_id/dst_ci_id`）
3. 对这些资源 ID **逐个**调用 real-alarm 查询告警（时间窗：告警前后 10 分钟）
4. 可选查询环比窗口做趋势对比

如果这一步没完成，不能宣称"分析完成"，只能标记为 `partial`，置信度降为低/中。

### 指标分析

已确认 ciType 后，执行聚合脚本：

```bash
cd skills/alarm-analyst && python scripts/analyze_alarm_context.py \
  --res-id <CI_ID> --alarm-title "<告警标题>" \
  --device-name <设备名> --manage-ip <管理IP> \
  --event-time "<告警时间>" --output markdown
```

该脚本会：查根资源详情 → 查拓扑 → 收集关联资源 ID → 查关联告警 → 查指标定义 → 筛选并查询指标值 → 输出结构化结果。

如果只需单独查指标：

```bash
cd skills/alarm-analyst && python scripts/get_metric_definitions.py \
  --metric-type <ciType> --res-id <CI_ID> --output markdown
```

### 故障类型识别

拿到拓扑告警 + 指标后，AI 判断故障更像哪一类：
- 基础资源（硬件/虚拟化/容器）
- 网络（时延/丢包/连通性）
- 应用（接口错误/线程阻塞）
- 数据库（锁/死锁/慢SQL/复制延迟）
- 中间件（MQ/Redis/网关）
- 业务逻辑（参数/规则/脏数据）

分析时参考 `references/rca-*.md` 中对应场景的经验知识。

### 推送分析报告

RCA 结论形成后，必须推送分析报告通知（不是可选的）：

```bash
cd skills/alarm-analyst && python scripts/send_analysis_report.py \
  --alarm-id <alarmId> --alarm-title "<标题>" \
  --device-name <设备名> --manage-ip <IP> \
  --root-cause "<根因>" --suggestion "<建议>" --output markdown
```

详见 `references/workorder-api.md`。推送成功后通知会发送到配置的渠道（见 `references/notification-protocol.md`）。

---

## 输出结构

用户可见输出采用阶段化结构：

1. 告警接收与解析
2. 智观告警上下文确认
3. CMDB / 应用拓扑确认
4. 拓扑关联资源告警查询结果
5. 指标采集与分析
6. 根因判断与影响范围
7. 处置建议与自动建单
8. 通知推送结果
9. 恢复验证与状态回写

最终必须追加 `📊 总结` 小节，包含：置信度（百分比，第一行）、故障性质、根因方向、影响范围、优先动作、关联资源告警查询状态、通知状态。

如果回复用于 Portal 展示卡片，须遵守 `references/portal-card-protocol.md` 中的 marker 和章节约定。

---

## 拓扑可视化

当 zgops-cmdb 或 query 返回拓扑时：
- 优先展示为 `echarts` 树状图（`series.type='tree'`, `orient='LR'`）
- 根节点使用实际应用名或核心资源名
- 保留 query 返回的 echarts 代码块，不要改写成纯文字

---

## 配置

`.env` 最小配置：

```bash
INOE_API_BASE_URL=http://192.168.130.51:30080
INOE_API_TOKEN=your_jwt_token_here
ALARM_ANALYST_METRIC_TIMEOUT_SECONDS=120
ALARM_ANALYST_METRIC_PAGE_SIZE=20
```

- 缺少 token 时必须停止调用并明确报错
- `getMetricDefinitions` 与 `getMetricData` 共用同一个 base URL
- 分析报告推送复用同一个 base URL / token

---

## references/ 目录说明

| 文件 | 何时读取 |
|------|---------|
| `rca-network.md` | 告警涉及网络层（链路/设备/性能劣化/配置错误/安全事件） |
| `rca-iaas.md` | 告警涉及 IaaS 层（硬件/虚拟化/存储/操作系统/资源耗尽） |
| `rca-paas.md` | 告警涉及 PaaS 层（容器编排/中间件/服务网格/数据库缓存/配置证书） |
| `rca-application.md` | 告警涉及应用层（代码缺陷/业务逻辑/依赖服务/API接口） |
| `rca-cross-layer.md` | 告警涉及跨层复合（级联故障/网络-应用联合/IaaS-PaaS联合/全链路退化） |
| `portal-card-protocol.md` | 输出需要 Portal 渲染卡片时 |
| `notification-protocol.md` | 处理通知推送逻辑时 |
| `workorder-api.md` | 推送分析报告时 |

AI 应根据当前告警场景**按需读取**对应的 reference 文件，不要全部加载。
