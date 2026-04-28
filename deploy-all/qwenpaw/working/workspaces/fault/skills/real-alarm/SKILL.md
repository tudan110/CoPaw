---
name: real-alarm
category: alarm
tags: [alarm, realtime, incident, severity, alert, monitoring]
triggers: [实时告警, 告警列表, 告警统计, 严重告警, 活跃告警, 端口DOWN, 链路中断, 告警分析]
description: 实时告警管理系统查询和统计分析。支持获取告警列表、统计告警信息、查询告警状态、按级别/设备/类型筛选告警、生成可视化图表。当用户询问告警、告警统计、告警分析、告警报告、告警列表、严重告警、活跃告警、告警级别、设备告警、告警分布、告警趋势、异常事件、系统故障、网络问题、设备状态、端口DOWN、链路中断、CPU过高、内存不足、告警总数、告警数量、告警详情、告警查询时使用。本技能专用于查询和分析告警系统中的实时告警数据，不用于一般编程问题、技术教程、API文档查询或其他非告警相关的任务。
---

# Real Alarm

为实时告警管理系统查询提供最短执行路径。适用于告警列表、告警统计、告警状态、级别/设备/专业分布、特定告警搜索与简要分析。

## 前置配置（给 Agent）

使用本技能前，需要确认技能目录下存在 `.env` 文件并配置了以下必需字段：

```bash
INOE_API_BASE_URL=http://<host>:<port>/prod-api
INOE_API_TOKEN=your_jwt_token_here
```

**获取 API Token 的方式**：
1. 登录告警管理系统
2. 进入个人设置或 API 配置页面
3. 生成或复制 JWT Token
4. 将 Token 填入 `.env` 文件

**配置优先级**：
1. 技能目录下的 `.env` 文件（优先）
2. 项目根目录下的 `.env` 文件（备选）

如果配置缺失或无效，技能会直接返回配置错误信息，不会继续执行请求。

## 触发条件（给 Agent）

当用户提到以下诉求时，优先使用本技能：

- 告警列表 / 告警总数 / 告警详情
- 严重告警 / 活跃告警 / 告警状态分布
- 告警级别 / 告警标题 / 设备告警统计
- 指定设备 / IP / 关键字搜索告警
- 告警分析 / 告警报告 / 可视化统计

若用户问题明显不是告警系统数据查询，不要使用本技能。

## 配置与最短路径（给 Agent）

- 原始查询入口：`uv run scripts/get_alarms.py [options]`
- 统一汇总入口：`uv run scripts/analyze_alarms.py --mode <mode> [options]`
- 页面类别统计入口：`uv run scripts/query_alarm_class_count.py [options]`
- 聊天窗口优先：`uv run scripts/analyze_alarms.py --mode <mode> --output markdown`
- 图表直出：`uv run scripts/analyze_alarms.py --mode <mode> --output markdown-echarts-only`
- 默认读取技能目录下的 `.env`
- 配置只关注 2 个字段：`INOE_API_BASE_URL`、`INOE_API_TOKEN`
- 不要要求用户手动拼接接口 URL
- 不要先做无意义预检查；直接执行真实查询
- 如果缺配置或 token 无效，停止后续分析，直接返回缺失项或错误原因

## 资源分类过滤（neAlias）

当用户提到数据库、网络设备、中间件、操作系统、服务器等资源分类时，必须把分类传给接口字段 `neAlias`，不要先查全量再本地过滤。

如果用户没有提到资源分类，不要传 `neAlias`，保持全量查询。`query_alarm_class_count.py` 也遵循同一规则：只传用户明确给出的 `startTime`、`endTime`、`alarmClass`、`alarmstatus`、`neAlias`。

硬性校验：

- “当前数据库告警”“查询当前数据库告警”“查询数据库当前告警”“数据库实时告警”都必须执行带 `--ne_alias 数据库 --alarm_status 1` 的命令。
- 不允许把不带 `neAlias` 的全量结果当成数据库告警结果。
- 如果结果总数等于全量告警总数，或 Top 告警主要是丢包 / ping 异常，说明漏传了 `neAlias`，必须重跑资源分类查询后再回复。

