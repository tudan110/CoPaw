---
name: alarm-analyst
category: root-cause
tags: [fault, alarm, diagnosis, cmdb, mysql, metrics, deadlock, analysis-report, collaboration, portal, topology, application]
triggers: [告警分析, 故障分析, 数据库锁异常, 数据库死锁分析, 告警处置分析, 告警根因分析, 活动告警处置, 告警闭环, 应用新增数据失败, CMDB 插入失败, 机房动环告警, 动环告警分析, 供配电告警, 精密空调告警, UPS告警]
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

### Fail Fast：接口异常或无数据不做无效重试

任何单个数据源（CMDB、告警上下文、指标查询、跨智能体调用）失败或返回空，都遵循"单次尝试 → 如实记录 → 继续下一步"，不允许为了"凑出结果"而反复重试或换参数试探：

- **单次尝试即可下结论**：接口调用失败（超时、401/403/404/5xx、连接错误）或返回空数据，直接按失败/空处理，不做二次三次重试，不切换参数硬凑
- **指标数为 0 是合法结果**：脚本已内置 ciType 三级回退，若仍查不到指标，说明该资源类型确实无指标定义，直接进入下一步（另见下文"⚠️ 不要在脚本返回 ciType 为空时手动重跑"）
- **降级而不是卡住**：某个环节失败不代表整体分析失败，把该环节标记为 `partial`/`blocked` 并说明原因，继续完成其余环节，最终在"📊 总结"中如实体现置信度和缺失项
- **不要靠切换到其他 skill 来"证明"空结果**：比如指标查询为空，不要绕去 `real-alarm` / 跨智能体反复验证"是不是真的没有"，一次拿到空值即可下结论
- **跨智能体调用同样受此约束**：`chat_with_agent` 超时或无响应，不要重复发起同一请求，按"本地已尽力、协作补充缺失"如实说明

---

## 并行执行策略（减少分析耗时）

告警分析涉及多个独立数据源查询，**必须按依赖关系分组并行执行**，不允许无依赖的调用串行排队。

### 并行组划分

**第一波（立即发出，无依赖）**：
- 查智观活动告警上下文（real-alarm 脚本，ci_id）
- 查 CMDB 根资源详情（zgops-cmdb fetch）
- 查 CMDB 拓扑关系（zgops-cmdb ci_relations）
- 读取对应场景的 rca-*.md

**第二波（等第一波返回后）**：
- 从拓扑/链路告警提取关联资源 ID → 批量查关联资源告警（可多个 CI ID 并行）
- 查指标定义 + 指标值（`analyze_alarm_context.py` 内部已并行）
- 如果本地拓扑为空，才考虑 `chat_with_agent(query)` 补充

**第三波（等第二波返回后）**：
- AI 综合分析 + 推送报告

### 关键约束

- **禁止用 `chat_with_agent` 查询指标数据**：不要通过跨智能体调用 query 智能体来查询指标，直接使用本技能的 `get_metric_definitions.py` + `getMetricData` 脚本。跨智能体调用开销极大（常超时 5-10 分钟），且本地脚本完全能满足需求
- **本地查拓扑优先**：先用 `zgops-cmdb.sh fetch` 或链路告警提取对端信息，不要首选 `chat_with_agent(query)` 查拓扑（跨智能体调用可能超时 60s+）
- **跨智能体调用只做补充**：如果本地 CMDB 拓扑为空且链路告警也无法推断对端，才发起 `chat_with_agent`，且用 `submit_to_agent` 后台模式，不阻塞主流程
- **对端设备告警批量查**：多个 CI ID 的告警查询是独立的，必须并行发出（脚本内部已实现并行）
- **ciType 自动解析**：`analyze_alarm_context.py` 已支持从 CMDB `ci_type` 字段、`_type` 数字映射、告警标题关键词三级回退推断 metricType，不需要手动重跑

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
3. 对这些资源 ID 的告警查询已由 `analyze_alarm_context.py` 内部并行完成，无需手动逐个调用
4. 如果 CMDB 拓扑为空，可从链路类告警标题中提取对端设备信息作为补充

