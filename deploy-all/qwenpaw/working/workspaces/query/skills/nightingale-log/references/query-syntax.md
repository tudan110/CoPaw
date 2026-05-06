# 夜莺日志查询语法（Lucene query_string）

夜莺日志页面同时支持 KQL 和 Lucene 两种语法，本技能默认走 Lucene
（`query_string`），原因是它能直接传给 ES 而无需做语法转译。

## 基本结构

- `字段:值` —— 精确匹配（含分词）：`level:ERROR`
- `字段:"短语"` —— 短语匹配：`message:"connection refused"`
- 多条件组合：`AND` / `OR` / `NOT`、括号分组
- 通配符：`*`、`?`，例如 `service:web-*`
- 范围：`status:[400 TO 599]`、`@timestamp:[2026-05-01 TO 2026-05-06]`
- 字段不写时，默认对所有 _all / `message` 类字段做全文检索

## 常见日志查询例子

```text
# 错误日志
level:ERROR

# 错误或警告
level:ERROR OR level:WARN

# 指定服务的错误
service:nginx AND level:ERROR

# 报错关键字
message:"Exception" OR message:"Traceback"

# HTTP 4xx / 5xx
http.response.status_code:[400 TO 599]

# 排除某些噪声
message:* AND NOT message:"healthcheck"

# 某主机的最近日志
host.name:"web-01"

# Kubernetes 场景
kubernetes.namespace_name:prod AND kubernetes.pod.name:web-*

# 多个关键字
message:(timeout OR refused OR unreachable)
```

## 字段名怎么找

不同采集链路（Filebeat / Fluentd / Vector / Logstash / 自研采集器）会写入不同
字段名。先用本技能的 meta 工具：

```bash
uv run scripts/n9e_log_meta.py --mode fields --output markdown
```

输出会标记常用字段（带 ✓），优先用它们写查询。

## 聚合时的字段选择

ES 的 terms 聚合通常需要 keyword 子字段（例如 `service.name.keyword`），
本技能的 `n9e_log_aggregate.py` 会自动尝试 `xxx.keyword` 与裸字段两种形式，
所以你只需要传 `--field service.name`。

## KQL（备用）

夜莺前端原生支持 KQL（Kibana Query Language），写法接近自然语言：
`level: ERROR and service: "nginx"`。如果用户给的是 KQL 表达式，也可以直接写到
`--query` 里——大部分 KQL 表达式恰好也是合法的 Lucene。差异点：

- KQL 用小写 `and / or / not`，Lucene 大写
- KQL 区间 `field >= 100`，Lucene 用 `field:[100 TO *]`
- KQL 的精确字符串自动 `match_phrase`，Lucene 需要加引号

如果遇到 ES 报 `parse_exception`，把表达式转成纯 Lucene 即可。
