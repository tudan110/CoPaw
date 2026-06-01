# Web 可用性监测技能设计文档

## 1. 背景

当前已有一个独立的 **Web 可用性监测** 系统可用：

- 访问地址：`http://192.168.134.96:3101/`
- 本次调研时间：`2026-04-30`
- 当前可直接访问，**未观察到登录门槛**

该系统已经具备较完整的任务编排、执行、截图取证和结果查询能力。基于这套现成能力，为 QwenPaw 增加一个 `web-availability-monitor` 技能，可以让智能体直接完成：

1. 新建网页监测任务
2. 查询监测任务与运行结果
3. 手工触发执行
4. 分析失败原因与步骤截图
5. 生成页面元素定位建议

这类能力和巡检/健康检查场景天然相关，但对象从数据库、中间件、主机扩展到了 **Web 页面与用户可见链路**。

---

## 2. 调研结论

## 2.1 页面能力概览

从页面交互和接口行为看，该系统包含 4 类核心能力：

### 2.1.1 监测看板

首页看板可展示：

1. 监测任务数
2. 总执行次数
3. 成功率 / 失败次数
4. 近 7 天执行趋势
5. 近期失败记录

这说明系统已经有现成的聚合统计接口，适合技能做“可用性总体态势”查询。

### 2.1.2 监测任务管理

任务页支持：

1. 任务列表查询
2. 模糊搜索
3. 查看详情
4. 删除任务 / 删除运行记录
5. 批量删除运行记录

任务详情页支持：

1. 编辑任务基本信息
2. 编辑步骤流
3. 配置定时策略
4. 手工执行
5. 查看最近执行记录

### 2.1.3 新建/编辑任务

表单已经体现出该系统的核心模型是 **步骤流定义**，不是单一 URL 存活探测。

当前已观察到的步骤类型：

1. `打开页面`
2. `等待条件`
3. `检查文本`
4. `检查元素`
5. `点击元素`
6. `输入内容`
7. `滚动页面`
8. `截图取证`

步骤具备以下共同属性：

1. 步骤名称
2. 动作类型
3. 失败策略（失败终止 / 失败继续并标记 Warning）
4. 启用状态

这非常适合抽象成 skill 的 DSL。

### 2.1.4 执行详情

执行详情页已经给出了完整的运行证据：

1. 运行状态
2. 触发方式（定时 / 手工）
3. 总耗时
4. 步骤级输入快照
5. 步骤级输出快照
6. 失败信息
7. 每一步对应截图

这意味着 skill 不需要自己重复实现“浏览器取证和步骤回放”，而应优先复用该系统。

---

## 2.2 已确认的 HTTP API

