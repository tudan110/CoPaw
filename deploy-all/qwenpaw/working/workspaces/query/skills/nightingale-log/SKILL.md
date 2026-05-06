---
name: nightingale-log
category: log
tags: [log, nightingale, n9e, elasticsearch, lucene, observability]
triggers: [日志查询, 日志检索, 查日志, 错误日志, 异常日志, 日志列表, 日志统计, 日志分布, 日志趋势, 夜莺日志, n9e日志, ES日志, 业务日志, 应用日志, 日志Top, 关键字日志]
description: 夜莺监控（Nightingale / n9e）日志即时查询。基于 ES 数据源支持 KQL / Lucene 语法的日志检索、级别分布、主机/服务分布、时间序列直方图与关键字搜索。当用户提到“查日志、日志列表、错误日志、异常日志、日志统计、日志分布、日志趋势、按服务/主机统计日志、近 N 分钟日志、夜莺/n9e/ES 日志检索”时使用本技能。本技能只用于日志数据查询与统计可视化，不用于告警查询（real-alarm）、CMDB 查询（zgops-cmdb）或一般技术问答。
---

# Nightingale Log（夜莺日志查询）

为夜莺监控（n9e）后端的 ElasticSearch 日志查询提供最短执行路径。覆盖：日志列表检索、关键字搜索、按级别 / 主机 / 服务的分布统计、时间直方图、原始命中导出。

## 前置配置（给 Agent）

使用本技能前，确认本技能目录下存在 `.env` 并填好以下字段：

```bash
# 夜莺前端地址（不带末尾斜杠）
N9E_API_BASE_URL=http://<host>:<port>

# 个人中心 -> Token 管理 创建出的 X-User-Token
N9E_USER_TOKEN=your_user_token_here

# 默认日志数据源 ID（在夜莺 “数据查询 -> 日志” 页面看到的 ES 数据源 ID）
# 示例页面 URL：/api/n9e/proxy/1/_msearch 表示数据源 ID = 1
N9E_LOG_DATASOURCE_ID=1

# 默认日志索引模式（可用通配符），例如 logstash-*、filebeat-*、app-logs-*
N9E_LOG_INDEX=*

# 默认时间字段（ES @timestamp 字段名），未指定时使用 @timestamp
N9E_LOG_TIMESTAMP_FIELD=@timestamp
```

**配置加载优先级**：

1. 本 skill 目录下的 `.env`（优先）
2. 项目根目录下的 `.env`（备选）

如果配置缺失或 token 无效，技能会直接返回配置错误信息，不会继续执行请求。

## 触发条件（给 Agent）

当用户提到以下诉求时，优先使用本技能：

- 查日志 / 日志列表 / 最近日志 / 显示日志
- 错误日志 / 异常日志 / 严重日志 / WARN / ERROR
- 关键字搜索日志（包含 xxx、含 xxx 的日志）
- 日志按级别 / 主机 / 服务 / 应用 / 容器 分布或排行
- 日志趋势 / 日志时间分布 / 每分钟日志数
- 某主机 / IP / 服务 / 容器 / pod 的日志
- 近 N 分钟 / 小时 / 天的日志

若用户问题明显不是日志检索（例如告警、CMDB、监控指标），不要使用本技能。

## 配置与最短路径（给 Agent）

- 元数据查询：`uv run scripts/n9e_log_meta.py --mode <datasources|indices|mapping|fields> [...]`
- 日志检索：`uv run scripts/n9e_log_query.py [--query <lucene>] [--from-time now-15m] [...]`
- 聚合统计：`uv run scripts/n9e_log_aggregate.py --mode <count|level|host|service|terms|histogram> [...]`
- 默认读取本技能目录下的 `.env`
- 不要要求用户手动拼接 `_msearch` URL 或写完整 ES DSL
- 不要先做无意义的 ping / 健康检查；直接执行真实查询
- 缺配置或 token 无效时，停止后续分析，直接返回缺失项或错误原因

## 时间范围约定

`--from-time` / `--to-time` 同时支持：

- ISO 时间：`2026-05-06T08:00:00`、`2026-05-06 08:00:00`
- 相对时间：`now`、`now-15m`、`now-1h`、`now-6h`、`now-1d`、`now-7d`
- 默认：`from-time=now-15m`，`to-time=now`

如果用户没说时间范围，默认查最近 15 分钟。如果用户说“最近 N 分钟 / 小时 / 天”，转换为对应的 `now-N(m|h|d)`。

## 主流程（给 Agent）

### 1. 先判断查询类型

- **看几条日志 / 简单列表 / 最新日志**：直接 `n9e_log_query.py`，size 默认 20
- **关键字 / 报错 / 异常**：用 `n9e_log_query.py --query "..."`
- **统计 / 分布 / 排行 / 趋势**：优先 `n9e_log_aggregate.py`
- **不知道索引或字段**：先 `n9e_log_meta.py`

