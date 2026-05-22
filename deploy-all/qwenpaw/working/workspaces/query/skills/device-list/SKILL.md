---
name: device-list
category: asset
tags: [device, asset, inventory, status, vendor, model]
triggers: [设备列表, 设备状态, 设备统计, 设备型号, 厂商分布, 在线设备, 离线设备, 资产清单]
description: 设备管理系统查询。支持获取设备列表、统计设备信息、查询设备状态、按型号/厂商/类型筛选设备。当用户询问设备列表、设备型号、设备状态、设备统计、设备信息时使用。
---

# Device List

为设备管理系统查询提供最短执行路径。适用于设备列表、设备统计、设备状态、型号/厂商/类型分布、特定设备搜索与简要分析。

## 触发条件（给 Agent）

当用户提到以下诉求时，优先使用本技能：

- 设备列表 / 设备总数 / 设备详情
- 在线离线 / 状态分布 / 异常设备
- 型号分布 / 厂商分布 / 类型统计
- 指定 IP / 名称 / 关键字搜索设备
- 设备分析 / 设备报告 / 可视化统计

若用户问题明显不是设备系统数据查询，不要使用本技能。

## 配置与最短路径（给 Agent）

- 原始查询入口：`uv run scripts/get_devices.py [options]`
- 统一汇总入口：`uv run scripts/analyze_devices.py --mode <mode> [options]`
- 聊天窗口优先：`uv run scripts/analyze_devices.py --mode <mode> --output markdown`
- 图表直出：`uv run scripts/analyze_devices.py --mode <mode> --output markdown-echarts-only`
- 优先读取共享 `secrets/`，未配置时回退技能目录下的 `.env`
- 配置只关注 2 个字段：`INOE_API_BASE_URL`、`INOE_API_TOKEN`
- 不要要求用户手动拼接接口 URL
- 不要先做无意义预检查；直接执行真实查询
- 如果缺配置或 token 无效，停止后续分析，直接返回缺失项或错误原因

配置文件示例：

```bash
INOE_API_BASE_URL=http://192.168.130.211:30080
INOE_API_TOKEN=your_jwt_token_here
```

缺配置时，只返回：

- `.env` 路径
- 缺失字段
- 最短填写示例
- “补齐后重试”

## 主流程（给 Agent）

### 1. 先判断查询类型

- **只看前几条 / 简单列表**：直接查询当前页
- **统计 / 分布 / 全量筛选 / 综合分析**：先拿 `total`，再决定是否全量拉取
- **指定设备搜索**：如能通过当前结果过滤解决，则先获取足够数据再过滤

### 2. 默认执行策略

#### 场景 A：简单列表

直接执行：

```bash
uv run scripts/get_devices.py --page_num 1 --page_size 10
```

#### 场景 B：统计、分布、筛选、分析

优先执行统一汇总脚本：

```bash
uv run scripts/analyze_devices.py --mode summary --output markdown
```

若需要更细分的统计，可使用：

```bash
uv run scripts/analyze_devices.py --mode vendor --output markdown
uv run scripts/analyze_devices.py --mode model --output markdown
uv run scripts/analyze_devices.py --mode abnormal --include-devices --output markdown
```

只有在需要原始分页结果时，才退回 `get_devices.py`。

如需自行拉全量数据，再按以下方式：

先取总数：

```bash
uv run scripts/get_devices.py --page_num 1 --page_size 1
```

再按 `total` 获取数据：

- 若 `total <= 100`：一次取完
- 若 `total > 100`：分页抓取，每页 100 条，直到取完

例如：

```bash
uv run scripts/get_devices.py --page_num 1 --page_size 100
uv run scripts/get_devices.py --page_num 2 --page_size 100
```

### 3. 数据处理默认规则

- 查询“任务式列表”时，优先返回关键字段，不要原样塞出全部 JSON
- 查询“统计/分布”时，先聚合，再展示表格或图表
- 查询“异常/离线/某厂商/某型号”时，在本地过滤 `rows`
- 如果用户没指定展示字段，默认优先展示：名称、IP、状态、资源状态、型号、厂商、类型
- 若匹配结果过多，只展示前 20 条，并说明总数

## 用户意图 -> 推荐动作