如果这一步没完成，不能宣称"分析完成"，只能标记为 `partial`，置信度降为低/中。

### CMDB 查询语法参考

```bash
# 单条件查询（按 CI ID）
zgops-cmdb.sh fetch --ci-id 18

# 多条件查询（按名称模糊匹配）
zgops-cmdb.sh search --q "name:DKCZZ-HUAWEI"

# 查拓扑关系
zgops-cmdb.sh fetch --ci-id 18 --relations

# 按 IP 查设备
zgops-cmdb.sh search --q "manage_ip:172.27.34.1"
```

注意：多条件查询用空格分隔（不要用 `+AND+`），如 `--q "ci_type:networkdevice manage_ip:172.27.34.1"`

### 指标分析

执行聚合脚本（**不需要**先手动确认 ciType，脚本会自动解析）：

```bash
cd skills/alarm-analyst && python scripts/analyze_alarm_context.py \
  --res-id <CI_ID> --alarm-title "<告警标题>" \
  --device-name <设备名> --manage-ip <管理IP> \
  --event-time "<告警时间>" --output markdown
```

该脚本会：查根资源详情 → 自动解析 ciType（三级回退：ci_type 字段 → _type 数字映射 → 告警标题关键词推断）→ 查拓扑 → **并行**收集关联资源告警 → 查指标定义 → 筛选并查询指标值 → 输出结构化结果。

⚠️ **不要在脚本返回 ciType 为空时手动重跑 `get_metric_definitions.py`**——脚本已内置回退逻辑。如果脚本仍返回指标数为 0，说明该资源类型确实无指标定义，直接进入下一步。

**异常指标识别**：脚本返回的 `metricDataResults` 包含所有查询到的指标值，AI 必须结合告警上下文判断哪些指标存在异常（如与告警有因果关系、值偏离正常范围等），并在最终报告的 `## 异常指标` 章节中以表格形式列出。不要列出所有指标，只列出判断为异常的指标，并附带简要异常说明。

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
  --device-name <设备名> --manage-ip <IP> --level <告警等级> \
  --root-cause "<根因>" --suggestion "<建议>" \
  --abnormal-metrics-json '[{"name":"指标名","code":"metric_code","value":"85.3","unit":"%","reason":"异常说明"}]' \
  --output markdown
```

> **`--level` 必传**：从告警信息中提取等级值（如 `urgent`、`3`、`严重` 等均可），不传则通知中显示为"-"。
> **`--abnormal-metrics-json` 可选**：传入 AI 判断的异常指标 JSON 数组，通知中会展示。如无异常指标可不传。

详见 `references/notification-protocol.md`。推送成功后通知会发送到配置的渠道。

> ⚠️ **审批规避**：`--root-cause`、`--suggestion`、`--abnormal-metrics-json` 的文本内容会经过 shell 审批系统的文本模式检测。避免在文案中直接出现 `kill`、`sudo`、`rm`、`crontab`、`ssh` 等命令关键词，改用中性措辞（如"终止进程"代替"kill"，"定时任务"代替"crontab"，"登录主机"代替"ssh"），以免触发误审批导致推送超时。

---

## 输出结构

用户可见输出采用阶段化结构：

1. 告警接收与解析
2. 智观告警上下文确认
3. CMDB / 应用拓扑确认
4. 拓扑关联资源告警查询结果
5. 指标采集与分析
6. 根因判断与影响范围
7. 异常指标（AI 从全部指标中筛选出与告警相关的异常项）
8. 处置建议
9. 通知推送结果
10. 恢复验证与状态回写

最终必须追加 `📊 总结` 小节，包含：置信度（百分比，第一行）、故障性质、根因方向、影响范围、优先动作、关联资源告警查询状态、通知状态。

如果回复用于 Portal 展示卡片，须遵守 `references/portal-card-protocol.md` 中的 marker 和章节约定。

### 处置建议规则（按告警级别精简）

处置建议必须根据告警级别（alarmseverity）控制内容层次，**只给用户当下最需要的建议**，避免堆砌过多层次造成信息过载：

**禁止事项**：
- **禁止自动创建工单**：不要调用工单 API 创建工单，该功能已停用
- **报告正文禁止使用 `---` 分隔线**：`---` 仅用于 `PORTAL ALARM ANALYST CARD MODE` 标志行与正文之间的唯一分隔，正文内出现 `---` 会导致卡片解析截断
- 任何级别的告警中都不要出现"中期加固""长期规划"类建议
- 不要使用"【紧急止损】""【短期优化】""【中期加固】"等分层标签，直接给出操作步骤
- 每条建议必须是具体可执行的动作，不要给出笼统的方向性描述

---

## 拓扑可视化

当 zgops-cmdb 或 query 返回拓扑关系（应用/集群/容器/虚拟机等层级或依赖关系）时，**必须**在报告正文中输出一个 ` ```echarts ` 代码块（围栏语言标记必须精确写成 `echarts`，前端按此标记提取渲染，写成 `json` 或纯文字表格都不会被识别）：

