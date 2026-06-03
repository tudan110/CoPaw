---
name: zgops-cmdb
description: 用于查询当前 `.env` 配置所指向的 CMDB 环境。当用户询问模型、关系、层级、IPAM、DCIM、应用拓扑、资源拓扑、资源数量统计、资源状态统计、制造商/厂商分布、CMDB count/group 类接口时使用。
---

# ZGOPS CMDB 查询技能

仅面向凭证（共享 `secrets/zgops-cmdb.env` 或本技能 `.env`）所配置的当前 CMDB 环境。
凭证优先从共享 `secrets/zgops-cmdb.env` 读取，未配置时回退本技能目录 `.env`（`.env.example` 仅模板）。
凭证解析顺序统一为 `$VEOPS_ENV_FILE` → 共享 `secrets/zgops-cmdb.env` → 本技能目录 `.env`（旧版回退）；不读取其他 skill 的 `.env`。

不要在对外描述里写死某个固定地址、某套“测试环境”或特定站点；环境信息应完全来自上述凭证文件。

## 默认行为

- 优先使用随 skill 附带的脚本。
- 即使 agent 具备 `browser_use` 或其他浏览器相关工具，处理本 skill 的 CMDB 查询时也**禁止**使用它们；只允许后台脚本、HTTP 请求、curl、Python 标准库/HTTP 客户端这类无界面方式。
- 除非用户明确询问页面布局、截图或仅能在页面上看到的配置，否则**不要**打开浏览器。
- 除非需要接口名或已整理的场景关系，否则**不要**读取 `references/endpoints.md`。
- 涉及统计分布、目标数量对比类图表时，优先使用 `scripts/zgops-cmdb.sh analyze ...`。
- 涉及资源数量、资源状态、制造商/厂商分布、`/cmdb/v0.1/ci/count...` 这类 INOE 网关 CMDB 统计接口时，使用 `scripts/zgops-cmdb.sh inoe-stat ...`，不要改用 `resource-insight-query`。
- 执行 `inoe-stat` 时，资源 `type` 默认从当前环境的 `/cmdb/v0.1/ci_types/groups` 动态解析；内置 `database=5 / middleware=6 ...` 只作为元数据接口不可用时的兜底。
- 涉及具体应用的关系拓扑，先运行 `scripts/zgops-cmdb.sh find-project <应用名>` 解析目标应用；唯一命中后直接使用 `scripts/zgops-cmdb.sh app-topology <应用名>` 输出标准 ECharts `series` 结构，不要手写拓扑 option。
- 如果用户只是说“简易拓扑 / 系统拓扑 / 全局拓扑 / 监控拓扑 / 总览拓扑”，且没有明确给出某个应用名或项目名，不要使用本 skill 追问应用；这类请求应交给 `monitoring-overview-query` 的 `topology`。
- 如果用户没有明确指定应用名，且当前系统里存在多个应用，**不要默认任选一个**。必须先列出候选应用名并请用户明确指定。
- 当用户要求展示某个应用的关系拓扑图时，默认使用 ECharts `series.type = 'tree'`，并设置为从左到右展开；根节点使用 CMDB 中实际应用名。
- 除非用户明确要求导出独立页面，否则**不要**生成 `.html` 图表文件；默认直接输出可渲染的 ```echarts 代码块。
- 默认返回精简总结，不返回原始 JSON；只有用户明确要求时才返回原始响应。

## 网关分工

本 skill 涉及两个网关，脚本内部已自动路由，但理解分工有助于排错：

| 网关 | 环境变量 | 职责 |
|------|----------|------|
| veops 网关 | `VEOPS_BASE_URL` | CI 类型查询、CI 实例搜索、关系拓扑（`list-models`、`fetch`） |
| INOE 网关 | `INOE_API_BASE_URL` | 统计类接口（`inoe-stat`） |

**重要：** 查 CI 类型和实例统一用 `list-models` + `fetch`，不要手动拼 INOE 网关路径（INOE 网关的 `/cmdb/v0.1/ci_types` 不可用）。

## 快速路径

1. 统一主入口是 `scripts/zgops-cmdb.sh`。
2. 需要鉴权时，先运行一次 `scripts/zgops-cmdb.sh login`。
   它现在走后台 HTTP 会话，不会再打开桌面浏览器。
3. `fetch` 子命令**只接受 API 路径**，不支持 `--ci-id` 等快捷参数。查询资源必须拼完整路径：
   - ✅ `scripts/zgops-cmdb.sh fetch "/api/v0.1/ci/s?q=_id:3034&count=1"`
   - ✅ `scripts/zgops-cmdb.sh fetch "/api/v0.1/ci_relations/s?root_id=3034&level=1,2,3&count=10000"`
   - ❌ `scripts/zgops-cmdb.sh fetch --ci-id 3034`（不存在此用法）
4. 按问题选择最小可用命令：

```bash
scripts/zgops-cmdb.sh find-project <应用名>
scripts/zgops-cmdb.sh app-topology <应用名>
scripts/zgops-cmdb.sh list-models
scripts/zgops-cmdb.sh model-attributes <type_id>
scripts/zgops-cmdb.sh model-relations <type_id>
scripts/zgops-cmdb.sh fetch "/api/v0.1/relation_types"
scripts/zgops-cmdb.sh fetch "/api/v0.1/ci/s?q=_type:project&count=20"
scripts/zgops-cmdb.sh fetch "/api/v0.1/ci_relations/s?root_id=<ci_id>&level=1,2,3&count=10000"
scripts/zgops-cmdb.sh analyze --mode summary --output markdown
scripts/zgops-cmdb.sh analyze --mode app-relations --output markdown
scripts/zgops-cmdb.sh analyze --mode summary --output markdown-echarts-only
scripts/zgops-cmdb.sh inoe-stat types --output markdown
scripts/zgops-cmdb.sh inoe-stat group --resource_type middleware --attr vendor --output markdown
scripts/zgops-cmdb.sh inoe-stat count --resource_type database --output markdown
scripts/zgops-cmdb.sh inoe-stat child-group --type_id 5 --attr vendor --output markdown
```

## 按类型查资源实例

当用户说"查 redis 资源""列出所有 MySQL 实例"等，需要两步：

**第一步：确认 CI 类型名**

```bash
scripts/zgops-cmdb.sh list-models
```

在输出的表格中找到目标类型的 `name` 列值（小写，如 `redis`、`mysql`、`Kafka`）。`name` 是后续查询所需的标识。

**第二步：按类型名查实例**

```bash
scripts/zgops-cmdb.sh fetch "/api/v0.1/ci/s?q=_type:<name>&page=1&count=100"
```

将 `<name>` 替换为第一步得到的值。例如：

```bash
# 查所有 redis 实例
scripts/zgops-cmdb.sh fetch "/api/v0.1/ci/s?q=_type:redis&page=1&count=100"