- “有多少台设备” → 先查询总数，直接返回 `total`
- “列出设备” → 查询第一页或用户指定数量，表格展示
- “哪些设备离线” → 优先执行 `analyze_devices.py --mode search --status offline --include-devices`
- “统计型号/厂商/类型分布” → 优先执行 `analyze_devices.py --mode model|vendor|type`
- “查设备 xxx / IP 是 xxx 的设备” → 优先执行 `analyze_devices.py --mode search --keyword <keyword>`
- “帮我分析一下设备情况” → 优先执行 `analyze_devices.py --mode summary`

## 输出约定

- 默认输出适合聊天窗口直接展示的 Markdown
- 如果调用 `analyze_devices.py`，优先附带 `--output markdown`
- `markdown` 输出会自动附带适合页面渲染的 ECharts 代码块（分布类场景）
- `markdown` 输出会自动补一段简短结论，适合直接回复用户
- `markdown-echarts-only` 只输出 ECharts 代码块，适合前端只消费图表
- 不要只把命令发给用户执行
- 列表查询：先给 1 句摘要，再给表格
- 统计查询：先给 1~3 句结论，再给表格或图表
- 综合分析：用分级标题组织为“概览 / 状态 / 厂商 / 型号 / 类型 / 异常”
- 单设备查询：用列表或表格展示关键字段；字段很多时分组展示
- 搜索/异常设备明细在聊天窗口默认只展示前 20 条，并说明总数

图表规则：

- 优先使用 ECharts
- 备选 Mermaid
- 不要生成 PNG 等图片文件
- 图表必须可直接在页面渲染
- `status` / `resource-status` 优先环形图，`model` 优先柱状图，`vendor` / `type` 优先饼图

## 错误处理规则

- **缺少 `INOE_API_TOKEN` / `INOE_API_BASE_URL`**：直接提示配置缺失，不继续请求
- **401**：提示 token 无效或过期，建议更新 `.env`
- **403**：提示权限不足
- **404**：提示接口地址可能错误
- **408 / 超时**：提示网络或服务响应慢，可稍后重试
- **空结果**：明确说“未找到匹配设备”，不要输出空表格后沉默
- **分页过程中部分页失败**：明确说明已成功获取的页数和失败页，避免假装是完整统计

## 何时读取参考文档

- 用户问典型查询场景或问法时，读取 `references/usage-scenarios.md`
- 用户问接口、分页、鉴权、参数时，读取 `references/api-specification.md`
- 用户问字段含义或返回结构时，读取 `references/response-format.md`
- 用户问如何做统计分析时，读取 `references/data-analysis-guide.md`
- 用户问图表展示形式时，读取 `references/chart-guide.md` 或 `references/echarts-examples.md`

默认不主动加载全部参考文档；只在需要解释细节时再读。

## Few-shot 示例

### 示例 1：查询设备总数

- 用户：现在一共有多少台设备？
- 动作：执行 `uv run scripts/get_devices.py --page_num 1 --page_size 1`
- 处理：读取返回中的 `total`
- 回复：直接给出总数；如有必要补一句“统计基于当前系统设备列表接口”

### 示例 2：统计离线设备

- 用户：帮我看看有多少设备离线，并列出它们
- 动作：执行 `uv run scripts/analyze_devices.py --mode search --status offline --include-devices --output markdown`
- 回复：先给离线数量，再用 Markdown 表格列出关键字段；若数量很多，只展示前 20 条并说明总数

### 示例 3：查看厂商分布

- 用户：按厂商统计设备数量
- 动作：执行 `uv run scripts/analyze_devices.py --mode vendor --output markdown`
- 回复：先给 Top 厂商结论，再输出统计表；如适合可补 ECharts 饼图或柱状图

### 示例 4：模糊搜索设备

- 用户：查一下名称里包含 core 的设备
- 动作：执行 `uv run scripts/analyze_devices.py --mode search --keyword core --output markdown`
- 回复：说明匹配数量，并表格展示设备名称、IP、状态、型号、厂商

## 注意事项

- Token 应只放在本地环境变量或 `.env` 中，不在对话中回显
- 做统计或筛选时，优先确认数据是否已全量获取
- 百分比分布优先用饼图，数量对比优先用柱状图
- 若用户只想快速看结果，避免输出大段原始 JSON
