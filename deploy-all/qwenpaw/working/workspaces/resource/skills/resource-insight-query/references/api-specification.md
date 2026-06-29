# API Specification

## 数据库状态总览

- Method: `GET`
- Path: `/resource/database/resource/status/overview`
- Response: `{ code, msg, data }`
- `data` 常见字段：
  - `total`
  - `normalCount`
  - `abnormalCount`
  - `alarmCount`
  - `unknownCount`

## 页面性能 Top

- Method: `POST`
- Path: `/resource/pm/TopMetricDataNew`
- Body:

```json
{
  "topNum": 5,
  "type": "数据库",
  "orderCode": "diskRate"
}
```

页面已确认的参数：

| 页面资源 | `type` | 默认 `orderCode` |
| --- | --- | --- |
| 数据库 | `数据库` | `diskRate` |
| 网络设备 | `网络设备` | `cpuRate` |
| 操作系统 | `操作系统` | `cpuRate` |
| 服务器 | `服务器` | `cpuRate` |
| 中间件 | `中间件` | `cpuRate` |

## 资源性能 Top

- Method: `POST`
- Path: `/resource/resource/performance/topResMetricData`
- Body:

```json
{
  "topNum": 10,
  "orderKey": "diskRate"
}
```

当前环境 `orderKey=diskRate` 有数据，`cpuRate` 可能返回空列表。

## 数据库性能指标分页

- Method: `POST`
- Path: `/resource/database/performance/metric/page?pageNum=1&pageSize=10`
- Body:

```json
{
  "pageNum": 1,
  "pageSize": 10
}
```

