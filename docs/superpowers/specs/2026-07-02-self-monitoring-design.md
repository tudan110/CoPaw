# QwenPaw 自监控能力设计 · 对标阿里云云监控(CMS)

> Spec · 2026-07-02 · 分支 `dev`
> 作者:与操作员共同敲定,Opus 4.8
> 状态:**设计稿待评审**(本轮只出设计,不写代码)
> 落地形态(操作员已确认):**两者都要** —— 内置 SQLite 自成闭环(离线可用)+ 对外暴露 Prometheus `/metrics`(被 n9e/Grafana 抓取)。
> 首期细化到 **P0**;P1/P2 给路线不给细节。

## 1. 背景与目标

QwenPaw **现在是在监控别人**:大屏拉 n9e/inoe/cmdb 时序与告警、`real-alarm` 查告警、工单查变更——镜头对外。但**系统自身**跑得好不好,基本靠人肉发现:大屏"又是模版"了才去翻日志,worker 死了靠 supervisor 默默拉起,LLM 偷偷降级到模版可以持续几天没人知道。

**自监控 = 把这套镜头掉过头对准自己。** 好在做别人监控攒下的家底(大屏渲染、告警渠道、诊断 agent、trace)大部分能 dogfood 直接复用,自监控主要是补一条"采集→汇聚→消费"的脊柱,而非从零造监控栈。

**目标**:让 QwenPaw 具备**分层、可度量、离线可用、可告警**的自监控能力——覆盖对话体验、Agent/技能/治理、LLM/外部依赖、进程/资源四层;既能自成闭环(内置大屏看板 + 渠道告警),也能作为标准被监控对象接入既有 n9e/Grafana。

**非目标**(本设计明确不做):
- 不重造采集:已有 `token_usage`/`agent_stats`/大屏 telemetry/`traceability`/`connection_status` 是数据源,自监控是它们之上的**聚合+事件+告警+可视化**层。
- 不替换 `traceability`(单会话深度回放)、不替换 supervisor(进程拉起)——见 §9 边界。
- P0 不做告警引擎、不做端到端拨测、不做 AIOps 根因(P1/P2)。

## 2. 对标阿里云 CMS:能力映射

| 阿里云 CMS 模块 | 对应 QwenPaw 自监控 | 现状 | 本设计阶段 |
| --- | --- | --- | --- |
| 主机/资源监控(Agent 采 CPU/内存/磁盘/进程) | L4 进程&主机:worker 存活、RSS、CPU、磁盘、SQLite 膨胀 | ❌ 仅 supervisor 拉起 | **P0** |
| 云产品监控(按产品维度) | 组件维度:runtime / provider / 渠道 / 大屏 各自健康 | 🟡 分散无统一视图 | **P0** |
| 站点监控 / 拨测(多地探活) | 端到端拨测:对话冒烟、门户首屏、关键 API 探活 | ❌ 无 | P1 |
| 自定义监控(业务指标上报) | 领域指标:技能成功率、大屏降级率、治理拦截率、ReAct 迭代 | 🟡 数据零散未成指标 | **P0** |
| 事件监控(系统+自定义事件) | 事件总线:worker died / 429 风暴 / 降级 / 治理 DENY 超时 / appkey 失效 / 白屏 | ❌ 只散在日志里 | **P0** |
| 报警服务(阈值/规则→多渠道) | 告警规则 → 复用现有渠道(钉钉/Slack/邮件) | ❌ 无 | P1 |
| Dashboard / 大盘 | 自监控大屏(dogfood 现有大屏) | ✅ 引擎现成,缺 `self:` 源 | **P0**(源) / P1(看板打磨) |
| 应用分组 | 按 workspace / agent / worker 分组聚合 | 🟡 `agent_stats` 有维度 | P0 打标签 |
| AIOps(2.0)根因 / Copilot 诊断 | dogfood 诊断 agent:关联 trace+event+metric 给根因 | 🟡 `/api/doctor` + `traceability` 雏形 | P2 |
| Prometheus / OTel 兼容 | 暴露 `/metrics` 被抓 | ❌ 无(有可选 Langfuse) | **P0** |

