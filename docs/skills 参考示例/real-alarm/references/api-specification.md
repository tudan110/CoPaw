# API 规范

本文档描述 `real-alarm` 技能的查询入口、参数、分页策略和错误处理约定。

## 推荐入口

### 1. 原始查询入口

```bash
uv run scripts/get_alarms.py [options]
```

适用于：

- 只查原始分页数据
- 需要精确控制页码和页大小
- 需要指定时间范围查询

### 2. 统一汇总入口

```bash
uv run scripts/analyze_alarms.py --mode <mode> [options]
```

适用于：综合概览、级别/标题/设备/专业/区域分布、严重告警清单、关键字搜索。

聊天窗口推荐：

```bash
uv run scripts/analyze_alarms.py --mode summary --output markdown
```

`markdown` 输出特性：

- 自动生成适合聊天窗口的标题、摘要和表格
- 自动补充简短分析结论
- 分布类模式自动附带 ECharts 配置代码块
- `severity` 默认环形图，`title` / `device` 默认柱状图
- 告警明细默认只展示前 20 条，并补充总数说明

只需要图表代码块时：

```bash
uv run scripts/analyze_alarms.py --mode summary --output markdown-echarts-only
```

### 3. 页面类别统计入口

```bash
uv run scripts/query_alarm_class_count.py [options]
```

适用于 `/resource/alarmQuery/queryAlarmClassCount` 对应的告警类别统计。不传筛选条件时请求体为 `{}`，用于查询全量；指定资源、状态、类别或时间时，只传对应字段。

## 参数说明

### get_alarms.py 参数

| 参数名称 | 类型 | 是否必填 | 说明 | 示例 |
|---------|------|---------|------|------|
| `page_num` | int | 否 | 页码，默认 `1` | `1` |
| `page_size` | int | 否 | 每页数量，默认 `10` | `10`, `100` |
| `token` | str | 否 | JWT 令牌；默认从环境变量 `INOE_API_TOKEN` 读取 | `eyJ...` |
| `api_base_url` | str | 否 | API 基础地址；默认从环境变量 `INOE_API_BASE_URL` 读取 | `http://<host>:<port>` |
| `begin_time` | str | 否 | 开始时间，格式 `YYYY-MM-DD HH:MM:SS`；缺省时按 `REAL_ALARM_QUERY_WINDOW_HOURS` 自动回溯 | `2026-03-15 10:00:00` |
| `end_time` | str | 否 | 结束时间，格式 `YYYY-MM-DD HH:MM:SS`；缺省时取当前时间 | `2026-03-16 10:00:00` |
| `alarm_severitys` | list | 否 | 告警级别列表，对应接口字段 `alarmSeverity`（逗号拼接） | `1 2` |
| `alarm_status` | str | 否 | 告警状态，`1` 表示活跃；脚本内部转换为接口的 `isClear`（语义反转，见下文） | `1` |
| `dev_name` | str | 否 | 设备名称，映射到接口的模糊搜索 `queryKey` | `device-core-01` |
| `manage_ip` | str | 否 | 管理IP，映射到接口的精确字段 `neIp` | `<device-ip>` |
| `ci_id` / `ne_id` | str | 否 | CI/网元 ID；新接口无按 ID 精确过滤字段，纯数字会被忽略，文本会回退到模糊搜索 `queryKey` | `18` |
| `ne_alias` / `neAlias` | str | 否 | 资源分类，对应接口字段 `alarmClassType` | `数据库`, `网络设备`, `中间件`, `操作系统`, `计算资源` |
| `resource_type` / `resource` | str | 否 | 资源分类别名，会映射为 `alarmClassType` | `database`, `network`, `middleware`, `os`, `server` |
| `alarm_title` | str | 否 | 告警标题，映射到接口的模糊搜索 `queryKey` | `端口DOWN` |

### query_alarm_class_count.py 参数