通过页面请求和前端 bundle 提取，已确认存在如下接口：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/health` | 健康检查 |
| `GET` | `/api/dashboard` | 看板聚合数据 |
| `GET` | `/api/monitors` | 查询监测任务列表 |
| `GET` | `/api/monitors/{id}` | 查询单个监测任务详情 |
| `POST` | `/api/monitors` | 创建监测任务 |
| `PUT` | `/api/monitors/{id}` | 更新监测任务 |
| `DELETE` | `/api/monitors/{id}` | 删除监测任务 |
| `POST` | `/api/monitors/{id}/publish` | 发布任务定义 |
| `POST` | `/api/monitors/{id}/trigger` | 手工触发执行 |
| `GET` | `/api/monitors/{id}/runs` | 查询某任务的运行记录 |
| `GET` | `/api/runs/{id}` | 查询单次运行详情 |
| `DELETE` | `/api/runs/{id}` | 删除单次运行记录 |
| `POST` | `/api/runs/batch-delete` | 批量删除运行记录 |
| `POST` | `/api/selector-helper` | 根据 URL 生成页面元素定位建议 |

**设计建议：技能优先走 HTTP API，而不是直接走浏览器 UI 自动化。**

原因：

1. 调用更稳定
2. 响应更快
3. 可直接拿结构化 JSON
4. 更适合被技能脚本封装
5. 浏览器自动化可作为兜底，而不是主路径

---

## 2.3 已观察到的数据模型

## 2.3.1 Dashboard

`GET /api/dashboard` 返回了这类聚合字段：

- `totalMonitors`
- `totalRuns`
- `successRuns`
- `warningRuns`
- `failedRuns`
- `skippedRuns`
- `recentTrend[]`
- `recentFailures[]`

适合 skill 直接做：

1. 看板摘要
2. 近期失败列表
3. 可用性趋势简报

## 2.3.2 Monitor

`GET /api/monitors` 返回的任务对象已观察到：

- `id`
- `name`
- `description`
- `targetUrl`
- `status`
- `draftDefinition`
- `publishedDefinition`
- `scheduleEnabled`
- `scheduleCron`
- `scheduleTimezone`
- `lastRunStatus`
- `lastRunStartedAt`
- `lastRunFinishedAt`
- `createdAt`
- `updatedAt`

其中 `draftDefinition/publishedDefinition` 的结构里已明确包含：

- `startUrl`
- `steps[]`

每个 `step` 至少包含：

- `id`
- `name`
- `actionType`
- `config`
- `enabled`
- `onFailure`

## 2.3.3 Run

`GET /api/runs/{id}` 返回结构为：

- `run`
- `steps`

其中：

### run

- `id`
- `monitorId`
- `triggerType`
- `status`
- `summary`
- `startedAt`
- `finishedAt`
- `durationMs`
- `artifactDir`
- `createdAt`

### steps[]

- `id`
- `runId`
- `stepIndex`
- `stepId`
- `stepName`
- `actionType`
- `onFailure`
- `status`
- `startedAt`
- `finishedAt`
- `durationMs`
- `inputSnapshot`
- `outputSnapshot`
- `errorMessage`
- `screenshotPath`
- `screenshotUrl`

这说明 skill 的结果输出可以天然支持：

1. 运行结论
2. 失败步骤定位
3. 参数快照
4. 截图链接/截图证据

## 2.3.4 Selector Helper

`POST /api/selector-helper` 已确认返回：

- `finalUrl`
- `pageTitle`
- `snapshot`
- `suggestions`

其中 `suggestions[]` 每项至少包含：

- `id`
- `label`
- `locator`
- `tagName`
- `text`
- `role`
- `bounds`

这意味着技能可以支持：

1. 根据 URL 自动推荐 locator
2. 把“点击元素 / 输入内容 / 检查元素”从手填 selector 升级成辅助选点

---

## 3. 技能目标

建议新建技能名：

- **`web-availability-monitor`**

目标不是做一个“网站探活脚本”，而是做一个 **面向业务巡检和 Web 链路验证的监测编排技能**。

### 3.1 必达目标

1. 让智能体能用自然语言创建一个 Web 监测任务
2. 让智能体能查询监测看板、任务列表和最近失败
3. 让智能体能查看某次执行详情和失败步骤
4. 让智能体能手工触发任务执行
5. 让智能体能借助 `selector-helper` 自动补 locator 建议

### 3.2 非目标

当前阶段先不做：

1. 技能内部自己实现一套浏览器执行引擎
2. 技能内部自己维护截图和 artifact 生命周期
3. 技能内部绕过系统直接操作目标网站
4. 技能直接做复杂登录态接管

这些能力可以留给后续二期，或在目标系统 API 不足时用浏览器自动化补齐。

---

## 4. 典型用户意图

该技能建议覆盖以下自然语言场景：

1. “帮我看看 Web 可用性监测最近失败的任务”
2. “查询笔点搜索网最近一次执行结果”
3. “帮我新建一个网站监测任务，每 30 分钟执行一次”
4. “打开 `https://example.com`，检查页面里是否出现 `Welcome`”
5. “访问某页面后点击登录，再检查是否出现用户名输入框”
6. “帮我手工执行一下 `网易163门户` 的监测任务”
7. “给这个页面生成一个可用的点击定位器”
8. “删除这批失败运行记录”

---

## 5. 技能能力设计

建议把技能能力拆成 6 个动作族：

## 5.1 看板查询

### action

- `get_dashboard`

### 能力

1. 返回总体统计
2. 返回近期趋势
3. 返回近期失败摘要

### 典型输出

- 总任务数 / 总运行数 / 成功率 / 失败次数
- 最近失败任务 Top N

## 5.2 任务查询

### action

- `list_monitors`
- `get_monitor`
- `list_monitor_runs`

### 能力

1. 模糊筛选任务
2. 获取任务定义和调度配置
3. 获取最近运行记录

## 5.3 任务编排

### action

- `create_monitor`
- `update_monitor`
- `publish_monitor`

### 能力

1. 创建草稿任务
2. 修改已有任务
3. 发布任务定义

### 默认策略建议