## 3. 现状盘点(按四层 + 有/缺)

| 层 | 已有(复用为采集端) | 缺(P0 要补) |
| --- | --- | --- |
| **L1 体验** | 渠道健康 `ChannelHealthResponse`(`app/routers/schemas_config.py:115`) | 会话成功率/首 token 延迟/白屏事件均无统一指标 |
| **L2 应用** | 会话聚合 `agent_stats/service.py:112`;全链路 `traceability`(`extensions/api/traces_backend.py`) | ReAct 迭代数、工具/技能成功率、治理 ASK/DENY/超时 无计数 |
| **L3 依赖** | Token 用量 `token_usage/manager.py`;大屏质量 `ai_big_screen/telemetry.py:42`(successRate/degradedRate/avgDurationMs——**自监控样板**);外部源探活 `ai_big_screen/connection_status.py:48`;限流/重试 `providers/retry_chat_model.py:41` | 429/重试/限流暂停/降级 无计数器;datasource up 未汇成指标 |
| **L4 资源** | supervisor `autorestart`(`deploy/config/supervisord.conf.template:14`) | CPU/内存/磁盘/worker 存活/日志 ERROR 率/SQLite 大小 全无 |
| **横切** | 结构化日志 `utils/logging.py:31`;可选 Langfuse `observability/langfuse.py:39`;dev-loop 记分器 `dev-loop/tools/big_screen_report.py`(离线雏形) | 统一指标注册表、事件总线、`/metrics` 导出、统一查询 API 全无 |

**结论**:采集端已散落一地成品数据,真正缺的是**中间那根汇聚脊柱**(注册表+事件总线+存储+双出口)和**统一消费面**(查询 API + 自监控大屏源)。P0 就干这两件事。

## 4. 核心架构决策

| # | 决策 | 取舍 |
| --- | --- | --- |
| D1 | **四层监控模型**(L1 体验 / L2 应用 / L3 依赖 / L4 资源)作为分类主干,每条指标/事件强制打 `layer` 标签 | 照搬 CMS「四层覆盖」;排障自上而下,天然可归因 |
| D2 | **采集复用、不重采**:自监控是聚合+事件+告警+可视化层,只对空白(L4 资源、事件总线)新增采集 | 避免与 `token_usage`/`agent_stats`/大屏 telemetry 双采、双写 |
| D3 | **统一 `MetricRegistry`(进程内)+ 双出口**:一份进程内注册表,两个 sink —— (a) SQLite rollup 供内置闭环&大屏消费,(b) Prometheus 文本供外部抓取 | 满足「两者都要」;一份数据两处消费,不各写各的 |
| D4 | **指标与事件分离**:指标是连续聚合量(counter/gauge/histogram),事件是离散带级别的信号(worker died、429 风暴) | 对齐 CMS「监控指标」vs「事件监控」;告警规则可分别作用 |
| D5 | **离线优先、外部可选**:SQLite + 内置大屏使系统不依赖 Prometheus/Grafana 也自成闭环;`/metrics` 为可选出口 | 对齐部署纪律(依赖烧镜像、离线);无外网监控栈也能用 |
| D6 | **dogfood 消费**:可视化走现有大屏(`self:` 源)、告警走现有渠道、根因走现有诊断 agent | 复用即验证产品,消费侧几乎零新代码 |
| D7 | **SQLite rollup 作为多 worker 聚合点**:`QWENPAW_APP_WORKERS>1` 时各 worker 进程内注册表定期快照落 SQLite(带 `worker_id`),查询/`/metrics`/大屏统一读 rollup 聚合 | 一举解决多 worker 指标一致性(见 §5.5 风险);顺带得到历史 |
| D8 | **fail-open + 不侵主干**:自监控自身故障绝不拖垮主流程;采集尽量挂现有 hook,新代码落 `self_monitor/` 模块 + `extensions/`,`/api/version` 保留为不依赖自监控的最底层 liveness | 「谁监控监控者」——监控层挂了系统还能跑;落点纪律对齐 §6 |

