---
name: resource-insight-query
description: 查询 INOE 资源状态与性能数据。适用于用户询问设备状态统计、数据库状态总览、资源性能 Top、CPU/内存/磁盘/响应时间等性能排行、数据库性能指标清单时使用。告警列表和告警统计继续使用 real-alarm；CMDB 模型/关系/ci count 查询继续使用 zgops-cmdb。
---

# Resource Insight Query

这是 query 数字员工的资源状态与性能查询技能。它只封装 INOE 资源状态/性能接口，不处理实时告警列表，也不替代 `zgops-cmdb`。

## 边界

- 实时告警列表、告警级别统计、当前告警详情：使用 `real-alarm`。
- CMDB 模型、CI 列表、CI 关系、`/cmdb/v0.1/ci/count...`：使用 `zgops-cmdb`。
- 资源状态总览、性能 Top、数据库指标清单：使用本技能。

## 配置

配置从本技能目录 `.env` 读取，也支持同名环境变量：

```bash
INOE_API_BASE_URL=http://<host>:<port>/prod-api
INOE_API_TOKEN=your_jwt_token_here
INOE_ENABLE_CURL_FALLBACK=true
```

不要在回答里泄露 token。

## 常用命令

查询数据库状态总览：

```bash
cd skills/resource-insight-query
python3 scripts/resource_insight.py status-overview --resource_type database --output markdown
```

查询数据库性能 Top：

```bash
cd skills/resource-insight-query
python3 scripts/resource_insight.py top-metric --resource_type database --top_num 5 --output markdown
```

查询网络设备 CPU Top：

```bash
cd skills/resource-insight-query
python3 scripts/resource_insight.py top-metric --resource_type network --order_code cpuRate --top_num 5 --output markdown
```

生成资源概览汇总：

```bash
cd skills/resource-insight-query
python3 scripts/resource_insight.py summary --resource_type database --output markdown
```

输出 JSON 给后续渲染：

```bash
python3 scripts/resource_insight.py top-metric --resource_type database --output json
```

## 自然语言映射

- “数据库状态总览 / 数据库状态统计 / 数据库资源状态”：执行 `status-overview --resource_type database`。
- “数据库性能 Top / 数据库磁盘使用率排行”：执行 `top-metric --resource_type database`，默认 `order_code=diskRate`。
- “网络设备性能 / 网络设备 CPU 排行”：执行 `top-metric --resource_type network --order_code cpuRate`。
- “操作系统性能 / 服务器性能”：分别使用 `resource_type os` 或 `resource_type server`。
- “帮我进行设备状态的统计”：如果用户没有指定资源类型，先用 `summary --resource_type database` 展示已封装的数据库状态，并说明其他资源状态统计后续由 CMDB count 类接口在 `zgops-cmdb` 中承载。

## 已封装接口

- `GET /resource/database/resource/status/overview`
- `POST /resource/pm/TopMetricDataNew`
- `POST /resource/resource/performance/topResMetricData`
- `POST /resource/database/performance/metric/page?pageNum=<pageNum>&pageSize=<pageSize>`