为了安全和可控，建议默认：

1. **先创建/更新草稿**
2. **返回任务定义摘要**
3. **用户确认后再 publish**

如果用户明确说“直接生效”，则可以自动发布。

## 5.4 执行控制

### action

- `trigger_monitor`
- `get_run`

### 能力

1. 触发手工执行
2. 查询当前执行结果
3. 返回步骤级诊断信息

## 5.5 清理能力

### action

- `delete_monitor`
- `delete_run`
- `batch_delete_runs`

### 能力

1. 删除监测任务
2. 删除单次运行
3. 批量删除运行记录

### 建议

删除类动作属于高风险写操作，建议技能层要求：

1. 明确对象 ID 或唯一名称
2. 默认二次确认

## 5.6 定位辅助

### action

- `selector_helper`

### 能力

1. 根据 URL 抓取页面快照
2. 返回可点击/可输入元素建议
3. 生成适用于步骤配置的 locator

---

## 6. 技能输入输出协议建议

建议技能脚本内部统一使用结构化请求：

```json
{
  "action": "create_monitor",
  "params": {
    "name": "笔点搜索网",
    "description": "首页关键内容可用性检查",
    "targetUrl": "https://www.bidianer.com/",
    "schedule": {
      "enabled": true,
      "cron": "*/30 * * * *",
      "timezone": "Asia/Shanghai"
    },
    "definition": {
      "startUrl": "https://www.bidianer.com/",
      "steps": [
        {
          "name": "打开页面",
          "actionType": "goto",
          "enabled": true,
          "onFailure": "abort",
          "config": {
            "url": "https://www.bidianer.com/",
            "waitUntil": "domcontentloaded"
          }
        }
      ]
    }
  }
}
```

建议统一结构化响应：

```json
{
  "ok": true,
  "action": "create_monitor",
  "summary": "已创建草稿监测任务：笔点搜索网",
  "data": {
    "monitorId": "e8d7427e-90de-452b-aa53-712538c0c2e8",
    "status": "enabled",
    "scheduleCron": "*/30 * * * *"
  }
}
```

---

## 7. 自然语言到步骤 DSL 的映射建议

这是该技能最关键的产品点。

建议让大模型只做 **自然语言转结构化步骤**，真正提交仍由脚本调用 API 完成。

### 7.1 典型映射

用户说：

> 帮我建一个任务，每 30 分钟打开笔点搜索网，确认页面里有“笔点”，再点击“购物旅游”，检查页面里有没有“京东商城”。

应映射为：

1. `goto`
2. `assertText`
3. `click`
4. `assertText`

### 7.2 建议动作映射表

| 自然语言意图 | DSL 动作 |
| --- | --- |
| 打开网页 / 访问页面 | `goto` |
| 等待元素 / 等待文本 / 等待网络空闲 | `wait` |
| 检查包含某文本 | `assertText` |
| 检查某元素存在 | `assertElement` |
| 点击某按钮/链接 | `click` |
| 在输入框中输入内容 | `input` |
| 下拉 / 滚动页面 | `scroll` |
| 截图留证 | `screenshot` |

### 7.3 locator 生成策略

建议优先级：

1. 用户显式提供 locator → 直接使用
2. 用户只给自然语言元素描述 → 先调用 `selector_helper`
3. `selector_helper` 失败 → 退回人工确认

---

## 8. 调度策略设计

页面已支持两种配置语义：

1. 简单模式（推荐）
2. 高级模式（Cron）

技能建议支持：

### 8.1 自然语言调度

例如：

1. 每 5 分钟
2. 每 30 分钟
3. 每小时整点
4. 每天 09:00
5. 每周一早上 8 点

### 8.2 直接 Cron

如果用户直接提供 Cron，则直接写入：

- `scheduleCron`
- `scheduleTimezone`

### 8.3 默认时区

调研中任务详情已显示：

- `scheduleTimezone = Asia/Shanghai`

建议技能默认用：

- `Asia/Shanghai`

除非用户明确指定其他时区。

---

## 9. 技能输出形式建议

建议按场景输出成 3 类结果：

## 9.1 看板摘要

适用于：

- `get_dashboard`

输出重点：

1. 总体健康度
2. 最近失败任务
3. 趋势结论

## 9.2 任务定义摘要

适用于：

- `create_monitor`
- `update_monitor`
- `get_monitor`

输出重点：

