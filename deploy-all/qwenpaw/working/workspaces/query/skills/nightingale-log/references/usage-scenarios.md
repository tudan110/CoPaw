# 智观日志查询常见场景

## 1. 看一下最近发生了什么

- 用户问法："看下最新日志" / "最近 15 分钟日志"
- 命令：

```bash
uv run scripts/n9e_log_query.py --from-time now-15m --size 20 --output markdown
```

- 输出建议：先 1 句摘要（命中 N 条），再表格

## 2. 排错：找最近的错误日志

- 用户问法："最近的报错" / "ERROR 日志"
- 命令：

```bash
uv run scripts/n9e_log_query.py --query 'level:ERROR' --from-time now-1h --output markdown
```

- 如果命中很多，自然衔接到下一步 "按服务统计"

## 3. 关键字检索

- 用户问法："包含 connection refused 的日志"
- 命令：

```bash
uv run scripts/n9e_log_query.py --query 'message:"connection refused"' --from-time now-1h
```

- 注意短语必须加引号；只把关键字段（时间/主机/服务/摘要）展示给用户

## 4. 按级别 / 主机 / 服务做分布

- 用户问法："最近 1 小时各级别日志多少条"
- 命令：

```bash
uv run scripts/n9e_log_aggregate.py --mode level --from-time now-1h --output markdown
```

- 输出：环形图 + 表格，先给 1 句结论（哪个级别最多）

- 用户问法："哪些主机日志最多"
- 命令：

```bash
uv run scripts/n9e_log_aggregate.py --mode host --from-time now-1h --top 10 --output markdown
```

## 5. 错误日志的时间趋势

- 用户问法："最近 6 小时错误日志的趋势"
- 命令：

```bash
uv run scripts/n9e_log_aggregate.py --mode histogram --interval 5m --from-time now-6h \
  --query 'level:ERROR' --output markdown
```

- 输出：折线图 + 峰值时段说明

## 6. 计数（不要表格）

- 用户问法："一共多少条错误日志" / "现在有多少日志"
- 命令：

```bash
uv run scripts/n9e_log_aggregate.py --mode count --query 'level:ERROR' --from-time now-1h
```

- 直接把 `total` 报出来即可

## 7. 探索：不知道字段叫什么

- 用户问法："这套日志有哪些字段" / "我能按什么过滤"
- 命令：

```bash
uv run scripts/n9e_log_meta.py --mode fields --output markdown
```

- 在结果里挑常用字段（标 ✓ 的），再回到场景 1~6

## 8. 探索：不知道有哪些索引 / 数据源

- 数据源：`n9e_log_meta.py --mode datasources`
- 索引：`n9e_log_meta.py --mode indices`

## 不在本技能职责内的场景

- 告警查询 → `real-alarm`
- CMDB / 资源数 / 拓扑 → `zgops-cmdb`
- 监控驾驶舱 → `monitoring-overview-query`
- 资源性能 / 数据库性能 Top → `resource-insight-query`
- 隐患识别（基于日志的根因推断） → 后续独立的 `log-hazard-detection`（待建）
- 日志安全（敏感信息识别） → 后续独立的 `log-security-scan`（待建）
