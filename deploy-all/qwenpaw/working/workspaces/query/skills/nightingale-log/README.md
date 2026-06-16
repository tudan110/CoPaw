# nightingale-log

夜莺监控（Nightingale / n9e）日志查询技能。把传统系统里 `数据查询 -> 日志`
页面背后的能力暴露给 query 智能体。

## 目录结构

```
nightingale-log/
├── SKILL.md                       # 给 agent 看的最短路径与触发条件
├── README.md                      # 给开发者看的（本文件）
├── .env.example                   # 配置模板
├── scripts/
│   ├── _n9e_client.py             # 共享：env 加载 / 时间解析 / HTTP / DSL
│   ├── n9e_log_meta.py            # 元数据：数据源 / 索引 / mapping / 字段
│   ├── n9e_log_query.py           # 命中检索（hits）
│   ├── n9e_log_aggregate.py       # 聚合：count / level / host / service / terms / histogram
│   └── pyproject.toml             # uv run 用
└── references/
    ├── api-specification.md       # n9e ES 代理接口契约
    ├── query-syntax.md            # Lucene query_string 速查
    └── usage-scenarios.md         # 用户问法 → 命令映射
```

## 配置

复制 `.env.example` 为 `.env` 并填入：

- `N9E_API_BASE_URL`：夜莺前端地址，如 `http://82.156.83.38:17001`
- `N9E_USER_TOKEN`：在夜莺「个人中心 -> Token 管理」创建
- `N9E_LOG_DATASOURCE_ID`：默认日志 ES 数据源 ID（页面 URL 里的那个数字）
- `N9E_LOG_INDEX`：默认索引模式（最好显式指定）

## 快速验证

```bash
cd <skill_dir>
uv run scripts/n9e_log_meta.py --mode datasources
uv run scripts/n9e_log_meta.py --mode indices
uv run scripts/n9e_log_query.py --from-time now-15m --size 5 --output markdown
uv run scripts/n9e_log_aggregate.py --mode level --from-time now-1h --output markdown
```

## 后续扩展（不在本技能内）

- 隐患识别：基于日志聚类 / 异常检测做高频错误根因推断 →
  规划为独立的 `log-hazard-detection` 技能
- 日志安全：扫描日志中是否打印了敏感信息（手机号、身份证、token、SQL 等）→
  规划为独立的 `log-security-scan` 技能

把这两块单独拆为新技能可以独立迭代而不污染本技能的查询职责。
