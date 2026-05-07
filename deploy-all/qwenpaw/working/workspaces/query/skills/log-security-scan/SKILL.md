---
name: log-security-scan
category: log
tags: [log, security, sensitive-info, secrets, pii, sql-injection, n9e, elasticsearch, compliance]
triggers: [日志安全扫描, 日志敏感信息, 日志泄露, 日志中密码, 日志中token, 日志中身份证, 日志中手机号, 日志中AK, 日志中SK, 日志中API key, 日志合规扫描, 敏感信息识别, 敏感词扫描, 数据泄露扫描, SQL注入征兆, SQL注入扫描, 隐私扫描, PII扫描, secret leak, log security, 合规检查, 安全审计日志]
description: 基于规则库的日志敏感信息与攻击征兆扫描。覆盖密码 / token / API key / AK·SK / 身份证 / 手机号 / 银行卡 / SQL 注入征兆等核心类目，对夜莺业务日志做正则匹配，每条命中按规则分类聚合（命中数、典型样例脱敏后展示、涉及主机/服务/索引），并按 severity（critical/high/medium）打分排序。当用户提到“日志里有没有敏感信息/密码/token/身份证/手机号/AK SK 泄露 / SQL 注入痕迹/合规扫描/数据泄露”等诉求时**必须使用本技能**。规则集默认保守（宁少不滥），用户可在 `references/security_rules.yml` 增删；本技能不做模板挖掘（那是 log-hazard-detection），也不做关键字检索（那是 nightingale-log）。
---

# Log Security Scan（日志敏感信息与攻击征兆扫描）

为夜莺监控（n9e）业务日志做规则化扫描，回答 “最近的业务日志里有没有泄露敏感信息 / 注入征兆 / 合规风险”。

底层是一组在 `references/security_rules.yml` 里手写、可热更新的正则规则；每条规则带 severity（critical / high / medium）、category（secret / pii / injection / crypto）、redact 模式（full / tail / hash）和可选的 post_filter（如 Luhn 校验过滤银行卡误报）。

## 前置配置（给 Agent）

使用本技能前，确认本技能目录下存在 `.env` 并填好以下字段（与 nightingale-log 同源）：

```bash
N9E_API_BASE_URL=http://<host>:<port>
N9E_USER_TOKEN=your_user_token_here
N9E_LOG_DATASOURCE_ID=1
N9E_LOG_INDEX=casaos-syslog-*
N9E_LOG_TIMESTAMP_FIELD=@timestamp
N9E_LOG_MAX_SIZE=10000      # 扫描需要更大拉取上限
N9E_LOG_TIMEOUT=60
```

可选：`SECURITY_RULES_FILE` 指定自定义规则文件；`SECURITY_SCAN_MAX_DOCS` 加硬上限。

如果配置缺失或 token 无效，技能会直接返回配置错误信息，不会继续执行请求。

## 触发条件（给 Agent）

当用户提到以下诉求时，**必须**使用本技能：

- 日志安全扫描 / 日志合规扫描 / 日志审计
- 日志里有没有：密码 / token / API key / API token / Bearer / JWT
- 日志里有没有：AK / SK / Access Key / Secret Key / 阿里云 LTAI
- 日志里有没有：身份证 / 手机号 / 银行卡 / 身份证号 / 个人信息 / PII
- 日志里有没有：私钥 / PEM / RSA Private Key
- SQL 注入痕迹 / SQL injection / UNION SELECT / OR 1=1
- 数据泄露扫描 / 敏感信息识别 / 隐私扫描

**关键澄清**：

- 本技能查询的是夜莺接入的**业务/应用/系统日志**（生产线上日志），不是 QwenPaw 智能体自身运行日志、控制台 stdout
- 本技能不做关键字检索（“查日志/看日志”请用 `nightingale-log`）
- 本技能不做模板挖掘 / 漂移分析（“日志聚类/隐患识别”请用 `log-hazard-detection`）
- 本技能不做单条告警根因（“这条告警怎么处置”请走 `fault`）
- **命中样例必经脱敏**——展示给用户的 match 字符串永远是 `***len{N}***` / `首2位***末2位` / `sha256:xxxxx` 形式，绝不展示原始密钥/PII

