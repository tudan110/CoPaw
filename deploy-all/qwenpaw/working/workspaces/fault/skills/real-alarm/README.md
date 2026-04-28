# 实时告警技能 (RealAlarm)

## 简介

实时告警技能用于查询和分析告警系统的实时告警数据。支持告警列表查询、统计分析、多维度筛选和可视化展示。

## 功能特性

- **告警查询**：支持分页查询、时间范围查询、资源分类筛选、多条件筛选
- **页面统计接口**：支持 `/resource/alarmQuery/queryAlarmClassCount`，按页面字段查询告警类别统计
- **统计分析**：按级别、标题、设备、专业、区域等多维度统计
- **数据筛选**：支持关键字搜索、设备筛选、级别筛选等
- **CI ID 兼容**：支持把接口返回中的 `devId` 识别为当前告警对应的 `resId/ci id`
- **可视化展示**：自动生成 ECharts 图表，支持饼图、柱状图、环形图等
- **多种输出格式**：支持 JSON、Markdown、图表代码块等输出格式

## 快速开始

### 1. 配置环境

复制环境变量示例文件并配置：

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入实际的 API 配置：

```bash
INOE_API_BASE_URL=http://<host>:<port>/prod-api
INOE_API_TOKEN=your_jwt_token_here
```

### 2. 查询告警

#### 查询告警总数

```bash
uv run scripts/get_alarms.py --page_num 1 --page_size 1
```

#### 查询告警列表

```bash
uv run scripts/get_alarms.py --page_num 1 --page_size 10
```

#### 查询指定时间范围的告警

```bash
uv run scripts/get_alarms.py --begin_time "2026-03-15 10:00:00" --end_time "2026-03-16 10:00:00"
```

### 3. 分析告警

#### 综合分析

```bash
uv run scripts/analyze_alarms.py --mode summary --output markdown
```

#### 按告警级别统计

```bash
uv run scripts/analyze_alarms.py --mode severity --output markdown
```

#### 按设备统计

```bash
uv run scripts/analyze_alarms.py --mode device --output markdown
```

#### 搜索严重告警

```bash
uv run scripts/analyze_alarms.py --mode search --severity 1 --include-alarms --output markdown
```

#### 搜索关键字

```bash
uv run scripts/analyze_alarms.py --mode search --keyword 端口 --output markdown
```

#### 页面告警类别统计

```bash
uv run scripts/query_alarm_class_count.py --alarm_status 1 --alarm_class application --output markdown
```

如果要查数据库当前告警类别统计：

```bash
uv run scripts/query_alarm_class_count.py --ne_alias 数据库 --alarm_status 1 --alarm_class application --output markdown
```

## 使用说明

### 脚本说明

#### get_alarms.py

基础查询脚本，用于直接查询告警列表数据。

**主要参数**：
- `--page_num`: 页码（默认 1）
- `--page_size`: 每页数量（默认 10）
- `--begin_time`: 开始时间（格式：YYYY-MM-DD HH:MM:SS）
- `--end_time`: 结束时间（格式：YYYY-MM-DD HH:MM:SS）
- `--alarm_severitys`: 告警级别列表（如：1 2）
- `--alarm_status`: 告警状态（1-活跃，0-已清除）
- `--dev_name`: 设备名称
- `--manage_ip`: 管理IP
- `--ci_id` / `--ne_id`: CI/网元 ID，对应接口字段 `neId`
- `--ne_alias` / `--neAlias`: 资源分类，对应接口字段 `neAlias`
- `--resource_type` / `--resource`: 资源分类别名，会映射为 `neAlias`
- `--cities`: 城市列表
- `--alarm_title`: 告警标题

#### analyze_alarms.py

统一汇总脚本，用于统计分析告警数据。

**主要参数**：
- `--mode`: 分析模式（summary/severity/title/device/speciality/region/search）
- `--keyword`: 搜索关键字
- `--severity`: 按告警级别过滤
- `--device_name`: 按设备名称过滤
- `--manage_ip`: 按管理IP过滤
- `--ci_id` / `--ne_id`: 按 CI/网元 ID 过滤
- `--ne_alias` / `--neAlias`: 按资源分类过滤，对应接口字段 `neAlias`
- `--resource_type` / `--resource`: 资源分类别名，会映射为 `neAlias`
- `--speciality`: 按专业过滤
- `--begin_time`: 开始时间
- `--end_time`: 结束时间
- `--alarm_severitys`: 告警级别列表
- `--alarm_status`: 告警状态
- `--cities`: 城市列表
- `--include-alarms`: 包含完整告警列表
- `--output`: 输出格式（json/markdown/markdown-echarts-only）

