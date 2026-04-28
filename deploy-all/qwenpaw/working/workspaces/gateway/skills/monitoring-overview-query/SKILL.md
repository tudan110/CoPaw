---
name: monitoring-overview-query
description: 查询监控总览/运维驾驶舱页面数据。适用于用户询问当前系统概览、智观系统运行状态、整体运行态势、监控概况、资产总览、应用健康概览、告警对象 Top5、全局/系统/监控/简易拓扑时使用。监控页中的实时告警时间范围查询继续使用 real-alarm；具体某个应用的 CMDB 关系拓扑继续使用 zgops-cmdb。
---

# Monitoring Overview Query

这是 `query` 数字员工的监控总览查询技能，封装 `topo/monitoring` 路由页对应的总览接口。这个 skill 面向“全局监控总览”和“系统级概览”，不需要用户先选择某个 CMDB 应用。

## 边界

- 告警列表、实时告警、按时间范围查询告警：继续使用 `real-alarm`。
- 数据库状态总览、资源性能 Top、数据库指标清单：继续使用 `resource-insight-query`。
- CMDB count/group、模型分布、厂商分布：继续使用 `zgops-cmdb`。
- 指定了具体应用名/项目名的应用关系拓扑、业务拓扑、资源依赖链：继续使用 `zgops-cmdb`。
- 未指定具体应用的“简易拓扑 / 系统拓扑 / 全局拓扑 / 监控拓扑 / 拓扑总览”：使用本技能的 `topology`，不要追问应用名。

## 配置

配置从本技能目录 `.env` 读取，也支持同名环境变量：

```bash
INOE_API_BASE_URL=http://<host>:<port>/prod-api
INOE_API_TOKEN=your_jwt_token_here
INOE_ENABLE_CURL_FALLBACK=true
```

## 常用命令

查询告警对象 Top5：

```bash
cd skills/monitoring-overview-query
python3 scripts/monitoring_overview.py alarm-top5 --output markdown
```

查询监控拓扑图：

```bash
cd skills/monitoring-overview-query
python3 scripts/monitoring_overview.py topology --output markdown
```

查询监控资产总览：

```bash
cd skills/monitoring-overview-query
python3 scripts/monitoring_overview.py asset-overview --output markdown
```

## 自然语言映射

- “告警对象 top5 / 告警对象排行 / 最常见告警对象”：执行 `alarm-top5`。
- “系统概览 / 当前系统概览 / 查询系统概况 / 智观系统运行状态 / 当前运行态势 / 运维概览 / 监控概况 / 应用健康概览”：优先执行 `asset-overview`；如果用户明确要“大屏/驾驶舱完整概览”，可补充 `alarm-top5`。
- “监控拓扑 / 简易拓扑 / 系统拓扑 / 全局拓扑 / 总览拓扑 / 监控总览拓扑 / 看一下整体拓扑”：执行 `topology`，优先输出可渲染 `echarts`，不需要用户选择应用。
- “资产总览 / 监控资产总览 / 当前资产情况 / 资源健康概览”：执行 `asset-overview`。
- “某某应用拓扑 / 某某项目资源关系 / 指定应用的依赖拓扑”：不要用本技能，改用 `zgops-cmdb` 的应用拓扑流程。
- “最近 24 小时实时告警 / 某时间段实时告警”：不要用本技能，改用 `real-alarm` 并传 `--begin_time/--end_time`。

## 已封装接口

- `GET /resource/alarm/statistics/statResTop`
- `GET /resource/monitor/overview/topology`
- `GET /resource/monitor/overview/asset/overview`