## 配置与最短路径（给 Agent）

- 一站式扫描：`uv run scripts/n9e_log_secscan.py [--from-time now-15m] [--severity-min medium]`
- 规则一览：`uv run scripts/n9e_log_secrules.py --mode list`
- 单规则详解：`uv run scripts/n9e_log_secrules.py --mode explain --rule-id <id>`
- 规则自检 / 试跑：`uv run scripts/n9e_log_secrules.py --mode test --rule-id <id> [--text '...']`

## 时间范围约定

`--from-time` / `--to-time` 同时支持：

- ISO 时间：`2026-05-06T08:00:00`
- 相对时间：`now`、`now-15m`、`now-1h`、`now-6h`、`now-1d`、`now-7d`
- 默认：`from-time=now-15m`，`to-time=now`

如果用户没说时间范围，默认查最近 15 分钟。

## 主流程（给 Agent）

### 1. 默认扫描

```bash
uv run scripts/n9e_log_secscan.py --from-time now-15m --output markdown
```

输出包含：
1. 总览（命中规则数、总命中数、按 severity 分布）
2. 命中明细（按 severity → hit_count 排序的规则表，含主机/服务 Top）
3. 命中样例（每条规则若干条**脱敏后**的上下文）
4. ECharts severity 饼图 + 规则命中柱图

### 2. 按 severity 缩窄

```bash
# 只关心 high 及以上
uv run scripts/n9e_log_secscan.py --severity-min high --from-time now-1h

# 只关心 critical
uv run scripts/n9e_log_secscan.py --severity-min critical --from-time now-1d
```

### 3. 大窗口扫描

```bash
uv run scripts/n9e_log_secscan.py --from-time now-1d --max-docs 8000 --output markdown
```

当 `total_docs > max_docs * 4` 时自动从 `tail` 降级为 `random_score` 抽样，并在报告里标注。

### 4. 规则管理

```bash
# 看规则一览（按 severity 排序）
uv run scripts/n9e_log_secrules.py --mode list

# 看一条规则的 pattern 与样例
uv run scripts/n9e_log_secrules.py --mode explain --rule-id secret-aws-ak

# 用规则自带 examples 自检
uv run scripts/n9e_log_secrules.py --mode test --rule-id pii-bankcard

# 用自定义文本试规则
uv run scripts/n9e_log_secrules.py --mode test --rule-id secret-aws-ak \
  --text 'foo AKIAIOSFODNN7EXAMPLE bar'
```

### 5. 自定义规则集

把 `references/security_rules.yml` 复制到自己的位置改完，再用 `--rules-file` 或 `SECURITY_RULES_FILE` 环境变量指过去。规则文件里：

- `version` / `defaults{context_chars, redact_keep}` / `rules[...]`
- 单条规则字段：`id` / `name` / `severity` / `category` / `pattern` / `flags` / `description` / `redact` / `post_filter` / `examples`
- 单条 pattern 编译失败 → skip + warn，**不会让整个扫描挂掉**
- 修改后下一次扫描即生效，不需要重启 portal

## 用户意图 → 推荐动作

**通用扫描**：
- “扫一下日志里有没有敏感信息” → `n9e_log_secscan.py --from-time now-15m --output markdown`
- “最近 1 小时日志合规扫描” → `n9e_log_secscan.py --from-time now-1h --output markdown`
- “只看高风险” → `n9e_log_secscan.py --severity-min high --from-time now-1h`

**目标性扫描**（用 `--query` 预过滤）：
- “xxx 服务里有没有 token 泄露” → `n9e_log_secscan.py --query 'service.name:xxx OR fcservice:xxx' --from-time now-1h`
- “某主机的日志安全扫描” → `n9e_log_secscan.py --query 'host.name:web-01 OR agent_hostname:web-01' --from-time now-1h`

**规则查询**：
- “都有哪些规则” → `n9e_log_secrules.py --mode list`
- “解释一下 xxx 规则” → `n9e_log_secrules.py --mode explain --rule-id <id>`
- “这个 token 会不会被识别” → `n9e_log_secrules.py --mode test --rule-id secret-bearer-token --text '...'`

