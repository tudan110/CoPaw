---
name: real-alarm
category: alarm
tags: [alarm, realtime, incident, severity, alert, monitoring]
triggers: [实时告警, 告警列表, 告警统计, 严重告警, 活跃告警, 端口DOWN, 链路中断, 告警分析]
description: 实时告警管理系统查询和统计分析。支持获取告警列表、统计告警信息、查询告警状态、按级别/设备/类型筛选告警、生成可视化图表。当用户询问告警、告警统计、告警分析、告警报告、告警列表、严重告警、活跃告警、告警级别、设备告警、告警分布、告警趋势、异常事件、系统故障、网络问题、设备状态、端口DOWN、链路中断、CPU过高、内存不足、告警总数、告警数量、告警详情、告警查询时使用。本技能专用于查询和分析告警系统中的实时告警数据，不用于一般编程问题、技术教程、API文档查询或其他非告警相关的任务。
---

# Real Alarm

为实时告警管理系统查询提供最短执行路径。适用于告警列表、告警统计、告警状态、级别/设备/专业分布、特定告警搜索与简要分析。

## 告警 MCP 优先级

本工作区已启用 `alarm` MCP Server。Agent 必须优先直接调用 `alarm__queryHistoricalAlarms` 获取告警数据；不要自行使用 `curl`、`requests`、SSE 或 JSON-RPC，也不要为此编写额外 MCP 客户端。

仅在 alarm MCP Driver 未加载、客户端/工具不可用或协议响应无法解析时，才允许回退到旧脚本路径（见末尾"旧脚本回退路径"）。MCP Tool 返回的可解析业务错误（4xx/5xx、鉴权、参数错误）必须 fail-fast，不换参数重试，也不回退脚本。

## 触发条件（给 Agent）

当用户提到以下诉求时，优先使用本技能：

- 告警列表 / 告警总数 / 告警详情
- 严重告警 / 活跃告警 / 告警状态分布
- 告警级别 / 告警标题 / 设备告警统计
- 指定设备 / IP / 关键字搜索告警
- 告警分析 / 告警报告 / 可视化统计

若用户问题明显不是告警系统数据查询，不要使用本技能。

## 告警 MCP 调用

### 唯一 MCP Tool

| MCP Tool | 用途 | 调用约束 |
|---|---|---|
| `alarm__queryHistoricalAlarms` | 查询告警列表，返回 `total` + `rows` | 每次调用只返回一页；统计/分析场景必须全量拉取 |

### 参数映射

| 脚本原参数 | MCP 参数 | 说明 |
|---|---|---|
| `--page_num` / `--page_size` | `pageNum` / `pageSize` | 分页参数，直接对应 |
| `--alarm_status 1` | `isClear: "0"` | 活跃告警：isClear=0 表示未清除（注意传字符串） |
| `--severity 1` | `alarmSeverity: "1"` | 告警级别，多个值可逗号分隔如 `"1,2"` |
| `--keyword` | `queryKey` | 关键字模糊搜索，可匹配资源名、IP、标题等 |
| `--manage_ip` | `neIp` | 管理 IP，直接对应 |
| `--begin_time` / `--end_time` | `beginTime` / `endTime` | 时间范围，格式 `YYYY-MM-DD HH:MM:SS`，**必填** |
| `--ne_alias` | `alarmClassType` | 资源分类（注意：参数名含 ClassType 但实际过滤 `neAlias`），枚举：数据库/网络设备/中间件/操作系统/计算资源 |
| `--alarm_class` | **无直接参数** | 需拉取后按 `alarmclass` 字段本地过滤（sys_log/threshold/derivative/pems/application） |
| `--device_name` | **无直接参数** | 需拉取后按 `devName` 字段本地过滤 |
| `--ci_id` | **无直接参数** | 需拉取后按 `devId` 字段本地过滤 |
| `--cities` | **无直接参数** | 需拉取后按 `alarmregion` 字段本地过滤 |

### 分页策略

1. **先查总数**：`pageNum=1, pageSize=1`，获取 `total`
2. **total ≤ 100**：单次 `pageSize=total` 取完
3. **total > 100**：逐页 `pageSize=100` 拉取，直到取完所有页
4. **统计/分析/分布模式必须全量拉取**，不能只取第一页或分页不完整
5. 简单列表场景（只看前 N 条）不需要全量拉取

