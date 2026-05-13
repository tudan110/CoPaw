---
name: inspection-analyst
category: inspection
tags: [inspection, health-check, cmdb, topology, metrics, database, middleware, resource]
triggers: [巡检, 资源巡检, 健康检查, 数据库巡检, 帮我巡检一下数据库, 帮我巡检一下中间件]
description: 面向 gateway 智能体的资源巡检技能。优先使用 gateway 工作区本地的 zgops-cmdb 明确巡检对象的拓扑、resId/CI ID 与 ciType；若本地 skill 不可用，再协作 query 或 inspection 智能体。随后查询该资源类型的全部指标定义与指标值，最后向用户展示包含 CMDB 拓扑关系的巡检结果。
---

# Inspection Analyst

该技能用于处理“帮我巡检一下数据库 / 中间件 / 某个资源”的场景。

它的目标不是只输出一句“可以巡检”，而是完成一条真实巡检链路：

1. 先识别用户要巡检的对象
2. 优先使用 gateway 本地的 `zgops-cmdb` 确认拓扑、资源 ID（CI ID / resId）与资源类型（`ciType` / `metricType`）；本地 skill 不可用时再协作 query 或 inspection
3. 调用指标定义接口，提取该资源类型的全部指标编码
4. 调用指标数据接口，使用 `resId + 全部指标编码数组` 获取巡检指标数据
5. 把拓扑确认结果与指标数据整理成用户可读的巡检结果，并明确展示被巡检对象的 CMDB 拓扑关系

### 4. Portal 卡片展示约定

如果最终回复用于 Portal 展示巡检卡片，必须遵守以下固定约定：

1. 在完整巡检报告最前面输出标志行：`# PORTAL INSPECTION CARD MODE`
2. 标志行后紧跟一个单独的分隔段：`---`
3. 分隔线之后再输出用户可见的完整巡检报告正文
4. 正文中必须包含以下固定章节名：
   - `## 巡检结果`
   - `## 基本信息`
   - `## 指标数据`
5. `## 基本信息` 章节必须使用两列表格，并至少包含以下字段名：
   - `巡检对象`
   - `资源名称`
   - `资源类型`
   - `状态`
   - `指标总数`
   - `数据来源`
   - `巡检时间`
6. 不要把通知结果、权限失败、渠道状态说明这类消息套用上述标志；只有完整巡检报告才允许输出该标志

---

## 本智能体本地 skill 优先级

为减少多智能体协作带来的额外耗时，`inspection-analyst` 默认遵循以下执行顺序：

1. **优先使用 gateway 智能体当前工作区下已有的本地 skill**
   - `skills/zgops-cmdb`
   - `skills/inspection-analyst`
2. 只有当本智能体下**不存在目标 skill**、本地 skill **配置缺失 / 未接通 / 执行失败**，或用户**明确要求协作其他智能体**时，才回退到跨智能体协作
3. 如果发生回退，必须在过程说明里明确写出：
   - 为什么没有直接使用本智能体下的本地 skill
   - 准备协作给哪个智能体
   - 准备调用哪个 skill

因此：

- 查 CMDB / 应用拓扑时，默认先使用 **gateway 本地的 `zgops-cmdb`**
- 只有本地 skill 不可用时，才回退去协作 `query` 或 `inspection`

---

## 一、何时使用

当用户请求满足以下特征时，优先使用本技能：

- 用户明确要“巡检 / 健康检查 / 查看指标”
- 用户给出了一个资源对象、资源名称、数据库、中间件、主机、应用实例等巡检目标
- 用户希望看到实际指标结果，而不是巡检方案

典型触发语句：

- `帮我巡检一下数据库`
- `帮我巡检一下 mysql`
- `帮我巡检 db_mysql_001`
- `帮我看一下这个中间件的指标`
- `对这个资源做健康检查`

---

## 二、执行原则

### 1. 先真实执行，再组织说明

如果当前工作区具备可用工具，就必须优先执行真实动作：

1. 默认优先使用 gateway 工作区下已有的本地 `zgops-cmdb`
2. 只有本地 `zgops-cmdb` 不可用时，才使用内置工具 `chat_with_agent` 协作 `query` 或 `inspection`
3. 让本地 `zgops-cmdb`（或回退协作的 query / inspection）明确：
   - 根资源名称
   - `resId / CI ID`
   - `ciType`
   - 基本拓扑关系
