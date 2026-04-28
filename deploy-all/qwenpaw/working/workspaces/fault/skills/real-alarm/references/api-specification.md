# API 规范

本文档描述 `real-alarm` 技能的查询入口、参数、分页策略和错误处理约定。

## 推荐入口

### 1. 原始查询入口

统一执行：

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

适用于：

- 综合概览
- 级别 / 标题 / 设备 / 专业 / 区域分布
- 严重告警清单
- 关键字搜索

如果结果要直接回到聊天窗口，推荐：

```bash
uv run scripts/analyze_alarms.py --mode summary --output markdown
```

`markdown` 输出特性：

- 自动生成适合聊天窗口的标题、摘要和表格
- 自动补充简短分析结论
- 分布类模式自动附带 ECharts 配置代码块
- `severity` 默认环形图，`title` / `device` 默认柱状图
- 告警明细默认只展示前 20 条，并补充总数说明

如果只需要图表代码块，可使用：

```bash
uv run scripts/analyze_alarms.py --mode summary --output markdown-echarts-only
```

适用场景：

- 前端只想渲染图表
- 不需要文字摘要和表格
- 需要把图表块嵌入其他响应内容

不要要求用户自行调用 HTTP API。

### 3. 页面类别统计入口

```bash
uv run scripts/query_alarm_class_count.py [options]
```

适用于页面中 `/resource/alarmQuery/queryAlarmClassCount` 对应的告警类别统计。该接口为通用接口，不传筛选条件时请求体为 `{}`，用于查询全量；指定资源、状态、类别或时间时，只传对应字段。

## 参数说明

### get_alarms.py 参数

| 参数名称 | 类型 | 是否必填 | 说明 | 示例 |
|---------|------|---------|------|------|
| `page_num` | int | 否 | 页码，默认 `1` | `1` |
| `page_size` | int | 否 | 每页数量，默认 `10` | `10`, `100`, `1000` |
| `token` | str | 否 | JWT 令牌；默认从环境变量 `INOE_API_TOKEN` 读取 | `eyJ...` |
| `api_base_url` | str | 否 | API 基础地址；默认从环境变量 `INOE_API_BASE_URL` 读取 | `http://host:port` |
| `begin_time` | str | 否 | 开始时间，格式 `YYYY-MM-DD HH:MM:SS` | `2026-03-15 10:00:00` |
| `end_time` | str | 否 | 结束时间，格式 `YYYY-MM-DD HH:MM:SS` | `2026-03-16 10:00:00` |
| `alarm_severitys` | list | 否 | 告警级别列表，如 `["1", "2"]` | `1 2` |
| `alarm_status` | str | 否 | 告警状态，`1` 表示活跃 | `1` |
| `dev_name` | str | 否 | 设备名称 | `SN-XA-LHL-A.Leaf-4` |
| `manage_ip` | str | 否 | 管理IP | `4.155.10.35` |
| `ci_id` / `ne_id` | str | 否 | CI/网元 ID，对应请求体字段 `neId` | `18` |
| `ne_alias` / `neAlias` | str | 否 | 资源分类，对应请求体字段 `neAlias` | `数据库`, `网络设备`, `中间件`, `操作系统`, `计算资源` |
| `resource_type` / `resource` | str | 否 | 资源分类别名，会映射为 `neAlias` | `database`, `network`, `middleware`, `os`, `server` |
| `cities` | list | 否 | 城市列表 | `南京 秦淮区` |
| `alarm_title` | str | 否 | 告警标题 | `端口DOWN` |

### query_alarm_class_count.py 参数

| 参数名称 | 类型 | 是否必填 | 页面字段 | 说明 | 示例 |
|---------|------|---------|----------|------|------|
| `token` | str | 否 | - | JWT 令牌；默认从环境变量 `INOE_API_TOKEN` 读取 | `eyJ...` |
| `api_base_url` | str | 否 | - | API 基础地址；默认从环境变量 `INOE_API_BASE_URL` 读取 | `http://host:port/prod-api` |
| `start_time` / `startTime` | str | 否 | `startTime` | 开始时间，格式 `YYYY-MM-DD HH:MM:SS`；不传则不带该字段 | `2026-04-22 12:00:00` |
| `end_time` / `endTime` | str | 否 | `endTime` | 结束时间，格式 `YYYY-MM-DD HH:MM:SS`；不传则不带该字段 | `2026-04-23 12:00:00` |
| `alarm_class` / `alarmClass` | str | 否 | `alarmClass` | 告警类别；页面数据库概览传 `application` | `application` |
| `alarm_status` / `alarmstatus` | str | 否 | `alarmstatus` | 告警状态；页面当前告警传 `1` | `1` |
| `ne_alias` / `neAlias` | str | 否 | `neAlias` | 资源分类；不传则查询全部资源分类 | `数据库` |
| `resource_type` / `resource` | str | 否 | `neAlias` | 资源分类别名，会映射为 `neAlias` | `database`, `network`, `middleware`, `os`, `server` |
| `output` | str | 否 | - | 输出格式 | `json`, `markdown` |

