# Nightingale (n9e) 日志查询接口说明

本技能依赖夜莺 v8 的「数据查询 -> 日志」页面背后的 REST 接口，全部基于
ElasticSearch 数据源代理。下面只列出本技能实际用到的端点。

## 鉴权

- Header：`X-User-Token: <token>`
- Token 创建路径：登录夜莺 -> 个人中心 -> Token 管理 -> 创建 Token
- 所有请求都加 `X-User-Token`、`Content-Type: application/json`、`Accept: application/json`
- v8 之前版本可能使用 `Authorization: Bearer ...`；本技能不兼容，请升级到 v8.0.0-beta.5+

## 数据源管理

| 用途 | 方法 | 路径 | 备注 |
|------|------|------|------|
| 列表 | POST | `/api/n9e/datasource/list` | body 可选：`{"typ":"elasticsearch","p":1,"limit":1000}` |
| 简表 | GET | `/api/n9e/datasource/brief` | 当 `list` 不可用时的兜底 |

返回结构（最常见的一种）：

```json
{
  "dat": {
    "list": [
      {"id": 1, "name": "default-es", "plugin_type": "elasticsearch", "description": ""}
    ],
    "total": 1
  },
  "err": ""
}
```

不同 v8 子版本的返回结构会有差别，本技能在解析时同时兼容 `{dat:{list:[...]}}`、
`{dat:[...]}`、和裸数组三种。

## ES 代理

夜莺通过 `/api/n9e/proxy/<datasource_id>/<es-path>` 把请求转发到目标 ES 实例。
本技能用到的常见端点：

| 用途 | 方法 | 路径 | 说明 |
|------|------|------|------|
| 单索引检索 | POST | `/api/n9e/proxy/<id>/<index>/_search` | body 是标准 ES query DSL |
| 批量检索 | POST | `/api/n9e/proxy/<id>/_msearch` | body 是 ndjson（夜莺前端默认走这条） |
| 索引列表 | GET | `/api/n9e/proxy/<id>/_cat/indices?format=json&bytes=b` | |
| 字段 mapping | GET | `/api/n9e/proxy/<id>/<index>/_mapping` | |
| 集群健康 | GET | `/api/n9e/proxy/<id>/_cluster/health` | 仅排错时用 |

`<index>` 支持单索引、逗号分隔多索引、通配符（`logstash-*`）。

## 查询请求体（_search）

本技能默认用 `query_string`（Lucene 语法）+ 时间过滤：

```json
{
  "size": 20,
  "track_total_hits": true,
  "sort": [{"@timestamp": {"order": "desc"}}],
  "query": {
    "bool": {
      "must": [
        {
          "query_string": {
            "query": "level:ERROR AND service:nginx",
            "analyze_wildcard": true,
            "default_operator": "AND"
          }
        }
      ],
      "filter": [
        {
          "range": {
            "@timestamp": {
              "gte": 1746489600000,
              "lte": 1746493200000,
              "format": "epoch_millis"
            }
          }
        }
      ]
    }
  }
}
```

返回结构（截取相关部分）：

```json
{
  "took": 42,
  "hits": {
    "total": {"value": 1234},
    "hits": [
      {
        "_index": "logstash-2026.05.06",
        "_id": "abc",
        "_source": {
          "@timestamp": "2026-05-06T08:00:00Z",
          "message": "...",
          "level": "ERROR",
          "host": {"name": "web-01"},
          "service": {"name": "nginx"}
        }
      }
    ]
  }
}
```

## 聚合请求体（terms / date_histogram）

按级别聚合：

```json
{
  "size": 0,
  "query": {"bool": {"must": [], "filter": [...]}},
  "aggs": {
    "by_field": {
      "terms": {"field": "log.level.keyword", "size": 10, "missing": "(unknown)"}
    }
  }
}
```

时间直方图：

```json
{
  "size": 0,
  "query": {"bool": {...}},
  "aggs": {
    "ts": {
      "date_histogram": {
        "field": "@timestamp",
        "fixed_interval": "1m",
        "min_doc_count": 0,
        "extended_bounds": {"min": <from_ms>, "max": <to_ms>}
      }
    }
  }
}
```

## 错误码与处理

| HTTP | 含义 | 处理 |
|-----:|------|------|
| 400 | DSL 解析失败 / 字段不存在 | 检查 `--query` 写法或字段名；先跑 `meta --mode fields` |
| 401 | Token 失效 | 重新生成并写回 `.env` 的 `N9E_USER_TOKEN` |
| 403 | 数据源未授权 | 联系夜莺管理员授予该用户数据源访问权 |
| 404 | URL 路径错 | 检查 `N9E_API_BASE_URL`、`datasource_id`、索引名 |
| 408 | 超时 | 缩小时间范围、降 size、加索引过滤 |
| 5xx | 后端错 | 透传 ES 错误信息前 300 字符 |

## 与夜莺前端的对应关系

- 前端 “数据查询 -> 日志” 页面命中的接口是 `/api/n9e/proxy/<id>/_msearch`
- 单 query 场景下 `_msearch` 与 `<index>/_search` 等价；本技能默认走 `_search`
  以方便排错；如果未来需要并发多 query，再切到 `_msearch`