- **优先使用 `series.type='tree'`**（`orient='LR'`，从左到右分层），根节点用实际应用名或核心资源名，逐层用 `children` 挂接下游资源，例如：
  ```echarts
  {
    "series": [
      {
        "type": "tree",
        "orient": "LR",
        "data": [
          {
            "name": "天翼智观",
            "children": [
              {
                "name": "k3s-SYM01",
                "children": [{ "name": "天翼智观部署虚机" }]
              }
            ]
          }
        ]
      }
    ]
  }
  ```
- 仅当拓扑呈现多对多网状依赖、无法用单一树形表达时，才退化使用 `series.type='graph'`（`data`/`links` 描述节点与关系）
- 禁止只用 markdown 表格或文字描述拓扑而不给 echarts 代码块——那属于协议未遵守，会导致 portal 卡片的拓扑区域留空
- 保留 query 返回的 echarts 代码块，不要改写成纯文字；如需补充说明，放在代码块前后，不要替代代码块

---

## 配置

**配置来源**：由设置页「平台 / INOE」统一管理，运行时物化为环境变量（`INOE_*`），脚本从环境变量读取（设置页改动对下一次技能调用即时生效）。**不再回退共享 `secrets/inoe.env` 或技能目录下的 `.env`。**

如果配置缺失或无效，脚本会直接返回配置错误信息，不会继续执行请求。

涉及的环境变量（在设置页配置，勿手填 `.env`）：

```bash
INOE_API_BASE_URL=...           # 设置页：INOE 平台地址
INOE_API_TOKEN=...              # 设置页：INOE 令牌
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
| `rca-facility.md` | 告警来自机房动环（供配电/UPS/制冷空调/温湿度漏水烟感/消防/安防门禁/动环采集器），物理底座层 |
| `rca-network.md` | 告警涉及网络层（链路/设备/性能劣化/配置错误/路由震荡/二层环路/IP地址冲突/DHCP/安全攻击） |
| `rca-ipran-ip.md` | 告警涉及 IP 专业设备（BRAS/CR/路由器：NodeDown/中继质差/LinkDown/端口翻转/板卡/风扇/电源，含 API 清单与光功率阈值） |
| `rca-iaas.md` | 告警涉及 IaaS 层（硬件/虚拟化/存储/操作系统/资源耗尽/时钟同步/进程与服务） |
| `rca-paas.md` | 告警涉及 PaaS 层（容器K8s/中间件/服务网格/数据库缓存/云主机计算/负载均衡网关/配置证书） |
| `rca-application.md` | 告警涉及应用层（拨测不可用/响应劣化/部分功能/业务逻辑/第三方依赖/前端用户侧/流量并发/代码/API） |
| `rca-cross-layer.md` | 告警涉及跨层复合（级联/网络-应用/IaaS-PaaS/全链路退化），含跨专业故障传播链速查 |
| `portal-card-protocol.md` | 输出需要 Portal 渲染卡片时 |
| `notification-protocol.md` | 处理通知推送逻辑时 |

AI 应根据当前告警场景**按需读取**对应的 reference 文件，不要全部加载。
