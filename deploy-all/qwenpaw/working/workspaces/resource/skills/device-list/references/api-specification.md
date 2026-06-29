# API 规范

本文档描述 `device-list` 技能的唯一查询入口、参数、分页策略和错误处理约定。

## 推荐入口

### 1. 原始查询入口

统一执行：

```bash
uv run scripts/get_devices.py [options]
```

适用于：

- 只查原始分页数据
- 需要精确控制页码和页大小

### 2. 统一汇总入口

```bash
uv run scripts/analyze_devices.py --mode <mode> [options]
```

适用于：

- 综合概览
- 厂商 / 型号 / 类型 / 状态分布
- 异常设备清单
- 关键字搜索

如果结果要直接回到聊天窗口，推荐：

```bash
uv run scripts/analyze_devices.py --mode summary --output markdown
```

`markdown` 输出特性：

- 自动生成适合聊天窗口的标题、摘要和表格
- 自动补充简短分析结论
- 分布类模式自动附带 ECharts 配置代码块
- `status` / `resource-status` 默认环形图，`model` 默认柱状图
- 设备明细默认只展示前 20 条，并补充总数说明

如果只需要图表代码块，可使用：

```bash
uv run scripts/analyze_devices.py --mode summary --output markdown-echarts-only
```

适用场景：

- 前端只想渲染图表
- 不需要文字摘要和表格
- 需要把图表块嵌入其他响应内容

不要要求用户自行调用 HTTP API。

## 参数说明

| 参数名称 | 类型 | 是否必填 | 说明 | 示例 |
|---------|------|---------|------|------|
| `page_num` | int | 否 | 页码，默认 `1` | `1` |
| `page_size` | int | 否 | 每页数量，默认 `10` | `10`, `35`, `100` |
| `token` | str | 否 | JWT 令牌；默认从环境变量 `INOE_API_TOKEN` 读取 | `eyJ...` |
| `api_base_url` | str | 否 | API 基础地址；默认从环境变量 `INOE_API_BASE_URL` 读取 | `http://host:port` |

## 配置

技能目录下的 `.env`：

```bash
INOE_API_BASE_URL=http://192.168.130.211:30080
INOE_API_TOKEN=your_jwt_token_here
```

配置文件位置：`.claude/skills/device-list/.env`

读取优先级：

1. 技能目录 `.env`
2. 项目根目录 `.env`

## 接口信息

- 请求方式：`GET`
- 接口地址：`{INOE_API_BASE_URL}/resource/device/device/list`
- 鉴权方式：`Authorization: Bearer <token>`
- 查询参数：`pageNum`、`pageSize`

## 推荐执行策略

### 场景 1：只查总数

```bash
uv run scripts/get_devices.py --page_num 1 --page_size 1
```

读取响应中的 `total`。

### 场景 2：简单列表

```bash
uv run scripts/get_devices.py --page_num 1 --page_size 10
```

适合“列出设备”“看前几台设备”。

### 场景 3：统计 / 分布 / 筛选 / 综合分析

优先使用：

```bash
uv run scripts/analyze_devices.py --mode summary --output markdown
uv run scripts/analyze_devices.py --mode vendor --output markdown
uv run scripts/analyze_devices.py --mode abnormal --include-devices --output markdown
```

`analyze_devices.py` 会自动分页抓取全部设备，再做本地汇总。

如果必须手动取数，再先取总数，再决定是否全量拉取：

- 若 `total <= 100`：一次性拉取
- 若 `total > 100`：分页拉取，每页 `100`

示例：

```bash
uv run scripts/get_devices.py --page_num 1 --page_size 1
uv run scripts/get_devices.py --page_num 1 --page_size 100
uv run scripts/get_devices.py --page_num 2 --page_size 100
```

## 分页约定

- 统计或筛选前，应确认数据是否全量获取
- 某页失败时，不要把不完整数据当成完整统计结果
- 若分页中断，应明确说明“已获取 X/Y 页，结果可能不完整”

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

## Agent 回复要求

- 不要只返回“命令执行成功”
- 不要原样输出整段 JSON，除非用户明确要求原始结果
- 应从 `total` 和 `rows` 中提炼用户真正需要的结论
- 统计类问题优先使用 `analyze_devices.py` 的结果，而不是手动重复聚合
- 聊天场景优先使用 `--output markdown`