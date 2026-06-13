# 智观AI 调用接口盘点

## 汇总表

| 模块/能力 | 对应 skill | 接口数 | 涉及范围 |
|---|---|---:|---|
| 设备管理 | `device-list` | 1 | 设备列表查询 |
| 日志服务 | `nightingale-log`、`log-hazard-detection`、`log-security-scan` | 6 | Nightingale / ES 日志查询、聚合、元数据 |
| 实时告警 | `real-alarm` | 2 | 告警列表、告警类别统计 |
| 资源性能 | `resource-insight-query` | 4 | 数据库状态、性能 Top、资源性能排行、数据库指标 |
| 监控总览 | `monitoring-overview-query` | 3 | 告警 Top、监控拓扑、资产总览 |
| CMDB 查询/统计 | `zgops-cmdb` | 16 | CI 类型、CI 实例、CI 关系、CMDB count/group |
| 故障/巡检指标 | `alarm-analyst`、`inspection-analyst` | 2 | 指标定义、指标值批量查询 |
| 传统工单 | `order-workflow` | 5 | 工单统计、创建、待办、已办、详情 |
| 巡检规则 | `inspection-analyst` | 2 | 巡检配置、字典解码 |
| Web 可用性 | `web-availability-monitor` | 14 | 监测任务、执行记录、选择器辅助 |
| CMDB 导入 | `zgops-cmdb-import` | 14 | CMDB 类型、分组、属性、关系、CI 写入 |
| **合计** |  | **69** |  |

## 接口明细

### 设备管理

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/resource/device/device/list` | 查询设备列表 |

### 日志服务

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/n9e/datasource/list` | 查询日志数据源列表 |
| GET | `/api/n9e/datasource/brief` | 查询日志数据源简表 |
| POST | `/api/n9e/proxy/{id}/{index}/_search` | ES 单索引日志检索/聚合 |
| POST | `/api/n9e/proxy/{id}/_msearch` | ES 批量日志检索 |
| GET | `/api/n9e/proxy/{id}/_cat/indices` | 查询日志索引列表 |
| GET | `/api/n9e/proxy/{id}/{index}/_mapping` | 查询日志索引字段 mapping |

### 实时告警

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/resource/realalarm/list` | 查询实时告警列表 |
| POST | `/resource/alarmQuery/queryAlarmClassCount` | 查询告警类别统计 |

### 资源性能

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/resource/database/resource/status/overview` | 数据库资源状态总览 |
| POST | `/resource/pm/TopMetricDataNew` | 查询页面性能 Top |
| POST | `/resource/resource/performance/topResMetricData` | 查询资源性能 Top |
| POST | `/resource/database/performance/metric/page` | 查询数据库性能指标分页 |

### 监控总览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/resource/alarm/statistics/statResTop` | 告警对象 Top 统计 |
| GET | `/resource/monitor/overview/topology` | 查询监控总览拓扑 |
| GET | `/resource/monitor/overview/asset/overview` | 查询资产总览 |

### CMDB 查询/统计

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/acl/login` | CMDB 登录 |
| GET | `/api/v1/acl/users/info` | 查询当前用户信息 |
| GET | `/api/v0.1/ci_types` | 查询 CI 类型列表 |
| GET | `/api/v0.1/ci_types/{id}/attributes` | 查询 CI 类型属性 |
| GET | `/api/v0.1/ci_type_relations` | 查询 CI 类型关系 |
| GET | `/api/v0.1/relation_types` | 查询关系类型 |
| GET | `/api/v0.1/ci/s` | 查询 CI 实例列表 |
| GET | `/api/v0.1/ci/{id}` | 查询 CI 实例详情 |
| GET | `/api/v0.1/ci_relations/s` | 查询 CI 关系拓扑 |
| GET | `/cmdb/v0.1/ci/count` | CMDB CI 数量统计 |
| GET | `/cmdb/v0.1/ci/count/group` | CMDB CI 分组统计 |
| GET | `/cmdb/v0.1/ci/count/child` | CMDB 子类数量统计 |
| GET | `/cmdb/v0.1/ci/count/child/group` | CMDB 子类分组统计 |
| GET | `/cmdb/v0.1/ci/count/group/attr` | CMDB 属性分组统计 |
| GET | `/cmdb/v0.1/ci_types` | INOE CMDB 类型列表 |
| GET | `/cmdb/v0.1/ci_types/groups` | INOE CMDB 类型分组 |

### 故障/巡检指标

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/resource/resource/threshold/getMetricDefinitions` | 查询资源指标定义 |
| POST | `/resource/pm/getMetricData` | 批量查询指标值 |

### 工单能力

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/flowable/workflow/workOrder/getWorkOrder` | 查询今日工单统计 |
| POST | `/flowable/workflow/workOrder/faultManualWorkorders` | 创建处置工单 |
| GET | `/flowable/workflow/process/todoList` | 查询待办工单列表 |
| GET | `/flowable/workflow/process/finishedList` | 查询已办工单列表 |
| GET | `/flowable/workflow/process/detail` | 查询工单详情 |

### 巡检规则

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/resource/inspection/config/list` | 查询巡检阈值/规则配置 |
| GET | `/admin/dict/data/list` | 查询字典数据，用于规则 operator 解码 |

### Web 拨测可用性

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 |
| GET | `/api/dashboard` | 查询监测看板 |
| GET | `/api/monitors` | 查询监测任务列表 |
| GET | `/api/monitors/{id}` | 查询监测任务详情 |
| POST | `/api/monitors` | 创建监测任务 |
| PUT | `/api/monitors/{id}` | 更新监测任务 |
| DELETE | `/api/monitors/{id}` | 删除监测任务 |
| POST | `/api/monitors/{id}/publish` | 发布监测任务 |
| POST | `/api/monitors/{id}/trigger` | 手工触发监测任务 |
| GET | `/api/monitors/{id}/runs` | 查询任务执行记录 |
| GET | `/api/runs/{id}` | 查询单次执行详情 |
| DELETE | `/api/runs/{id}` | 删除单次执行记录 |
| POST | `/api/runs/batch-delete` | 批量删除执行记录 |
| POST | `/api/selector-helper` | 生成页面元素选择器建议 |

### CMDB 导入

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v0.1/ci_types/groups` | 查询 CI 类型分组 |
| POST | `/api/v0.1/ci_types/groups` | 创建 CI 类型分组 |
| DELETE | `/api/v0.1/ci_types/groups/{id}` | 删除 CI 类型分组 |
| POST | `/api/v0.1/ci_types` | 创建 CI 类型 |
| POST | `/api/v0.1/ci_types/inheritance` | 创建 CI 类型继承关系 |
| GET | `/api/v0.1/preference/ci_types/{id}/attributes` | 查询 CI 类型偏好属性 |
| GET | `/api/v0.1/attributes/s` | 查询属性列表 |
| GET | `/api/v0.1/ci_type_relations/{id}/parents` | 查询 CI 类型父级关系 |
| POST | `/api/v0.1/ci_type_relations/{parent_type_id}/{child_type_id}` | 创建 CI 类型关系 |
| POST | `/api/v0.1/ci` | 创建 CI 实例 |
| PUT | `/api/v0.1/ci/{id}` | 更新 CI 实例 |
| DELETE | `/api/v0.1/ci/{id}` | 删除 CI 实例 |
| POST | `/api/v0.1/ci_relations/{src_id}/{dst_id}` | 创建 CI 实例关系 |
| DELETE | `/api/v0.1/ci_relations/{id}` | 删除 CI 实例关系 |