### 2. 默认执行策略

#### 场景 A：简单看日志

```bash
uv run scripts/n9e_log_query.py --from-time now-15m --size 20 --output markdown
```

#### 场景 B：关键字 / 错误日志检索

```bash
uv run scripts/n9e_log_query.py \
  --query 'level:ERROR OR level:WARN' \
  --from-time now-1h --size 50 --output markdown

uv run scripts/n9e_log_query.py \
  --query 'message:"connection refused"' \
  --from-time now-1h --output markdown
```

#### 场景 C：按主机 / 服务 / 级别分布

```bash
uv run scripts/n9e_log_aggregate.py --mode level --from-time now-1h --output markdown
uv run scripts/n9e_log_aggregate.py --mode host  --from-time now-1h --output markdown
uv run scripts/n9e_log_aggregate.py --mode service --from-time now-1h --output markdown
uv run scripts/n9e_log_aggregate.py --mode terms --field log.level --top 10 --output markdown
```

#### 场景 D：日志趋势（时间直方图）

```bash
uv run scripts/n9e_log_aggregate.py --mode histogram --interval 1m --from-time now-1h --output markdown
uv run scripts/n9e_log_aggregate.py --mode histogram --interval 5m --from-time now-6h \
  --query 'level:ERROR' --output markdown
```

#### 场景 E：按主机或服务过滤

```bash
uv run scripts/n9e_log_query.py --query 'host.name:"web-01"' --from-time now-1h
uv run scripts/n9e_log_query.py --query 'service:nginx AND level:ERROR' --from-time now-30m
```

#### 场景 F：探索数据源 / 索引 / 字段

```bash
uv run scripts/n9e_log_meta.py --mode datasources                   # 列出所有日志数据源
uv run scripts/n9e_log_meta.py --mode indices                       # 列出当前数据源的索引
uv run scripts/n9e_log_meta.py --mode mapping --index logstash-*    # 查看索引 mapping
uv run scripts/n9e_log_meta.py --mode fields  --index logstash-*    # 列出可用字段（精简）
```

### 3. 数据处理默认规则

- **任务式列表**：默认只展示 `时间`、`级别`、`主机`、`服务`、`message 摘要` 等关键字段，不要原样塞出整段 JSON
- **统计 / 分布**：先聚合再展示表格或图表
- **关键字检索**：高亮命中关键字到摘要前 200 字符
- **超过 size 上限**：默认每次最多 500 条；统计场景由聚合替代逐条拉取
- **未指定字段**：使用 `--fields` 默认展示
- **结果过多**：聊天窗口默认只展示前 20 条，并说明命中总数

## 用户意图 → 推荐动作

**基础检索**：
- “最近的日志” / “显示最近日志” / “看一下日志” → `n9e_log_query.py --from-time now-15m --size 20 --output markdown`
- “最近 1 小时日志” → `n9e_log_query.py --from-time now-1h --size 30 --output markdown`
- “近 24 小时日志” → `n9e_log_query.py --from-time now-1d --size 50 --output markdown`

**关键字 / 错误检索**：
- “错误日志” / “ERROR 日志” / “报错日志” → `n9e_log_query.py --query 'level:ERROR' --from-time now-1h`
- “异常日志” / “Exception 日志” → `n9e_log_query.py --query 'message:Exception OR message:Traceback' --from-time now-1h`
- “包含 xxx 的日志” → `n9e_log_query.py --query 'message:"xxx"' --from-time now-1h`
- “xxx 服务的报错” → `n9e_log_query.py --query 'service:"xxx" AND level:ERROR' --from-time now-1h`
- “xxx 主机的日志” → `n9e_log_query.py --query 'host.name:"xxx"' --from-time now-1h`

**统计 / 分布类**：
- “按级别统计日志” / “日志级别分布” → `n9e_log_aggregate.py --mode level --from-time now-1h --output markdown`
- “哪些主机日志最多” / “主机日志排行” → `n9e_log_aggregate.py --mode host --from-time now-1h --output markdown`
- “按服务统计日志” / “服务日志分布” → `n9e_log_aggregate.py --mode service --from-time now-1h --output markdown`
- “按 X 字段分组统计” → `n9e_log_aggregate.py --mode terms --field <X> --from-time now-1h --output markdown`

**趋势类**：
- “日志趋势” / “每分钟日志量” / “日志数变化” → `n9e_log_aggregate.py --mode histogram --interval 1m --from-time now-1h --output markdown`
- “错误日志趋势” → `n9e_log_aggregate.py --mode histogram --interval 5m --from-time now-6h --query 'level:ERROR' --output markdown`