| 参数名称 | 类型 | 是否必填 | 页面字段 | 说明 | 示例 |
|---------|------|---------|----------|------|------|
| `token` | str | 否 | - | JWT 令牌 | `eyJ...` |
| `api_base_url` | str | 否 | - | API 基础地址 | `http://<host>:<port>` |
| `start_time` / `startTime` | str | 否 | `startTime` | 开始时间 | `2026-04-22 12:00:00` |
| `end_time` / `endTime` | str | 否 | `endTime` | 结束时间 | `2026-04-23 12:00:00` |
| `alarm_class` / `alarmClass` | str | 否 | `alarmClass` | 告警类别；页面传 `application` | `application` |
| `alarm_status` / `alarmstatus` | str | 否 | `alarmstatus` | 告警状态 | `1` |
| `ne_alias` / `neAlias` | str | 否 | `neAlias` | 资源分类 | `数据库` |
| `resource_type` / `resource` | str | 否 | `neAlias` | 资源分类别名 | `database`, `network` |
| `output` | str | 否 | - | 输出格式 | `json`, `markdown` |

### analyze_alarms.py 参数

| 参数名称 | 类型 | 是否必填 | 说明 | 示例 |
|---------|------|---------|------|------|
| `mode` | str | 否 | 分析模式，默认 `summary` | `summary`, `severity`, `title`, `device`, `speciality`, `search` |
| `keyword` | str | 否 | 搜索关键字 | `端口` |
| `keyword_field` | str | 否 | 关键字搜索字段，默认 `all` | `all`, `alarmtitle`, `devName`, `manageIp` |
| `severity` | str | 否 | 按告警级别过滤 | `1` |
| `device_name` | str | 否 | 按设备名称过滤 | `device-core-01` |
| `manage_ip` | str | 否 | 按管理IP过滤 | `<device-ip>` |
| `ci_id` / `ne_id` | str | 否 | 按 CI/网元 ID 过滤 | `18` |
| `ne_alias` / `neAlias` | str | 否 | 按资源分类过滤 | `数据库`, `网络设备` |
| `resource_type` / `resource` | str | 否 | 资源分类别名 | `database`, `network` |
| `speciality` | str | 否 | 按专业过滤 | `IPM` |
| `region` | str | 否 | 按区域过滤 | `区域A` |
| `begin_time` | str | 否 | 开始时间 | `2026-03-15 10:00:00` |
| `end_time` | str | 否 | 结束时间 | `2026-03-16 10:00:00` |
| `alarm_severitys` | list | 否 | 告警级别列表 | `1 2` |
| `alarm_status` | str | 否 | 告警状态 | `1` |
| `cities` | list | 否 | 保留参数，新接口无城市过滤字段，传了也不生效 | `南京` |
| `fetch_page_size` | int | 否 | 抓取全量告警时的分页大小，默认 `100` | `100` |
| `top_n` | int | 否 | 分组结果或预览告警数量，默认 `10` | `10`, `20` |
| `include-alarms` | flag | 否 | 输出完整告警预览列表 | - |
| `output` | str | 否 | 输出格式，默认 `json` | `json`, `markdown`, `markdown-echarts-only` |

## 配置

技能目录下的 `.env`（共享 secrets 优先）：

```bash
INOE_API_BASE_URL=http://<host>:<port>
INOE_API_TOKEN=your_jwt_token_here
USE_MOCK_DATA=false
REAL_ALARM_QUERY_WINDOW_HOURS=24
```

读取优先级：

1. 共享 `secrets/` 注入的环境变量（优先）
2. 技能目录 `.env`（回退）
3. 项目根目录 `.env`（最后回退）

`USE_MOCK_DATA=true` 时读取 `mock_data.json`、不发真实请求，适合还没拿到接口权限时先验证技能的参数解析、过滤、渲染逻辑。

## 接口信息

- 实时告警列表：`GET {INOE_API_BASE_URL}/resource/alarm/statistics/hisAlarmList`
- 告警类别统计：`POST {INOE_API_BASE_URL}/resource/alarmQuery/queryAlarmClassCount`
- 鉴权方式：`Authorization: Bearer <token>`
- 实时告警列表请求参数：Query String，`alarmClassType` 只在用户指定资源分类时传
- `hisAlarmList` **强制要求** `beginTime`/`endTime` 时间窗；调用方未传时，脚本按 `REAL_ALARM_QUERY_WINDOW_HOURS`（默认 24 小时）自动回溯生成
- `isClear` 字段与旧接口的 `alarmstatus` **语义相反**：`alarmstatus=1`（活跃）→ `isClear=0`；脚本内部已做转换（`_alarm_status_to_is_clear`），Agent 只需要继续传 `--alarm_status`，不需要关心 `isClear`