| 用户说法 | 推荐参数 | 接口 neAlias |
|---------|----------|--------------|
| 数据库 / database / db | `--ne_alias 数据库` | `数据库` |
| 网络设备 / network | `--ne_alias 网络设备` | `网络设备` |
| 中间件 / middleware | `--ne_alias 中间件` | `中间件` |
| 操作系统 / os | `--ne_alias 操作系统` | `操作系统` |
| 服务器 / 计算资源 / server | `--ne_alias 计算资源` | `计算资源` |

配置文件示例：

```bash
INOE_API_BASE_URL=http://<host>:<port>/prod-api
INOE_API_TOKEN=your_jwt_token_here
```

缺配置时，只返回：

- `.env` 路径
- 缺失字段
- 最短填写示例
- "补齐后重试"

## 主流程（给 Agent）

### 1. 先判断查询类型

- **只看前几条 / 简单列表**：直接查询当前页
- **统计 / 分布 / 全量筛选 / 综合分析**：先拿 `total`，再决定是否全量拉取
- **指定告警搜索**：如能通过当前结果过滤解决，则先获取足够数据再过滤

### 2. 默认执行策略

#### 场景 A：简单列表

直接执行：

```bash
uv run scripts/get_alarms.py --page_num 1 --page_size 10
```

如果用户指定资源分类，例如"查询数据库当前告警"或"查询当前数据库告警"，应执行：

```bash
uv run scripts/get_alarms.py --ne_alias 数据库 --alarm_status 1 --page_num 1 --page_size 10
```

#### 场景 B：统计、分布、筛选、分析

优先执行统一汇总脚本：

```bash
uv run scripts/analyze_alarms.py --mode summary --output markdown
```

如果用户指定了资源分类，统计脚本也必须带 `--ne_alias`，例如：

```bash
uv run scripts/analyze_alarms.py --mode summary --ne_alias 数据库 --alarm_status 1 --output markdown
```

若需要更细分的统计，可使用：

```bash
uv run scripts/analyze_alarms.py --mode severity --output markdown
uv run scripts/analyze_alarms.py --mode title --output markdown
uv run scripts/analyze_alarms.py --mode device --output markdown
uv run scripts/analyze_alarms.py --mode speciality --output markdown
```

只有在需要原始分页结果时，才退回 `get_alarms.py`。

如需自行拉全量数据，再按以下方式：

先取总数：

```bash
uv run scripts/get_alarms.py --page_num 1 --page_size 1
```

再按 `total` 获取数据：

- 若 `total <= 100`：一次取完
- 若 `total > 100`：分页抓取，每页 100 条，直到取完

例如：

```bash
uv run scripts/get_alarms.py --page_num 1 --page_size 100
uv run scripts/get_alarms.py --page_num 2 --page_size 100
```

### 3. 数据处理默认规则

- 查询"任务式列表"时，优先返回关键字段，不要原样塞出全部 JSON
- 查询"统计/分布"时，先聚合，再展示表格或图表
- 查询"严重/活跃/某设备/某级别"时，在本地过滤 `rows`
- 如果用户没指定展示字段，默认优先展示：告警标题、告警级别、设备名称、管理IP、告警发生时间、专业、告警状态
- 若匹配结果过多，只展示前 20 条，并说明总数

## 用户意图 -> 推荐动作

**基础查询类**：
- "有多少条告警" / "告警总数是多少" / "现在有几条告警" → 先查询总数，直接返回 `total`
- "列出告警" / "显示告警列表" / "看最近的告警" → 查询第一页或用户指定数量，表格展示
- "查询告警详情" / "查看告警信息" → 查询告警并展示详细信息

