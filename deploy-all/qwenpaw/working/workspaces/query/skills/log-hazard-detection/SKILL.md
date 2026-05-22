---
name: log-hazard-detection
category: log
tags: [log, hazard, drain3, clustering, anomaly, observability, elasticsearch]
triggers: [日志隐患, 日志聚类, 日志模板, 模板挖掘, 模板提取, 隐患识别, 异常模板, 突增日志, 突增模板, 新增模板, 消失模板, 日志漂移, 错误模板, 错误密集模板, 稀有日志, 稀有模板, 罕见日志, 异常聚类, 报错聚类, 异常归并, drain3, log clustering, hazard report, 日志根因线索, 智观日志聚类, 智观日志隐患]
description: 基于 Drain3 在线模板挖掘的日志隐患识别。把当前窗口的智观日志服务业务日志压成 N 个稳定模板，对比 24h / 7d 前的基线模板分布，找出突增模板、新增模板、消失模板、稀有模板与错误密集模板，输出 Markdown 报告 + ECharts 图。当用户提到“日志隐患/日志聚类/日志模板/突增日志/异常模板/罕见日志/错误集中爆发/与昨天相比日志变化/最近多出哪些报错模式”等诉求时**必须使用本技能**。本技能不是关键字检索（那是 nightingale-log）、不做敏感信息扫描（那是 log-security-scan）、不做单告警根因（那是 fault），只回答“这段时间日志里冒出哪些值得关注的模式”。
---

# Log Hazard Detection（日志隐患识别）

为智观日志服务的业务日志做模式分析，回答 “最近一段时间，日志里冒出了哪些值得关注的模式 / 异常 / 错误聚簇 / 漂移”。

