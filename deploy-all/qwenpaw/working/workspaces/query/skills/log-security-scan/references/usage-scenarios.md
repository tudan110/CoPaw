# 典型问法 → 命令映射

## 通用扫描

| 用户问法 | 推荐命令 |
|---------|---------|
| 扫一下日志里有没有敏感信息 | `n9e_log_secscan.py --from-time now-15m --output markdown` |
| 最近 1 小时日志合规扫描 | `n9e_log_secscan.py --from-time now-1h --output markdown` |
| 做一次日志安全审计 | `n9e_log_secscan.py --from-time now-1d --output markdown` |
| 只看高风险 | `n9e_log_secscan.py --severity-min high --from-time now-1h` |
| 只看 critical 项 | `n9e_log_secscan.py --severity-min critical --from-time now-1d` |

## 类目专扫

| 用户问法 | 推荐命令 |
|---------|---------|
| 日志里有没有 token 泄露 | `n9e_log_secscan.py --severity-min high --from-time now-1h`（关注 secret-bearer-token / secret-jwt） |
| 日志里有没有 AK SK | `n9e_log_secscan.py --severity-min critical --from-time now-1d`（关注 secret-aws-* / secret-aliyun-ak） |
| 日志里有没有密码 | `n9e_log_secscan.py --severity-min high`（关注 secret-password-kv） |
| 日志里有没有手机号 | `n9e_log_secscan.py --severity-min medium`（关注 pii-mobile-cn，注意误报） |
| 日志里有没有身份证 | `n9e_log_secscan.py --severity-min high`（关注 pii-id-cn） |
| 日志里有没有银行卡 | `n9e_log_secscan.py --severity-min high`（关注 pii-bankcard，已 Luhn 校验） |
| 日志里有没有 SQL 注入痕迹 | `n9e_log_secscan.py --severity-min high`（关注 injection-sql-union） |
| 日志里有没有私钥 | `n9e_log_secscan.py --severity-min critical`（关注 secret-private-key） |

## 范围预过滤

| 用户问法 | 推荐命令 |
|---------|---------|
| xxx 服务里有没有 token 泄露 | `n9e_log_secscan.py --query 'service.name:xxx OR fcservice:xxx' --severity-min high` |
| 某主机日志安全扫描 | `n9e_log_secscan.py --query 'host.name:web-01 OR agent_hostname:web-01' --from-time now-1h` |
| 某索引的扫描 | `n9e_log_secscan.py --index app-logs-* --from-time now-1h` |

## 规则管理

| 用户问法 | 推荐命令 |
|---------|---------|
| 都有哪些规则 | `n9e_log_secrules.py --mode list` |
| 解释一下 secret-aws-ak | `n9e_log_secrules.py --mode explain --rule-id secret-aws-ak` |
| 自检规则 | `n9e_log_secrules.py --mode test --rule-id pii-bankcard` |
| 测一段文本会不会被识别 | `n9e_log_secrules.py --mode test --rule-id secret-bearer-token --text '...'` |
| 我想加一条规则 | 指引用户在 `references/security_rules.yml` 加一条，再 test |

## 不在本技能范围（指引到对应 skill）

| 用户问法 | 应该走 |
|---------|------|
| 看一下最近的日志 / 查日志 / 错误日志 | `nightingale-log` |
| 日志聚类 / 模板挖掘 / 异常模式 | `log-hazard-detection` |
| 这条告警怎么处置 / 故障根因 | `fault` |
| CMDB 资源 / 数据库状态 | `zgops-cmdb` / `resource-insight-query` |