**筛选查询类**：
- "有哪些严重告警" / "列出所有严重告警" / "critical告警" → 优先执行 `analyze_alarms.py --mode search --severity 1 --include-alarms`
- "活跃告警有哪些" / "未清除的告警" / "current告rms" → 优先执行 `analyze_alarms.py --mode search --alarm_status 1 --include-alarms`
- "查询数据库当前告警" / "查询当前数据库告警" / "当前数据库告警" / "数据库实时告警" → 优先执行 `analyze_alarms.py --mode search --ne_alias 数据库 --alarm_status 1 --include-alarms`
- "查询网络设备当前告警" / "网络设备实时告警" → 优先执行 `analyze_alarms.py --mode search --ne_alias 网络设备 --alarm_status 1 --include-alarms`
- "查询中间件当前告警" → 优先执行 `analyze_alarms.py --mode search --ne_alias 中间件 --alarm_status 1 --include-alarms`
- "查询操作系统当前告警" → 优先执行 `analyze_alarms.py --mode search --ne_alias 操作系统 --alarm_status 1 --include-alarms`
- "查询服务器当前告警" / "查询计算资源当前告警" → 优先执行 `analyze_alarms.py --mode search --ne_alias 计算资源 --alarm_status 1 --include-alarms`
- "某个设备的告警" / "设备xxx的告警" → 优先执行 `analyze_alarms.py --mode search --device_name <name> --include-alarms`
- "某个IP的告警" / "IP为xxx的告警" → 优先执行 `analyze_alarms.py --mode search --manage_ip <ip> --include-alarms`
- "某个 CI ID 的告警" / "ci id=18 的告警" / "网元ID 18 的告警" → 优先执行 `analyze_alarms.py --mode search --ci_id 18 --include-alarms`

**统计分析类**：
- "统计告警级别" / "各级别告警数量" / "告警严重程度分布" → 优先执行 `analyze_alarms.py --mode severity`
- "统计告警类别" / "告警类别数量" / "当前应用类告警统计" → 可执行 `query_alarm_class_count.py --alarm_status 1 --alarm_class application --output markdown`
- "数据库当前告警类别统计" → 执行 `query_alarm_class_count.py --ne_alias 数据库 --alarm_status 1 --alarm_class application --output markdown`
- "按设备统计告警" / "哪些设备告警最多" / "设备告警排行" → 优先执行 `analyze_alarms.py --mode device`
- "按专业统计告警" / "各专业告警情况" / "IPM/TRM专业告警" → 优先执行 `analyze_alarms.py --mode speciality`
- "按区域统计告警" / "各区域告警分布" / "南京/北京告警情况" → 优先执行 `analyze_alarms.py --mode region`
- "告警类型统计" / "常见告警类型" / "端口DOWN告警数量" → 优先执行 `analyze_alarms.py --mode title`

**搜索查询类**：
- "查端口DOWN告警" / "搜索包含端口的告警" / "port down告警" → 优先执行 `analyze_alarms.py --mode search --keyword 端口`
- "设备xxx的告警" / "搜索设备名称包含xxx的告警" → 优先执行 `analyze_alarms.py --mode search --keyword <device_name>`
- "包含xxx的告警" / "关键字搜索告警" → 优先执行 `analyze_alarms.py --mode search --keyword <keyword>`

**综合分析类**：
- "帮我分析一下告警情况" / "告警整体情况" / "告警分析报告" → 优先执行 `analyze_alarms.py --mode summary`
- "告警趋势分析" / "最近告警变化" / "告警时间分布" → 优先执行 `analyze_alarms.py --mode summary` 并结合时间范围参数
- "生成告警报告" / "告警可视化" / "告警图表" → 优先执行 `analyze_alarms.py --mode summary --output markdown`

**时间范围查询**：
- "昨天的告警" / "最近24小时告警" / "今天的告警" → 使用 `--begin_time` 和 `--end_time` 参数
- "指定时间段的告警" / "2026-03-15到2026-03-16的告警" → 使用时间范围参数查询

**城市/区域查询**：
- "南京的告警" / "某个城市的告警" / "区域告警查询" → 使用 `--cities` 参数筛选

## 输出约定