4. 一旦拿到 `resId` 与 `ciType`，立即执行：

```bash
cd skills/inspection-analyst && python scripts/inspect_resource_metrics.py --res-id <CI_ID> --metric-type <ciType> --inspection-object "<用户巡检对象>" --resource-name "<CMDB确认的资源名>" --output markdown
```

不要停在“计划调用”“下一步执行”“是否继续”。

### 2. 不能猜测 resId / ciType

如果本地 `zgops-cmdb` 或回退协作的 query / inspection 返回多个候选资源，不能默认任选一个继续巡检。

此时应明确告诉用户：

- 当前存在多个候选资源
- 每个候选资源的名称 / `resId` / `ciType`
- 请用户指定后再继续

### 3. 默认巡检输出必须包含指标结果

完成巡检后，用户可见输出至少要包含：

1. 巡检对象
2. CMDB 确认的资源信息（资源名、`resId/CI ID`、`ciType`）
3. 被巡检对象的 CMDB 拓扑关系（不能只写“已确认拓扑”，要把根资源、关键上下游/关联资源展示出来）
4. 指标定义数量 / 实际采集数量
5. 指标数据表
6. 巡检结论

---

## 三、本地优先与跨智能体协作要求

涉及 CMDB / 拓扑确认时，必须优先使用 gateway 本地的 `zgops-cmdb`，不要只凭用户一句“数据库”就直接假定资源。

只有以下情况才回退到 `query` 或 `inspection`：

1. gateway 工作区下没有 `zgops-cmdb`
2. 本地 `zgops-cmdb` 缺少配置、接口未接通或执行失败
3. 用户明确要求“让 query / inspection 来查”

如果回退到 `query` 或 `inspection`，优先使用 `chat_with_agent`，并在过程说明中明确写出回退原因。

推荐本地优先提示：

```text
请优先使用 gateway 工作区下的 zgops-cmdb，确认巡检对象“<用户巡检对象>”在 CMDB 中对应的资源信息，返回：
1. 最匹配的根资源名称
2. resId / CI ID
3. ciType
4. 简要拓扑摘要
5. 如果存在多个候选资源，列出候选清单，不要默认任选一个
```

本地 skill 不可用时，推荐协作提示：

```text
请使用 zgops-cmdb 帮我确认巡检对象“<用户巡检对象>”在 CMDB 中对应的资源信息，返回：
1. 最匹配的根资源名称
2. resId / CI ID
3. ciType
4. 简要拓扑摘要
5. 如果存在多个候选资源，列出候选清单，不要默认任选一个
```

如果最终回复用于 Portal 展示卡片，输出最终答案时必须直接保留完整巡检报告协议，不要在 marker 前后额外包裹新的总结段，也不要改写固定章节标题。

---

## 四、指标接口配置

该技能固定读取自己目录下的 `.env`，不要回退到别的技能目录。

最小配置：

```bash
INOE_API_BASE_URL=http://192.168.130.51:30080
INOE_API_TOKEN=your_jwt_token_here
INSPECTION_METRIC_TIMEOUT_SECONDS=120
INSPECTION_METRIC_PAGE_SIZE=100
INSPECTION_NOTIFY_PUSH_URL=
INSPECTION_NOTIFY_DINGTALK_WEBHOOK_URL=
INSPECTION_NOTIFY_DINGTALK_SECRET=
INSPECTION_NOTIFY_FEISHU_WEBHOOK_URL=
INSPECTION_NOTIFY_FEISHU_SECRET=
INSPECTION_NOTIFY_TIMEOUT_SECONDS=8
INSPECTION_NOTIFY_MENTION_ALL=true
```

规则：