## 5. 详细设计(P0)

### 5.1 四层指标目录(命名遵循 Prometheus 惯例,前缀 `qwenpaw_`)

**L1 体验层**
- `qwenpaw_chat_sessions_total{channel,status}` — status=success|error|timeout
- `qwenpaw_chat_first_token_seconds`(histogram)— 首 token 延迟
- `qwenpaw_chat_turn_duration_seconds`(histogram)
- `qwenpaw_portal_probe_up{target}`(gauge, 0/1)— 拨测占位,P1 填数

**L2 应用层**
- `qwenpaw_agent_iterations`(histogram)— ReAct 迭代数(过高=打转)
- `qwenpaw_tool_calls_total{tool,status}` / `qwenpaw_skill_runs_total{skill,status}`
- `qwenpaw_agent_task_duration_seconds`(histogram)
- `qwenpaw_governance_decisions_total{decision}` — decision=allow|ask|deny|timeout(**盯 No-rule-hit→ASK→超时 DENY**)

**L3 依赖层**
- `qwenpaw_llm_requests_total{provider,model,status}` — status=ok|429|5xx|timeout
- `qwenpaw_llm_tokens_total{provider,model,kind}` — kind=prompt|completion(取自 `token_usage`)
- `qwenpaw_llm_retries_total{provider}` / `qwenpaw_llm_rate_limit_pause_seconds_total`(counter)
- `qwenpaw_llm_request_duration_seconds`(histogram)
- `qwenpaw_bigscreen_generation_total{kind,degraded}`(取自大屏 telemetry)
- `qwenpaw_datasource_up{source}`(gauge)— source=inoe|n9e|zgops|order|proxy(取自 `connection_status`)
- `qwenpaw_degrade_events_total{component}` — **本方案第一优先指标**:任何组件退回模版/降级即 +1

**L4 资源层**
- `qwenpaw_process_cpu_percent{worker}` / `qwenpaw_process_memory_rss_bytes{worker}`(gauge, psutil)
- `qwenpaw_worker_up{worker}`(gauge)+ `qwenpaw_worker_heartbeat_timestamp{worker}`
- `qwenpaw_disk_usage_bytes{path}` — path=working|secret
- `qwenpaw_sqlite_size_bytes{db}` — db=self_monitor|bigscreen|history|traces
- `qwenpaw_log_errors_total{level}` — level=error|critical(挂 logging handler)

### 5.2 `MetricRegistry`(进程内,数据结构)

```python
# src/qwenpaw/self_monitor/registry.py
class Metric:
    name: str
    kind: str                 # counter | gauge | histogram
    layer: str                # l1 | l2 | l3 | l4
    help: str
    # 值按 label 组合分桶存活于内存
    samples: dict[LabelKey, float | HistogramState]

class MetricRegistry:            # 进程级单例(每 worker 一个)
    def counter(name, layer, help): ...      # .inc(labels, n=1)
    def gauge(name, layer, help): ...        # .set(labels, v) / .inc / .dec
    def histogram(name, layer, help, buckets): ...  # .observe(labels, v)
    def snapshot() -> list[MetricSample]     # 供 rollup 落盘 & /metrics 渲染
```

- 操作 O(1)、线程安全(轻量锁或 `contextvars`);**绝不阻塞主循环**。
- 单例获取 `get_registry()`,风格对齐 `token_usage` 的单例 manager。

### 5.3 事件总线(离散信号,数据结构)

```python
# src/qwenpaw/self_monitor/events.py
class Event:
    ts: float
    type: str            # 见下表
    severity: str        # info | warn | error | critical
    layer: str
    source: str          # 组件/agent/worker 名
    labels: dict[str, str]
    message: str
    dedup_key: str       # 同 key 在抑制窗口内合并计数,防事件风暴

def emit(event: Event) -> None   # 异步入队 → 批量落 SQLite;满则丢弃并计 dropped(fail-open)
```