### 返回字段说明

MCP 返回的 `rows` 中每条告警包含以下关键字段：

| 字段 | 含义 | 取值范围 |
|---|---|---|
| `alarmtitle` | 告警标题 | 文本 |
| `alarmseverity` | 告警级别 | 1-紧急，2-严重，3-普通，4-预警 |
| `alarmstatus` | 告警状态 | 0-自动清除，1-活跃，2-同步清除，3-手工清除 |
| `alarmclass` | 告警类别 | sys_log/设备告警，threshold/性能，derivative/衍生，pems/动环，application/应用（无 MCP 参数，需本地过滤） |
| `devId` | 资源 CI ID | 整数 |
| `devName` | 设备名称 | 文本 |
| `manageIp` | 管理 IP | 文本 |
| `neAlias` | 资源分类 | 如"数据库""网络设备""中间件""操作系统""计算资源" |
| `speciality` | 专业分类 | 文本 |
| `alarmregion` | 告警区域 | 文本 |
| `eventtime` | 告警发生时间 | 时间戳 |
| `eventlasttime` | 最后发生时间 | 时间戳 |
| `alarmuniqueid` | 告警唯一标识 | 文本 |
| `alarmDuration` | 告警持续时间 | 文本 |

### 场景 A：简单列表 / 总数查询

调用 1 次 `alarm__queryHistoricalAlarms`，不需要全量拉取。`beginTime`/`endTime` 必填，推荐默认传最近 24 小时。

```json
{
  "beginTime": "<24小时前>",
  "endTime": "<当前时间>",
  "pageNum": 1,
  "pageSize": 10,
  "isClear": "0"
}
```

- 只看总数 → `pageSize: 1`，从返回中读取 `total`
- 看最近告警 → 默认 `pageSize: 10`，传最近 24 小时时间范围
- 看活跃告警 → `isClear: "0"`（注意传字符串）

### 场景 B：统计 / 分布 / 综合分析

必须全量拉取后，Agent 在本地按字段分组聚合：

- **按级别统计** → 按 `alarmseverity` 字段分组计数，用环形图展示
- **按设备统计** → 按 `devName` 字段分组计数，取 Top 10，用柱状图展示
- **按专业统计** → 按 `speciality` 字段分组计数，用饼图展示（注意：该字段可能为空，空值时标注"未分类"）
- **按区域统计** → 按 `alarmregion` 字段分组计数，用饼图展示
- **按标题统计** → 按 `alarmtitle` 字段分组计数，取 Top 10，用柱状图展示
- **按类别统计** → 按 `alarmclass` 字段分组计数，用饼图展示
- **综合概览** → 先做总览摘要（总数/活跃数/严重数/紧急数），再按级别和设备展开

### 场景 C：筛选查询

- **有 MCP 参数直接支持的筛选**：`alarmSeverity`、`isClear`、`queryKey`、`neIp`、`alarmClassType`、`beginTime`/`endTime` → 直接传参
- **无 MCP 参数支持的筛选**：`devName`（设备名）、`devId`（CI ID）、`alarmregion`（区域）、`alarmclass`（告警类别 sys_log/threshold/derivative）→ 全量拉取后按对应字段本地过滤

### 资源分类过滤（neAlias）

使用 `alarmClassType` 参数直接过滤（注意：参数名含 ClassType 但实际过滤的是 `neAlias` 字段，不是 `alarmclass`）。枚举值：

| 用户说法 | MCP 参数 |
|---------|----------|
| 数据库 / database / db | `alarmClassType: "数据库"` |
| 网络设备 / network | `alarmClassType: "网络设备"` |
| 中间件 / middleware | `alarmClassType: "中间件"` |
| 操作系统 / os | `alarmClassType: "操作系统"` |
| 服务器 / 计算资源 / server | `alarmClassType: "计算资源"` |

硬性规则：

- "当前数据库告警""查询数据库当前告警""数据库实时告警" → 直接传 `alarmClassType: "数据库"` + `isClear: "0"`
- 不允许把不带 `alarmClassType` 的全量结果当成分类告警结果
- 如果返回结果总数等于全量告警总数，或 Top 告警主要是丢包/ping 异常，说明 `alarmClassType` 可能未生效，需重新确认