- 必须使用 `INOE_API_BASE_URL` 与 `INOE_API_TOKEN`
- 通知推送配置优先读取 Portal「高级功能 → 设置 → 通知」中的 `inspection` 配置；只有未设置时才回退 `INSPECTION_NOTIFY_*` / `ORDER_CREATE_NOTIFY_*`
- `getMetricDefinitions` 与 `getMetricData` 共用同一个 base URL
- 巡检指标判定时，优先查询 `/resource/inspection/config/list` 获取该指标对应的阈值规则
- `operator` 不是直接可读文案，必须再查询 `/admin/dict/data/list?dictType=verification_rules_new` 做字典解码
- 命中规则配置时：**满足规则=正常，不满足规则=异常**
- 如果某个指标没有对应规则配置，必须明确标注“需结合上下文由大模型判断”，不要擅自伪造阈值
- 缺少 token 时，必须明确报错，不能假装查询成功
- `INSPECTION_NOTIFY_PUSH_URL` 是应用推送接口地址，可对接量子密信 `/api/push/{token}`
- 支持按配置同时推送到：应用（可配置为量子密信）、钉钉、飞书
- 当前通知推送展示约定：
  - 飞书：优先发送 `interactive` 卡片，并明确展示整体状态、全量指标表格、巡检结论
  - 钉钉：发送 `markdown` 消息；由于自定义机器人移动端不支持 Markdown 表格，指标值使用逐条列表展示，不依赖表格
  - 应用推送接口（如量子密信）：使用 `POST /api/push/{token}`，请求体为 `{title, content, type}`，正文使用纯文本列表，不发送 `**`、`>` 等 Markdown 控制符；至少要体现状态、全量指标值、巡检结论
- 如果未配置任何 webhook，必须明确体现“通知未配置”

---

## 五、巡检脚本能力

本技能目录下的 `scripts/inspect_resource_metrics.py` 负责：

1. 查询全部指标定义
2. 提取全部指标编码
3. 调用 `/resource/pm/getMetricData`
4. 调用 `/resource/inspection/config/list` 与 `verification_rules_new` 字典，给指标结果补齐阈值判定依据
5. 使用 `resId + queryKeys=[全部指标编码]` 一次性查询指标数据
6. 在通知地址已配置时，自动把巡检结果推送到应用（可配置为量子密信）、钉钉、飞书
7. 输出 Markdown / JSON 结果，并标注每个指标是“正常 / 异常 / 需大模型判断”以及对应依据

常用方式：

```bash
cd skills/inspection-analyst
python scripts/inspect_resource_metrics.py \
  --res-id 3094 \
  --metric-type mysql \
  --inspection-object "数据库" \
  --resource-name "db_mysql_001" \
  --output markdown
```

---

## 六、最终输出要求

最终回复要以巡检结果为主，不要输出 alarm-analyst 那种工单、告警闭环、清警等内容。

建议结构：

```markdown
## 巡检结果
- 巡检对象：...
- 资源名称：...
- 资源 ID（CI ID）：...
- 资源类型：...
- 指标总数：...
- 数据来源：...
- 通知状态：...

## CMDB 拓扑关系
- 根资源：...
- 上游 / 下游 / 关联资源：...
- 关键关系说明：...

## 指标数据
| 指标名 | 指标编码 | 最近值 | 采样时间 | Min/Avg/Max | 数据来源 |
|---|---|---|---|---|---|

## 巡检结论
- ...
```

用户可见输出要直接解释资源状态，不要只贴原始 JSON。
另外，最终输出中必须显式展示被巡检对象的 CMDB 拓扑关系，不能省略成一句“拓扑已确认”。
如果需要 Portal 渲染巡检卡片，还必须遵守上面的 marker、章节名和字段名约定，否则前端无法稳定提取卡片信息。

---

## 七、通知要求

巡检结果生成后，必须执行通知推送：

1. 通知由 `scripts/inspect_resource_metrics.py` 内部自动完成
2. 可按 `.env` 配置同时推送到：
   - 应用推送接口（可配置为量子密信）
   - 钉钉
   - 飞书
3. 推送内容必须体现这是 **AI 巡检结果**
4. 至少包含：
    - 巡检对象
    - 资源名称
    - 资源 ID（CI ID）
    - 资源类型
    - 整体状态
    - 指标总数
    - 巡检时间
    - 巡检结论
    - 全量指标值（飞书 interactive 用表格；其它渠道按各自能力展示）
5. 如果未配置任何通知地址，必须明确写出“通知未配置”
6. 如果部分渠道推送失败，必须明确写出“部分通知发送失败”
