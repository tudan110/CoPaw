# 典型问法 → 命令映射

## 综合（默认入口）

| 用户问法 | 推荐命令 |
|---------|---------|
| 看下最近 15 分钟日志里有没有什么异常模式 | `n9e_log_hazard.py --output markdown` |
| 最近 1 小时日志综合分析 | `n9e_log_hazard.py --from-time now-1h --output markdown` |
| 最近日志有什么隐患 | `n9e_log_hazard.py --output markdown` |
| 跟昨天比，最近 1 小时多出哪些日志模式 | `n9e_log_hazard.py --from-time now-1h --baseline 24h --output markdown` |

## 单窗口聚类

| 用户问法 | 推荐命令 |
|---------|---------|
| 最近 15 分钟日志聚一聚 | `n9e_log_cluster.py --from-time now-15m --output markdown` |
| 错误日志聚类 | `n9e_log_cluster.py --query 'level:ERROR OR message:Exception OR message:failed' --from-time now-1h --output markdown` |
| 哪些日志模板命中最多 | `n9e_log_cluster.py --top 20 --output markdown` |
| 把 nginx 日志聚类一下 | `n9e_log_cluster.py --query 'service.name:nginx OR fcservice:nginx' --from-time now-1h --output markdown` |
| 某主机最近 1 小时日志聚类 | `n9e_log_cluster.py --query 'host.name:web-01 OR agent_hostname:web-01' --from-time now-1h --output markdown` |

## 漂移分析

| 用户问法 | 推荐命令 |
|---------|---------|
| 跟昨天比多出哪些新模板 | `n9e_log_drift.py --baseline 24h --output markdown` |
| 跟上周同期比 | `n9e_log_drift.py --baseline 7d --from-time now-1h --output markdown` |
| 模板漂移分析 | `n9e_log_drift.py --baseline 24h --output markdown` |
| 突增的报错模板 | `n9e_log_drift.py --baseline 24h --query 'level:ERROR' --output markdown` |
| 自定义对比窗口（早 8~9 vs 昨天早 8~9） | `n9e_log_drift.py --baseline custom --from-time 'YYYY-MM-DDT08:00:00' --to-time 'YYYY-MM-DDT09:00:00' --baseline-from-time 'YYYY-MM-DDT08:00:00' --baseline-to-time 'YYYY-MM-DDT09:00:00'` |

## 按结果聚焦

如果用户只关心一个维度：

| 关注点 | 入口 | 报告中关注哪段 |
|--------|------|---------|
| “什么是高频模板” | `n9e_log_hazard.py` | 第 1 段：模板 Top |
| “哪些模板里报错多” | `n9e_log_hazard.py` | 第 2 段：错误密集模板 |
| “有没有奇怪的偶发日志” | `n9e_log_hazard.py` | 第 3 段：稀有模板 |
| “跟历史比变化在哪” | `n9e_log_hazard.py` 或 `n9e_log_drift.py` | 第 4 段 / 三段表 |

## 不在本技能范围（指引到对应 skill）

| 用户问法 | 应该走 |
|---------|------|
| 看一下最近的日志 / 查日志 / 错误日志列表 | `nightingale-log` |
| 日志里有没有密码 / token / AK SK / 手机号 / 身份证 | `log-security-scan` |
| SQL 注入痕迹 / 日志合规扫描 | `log-security-scan` |
| 这条告警怎么处置 / 故障根因 | `fault` |
| CMDB 资源 / 数据库状态 | `zgops-cmdb` / `resource-insight-query` |