底层是 [Drain3](https://github.com/logpai/Drain3)：在线模板挖掘——把成千上万条相似日志压成稳定的模板（带通配符占位），统计每种模板的频次、参与主机/服务，再对比基线窗口找出漂移。

## 前置配置（给 Agent）

使用本技能前，确认本技能目录下存在 `.env` 并填好以下字段（与 nightingale-log 同源）：

```bash
N9E_API_BASE_URL=http://<host>:<port>
N9E_USER_TOKEN=your_user_token_here
N9E_LOG_DATASOURCE_ID=1
N9E_LOG_INDEX=casaos-syslog-*
N9E_LOG_TIMESTAMP_FIELD=@timestamp
N9E_LOG_MAX_SIZE=5000          # drain3 抽样允许更大
N9E_LOG_TIMEOUT=60             # 模板挖掘比一般查询稍慢
```

如果配置缺失或 token 无效，技能会直接返回配置错误信息，不会继续执行请求。

## 触发条件（给 Agent）

当用户提到以下诉求时，**必须**使用本技能：

- 日志隐患识别 / 日志聚类 / 日志模板挖掘
- 突增模板 / 新增模板 / 消失模板 / 模板漂移
- 错误密集模板 / 异常聚簇 / 报错聚类
- 稀有日志 / 罕见日志 / 异常模式
- “最近多出哪些报错模式” / “跟昨天比日志冒出哪些新的东西” / “异常日志聚一聚”
- “Drain3” / “log clustering” / “模板分析”

**关键澄清**：

- 本技能查询的是平台接入的**业务/应用/系统日志**（生产线上日志），不是 QwenPaw 智能体自身运行日志、控制台 stdout、agent reload 事件
- 本技能不做关键字检索（“查日志/看日志/最近 N 分钟日志/包含 xxx 的日志”请用 `nightingale-log`）
- 本技能不做敏感信息扫描（“日志里有没有密码/token/PII”请用 `log-security-scan`）
- 本技能不做单条告警根因（“这条告警怎么处置”请走 `fault`）

## 配置与最短路径（给 Agent）

- 一站式综合报告：`uv run scripts/n9e_log_hazard.py [--from-time now-15m] [--baseline 24h]`
- 单窗口聚类：`uv run scripts/n9e_log_cluster.py [--from-time now-15m] [--top 20]`
- 漂移分析：`uv run scripts/n9e_log_drift.py [--baseline 24h] [--from-time now-1h]`
- 优先读取共享 `secrets/`，未配置时回退本技能目录下的 `.env`
- 不要要求用户手动拼接 `_msearch` URL 或写 ES DSL
- 不要先做无意义的 ping / 健康检查；直接执行真实分析
- 缺配置或 token 无效时，停止后续分析，直接返回原因

## 时间范围约定

`--from-time` / `--to-time` 同时支持：

- ISO 时间：`2026-05-06T08:00:00`、`2026-05-06 08:00:00`
- 相对时间：`now`、`now-15m`、`now-1h`、`now-6h`、`now-1d`、`now-7d`
- 默认：`from-time=now-15m`，`to-time=now`，`--baseline=24h`（漂移使用）

如果用户没说时间范围，默认查最近 15 分钟。如果用户说 “最近 N 分钟 / 小时 / 天”，转换为对应的 `now-N(m|h|d)`。

## 主流程（给 Agent）

### 1. 先选脚本

| 用户问法（示例） | 推荐脚本 | 为什么 |
|------|---------|------|
| “最近日志里冒出哪些异常模式 / 隐患 / 罕见错误” | `n9e_log_hazard.py` | 一份完整报告：top + 错误密集 + 稀有 + 漂移 |
| “最近 15 分钟日志聚一聚 / 模板挖掘一下” | `n9e_log_cluster.py` | 单窗口模板表 + 占比饼图 |
| “跟昨天比日志多出哪些新模式” / “模板漂移” | `n9e_log_drift.py` | 当前 vs 基线，分突增 / 新增 / 消失 |

不确定时优先 `n9e_log_hazard.py`——一次完成大部分场景。

### 2. 默认执行策略

#### 场景 A：综合隐患报告（最常用）

```bash
uv run scripts/n9e_log_hazard.py --output markdown
```

默认窗口 `now-15m..now`，基线 `24h ago` 的同长窗口，输出包含 4 章：
1. 模板 Top（按命中数）
2. 错误密集模板（含 ERROR/Exception/failed/...）
3. 稀有模板（占比极小但出现至少 2 次）
4. 漂移（当前 vs 24h 前）

#### 场景 B：单窗口聚类

```bash
uv run scripts/n9e_log_cluster.py --from-time now-15m --top 20 --output markdown
uv run scripts/n9e_log_cluster.py --query 'level:ERROR' --from-time now-1h --output markdown
```

#### 场景 C：当前 vs 基线漂移

```bash
uv run scripts/n9e_log_drift.py --baseline 24h --output markdown
uv run scripts/n9e_log_drift.py --baseline 7d  --from-time now-1h --output markdown
```

#### 场景 D：自定义基线

```bash
uv run scripts/n9e_log_drift.py \
  --baseline custom \
  --from-time '2026-05-06T08:00:00' --to-time '2026-05-06T09:00:00' \
  --baseline-from-time '2026-05-05T08:00:00' --baseline-to-time '2026-05-05T09:00:00' \
  --output markdown
```

### 3. 数据处理默认规则

- **抽样**：默认 `--sample-size 2000`；当 ES 命中量 > sample_size × 4 时，自动从 `tail`（最新优先）降级为 `random_score` 抽样，并在报告里标注 “采样比 X%”
- **字段**：默认 `--message-fields app_json,message`；如果 `app_json` 字段不存在会退化为 syslog 头模板，可显式覆盖：`--message-fields message,raw_event.message`
- **错误密度**：模板里命中 `ERROR / Exception / Traceback / failed / panic / fatal / refused / timeout / denied / unreachable / crash / abort / critical` 的 token 数 / 模板长度比例
- **稀有判定**：占比 < 0.1% 且 count ∈ [2, 10]
- **drain3 兜底**：`max_clusters=2000`，超过即不再分裂

## 用户意图 → 推荐动作

**综合诉求**：
- “最近日志有什么异常 / 隐患 / 错误模式” → `n9e_log_hazard.py --from-time now-15m --output markdown`
- “最近 1 小时日志综合分析” → `n9e_log_hazard.py --from-time now-1h --output markdown`

**单窗口聚类**：
- “最近 15 分钟日志聚类” / “模板挖掘” → `n9e_log_cluster.py --from-time now-15m --output markdown`
- “错误日志聚类一下” → `n9e_log_cluster.py --query 'level:ERROR OR message:Exception' --from-time now-1h --output markdown`
- “xxx 服务日志聚类” → `n9e_log_cluster.py --query 'service.name:xxx OR fcservice:xxx' --from-time now-1h --output markdown`

**漂移**：
- “跟昨天比最近 1 小时日志多出哪些模式” → `n9e_log_drift.py --baseline 24h --from-time now-1h --output markdown`
- “跟上周同期比” → `n9e_log_drift.py --baseline 7d --from-time now-1h --output markdown`
- “最近多出哪些新模板” / “新增模板” → `n9e_log_drift.py --baseline 24h --output markdown`
- “消失了哪些模板” → `n9e_log_drift.py --baseline 24h --output markdown`（同样输出三段，关注消失段）

**异常 / 边角**：
- “稀有日志 / 罕见日志” → `n9e_log_hazard.py --output markdown`（看 “稀有模板” 段）
- “错误密集 / 错误集中爆发” → `n9e_log_hazard.py --output markdown`（看 “错误密集模板” 段）

## 输出约定

- 默认输出适合聊天窗口直接展示的 Markdown
- 调用任意一个脚本时优先附带 `--output markdown`
- `markdown` 输出会自动附带 ECharts 代码块（饼图 / 柱图）
- `markdown-echarts-only` 只输出 ECharts 代码块，适合前端只消费图表
- 报告先给结论：模板总数、命中数、采样比、最显眼模板
- 不要只把命令贴给用户去执行
- 表格中的模板使用 `<NUM>`、`<IP>`、`<UUID>`、`<PATH>`、`<HEX>`、`<STR>` 等占位符——这是 drain3 的归并标记，不是 bug

## 错误处理规则

- **缺少 `N9E_API_BASE_URL` / `N9E_USER_TOKEN`**：直接提示配置缺失，不继续请求
- **drain3 未安装**：报错提示用 `uv run` 跑（pyproject.toml 已声明 drain3 依赖）；本技能不会自动 pip install
- **401 / 403**：提示 token 无效 / 权限不足，建议更新 `.env` 或重新生成 Token
- **404**：提示数据源 ID / 索引名错误，建议先跑 `nightingale-log/scripts/n9e_log_meta.py --mode datasources`
- **空命中**：明确说 “未挖掘出任何模板”，并提示放宽时间范围、加大 `--sample-size`、检查 `--message-fields`
- **drain3 内存膨胀**：报告里会显示 `auto_random=true` 表示已降级抽样；过大窗口建议拆开多次跑

## 何时读取参考文档

- 用户问 drain3 原理 / 调参 → `references/templates-howto.md`
- 用户问典型场景或问法 → `references/usage-scenarios.md`

默认不主动加载全部参考文档；只在需要解释细节时再读。

## Few-shot 示例

### 示例 1：综合隐患报告

- 用户：看下最近 15 分钟日志里有没有什么异常模式
- 动作：`uv run scripts/n9e_log_hazard.py --from-time now-15m --output markdown`
- 回复：先 1~2 句结论（最显眼的 surge / error_dense / rare），再分章 markdown + ECharts

### 示例 2：错误日志聚类

- 用户：把最近 1 小时的报错日志聚一下
- 动作：`uv run scripts/n9e_log_cluster.py --query 'level:ERROR OR message:Exception OR message:failed' --from-time now-1h --output markdown`
- 回复：1 句结论（命中数 / Top 模板 / 涉及主机数），再表格 + ECharts 饼图

### 示例 3：与昨天比

- 用户：跟昨天同时段比，最近 1 小时多出哪些日志模式
- 动作：`uv run scripts/n9e_log_drift.py --baseline 24h --from-time now-1h --output markdown`
- 回复：1 句结论（surged 数 / new 数 / vanished 数），再三段表 + 双柱图

### 示例 4：稀有日志

- 用户：最近有什么稀有日志
- 动作：`uv run scripts/n9e_log_hazard.py --output markdown`
- 回复：聚焦 “稀有模板” 段，给前 5 条；说明判定标准（占比 < 0.1% 且 count ∈ [2,10]）

### 示例 5：自定义基线

- 用户：拿今天上午 8~9 点跟昨天上午 8~9 点比
- 动作：`uv run scripts/n9e_log_drift.py --baseline custom --from-time 2026-05-07T08:00:00 --to-time 2026-05-07T09:00:00 --baseline-from-time 2026-05-06T08:00:00 --baseline-to-time 2026-05-06T09:00:00 --output markdown`
- 回复：同示例 3，但基线是用户指定的窗口

## 注意事项

- Token 应只放在本地环境变量或 `.env` 中，不在对话中回显
- 时间范围越大，drain3 内存压力越大；超过 6h 建议分批跑
- drain3 模板里的 `<NUM>` / `<IP>` 等不是泄漏，是占位符——drain3 把数字、IP、UUID、路径屏蔽以稳定模板
- `_n9e_client.py` 是 nightingale-log 的物理拷贝；上游修复 / 升级时，本技能与 log-security-scan 都要同步
- 这是 “识别” 能力，不做修复 / 处置；找到隐患后，告警根因走 `fault`，工单走 `order`