## 用户意图 -> 推荐动作

**基础查询类**：
- "有多少条告警" / "告警总数是多少" → 调 `alarm__queryHistoricalAlarms(pageNum=1, pageSize=1)`，返回 `total`
- "列出告警" / "显示告警列表" → 调 `alarm__queryHistoricalAlarms(pageNum=1, pageSize=10)`，表格展示
- "查询告警详情" / "查看告警信息" → 查询告警并展示详细信息

**筛选查询类**：
- "有哪些严重告警" / "critical 告警" → 调 `alarm__queryHistoricalAlarms(alarmSeverity=1)`，全量拉取后展示
- "活跃告警有哪些" / "未清除的告警" → 调 `alarm__queryHistoricalAlarms(isClear=0)`，全量拉取
- "查询数据库当前告警" / "数据库实时告警" → 调 `alarm__queryHistoricalAlarms(alarmClassType="数据库", isClear="0")`
- "查询网络设备当前告警" → 同上，`alarmClassType="网络设备"`
- "查询中间件当前告警" → 同上，`alarmClassType="中间件"`
- "查询操作系统当前告警" → 同上，`alarmClassType="操作系统"`
- "查询服务器当前告警" → 同上，`alarmClassType="计算资源"`
- "某个设备的告警" / "设备 xxx 的告警" → 全量拉取后本地过滤 `devName` 匹配
- "某个 IP 的告警" → 直接传 `neIp` 参数
- "某个 CI ID 的告警" → 全量拉取后本地过滤 `devId` 匹配

**统计分析类**：
- "统计告警级别" / "告警严重程度分布" → 全量拉取后按 `alarmseverity` 分组计数，环形图
- "统计告警类别" / "当前应用类告警统计" → 全量拉取后按 `alarmclass` 分组计数，饼图
- "数据库当前告警类别统计" → 调 `alarm__queryHistoricalAlarms(alarmClassType="数据库", isClear="0")`，全量拉取后按 `alarmclass` 分组
- "按设备统计告警" / "哪些设备告警最多" → 全量拉取后按 `devName` 分组计数，取 Top 10，柱状图
- "按专业统计告警" → 全量拉取后按 `speciality` 分组计数，饼图
- "按区域统计告警" → 全量拉取后按 `alarmregion` 分组计数，饼图
- "告警类型统计" / "端口 DOWN 告警数量" → 全量拉取后按 `alarmtitle` 分组计数，取 Top 10，柱状图

**搜索查询类**：
- "查端口 DOWN 告警" / "搜索包含端口的告警" → 调 `alarm__queryHistoricalAlarms(queryKey="端口")`
- "设备 xxx 的告警" / "搜索设备名称包含 xxx" → 全量拉取后本地过滤 `devName` 包含关键字
- "包含 xxx 的告警" / "关键字搜索告警" → 直接传 `queryKey` 参数

**综合分析类**：
- "帮我分析一下告警情况" / "告警分析报告" → 全量拉取，按"概览 / 级别 / 设备 / 专业 / 区域"结构组织
- "告警趋势分析" / "最近告警变化" → 全量拉取并结合 `beginTime`/`endTime` 时间范围
- "生成告警报告" / "告警可视化" → 全量拉取，各维度生成 ECharts 图表

**时间范围查询**：
- "昨天的告警" / "最近 24 小时告警" → 传 `beginTime` 和 `endTime` 参数
- "指定时间段的告警" → 传 `beginTime` 和 `endTime` 参数

**城市/区域查询**：
- "南京的告警" / "某个城市的告警" → 全量拉取后本地过滤 `alarmregion` 匹配

## 输出约定

- 默认输出适合聊天窗口直接展示的 Markdown
- 列表查询：先给 1 句摘要，再给表格
- 统计查询：先给 1~3 句结论，再给表格或图表
- 综合分析：用分级标题组织为"概览 / 级别 / 设备 / 专业 / 区域"
- 单告警查询：用列表或表格展示关键字段；字段很多时分组展示
- 搜索/严重/活跃告警明细在聊天窗口默认只展示前 20 条，并说明总数
- 如果用户按 `ci id`/`neId` 查询，优先在结果里展示 `CI ID` 列，便于确认筛选命中
- 返回里的 `devId` 视为 `resId/CI ID`；当 `neId` 缺失时，优先用 `devId` 回填 `CI ID` 列和本地筛选
- 不要只把命令发给用户执行