## 告警级别

| 级别 | 名称 | 说明 |
|------|------|------|
| 1 | 紧急 | 需要立即处理的紧急故障 |
| 2 | 严重 | 严重告警，需要重点关注 |
| 3 | 普通 | 普通告警 |
| 4 | 预警 | 预警性信息 |

## 告警状态

| 状态 | 名称 | 说明 |
|------|------|------|
| 0 | 自动清除 | 网元自动清除的告警 |
| 1 | 活跃 | 告警未清除，持续中 |
| 2 | 同步清除 | 同步清除的告警 |
| 3 | 手工清除 | 手工清除的告警 |

## 告警类别

| 类别 | 名称 | 说明 |
|------|------|------|
| sys_log | 设备告警 | 设备相关告警 |
| threshold | 性能告警 | 性能指标告警 |
| derivative | 衍生告警 | 衍生告警 |

## 推荐执行策略

### 场景 1：只查总数

```bash
uv run scripts/get_alarms.py --page_num 1 --page_size 1
```

读取响应中的 `total`。

### 场景 2：简单列表

```bash
uv run scripts/get_alarms.py --page_num 1 --page_size 10
```

### 场景 3：查询指定时间范围

```bash
uv run scripts/get_alarms.py --begin_time "2026-03-15 10:00:00" --end_time "2026-03-16 10:00:00"
```

### 场景 4：按 CI ID 查询告警

```bash
uv run scripts/analyze_alarms.py --mode search --ci_id 18 --include-alarms --output markdown
```

注意：新接口没有按资源 ID 精确过滤的字段，纯数字 `ci_id` 只能靠 `search` 模式在本地结果里再筛一遍；如果 `ci_id` 是设备名一类的文本，会回退到接口的模糊搜索 `queryKey`。

### 场景 5：按资源分类查询当前告警

```bash
uv run scripts/analyze_alarms.py --mode search --ne_alias 数据库 --alarm_status 1 --include-alarms --output markdown
```

注意：不传 `neAlias` 时接口返回全量告警，不能把全量总数当作特定资源分类的告警总数。

### 场景 6：统计 / 分布 / 综合分析

```bash
uv run scripts/analyze_alarms.py --mode summary --output markdown
uv run scripts/analyze_alarms.py --mode severity --output markdown
uv run scripts/analyze_alarms.py --mode device --output markdown
uv run scripts/analyze_alarms.py --mode search --severity 1 --include-alarms --output markdown
```

## 分页约定

- 统计或筛选前，应确认数据是否全量获取
- 某页失败时，不要把不完整数据当成完整统计结果
- 若分页中断，应明确说明"已获取 X/Y 页，结果可能不完整"

## 成功与失败判断

- `code = 200`：成功
- 非 `200`：失败
- 命令退出码：成功 `0`，失败 `1`

## 常见错误

| 场景 | 典型表现 | 处理建议 |
|------|----------|----------|
| 缺少 token | 脚本直接报错退出 | 提示补充 `INOE_API_TOKEN` |
| 401 | 认证失败 | 提示 token 无效或过期 |
| 403 | 权限不足 | 提示当前账号无访问权限 |
| 404 | 接口不存在 | 检查 `INOE_API_BASE_URL` |
| 408 / Timeout | 请求超时 | 稍后重试，必要时减少单页数据量 |
| ConnectionError | 连接失败 | 检查网络或服务地址 |
| 时间格式错误 | 提示时间格式无效 | 确保格式为 `YYYY-MM-DD HH:MM:SS` |

## Agent 回复要求

- 不要只返回"命令执行成功"
- 不要原样输出整段 JSON，除非用户明确要求原始结果
- 应从 `total` 和 `rows` 中提炼用户真正需要的结论
- 统计类问题优先使用 `analyze_alarms.py` 的结果
- 聊天场景优先使用 `--output markdown`
- 告警级别应转换为可读名称（紧急/严重/普通/预警）
- 告警状态应转换为可读名称（活跃/已清除）