**SQL 注入专项**：
- “最近有没有 SQL 注入痕迹” → `n9e_log_secscan.py --severity-min high --from-time now-1d --query 'message:union OR message:OR OR message:select'`
- 也可以直接默认扫描，`injection-sql-union` 是自带的 high 规则

## 输出约定

- 默认输出适合聊天窗口直接展示的 Markdown
- 命中样例**永远**脱敏后展示；不要在对话里二次展示原始 message
- `markdown` 输出会自动附带 ECharts 代码块（severity 饼图、规则命中柱图）
- `markdown-echarts-only` 只输出 ECharts，适合前端只消费图表
- 报告先给结论：命中规则数、总命中数、最严重的 1~3 条规则
- 不要只把命令贴给用户去执行
- 0 命中也要明确说明 “未命中任何规则”，并提示 “可调低 --severity-min / 放宽时间范围”

## 错误处理规则

- **缺少 `N9E_API_BASE_URL` / `N9E_USER_TOKEN`**：直接提示配置缺失
- **PyYAML 未安装**：报错提示用 `uv run` 跑（PEP 723 内联依赖）
- **规则文件不存在**：返回 400 并展示期待路径
- **单条规则 pattern 编译失败**：跳过该条 + warn 在报告顶部，其它规则正常
- **401 / 403**：提示 token 无效 / 权限不足
- **空命中**：明确说 “未命中任何规则”，并提示放宽 `--from-time` / 调低 `--severity-min`

## 何时读取参考文档

- 用户问规则原理 / 脱敏算法 / 误报排查 → `references/redaction.md`
- 用户问典型场景或问法 → `references/usage-scenarios.md`
- 用户问规则字段 / 写法 → `references/security_rules.yml`（规则源文件本身就是文档）

默认不主动加载全部参考文档；只在需要解释细节时再读。

## Few-shot 示例

### 示例 1：日常扫描

- 用户：扫一下最近 15 分钟日志里有没有敏感信息
- 动作：`uv run scripts/n9e_log_secscan.py --from-time now-15m --output markdown`
- 回复：先 1~2 句结论（命中规则数 + 最严重的 1~2 条），再总览 + 明细表 + 脱敏样例

### 示例 2：高危项专扫

- 用户：检查一下日志里有没有 AK SK 泄露
- 动作：`uv run scripts/n9e_log_secscan.py --severity-min critical --from-time now-1d --output markdown`
- 回复：聚焦 secret-aws-ak / secret-aws-sk / secret-aliyun-ak / secret-private-key 命中

### 示例 3：规则一览

- 用户：都有哪些规则
- 动作：`uv run scripts/n9e_log_secrules.py --mode list`
- 回复：直接展示规则表

### 示例 4：测一条规则

- 用户：这一段 `Authorization: Bearer eyJ...` 会不会被识别
- 动作：`uv run scripts/n9e_log_secrules.py --mode test --rule-id secret-bearer-token --text 'Authorization: Bearer eyJabc...'`
- 回复：展示命中数 + 脱敏 match + context

### 示例 5：用户加规则

- 用户：我想加一条规则识别 GitHub PAT
- 回复：指引在 `references/security_rules.yml` 加一条（给字段格式 + 示例 pattern `\bghp_[A-Za-z0-9]{36}\b`），然后 `uv run scripts/n9e_log_secrules.py --mode test --rule-id <new-id>` 自检

## 注意事项

- **命中样例永远脱敏**——这是硬约束。即便用户说 “给我看原文”，也要明确拒绝（建议用户改用 nightingale-log 的关键字检索按权限自查 ES）
- Token 应只放在本地环境变量或 `.env` 中，不在对话中回显
- `pii-mobile-cn` 默认 medium——容器/订单 ID 误判重灾区，不要把它当 critical 看
- `pii-bankcard` 已内置 Luhn 校验，但仍可能误判长数字串（订单号、时间戳）
- `_n9e_client.py` 是 nightingale-log 的物理拷贝；上游修复 / 升级时，本技能与 log-hazard-detection 都要同步
- 这是 “扫描” 能力，不做处置/修复；找到泄露后，建议结合 `nightingale-log` 反查具体上下文，再走对应工单流程
