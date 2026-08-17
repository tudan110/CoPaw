---
name: resource-insight-query
description: 查询 INOE 资源状态与性能数据。适用于用户询问设备状态统计、数据库状态总览、资源性能 Top、CPU/内存/磁盘/响应时间等性能排行、数据库性能指标清单时使用。告警列表和告警统计继续使用 real-alarm；CMDB 模型/关系/ci count 查询继续使用 zgops-cmdb。
---

# Resource Insight Query

查询 INOE 资源状态与性能数据。不处理实时告警列表，也不替代 `zgops-cmdb`。

## MCP 优先级

本工作区已启用 `resource` MCP Server。Agent 必须优先直接调用以下 MCP Tools；不要自行使用 `curl`、`requests`、SSE 或 JSON-RPC。

仅在 resource MCP Driver 未加载、客户端/工具不可用或协议响应无法解析时，才允许回退到旧脚本路径（见末尾"旧脚本回退路径"）。

## 边界

- 实时告警列表、告警级别统计、当前告警详情：使用 `real-alarm`
- CMDB 模型、CI 列表、CI 关系、count 类接口：使用 `zgops-cmdb`
- 资源状态总览、性能 Top、数据库指标清单：使用本技能

## MCP Tools

| 操作 | MCP Tool | 参数 |
| --- | --- | --- |
| 数据库状态总览 | `resource__getDatabaseResourceStatusOverview` | 无 |
| 页面性能 Top | `resource__getTopMetricData` | `orderCode`, `topNum`, `type` |
| 资源性能 Top | `resource__getTopResourceMetricData` | `orderKey`, `topNum`, `type` |
| 数据库性能指标 | `resource__queryDatabasePerformanceMetrics` | `keyWord`, `pageNum`, `pageSize` |

## 自然语言映射

- "数据库状态总览 / 数据库状态统计" → `resource__getDatabaseResourceStatusOverview`
- "数据库性能 Top / 磁盘使用率排行" → `resource__getTopMetricData(orderCode="diskRate", topNum=5)`
- "网络设备性能 / CPU 排行" → `resource__getTopResourceMetricData(orderKey="cpuRate", topNum=5)`
- "操作系统性能 / 服务器性能" → `resource__getTopResourceMetricData(type="os" 或 "server")`
- "主机磁盘使用率排行 / 磁盘 Top" → `resource__getTopResourceMetricData(orderKey="diskRate", topNum=5)`
- "列出磁盘使用率超 80% 的主机" → 调对应 MCP Tool 获取数据后，本地过滤
- "数据库性能指标清单" → `resource__queryDatabasePerformanceMetrics(pageNum=1, pageSize=20)`
- "资源概览汇总" → 组合调用上述 MCP Tools 后自行汇总

## 旧脚本回退路径

仅当 resource MCP Driver 不可用时，才执行以下命令。脚本自动从环境变量读取凭证。

```bash
cd skills/resource-insight-query
python3 scripts/resource_insight.py status-overview --resource_type database --output markdown
python3 scripts/resource_insight.py top-metric --resource_type database --top_num 5 --output markdown
python3 scripts/resource_insight.py summary --resource_type database --output markdown
```

回退时必须在过程说明中写明回退原因（如 `resource-mcp-unavailable`）。