**P0 首批事件类型**(每条都对应过一次真实事故):

| type | severity | 触发点 | 对应历史事故 |
| --- | --- | --- | --- |
| `worker.died` / `worker.restart` | error | worker 心跳缺失 / supervisor 重启 | worker 反复 died、5173 孤儿 |
| `llm.rate_limit_storm` | warn | 429 计数在窗口内超阈值 | 429 被误判成「访问量大」 |
| `component.degraded` | error | 大屏退模版 / LLM 路径失败 | llm.py 两处 bug 一路退模版 |
| `governance.deny_timeout` | warn | 判定 15s 超时 → DENY | 领域守卫超时拦截导入 |
| `appkey.invalid` | error | 「AppKey 不存在」错误路径 | appkey 主密钥漂移 |
| `portal.whitescreen` | warn | 前端看门狗上报 beacon | aTrust 网络抖动白屏 |
| `datasource.down` | warn | `connection_status` 探活失败 | zgops cmdb 不通 |
| `resource.high` | warn | CPU/内存/磁盘越阈 | — |

### 5.4 存储(SQLite,`~/.qwenpaw/self_monitor.db`,WAL 模式)

```sql
-- 指标不存原始样本,只存周期 rollup 快照(控膨胀 + 得历史 + 多 worker 聚合)
CREATE TABLE metric_rollup (
  ts INTEGER, name TEXT, layer TEXT,
  labels_json TEXT, value REAL, worker_id TEXT
);                                     -- 索引: (name, ts), (ts)
CREATE TABLE events (
  ts INTEGER, type TEXT, severity TEXT, layer TEXT,
  source TEXT, labels_json TEXT, message TEXT, dedup_key TEXT, count INTEGER
);                                     -- 索引: (type, ts), (severity, ts)
-- alerts 表 P1 引入
```

- 表结构直接沿用大屏 telemetry 的 SQLite 落地范式(`ai_big_screen/telemetry.py:42` 已验证)。
- **保留策略**:`QWENPAW_SELF_MONITOR_RETENTION_DAYS`(默认 7)后台裁剪。
- **写入**:rollup 每 `QWENPAW_SELF_MONITOR_ROLLUP_INTERVAL`(默认 15s)批量快照;events 异步批量 append。均参照 `token_usage/buffer.py` 的 10s 刷盘模式,不同步阻塞。

### 5.5 双出口:SQLite 闭环 + Prometheus `/metrics`(含多 worker)

```
每 worker: MetricRegistry(内存) ──15s快照──▶ metric_rollup(SQLite, 带 worker_id)
                                                      │
                            ┌─────────────────────────┼─────────────────────────┐
                            ▼                          ▼                          ▼
                  内置闭环: 查询API/大屏          /metrics(Prometheus)      外部 n9e/Grafana 抓
                  (读 rollup 跨 worker 聚合)      (读 rollup 渲染文本)
```

**关键点 —— 多 worker 一致性**:uvicorn 多 worker 共享端口,`/metrics` 若渲染"当前进程内存"会随机命中某 worker → 数据抖动。**故 `/metrics` 与查询 API 一律读 SQLite rollup**(D7),按 `worker_id` 聚合(counter 求和、gauge 取最新/求和视语义),得到跨 worker 稳定视图。代价:N 秒陈旧(可接受)+ worker 重启导致 counter 归零(Prometheus `rate()` 天然容忍 counter reset)。
- 备选:若要零陈旧,可用 `prometheus_client` multiprocess 模式(共享 mmap 目录)。本设计选 **SQLite rollup 为主**,因为它同时给了内置闭环所需的历史,不必为外部出口单独维护一套。
- `/metrics` 由 `QWENPAW_METRICS_ENABLED`(默认 **false**)开关;开启时**必须**过鉴权或仅内网,避免指标裸奔(§8 安全)。

