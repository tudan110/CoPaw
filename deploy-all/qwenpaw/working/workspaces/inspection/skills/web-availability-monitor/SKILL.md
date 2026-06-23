---
name: web-availability-monitor
category: workflow
tags: [web, monitor, availability, browser, synthetic]
triggers: [Web可用性监测, 网站可用性, 页面可用性, 监测任务, 新建监测任务, 手工执行监测, 查看监测结果, 网站监测]
description: 查询和编排 Web 可用性监测任务。适用于查看监测看板、查询网站监测任务、查看执行详情、手工触发执行、为页面动作生成 locator 建议，以及创建/更新网站监测任务。
---

# Web Availability Monitor

这是 inspection 本地的 **Web 可用性监测** 技能，对接 `http://82.156.83.38:31010` 对应的网页监测系统。

它不是普通“站点 ping 一下”的探活脚本，而是一个 **可编排的页面监测技能**：支持任务、步骤流、定时调度、手工执行、步骤截图和失败复盘。

## 边界

- “当前系统监控总览 / 运维驾驶舱 / 监控态势”这类全局监控概况：继续使用 `monitoring-overview-query`
- 资源巡检、数据库/中间件健康检查：继续使用 `inspection-analyst`
- CMDB、拓扑、资源关系：继续使用 `zgops-cmdb`
- 本技能只负责 **Web 页面可用性监测系统**

## 配置

配置优先从本技能目录 `.env` 读取，也支持同名环境变量：

```bash
WEB_MONITOR_BASE_URL=http://82.156.83.38:31010
WEB_MONITOR_AUTHORIZATION=
WEB_MONITOR_COOKIE=
WEB_MONITOR_TIMEOUT_SECONDS=20
WEB_MONITOR_VERIFY_SSL=true
WEB_MONITOR_ENABLE_CURL_FALLBACK=false
WEB_MONITOR_EXTRA_HEADERS={}
```

说明：

1. 当前系统默认可匿名访问，所以 `WEB_MONITOR_AUTHORIZATION` / `WEB_MONITOR_COOKIE` 可以为空
2. 如果后续接入认证，再把 token 或 cookie 填进去
3. 不要在回答中泄露 token、cookie 或额外请求头明文

## 常用命令

查看可用性监测看板：

```bash
cd skills/web-availability-monitor
python3 scripts/web_monitor.py dashboard --output markdown
```

查看监测任务列表：

```bash
cd skills/web-availability-monitor
python3 scripts/web_monitor.py list-monitors --limit 10 --output markdown
```

查看某个监测任务详情：

```bash
cd skills/web-availability-monitor
python3 scripts/web_monitor.py detail --monitor-name "网易163门户" --output markdown
```

查看某个监测任务最近执行：

```bash
cd skills/web-availability-monitor
python3 scripts/web_monitor.py runs --monitor-name "网易163门户" --limit 10 --output markdown
```

查看单次运行详情：

```bash
cd skills/web-availability-monitor
python3 scripts/web_monitor.py run --run-id 0fbbffaa-0e8f-4c85-80da-a85366a0aa71 --output markdown
```

手工触发一次监测：

```bash
cd skills/web-availability-monitor
python3 scripts/web_monitor.py trigger --monitor-name "网易163门户" --output markdown
```

触发后等待结果：

```bash
cd skills/web-availability-monitor
python3 scripts/web_monitor.py trigger --monitor-name "网易163门户" --wait-seconds 90 --output markdown
```

根据 URL 获取页面元素定位建议：

```bash
cd skills/web-availability-monitor
python3 scripts/web_monitor.py selector-helper --url https://example.com --output markdown
```

创建监测任务：

```bash
cd skills/web-availability-monitor
python3 scripts/web_monitor.py create --payload-file /tmp/web_monitor_create.json --publish --output markdown
```

更新监测任务：

```bash
cd skills/web-availability-monitor
python3 scripts/web_monitor.py update --monitor-name "网易163门户" --payload-file /tmp/web_monitor_update.json --output markdown
```

## 载荷格式

创建/更新支持两类 JSON：

### 1. 页面接口原生格式

```json
{
  "name": "网易163门户",
  "description": "首页搜索链路校验",
  "targetUrl": "https://www.163.com",
  "status": "enabled",
  "scheduleEnabled": true,
  "scheduleCron": "0 * * * *",
  "scheduleTimezone": "Asia/Shanghai",
  "definition": {
    "startUrl": "https://www.163.com",
    "steps": [
      {
        "name": "打开页面",
        "actionType": "goto",
        "enabled": true,
        "onFailure": "abort",
        "config": {
          "url": "https://www.163.com",
          "waitUntil": "domcontentloaded"
        }
      }
    ]
  }
}
```

### 2. 轻量格式

```json
{
  "name": "示例站点监测",
  "description": "首页关键文案检查",
  "targetUrl": "https://example.com",
  "status": "enabled",
  "schedule": {
    "enabled": true,
    "cron": "*/30 * * * *",
    "timezone": "Asia/Shanghai"
  },
  "steps": [
    {
      "name": "打开页面",
      "actionType": "goto",
      "config": {
        "url": "https://example.com",
        "waitUntil": "domcontentloaded"
      }
    },
    {
      "name": "检查文本",
      "actionType": "assertText",
      "config": {
        "expectedText": "Example Domain"
      }
    }
  ]
}
```

脚本会自动把第二种轻量格式规范化成接口需要的结构。

## 自然语言映射

- “看一下 Web 可用性监测概况 / 最近失败”：执行 `dashboard`
- “查看网站监测任务 / 当前有哪些监测任务”：执行 `list-monitors`
- “看一下某个监测任务详情”：执行 `detail`
- “看一下某个任务最近执行 / 最近失败记录”：执行 `runs`
- “查看这次执行失败在哪一步”：执行 `run`
- “帮我手工执行一下这个网站监测”：执行 `trigger`
- “给这个页面推荐 locator / 选择器”：执行 `selector-helper`
- “帮我新建一个网站监测任务”：整理 JSON 后执行 `create`
- “帮我修改这个监测任务”：整理 JSON 后执行 `update`

## 执行要求

1. **优先走 HTTP API，不要默认用浏览器自动化点击页面**
2. 查询类请求直接执行
3. 创建/更新/发布前，先确认任务名、URL、调度和步骤定义
4. 删除类操作必须明确对象并得到用户确认
5. 如果用户只描述了“点击某元素/检查某元素”，但没有 locator，优先先调用 `selector-helper`
6. 如果 `selector-helper` 返回多个候选，优先用语义更稳定的 locator（`role` / `text`）而不是脆弱 CSS 路径

## 返回要求

- 看板查询：优先返回摘要 + 近期失败表格
- 任务详情：返回任务基本信息、调度信息、步骤预览、最近状态
- 运行详情：返回运行结论、失败步骤、关键错误、截图链接
- 若脚本已经输出 markdown 表格或分段内容，agent 层必须逐字保留，不要重写成一整段摘要
- 对于创建/更新/发布/触发，结果中必须保留 monitorId 或 runId，便于后续继续操作

## 已封装接口

- `GET /api/health`
- `GET /api/dashboard`
- `GET /api/monitors`
- `GET /api/monitors/{id}`
- `POST /api/monitors`
- `PUT /api/monitors/{id}`
- `DELETE /api/monitors/{id}`
- `POST /api/monitors/{id}/publish`
- `POST /api/monitors/{id}/trigger`
- `GET /api/monitors/{id}/runs`
- `GET /api/runs/{id}`
- `DELETE /api/runs/{id}`
- `POST /api/runs/batch-delete`
- `POST /api/selector-helper`