# 查所有 mysql 实例
scripts/zgops-cmdb.sh fetch "/api/v0.1/ci/s?q=_type:mysql&page=1&count=100"
```

返回结果中每条 CI 的 `_id` 就是 `CI_ID`（即其他 skill 所需的 `resId`），`_type` 对应 `ciType`。

**多实例时：** 如果返回多条记录且上下文无法确定唯一目标，列出候选让用户选择。

## INOE 网关 CMDB 统计

当用户询问“中间件制造商分布统计 / 中间件厂商统计 / 中间件按厂家分布”时，直接执行：

```bash
scripts/zgops-cmdb.sh inoe-stat group --resource_type middleware --attr vendor --output markdown
```

资源类型解析（仅针对 `inoe-stat` 统计场景）：

- `inoe-stat` 内部使用 INOE 网关的分组接口解析分组 id。
- 如果用户输入的是具体模型名（如 `Kafka`、`Redis`、`mysql`），**不要用 `inoe-stat` 查类型**——改用 `list-models` 确认类型名后按"按类型查资源实例"流程操作。
- 只有在做分组统计（如"中间件按厂商分布"）且元数据接口不可用时，才使用下面的兜底映射：

- `database / 数据库` -> `type=5`
- `middleware / 中间件` -> `type=6`
- `network / 网络设备` -> `type=4`
- `server / 服务器 / 计算资源` -> `type=2`
- `os / 操作系统` -> `type=17`

查询当前环境可用类型目录：

```bash
scripts/zgops-cmdb.sh inoe-stat types --output markdown
```

环境切换：

- 测试、生产等不同环境只需要替换共享 `secrets/zgops-cmdb.env` 的 `INOE_API_BASE_URL` 和 `INOE_API_TOKEN`；本技能目录 `.env` 仅作旧版回退或临时覆盖。
- 如果 CMDB 接口走独立网关，可单独配置 `INOE_CMDB_API_BASE_URL`。
- 如果不同网关路径前缀不同，可覆盖 `INOE_CMDB_TYPES_PATH`、`INOE_CMDB_TYPE_GROUPS_PATH`、`INOE_CMDB_COUNT_GROUP_PATH` 等路径变量。

分组字段映射：

- `制造商 / 厂商 / 厂家 / vendor / manufacturer` -> `attr=vendor`
- `数据库类型` -> `attr=db_type`
- `系统类型` -> `attr=os_type`
- `设备类型` -> `attr=dev_class`

## 输出风格

- 模型列表类问题：优先输出 `ID / 名称 / 别名 / 唯一键` 表格。
- 单模型问题：只总结关键字段和关键关系。
- 场景类问题：简要说明业务、运行时、IPAM、DCIM 四条链路。
- 图表类问题：优先输出 ECharts；饼图用于分布，占比；柱状图用于目标数量对比。
- 关系拓扑类问题：优先输出从左到右树状图；根节点放应用，向右展开产品归属、运行时、中间件、数据库、IPAM、DCIM 等关系链。
- 若用户要“某个应用的关系拓扑 / 拓扑图 / 架构关系图”，先用 `find-project` 明确目标应用；只有在唯一命中时才运行 `app-topology`，并直接返回它生成的标准 ```echarts 代码块，不要自己重写成简写结构。
- 若用户没有提供应用名，只问“简易拓扑 / 全局拓扑 / 监控拓扑 / 系统拓扑”，这不是 CMDB 应用拓扑，改用 `monitoring-overview-query`。
- 若当前存在多个应用而用户没有给出明确应用名，先回复候选应用名让用户选择，不要默认返回任意一个应用的拓扑。
- 若用户只说“画图 / 渲染图表 / 可视化”，默认返回 Markdown + ```echarts，而不是 HTML 文件路径。
- 面向最终用户的回复、标题、摘要、图表标题中，不要出现 `VEOPS`、`veops`、`OneOps` 等产品字样，除非用户明确要求保留这些名称。

## 备注

- 这套环境中，`project` 对应“应用”模型。
- 凭据默认保留在共享 `secrets/zgops-cmdb.env` 中；本技能 `.env` 仅作为旧版回退或临时覆盖。
- 如果 `.env` 中配置了用户名密码但登录失败，允许继续尝试匿名访问只读接口；不要因为登录失败就阻断整个查询链路。
- 如需图表规范，读取 `references/chart-guide.md` 或 `references/echarts-examples.md`。
- 如果用户要做资源导入、资源纳管、批量导入，改用同级 `zgops-cmdb-import` skill。