### 5.6 采集接线(如何采,尽量挂 hook 不改主干)

| 层 | 接线方式 | 落点 |
| --- | --- | --- |
| L2 | 新增 `SelfMonitorHook`(PRE_EXECUTE/FINALLY),仿 `LangfuseTraceHook` 记迭代数/工具/技能/时长 | `runtime/hooks.py` 注册,不改 ReAct 主循环 |
| L2 治理 | 在 `tool_guard` 决策点打点 allow/ask/deny/timeout | `runtime/tool_guard.py`(小改) |
| L3 LLM | 在重试/限流咽喉处 `inc` 429/重试/暂停/降级计数 | `providers/retry_chat_model.py:41` |
| L3 token | 订阅/tap `token_usage` 记录事件,不重算 | `token_usage/manager.py` 加 tap |
| L3 大屏 | tap 大屏 telemetry 的 degraded,或直接读其 SQLite | `ai_big_screen/telemetry.py` |
| L3 源探活 | 复用 `connection_status` 结果转 gauge | `ai_big_screen/connection_status.py` |
| L4 资源 | 后台采样任务(psutil),app lifespan 启动,仿 `token_usage` 刷盘协程 | `self_monitor/sampler.py` |
| L4 日志 | 挂一个 logging handler 统计 ERROR/CRITICAL | `utils/logging.py` 加 handler |
| L1 | 会话边界(渠道/runtime 入出)记 status/首 token/时长 | 渠道层 + runtime |
| 事件 | 上表各触发点调用 `events.emit()` | 分散但都是单行调用 |

原则:**能挂 hook 就挂 hook,单行打点为主,避免大面积改主干**(D8)。

### 5.7 查询 API(只读,挂 `/api/portal/self-monitor/*`)

| 端点 | 用途 |
| --- | --- |
| `GET /api/portal/self-monitor/overview` | 四层健康总览:每层 status + 关键指标摘要(给大屏/首页) |
| `GET /api/portal/self-monitor/metrics?name=&layer=&from=&to=` | 时序查询(读 rollup) |
| `GET /api/portal/self-monitor/events?type=&severity=&from=&to=` | 事件列表 |
| `GET /api/portal/self-monitor/health` | 增强健康(liveness+readiness+四层概览),不依赖自身以外重组件 |
| `GET /metrics` | Prometheus 文本(开关+鉴权) |

路由落 `src/qwenpaw/extensions/api/self_monitor_api.py`,风格对齐 `traces_backend.py`。

### 5.8 dogfood 消费:自监控大屏(P0 出源,P1 打磨看板)

- 新增大屏数据源 `self:`(或直接让现有 proxy 源指向本机 overview/metrics API)。**大屏渲染代码一行不改**——它本就会渲染 Prometheus 形状的时序,给 `self:` 喂同形状数据即得自监控大盘。
- `connection_status` 增加 `self:` 一项健康检查,纳入大屏能力目录。
- 效果:自然语言"给我 QwenPaw 自己的健康大屏"即出 L1–L4 看板。

## 6. 配置与代码落点

**环境变量**
- `QWENPAW_SELF_MONITOR_ENABLED`(默认 true)
- `QWENPAW_METRICS_ENABLED`(默认 false,外部导出显式开)
- `QWENPAW_SELF_MONITOR_ROLLUP_INTERVAL`(默认 15s)
- `QWENPAW_SELF_MONITOR_RETENTION_DAYS`(默认 7)
- 存储:`~/.qwenpaw/self_monitor.db`(随 `QWENPAW_WORKING_DIR`)

**代码落点(新增为主,主干仅单行打点)**
```
src/qwenpaw/self_monitor/           # 新模块,peer 于 token_usage/ agent_stats/ observability/
  registry.py        # MetricRegistry + 单例
  events.py          # 事件总线 + emit
  store.py           # SQLite rollup/events 读写(WAL)
  sampler.py         # L4 资源采样 + rollup 刷盘协程(lifespan 启动)
  hook.py            # SelfMonitorHook(L2 采集)
src/qwenpaw/extensions/api/self_monitor_api.py   # 查询 API + /metrics
# 主干打点(单行级):retry_chat_model.py / tool_guard.py / token_usage tap / logging handler
```