图表规则：

- 优先使用 ECharts
- 备选 Mermaid
- 不要生成 PNG 等图片文件
- 图表必须可直接在页面渲染
- `severity` 优先环形图，`title` / `device` 优先柱状图，`speciality` / `region` 优先饼图

## 错误处理规则

- **MCP Tool 返回上游错误、协议错误或不可解析结果**：立即 fail-fast，不换参数反复重试，不回退脚本
- **MCP Driver 未加载、客户端/工具不可用或协议无法解析**：回退到旧脚本路径（见末尾），并在过程说明中写明回退原因
- **空结果**：明确说"未找到匹配告警"，不要输出空表格后沉默
- **分页过程中部分页失败**：明确说明已成功获取的页数和失败页，避免假装是完整统计
- **本地过滤后无结果**：明确说明过滤条件与结果，不输出空表格

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
- 动作：调用 `alarm__queryHistoricalAlarms(pageNum=1, pageSize=1)`
- 处理：读取返回中的 `total`
- 回复：直接给出总数；如有必要补一句"统计基于当前系统告警列表接口"

### 示例 2：统计严重告警

- 用户：帮我看看有多少严重告警，并列出它们
- 动作：调用 `alarm__queryHistoricalAlarms(alarmSeverity=2)`，全量拉取
- 回复：先给严重告警数量，再用 Markdown 表格列出关键字段；若数量很多，只展示前 20 条并说明总数

### 示例 3：查看告警级别分布

- 用户：按告警级别统计告警数量
- 动作：调用 `alarm__queryHistoricalAlarms` 全量拉取，按 `alarmseverity` 字段分组计数
- 回复：先给各级别结论，再输出统计表；如适合可补 ECharts 环形图

### 示例 4：模糊搜索告警

- 用户：查一下标题里包含端口的告警
- 动作：调用 `alarm__queryHistoricalAlarms(queryKey="端口")`，全量拉取
- 回复：说明匹配数量，并表格展示告警标题、设备名称、告警级别、告警发生时间等字段

### 示例 5：按 CI ID 查询告警

- 用户：帮我查 ci id 等于 18 的所有告警
- 动作：调用 `alarm__queryHistoricalAlarms` 全量拉取活跃告警，本地过滤 `devId == "18"`
- 回复：先说明匹配总数，再表格展示告警标题、设备名称、管理 IP、CI ID、告警发生时间、告警状态

### 示例 6：查询数据库当前告警

- 用户：查询当前数据库告警
- 动作：调用 `alarm__queryHistoricalAlarms(isClear=0)` 全量拉取活跃告警，本地过滤 `neAlias == "数据库"`
- 校验：确认过滤后总数不等于全量总数，且告警标题不是以丢包/ping 异常为主
- 回复：先给摘要（数据库当前告警 X 条），再表格展示

## 旧脚本回退路径

仅当 alarm MCP Driver 未加载、客户端/工具不可用或协议响应无法解析时，才执行以下命令。脚本自动从环境变量读取 `INOE_API_TOKEN` 和 `INOE_API_BASE_URL`（由设置页热加载），无需手动配置 `.env`。

**场景 A：简单列表**

```bash
python3 scripts/get_alarms.py --page_num 1 --page_size 10
```

**场景 B：统一汇总**

```bash
python3 scripts/analyze_alarms.py --mode summary --output markdown
```

**场景 C：类别统计**

```bash
python3 scripts/query_alarm_class_count.py --alarm_status 1 --output markdown
```

回退时必须在过程说明中写明回退原因（如 `alarm-mcp-unavailable` 或 `alarm-mcp-protocol-error`）。

## 注意事项

- 凭证由设置页统一管理，不要在对话中回显 Token
- 做统计或筛选时，优先确认数据是否已全量获取
- 百分比分布优先用饼图，数量对比优先用柱状图
- 若用户只想快速看结果，避免输出大段原始 JSON
- 告警级别说明：1-紧急，2-严重，3-普通，4-预警
- 告警状态说明：0-自动清除，1-活跃，2-同步清除，3-手工清除
- 告警类别说明：sys_log-设备告警，threshold-性能告警，derivative-衍生告警