**计数类**：
- “一共多少条日志” / “日志总数” → `n9e_log_aggregate.py --mode count --from-time now-1h`
- “最近一小时多少条错误日志” → `n9e_log_aggregate.py --mode count --query 'level:ERROR' --from-time now-1h`

**元数据探索**：
- “有哪些日志数据源” → `n9e_log_meta.py --mode datasources`
- “有哪些索引” / “索引列表” → `n9e_log_meta.py --mode indices`
- “日志有哪些字段” / “这个索引的字段” → `n9e_log_meta.py --mode fields --index <idx>`

## 输出约定

- 默认输出适合聊天窗口直接展示的 Markdown
- 调用 `n9e_log_query.py` / `n9e_log_aggregate.py` 时优先附带 `--output markdown`
- `markdown` 输出会自动附带 ECharts 代码块（分布 / 趋势场景）
- `markdown-echarts-only` 只输出 ECharts 代码块，适合前端只消费图表
- 列表查询：先 1 句摘要（命中数 / 时间范围），再表格
- 统计查询：先 1~3 句结论，再表格或图表
- 趋势查询：先趋势结论，再 ECharts 折线图
- 不要只把命令贴给用户去执行
- `level` 优先环形图，`host` / `service` 优先柱状图，`histogram` 优先折线图

## 错误处理规则

- **缺少 `N9E_API_BASE_URL` / `N9E_USER_TOKEN`**：直接提示配置缺失，不继续请求
- **401 / 403**：提示 token 无效 / 权限不足，建议更新 `.env` 或重新生成 Token
- **404**：提示数据源 ID / 索引名错误，建议先跑 `n9e_log_meta.py --mode datasources` 确认
- **400（ES query parse error）**：提示查询语法可能写错，建议简化或改用 `--query-mode lucene` / 检查字段名
- **408 / 超时**：提示网络或 ES 响应慢，可缩小时间范围或加 `--size` 限制
- **空命中**：明确说“未命中日志”，并提示尝试放宽时间范围或换关键字
- **集群只读 / shards failed**：原样透出 ES 失败原因前 300 字符，不要假装是完整结果

## 何时读取参考文档

- 用户问查询语法、KQL/Lucene 写法时 → `references/query-syntax.md`
- 用户问接口、鉴权、`_msearch` 协议时 → `references/api-specification.md`
- 用户问典型场景或问法时 → `references/usage-scenarios.md`

默认不主动加载全部参考文档；只在需要解释细节时再读。

## Few-shot 示例

### 示例 1：看一下最近的日志

- 用户：看一下最近 15 分钟的日志
- 动作：`uv run scripts/n9e_log_query.py --from-time now-15m --size 20 --output markdown`
- 回复：先给 1 句摘要（命中总数 / 时间窗），再表格列出 时间、级别、主机、服务、message 摘要

### 示例 2：错误日志统计

- 用户：最近 1 小时各级别日志多少条
- 动作：`uv run scripts/n9e_log_aggregate.py --mode level --from-time now-1h --output markdown`
- 回复：先给结论（哪个级别最多），再表格 + ECharts 环形图

### 示例 3：错误日志趋势

- 用户：最近 6 小时错误日志的趋势
- 动作：`uv run scripts/n9e_log_aggregate.py --mode histogram --interval 5m --from-time now-6h --query 'level:ERROR' --output markdown`
- 回复：先给峰值时段结论，再表格 + ECharts 折线图

### 示例 4：关键字搜索

- 用户：查一下日志里包含 connection refused 的
- 动作：`uv run scripts/n9e_log_query.py --query 'message:"connection refused"' --from-time now-1h --output markdown`
- 回复：说明命中数量，然后表格展示 时间 / 主机 / 服务 / message 摘要；超过 20 条只展示前 20 条

### 示例 5：探索字段

- 用户：当前日志数据源里有哪些字段可以用
- 动作：`uv run scripts/n9e_log_meta.py --mode fields --output markdown`
- 回复：表格输出 字段名 / 类型 / 是否常用，并提示常用字段如何写到 `--query`

## 注意事项

- Token 应只放在本地环境变量或 `.env` 中，不在对话中回显
- 时间范围越大，ES 压力越大；统计 / 分布场景优先用聚合接口而非全量拉取
- 字段名以实际索引 mapping 为准；常见 ECS 字段：`@timestamp`、`message`、`log.level`、`host.name`、`service.name`、`container.name`、`kubernetes.pod.name`
- 不同环境的级别字段名可能不同：`level` / `log.level` / `severity`，本技能聚合时会自动尝试常见字段
- 这是“查询”能力，不做修复 / 配置 / 写入；后续“隐患识别”“日志安全”能力会作为高价值场景独立扩展，不在本技能范围内