### analyze_alarms.py 参数

| 参数名称 | 类型 | 是否必填 | 说明 | 示例 |
|---------|------|---------|------|------|
| `mode` | str | 否 | 分析模式，默认 `summary` | `summary`, `severity`, `title`, `device`, `speciality`, `search` |
| `keyword` | str | 否 | 搜索关键字 | `端口` |
| `keyword_field` | str | 否 | 关键字搜索字段，默认 `all` | `all`, `alarmtitle`, `devName`, `manageIp`, `speciality`, `alarmregion` |
| `severity` | str | 否 | 按告警级别过滤 | `1` |
| `device_name` | str | 否 | 按设备名称过滤 | `SN-XA-LHL-A.Leaf-4` |
| `manage_ip` | str | 否 | 按管理IP过滤 | `4.155.10.35` |
| `ci_id` / `ne_id` | str | 否 | 按 CI/网元 ID 过滤，对应请求体字段 `neId` | `18` |
| `ne_alias` / `neAlias` | str | 否 | 按资源分类过滤，对应请求体字段 `neAlias` | `数据库`, `网络设备`, `中间件`, `操作系统`, `计算资源` |
| `resource_type` / `resource` | str | 否 | 资源分类别名，会映射为 `neAlias` | `database`, `network`, `middleware`, `os`, `server` |
| `speciality` | str | 否 | 按专业过滤 | `IPM` |
| `region` | str | 否 | 按区域过滤 | `XA` |
| `begin_time` | str | 否 | 开始时间，格式 `YYYY-MM-DD HH:MM:SS` | `2026-03-15 10:00:00` |
| `end_time` | str | 否 | 结束时间，格式 `YYYY-MM-DD HH:MM:SS` | `2026-03-16 10:00:00` |
| `alarm_severitys` | list | 否 | 告警级别列表 | `1 2` |
| `alarm_status` | str | 否 | 告警状态 | `1` |
| `cities` | list | 否 | 城市列表 | `南京 秦淮区` |
| `fetch_page_size` | int | 否 | 抓取全量告警时的分页大小，默认 `100` | `100` |
| `top_n` | int | 否 | 分组结果或预览告警数量，默认 `10` | `10`, `20` |
| `include-alarms` | flag | 否 | 输出完整告警预览列表 | - |
| `output` | str | 否 | 输出格式，默认 `json` | `json`, `markdown`, `markdown-echarts-only` |

## 配置

技能目录下的 `.env`：

```bash
INOE_API_BASE_URL=http://<host>:<port>/prod-api
INOE_API_TOKEN=your_jwt_token_here
```

配置文件位置：当前 skill 目录下的 `.env`

读取优先级：

1. 技能目录 `.env`
2. 项目根目录 `.env`

## 接口信息

- 实时列表请求方式：`POST`
- 实时列表接口地址：`{INOE_API_BASE_URL}/resource/realalarm/list`
- 告警类别统计请求方式：`POST`
- 告警类别统计接口地址：`{INOE_API_BASE_URL}/resource/alarmQuery/queryAlarmClassCount`
- 鉴权方式：`Authorization: Bearer <token>`
- 实时列表请求体：JSON 格式，包含分页参数和筛选条件；`neAlias` 只有在用户指定资源分类时才传，不指定时查询全部
- 告警类别统计请求体：页面确认字段为 `startTime`、`endTime`、`alarmClass`、`alarmstatus`、`neAlias`；脚本只传明确给出的字段，不指定时查询全部
- 告警类别统计返回：当前接口会直接返回数组，例如元素包含 `alarmSeverity`、`count`；脚本会规范化为 `{"code": 200, "msg": "操作成功", "data": [...]}` 便于 Agent 统一处理
- 资源分类字段：`neAlias`，可用值包括 `数据库`、`网络设备`、`中间件`、`操作系统`、`计算资源`
- 返回兼容约定：接口返回中的 `devId` 现在表示当前告警对应的 `resId/CI ID`；skill 在展示和本地筛选时会把 `devId` 作为 `CI ID` 的回退字段