## 7. 分期路线(P0 已细化,P1/P2 给方向)

| 阶段 | 内容 | 见效 |
| --- | --- | --- |
| **P0 脊柱**(本设计) | MetricRegistry + 事件总线 + SQLite rollup + 双出口(`/metrics`)+ 四层采集接线 + 查询 API + `self:` 大屏源 | 看得见:降级率/429/worker 存活/资源一屏可见,且可被 n9e 抓 |
| **P1 告警+拨测** | 告警规则引擎(阈值+简单同比/环比)→ 复用渠道推送;端到端拨测(对话冒烟/首屏/关键 API)挂 heartbeat/schedule 定时跑;白屏 beacon 前端接线 | 从"看得见"到"主动喊" |
| **P2 智能+图谱** | AIOps 根因 agent(dogfood,喂 trace+event+metric 出根因)强化 `/api/doctor`;成本(¥)关联+预算告警;依赖关系图谱(UModel 简化:agent→skill→provider→datasource) | 从"喊"到"说清为什么" |

## 8. 已知边界与风险

| 风险 | 缓解 |
| --- | --- |
| 多 worker 指标一致性(Prometheus 多进程经典问题) | SQLite rollup 聚合(D7);接受 N 秒陈旧 + counter reset(rate() 容忍);备选 `prometheus_client` multiprocess |
| 自监控自身开销 | 全异步/采样/批写;registry O(1);rollup 15s 一次,不同步阻塞主循环 |
| **谁监控监控者** | fail-open:自监控挂了不拖垮主流程;`/api/version` 保留为不依赖自监控的最底层 liveness |
| 存储膨胀 | 只存 rollup 不存原始样本;retention 裁剪;events dedup 合并 |
| 事件风暴(429 风暴时事件也风暴) | `dedup_key` + 抑制窗口内合并计数;队列满 fail-open 丢弃并计 `dropped` |
| **安全/隐私** | 指标 label 严禁带 secret/PII;`/metrics` 默认关,开启须鉴权或仅内网;对齐 secrets 明文在 settings.db 的既有敏感面 |
| 多 workspace 读取被治理拦 | 自监控读自身运行时数据,注意别触发跨 workspace governance ASK(参考既有放行经验) |

## 9. 与现有能力的边界(防重叠)

| 能力 | 职责 | 与自监控关系 |
| --- | --- | --- |
| `traceability` | 单会话**深度**回放(逐消息/工具/决策) | 自监控是**跨会话聚合**;两者互补,自监控事件可深链到某 trace |
| `agent_stats` | 会话计数聚合 | 作为 L2 采集**数据源**被消费,不重算 |
| `token_usage` | Token 明细账 | 作为 L3 采集**数据源**;自监控加成本/速率视角 |
| 大屏 telemetry | 大屏生成质量 | 作为 L3 采集**数据源**;degraded 直接喂 `degrade_events` |
| `/api/doctor` | 点检快照 | 自监控 `health` 端点扩展它;P2 诊断 agent 消费自监控数据 |
| Langfuse | 可选外部 trace 平台 | 平行可选;自监控是内置默认路径,不互斥 |
| supervisor | 进程拉起/重启 | 自监控**观测**其结果(worker.died 事件),不接管拉起 |

## 10. 三根柱子

整套方案的灵魂:**四层模型**(分层归因,照搬 CMS 四层覆盖)· **一份数据双出口**(进程内 registry → SQLite rollup,内置闭环与 Prometheus 导出共用一份,不各写各的)· **dogfood 消费**(大屏可视化、渠道告警、诊断 agent 全部复用现成,消费侧近零新代码)。其余能力都往这三根柱子上挂。