#### query_alarm_class_count.py

页面告警类别统计脚本，对应接口 `/resource/alarmQuery/queryAlarmClassCount`。

**主要参数**：
- `--start_time` / `--startTime`: 开始时间，对应页面字段 `startTime`
- `--end_time` / `--endTime`: 结束时间，对应页面字段 `endTime`
- `--alarm_class` / `--alarmClass`: 告警类别，对应页面字段 `alarmClass`
- `--alarm_status` / `--alarmstatus`: 告警状态，对应页面字段 `alarmstatus`
- `--ne_alias` / `--neAlias`: 资源分类，对应页面字段 `neAlias`
- `--resource_type` / `--resource`: 资源分类别名，会映射为 `neAlias`
- `--output`: 输出格式（json/markdown）

未指定的筛选条件不会出现在请求体中。例如不传 `neAlias` 就查全部资源分类。

### 输出格式

#### JSON 格式

```bash
uv run scripts/analyze_alarms.py --mode summary --output json
```

适合程序调用和数据交换。

#### Markdown 格式

```bash
uv run scripts/analyze_alarms.py --mode summary --output markdown
```

适合聊天窗口展示，包含标题、摘要、表格和图表。

#### 图表代码块格式

```bash
uv run scripts/analyze_alarms.py --mode summary --output markdown-echarts-only
```

只输出 ECharts 图表代码块，适合前端渲染。

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
| 1 | 活跃 | 告警未清除，持续中 |
| 0 | 已清除 | 告警已恢复 |

## 常见使用场景

### 场景 1：查询严重告警

```bash
uv run scripts/analyze_alarms.py --mode search --severity 1 --include-alarms --output markdown
```

### 场景 2：查询活跃告警

```bash
uv run scripts/analyze_alarms.py --mode search --alarm_status 1 --include-alarms --output markdown
```

### 场景 3：按告警类型统计

```bash
uv run scripts/analyze_alarms.py --mode title --output markdown
```

### 场景 4：按设备统计

```bash
uv run scripts/analyze_alarms.py --mode device --output markdown
```

### 场景 5：查询指定设备的告警

```bash
uv run scripts/analyze_alarms.py --mode search --device_name SN-XA-LHL-A --include-alarms --output markdown
```

### 场景 6：查询指定城市的告警

```bash
uv run scripts/analyze_alarms.py --mode summary --cities 南京 --output markdown
```

### 场景 7：查询指定 CI ID 的告警

```bash
uv run scripts/analyze_alarms.py --mode search --ci_id 18 --include-alarms --output markdown
```

### 场景 8：查询数据库当前告警

```bash
uv run scripts/analyze_alarms.py --mode search --ne_alias 数据库 --alarm_status 1 --include-alarms --output markdown
```

资源分类映射：数据库 -> `数据库`，网络设备 -> `网络设备`，中间件 -> `中间件`，操作系统 -> `操作系统`，服务器/计算资源 -> `计算资源`。

## 参考文档

- [API 规范](references/api-specification.md) - 接口参数和使用说明
- [响应格式](references/response-format.md) - 数据结构和字段说明
- [使用场景](references/usage-scenarios.md) - 典型使用场景和问法
- [数据分析指南](references/data-analysis-guide.md) - 统计分析方法
- [图表展示指南](references/chart-guide.md) - 图表类型和配置
- [ECharts 示例](references/echarts-examples.md) - 图表代码示例

## 注意事项

1. **配置安全**：不要将 `.env` 文件提交到版本控制系统
2. **Token 管理**：定期更新 API Token，确保安全性
3. **数据量控制**：大量数据时使用分页查询，避免一次性加载过多数据
4. **时间格式**：时间参数格式必须为 `YYYY-MM-DD HH:MM:SS`
5. **告警级别**：重点关注级别 1（严重）和级别 2（重要）的告警

## 故障排查

### Token 无效

错误信息：认证失败，请检查 token 是否有效

解决方法：更新 `.env` 文件中的 `INOE_API_TOKEN`

### 接口地址错误

错误信息：接口不存在，请检查接口地址

解决方法：更新 `.env` 文件中的 `INOE_API_BASE_URL`

### 时间格式错误

错误信息：begin_time 格式无效，应为 YYYY-MM-DD HH:MM:SS

解决方法：确保时间格式正确，如 `2026-03-16 10:00:00`

### 网络超时

错误信息：请求超时，请检查网络连接或稍后重试

解决方法：检查网络连接，减少单页数据量

## 技术支持

如有问题，请参考相关文档或联系技术支持。