## 告警级别说明

| 级别 | 名称 | 说明 |
|------|------|------|
| 1 | 严重 | 需要立即处理的严重故障 |
| 2 | 重要 | 重要告警，需要关注 |
| 3 | 一般 | 一般性告警 |
| 4 | 提示 | 提示性信息 |

## 告警状态说明

| 状态 | 名称 | 说明 |
|------|------|------|
| 0 | 自动清除 | 网元自动清除的告警 |
| 1 | 活跃 | 告警未清除，持续中 |
| 2 | 同步清除 | 同步清除的告警 |
| 3 | 手工清除 | 手工清除的告警 |

## 告警类别说明

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

适合"列出告警""看前几条告警"。

### 场景 3：查询指定时间范围

```bash
uv run scripts/get_alarms.py --begin_time "2026-03-15 10:00:00" --end_time "2026-03-16 10:00:00"
```

### 场景 4：按 CI ID 查询告警

```bash
uv run scripts/get_alarms.py --ci_id 18 --page_num 1 --page_size 100
uv run scripts/analyze_alarms.py --mode search --ci_id 18 --include-alarms --output markdown
```

### 场景 5：按资源分类查询当前告警

```bash
uv run scripts/get_alarms.py --ne_alias 数据库 --alarm_status 1 --page_num 1 --page_size 10
uv run scripts/analyze_alarms.py --mode search --ne_alias 数据库 --alarm_status 1 --include-alarms --output markdown
```

注意：“查询当前数据库告警”和“查询数据库当前告警”等价，都必须传 `neAlias=数据库`。如果不传 `neAlias`，接口会返回全量告警，不能把全量总数当作数据库告警总数。

资源分类映射：

| 用户说法 | 接口 `neAlias` |
|---------|----------------|
| 数据库 / database / db | `数据库` |
| 网络设备 / network | `网络设备` |
| 中间件 / middleware | `中间件` |
| 操作系统 / os | `操作系统` |
| 服务器 / 计算资源 / server | `计算资源` |

### 场景 6：调用页面类别统计接口

查询全量告警类别统计：

```bash
uv run scripts/query_alarm_class_count.py --output markdown
```

查询数据库当前应用类告警统计：

```bash
uv run scripts/query_alarm_class_count.py --ne_alias 数据库 --alarm_status 1 --alarm_class application --output markdown
```

### 场景 7：统计 / 分布 / 筛选 / 综合分析

优先使用：

```bash
uv run scripts/analyze_alarms.py --mode summary --output markdown
uv run scripts/analyze_alarms.py --mode severity --output markdown
uv run scripts/analyze_alarms.py --mode device --output markdown
uv run scripts/analyze_alarms.py --mode search --severity 1 --include-alarms --output markdown
```

`analyze_alarms.py` 会自动分页抓取全部告警，再做本地汇总。

如果必须手动取数，再先取总数，再决定是否全量拉取：

- 若 `total <= 100`：一次性拉取
- 若 `total > 100`：分页拉取，每页 `100`

示例：

```bash
uv run scripts/get_alarms.py --page_num 1 --page_size 1
uv run scripts/get_alarms.py --page_num 1 --page_size 100
uv run scripts/get_alarms.py --page_num 2 --page_size 100
```

## 分页约定

- 统计或筛选前，应确认数据是否全量获取
- 某页失败时，不要把不完整数据当成完整统计结果
- 若分页中断，应明确说明"已获取 X/Y 页，结果可能不完整"

## 成功与失败判断

- `code = 200`：成功
- 非 `200`：失败
- 命令退出码：成功返回 `0`，失败返回 `1`

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
- 统计类问题优先使用 `analyze_alarms.py` 的结果，而不是手动重复聚合
- 聊天场景优先使用 `--output markdown`
- 告警级别应转换为可读名称（严重/重要/一般/提示）
- 告警状态应转换为可读名称（活跃/已清除）
