# resource-insight-query

query 数字员工的资源状态与性能查询技能。

## 已支持

- 数据库状态总览：`/resource/database/resource/status/overview`
- 页面性能 Top：`/resource/pm/TopMetricDataNew`
- 资源性能 Top：`/resource/resource/performance/topResMetricData`
- 数据库性能指标清单：`/resource/database/performance/metric/page`

## 快速验证

```bash
python3 scripts/resource_insight.py status-overview --resource_type database --output markdown
python3 scripts/resource_insight.py top-metric --resource_type database --top_num 5 --output markdown
python3 scripts/resource_insight.py metric-page --page_num 1 --page_size 5 --output markdown
```