1. 任务名称 / URL
2. 调度策略
3. 步骤列表
4. 当前状态
5. 最近运行状态

## 9.3 执行诊断摘要

适用于：

- `trigger_monitor`
- `get_run`

输出重点：

1. 运行结论
2. 失败步骤
3. 失败原因
4. 关键截图 URL
5. 建议动作

---

## 10. 技能实现建议

## 10.1 推荐实现路径

建议用 **Python skill + HTTP API 封装** 实现，而不是先用浏览器自动化。

建议目录形态：

```text
deploy-all/qwenpaw/working/workspaces/<agent>/skills/web-availability-monitor/
├── SKILL.md
├── scripts/
│   ├── web_monitor_client.py
│   ├── list_dashboard.py
│   ├── manage_monitor.py
│   ├── trigger_monitor.py
│   └── selector_helper.py
└── references/
    └── api.md
```

## 10.2 Python 客户端抽象

建议先抽一个统一 client：

- `get_dashboard()`
- `list_monitors()`
- `get_monitor(monitor_id)`
- `create_monitor(payload)`
- `update_monitor(monitor_id, payload)`
- `publish_monitor(monitor_id)`
- `trigger_monitor(monitor_id, definition=None)`
- `list_runs(monitor_id)`
- `get_run(run_id)`
- `delete_run(run_id)`
- `batch_delete_runs(ids)`
- `selector_helper(url)`

## 10.3 skill 提示词职责

`SKILL.md` 主要负责：

1. 判断用户意图属于查询 / 创建 / 更新 / 执行 / 清理哪一类
2. 从自然语言提炼步骤 DSL
3. 在高风险写操作前明确对象与确认语义
4. 组织对用户友好的摘要结果

真正的 API 调用、重试和错误处理应留在脚本层。

---

## 11. 风险与约束

## 11.1 目标系统可用性依赖

技能会依赖：

- `192.168.134.96:3101`

因此需要考虑：

1. 服务不可达
2. 接口超时
3. 接口 schema 变化

## 11.2 未登录场景不代表永远无认证

本次调研未观察到登录门槛，但文档应按“未来可能需要认证”设计：

1. base URL 可配置
2. Token / Basic Auth / Cookie 预留
3. skill 配置与脚本参数支持认证注入

## 11.3 写操作安全

以下动作不应无确认直接执行：

1. 删除任务
2. 批量删除运行记录
3. 大范围覆盖更新已有任务

## 11.4 locator 不稳定

`selector_helper` 适合做初始建议，但不保证长期稳定。

因此建议：

1. 优先使用 role/text 等语义化 locator
2. 尽量避免脆弱 CSS 路径
3. 复杂页面保留人工确认环节

---

## 12. 分期建议

## Phase 1：可用版

先做：

1. 看板查询
2. 任务列表 / 详情查询
3. 运行详情查询
4. 手工触发执行
5. selector helper

特点：

- 只读 + 少量安全写操作
- 风险最低
- 最快形成可见价值

## Phase 2：编排版

增加：

1. 创建监测任务
2. 更新监测任务
3. 发布任务
4. 自然语言转步骤 DSL

## Phase 3：产品化版

再增加：

1. 失败诊断卡片
2. 运行详情卡片
3. 截图预览 / 链接聚合
4. 与巡检/故障分析联动

---

## 13. 推荐的首版范围

如果下一步开始做技能，建议首版只做下面 5 个动作：

1. `get_dashboard`
2. `list_monitors`
3. `get_monitor`
4. `trigger_monitor`
5. `get_run`

原因：

1. 已有 API 清晰
2. 风险低
3. 最容易先验证价值
4. 用户能立刻问“最近失败了什么 / 某任务现在怎么样 / 帮我手工跑一次”

在首版验证稳定后，再接入 `create_monitor / update_monitor / publish_monitor / selector_helper`。

---

## 14. 结论

这个 Web 可用性监测系统已经具备成熟的任务模型和执行证据链，**非常适合被封装成 QwenPaw 技能**。  
从实现路径上看，最佳方案不是“再造一个浏览器监测器”，而是：

1. **QwenPaw 负责自然语言理解与任务编排**
2. **监测系统负责执行、调度、截图与结果留存**
3. **技能优先调用 HTTP API，浏览器自动化只做兜底或辅助**

因此，`web-availability-monitor` 技能应被定位为：

> 一个面向 Web 业务链路巡检、可用性监测和失败复盘的编排型技能。
