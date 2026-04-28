# 图表使用指南

本技能支持用 ECharts 渲染 CMDB 统计图。默认优先返回 Markdown；只有用户明确要图表或页面直渲染时，再输出 ECharts 代码块。

## 规则

- 优先使用 ECharts
- 不生成 PNG 等图片文件
- 图表必须能直接放进 ```echarts 代码块渲染
- 一次回复通常 1~3 个图表就够了
- 先给一句结论，再给图表
- 除非用户明确要求“导出 HTML 页面”或“保存为文件”，否则不要生成独立 `.html` 文件
- 默认把图表直接写在回复里，而不是返回工作区文件路径
- 图表标题、统计摘要、图下注释默认不要出现 `VEOPS`、`veops`、`OneOps`
- 如果是具体应用的关系拓扑，优先输出树状图，不要用柱状图、饼图去替代拓扑结构
- 如果用户要看某个应用的拓扑，先确认 CMDB 里实际管理的是哪个应用实例，再使用 ECharts `series.type = 'tree'`，并设置 `orient: 'LR'`

## 推荐图表

| 场景 | 推荐图表 |
|---|---|
| 模型分组分布 | 饼图 |
| 关系类型分布 | 环形图 |
| 应用关联目标分布 | 柱状图 |
| 应用关系拓扑 | 从左到右树状图（`type: 'tree'`, `orient: 'LR'`） |
| 只想给前端喂图表 | 只输出 ```echarts 代码块 |

## 调用方式

```bash
bash scripts/zgops-cmdb.sh analyze --mode summary --output markdown
bash scripts/zgops-cmdb.sh analyze --mode model-groups --output markdown
bash scripts/zgops-cmdb.sh analyze --mode relation-types --output markdown
bash scripts/zgops-cmdb.sh analyze --mode app-relations --output markdown
bash scripts/zgops-cmdb.sh analyze --mode summary --output markdown-echarts-only
```

## 模式说明

- `summary`：模型分组、关系类型、应用关联目标三类总览
- `model-groups`：模型分组统计
- `relation-types`：关系类型统计
- `app-relations`：应用模型 `project` 的入向/出向关系与目标分布

## 关系拓扑建议

- 先通过 `GET /api/v0.1/ci/s?q=_type:project` 找到目标应用实例，再用 `GET /api/v0.1/ci_relations/s?root_id=<ci_id>&level=1,2,3` 拉取关系树。
- `app-relations` 适合做“关联目标分布”统计，不适合作为具体应用关系拓扑图的最终形态。
- 输出树状图时，把应用放在左侧根节点，向右展开产品归属、虚拟机、中间件、数据库、机柜、IP 地址等链路。
- 根节点名称必须使用 CMDB 中实际查询到的应用实例名，不要预设某个固定应用名称。