- 默认输出适合聊天窗口直接展示的 Markdown
- 如果调用 `analyze_alarms.py`，优先附带 `--output markdown`
- `markdown` 输出会自动附带适合页面渲染的 ECharts 代码块（分布类场景）
- `markdown` 输出会自动补一段简短结论，适合直接回复用户
- `markdown-echarts-only` 只输出 ECharts 代码块，适合前端只消费图表
- 不要只把命令发给用户执行
- 列表查询：先给 1 句摘要，再给表格
- 统计查询：先给 1~3 句结论，再给表格或图表
- 综合分析：用分级标题组织为"概览 / 级别 / 标题 / 设备 / 专业 / 区域"
- 单告警查询：用列表或表格展示关键字段；字段很多时分组展示
- 搜索/严重/活跃告警明细在聊天窗口默认只展示前 20 条，并说明总数
- 如果用户按 `ci id`/`neId` 查询，优先在结果里展示 `CI ID` 列，便于确认筛选命中
- `/resource/realalarm/list` 返回里的 `devId` 现在也视为 `resId/CI ID`；当 `neId` 缺失时，优先用 `devId` 回填 `CI ID` 列和本地筛选

图表规则：

- 优先使用 ECharts
- 备选 Mermaid
- 不要生成 PNG 等图片文件
- 图表必须可直接在页面渲染
- `severity` 优先环形图，`title` / `device` 优先柱状图，`speciality` / `region` 优先饼图

## 错误处理规则

- **缺少 `INOE_API_TOKEN` / `INOE_API_BASE_URL`**：直接提示配置缺失，不继续请求
- **401**：提示 token 无效或过期，建议更新 `.env`
- **403**：提示权限不足
- **404**：提示接口地址可能错误
- **408 / 超时**：提示网络或服务响应慢，可稍后重试
- **空结果**：明确说"未找到匹配告警"，不要输出空表格后沉默
- **分页过程中部分页失败**：明确说明已成功获取的页数和失败页，避免假装是完整统计

## 何时读取参考文档

- 用户问典型查询场景或问法时，读取 `references/usage-scenarios.md`
- 用户问接口、分页、鉴权、参数时，读取 `references/api-specification.md`
- 用户问字段含义或返回结构时，读取 `references/response-format.md`
- 用户问如何做统计分析时，读取 `references/data-analysis-guide.md`
- 用户问图表展示形式时，读取 `references/chart-guide.md` 或 `references/echarts-examples.md`

默认不主动加载全部参考文档；只在需要解释细节时再读。

## Few-shot 示例

### 示例 1：查询告警总数

- 用户：现在一共有多少条告警？
- 动作：执行 `uv run scripts/get_alarms.py --page_num 1 --page_size 1`
- 处理：读取返回中的 `total`
- 回复：直接给出总数；如有必要补一句"统计基于当前系统告警列表接口"

### 示例 2：统计严重告警

- 用户：帮我看看有多少严重告警，并列出它们
- 动作：执行 `uv run scripts/analyze_alarms.py --mode search --severity 1 --include-alarms --output markdown`
- 回复：先给严重告警数量，再用 Markdown 表格列出关键字段；若数量很多，只展示前 20 条并说明总数

### 示例 3：查看告警级别分布

- 用户：按告警级别统计告警数量
- 动作：执行 `uv run scripts/analyze_alarms.py --mode severity --output markdown`
- 回复：先给各级别结论，再输出统计表；如适合可补 ECharts 饼图或环形图

### 示例 4：模糊搜索告警

- 用户：查一下标题里包含端口的告警
- 动作：执行 `uv run scripts/analyze_alarms.py --mode search --keyword 端口 --output markdown`
- 回复：说明匹配数量，并表格展示告警标题、设备名称、告警级别、告警发生时间等字段

### 示例 5：按 CI ID 查询告警

- 用户：帮我查 ci id 等于 18 的所有告警
- 动作：执行 `uv run scripts/analyze_alarms.py --mode search --ci_id 18 --include-alarms --output markdown`
- 回复：先说明匹配总数，再表格展示告警标题、设备名称、管理IP、CI ID、告警发生时间、告警状态

## 注意事项

- Token 应只放在本地环境变量或 `.env` 中，不在对话中回显
- 做统计或筛选时，优先确认数据是否已全量获取
- 百分比分布优先用饼图，数量对比优先用柱状图
- 若用户只想快速看结果，避免输出大段原始 JSON
- 告警级别说明：1-严重，2-重要，3-一般，4-提示
- 告警状态说明：0-自动清除，1-活跃，2-同步清除，3-手工清除
- 告警类别说明：sys_log-设备告警，threshold-性能告警，derivative-衍生告警
