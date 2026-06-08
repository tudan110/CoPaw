# AI 大屏工坊 · 重做设计 (Redesign Spec)

- 状态：草案，待 review
- 日期：2026-06-08
- 范围：完整四期（P1–P4）重做 `ai-big-screen` 子系统
- 配套阅读：`docs/solution-design/ai-big-screen-development-lessons.md`（上一版经验沉淀，产品判断继续沿用）
- 工程边界：所有改动落在 `src/qwenpaw/extensions/` + `portal/`，不污染 upstream core；保留 no-fake-data 铁律。

---

## 1. 背景与目标

现版（codex 实现）链路方向是对的：

> 自然语言 → 数据意图 → 真实取数 → 安全视觉 DSL → 可持久化资产 → 发布/二次修改

但实现层把每条承诺都打了折，导致四个痛点同时存在（均为用户确认）：

1. **AI 不够真智能** —— `ai_big_screen_service.py` 用关键词 `if` 阶梯做能力路由（`_extract_semantic_capability_ids` 子串匹配），常见 prompt 直接旁路 LLM；即便走 LLM，`_normalize_plan_component` 还会用关键词覆盖它选的能力和图表；`dataIntentPlan` 是取完数事后反推、confidence 写死魔法数。
2. **大屏不够炫酷** —— 渲染器只有 ~9 个写死组件 + 折线/柱；`visualSpec.highlightRules/emphasisRules` 渲染器从未读取（死代码）；`motion: pulse/stagger` 无 CSS（no-op）；ECharts 用 light 主题 → 深色大屏里白底图表。
3. **不稳定/慢/会崩** —— 资产存单一 `registry.json` + 进程锁 + 全量重写；异步任务存内存 dict（重启即丢、多 worker 404、无上限）；并存同步/异步两条生成路径；patch 内联无超时；取数阻塞事件循环。
4. **形态与交互别扭** —— `aiBigScreenPanel.tsx` 709 行单体 + 18 个 `useState`；"确认生成大屏"被挤出视口、预览强制横向滚动；与 `dashboardAssemblyPanel`（另一套 iframe 拼屏）作为产品重复。

**值得保留（不推倒）**：经验文档的产品判断（资产化、不许假数据、查询≠分析、安全 DSL、意图先于组件、patch 需选区上下文）；no-fake-data 三道闸（工单 source 校验、capability-gap、visualSpec 白名单）及其 golden 测试；取数 integration 层复用；渲染器无 XSS 面。

### 目标（成功标准）

- **真智能**：能力路由与视觉编排由 LLM 主导，关键词仅作护栏；换说法不再选错数据；新增数据源/视觉是"加一个描述符/组件"，而非改五处元组。
- **真炫酷**：玻璃极光 + 满屏密度 + 地图飞线/翻牌/水球/雷达/3D/粒子；`visualSpec` 高亮与动效真正生效；图表暗色统一。视觉方向已与用户锁定为 **D-max**。
- **稳**：SQLite 持久化、可重启可回滚的任务、全链路超时、取数不堵事件循环。
- **顺**：真·满屏自适应布局（无空白带、按钮不被挤出、拼接屏成立）；工坊 UI 拆分为可独立理解的单元。
- **可信**：默认不出现假数据；后端失败如实显示 failed（修掉"500 被吞成空 live"）。

### 非目标 / 约束

- 不引入"AI 每次直接写前端代码"作为默认路线（数据诚实/安全/可局部改/可版本 优先于无限上限）。
- 沙箱化"自定义视觉逃生口"作为**可选扩展点**预留，P4 视情况，一期默认不做。
- `dashboard-assembly` 一期不动（是否收编后续单独决策）。
- 目标环境/数据口径不变（INOE 网关 `gateway:30080` 及现有 6 能力）。

---

## 2. 总架构：三层解耦

核心原则：**把"取什么数"与"怎么展示"彻底拆成两个独立的 AI 决策**，中间用一层真实取数衔接。

```
NL prompt
   │
   ▼  L1 数据意图层 (LLM 主导, 关键词护栏)
DataIntentPlan { capabilities[], timeRange, intentKind(query|analysis), reasoning }
   │
   ▼  L2 取数层 (capability 描述符注册表; 一次取数→缓存→多组件共享)
CapabilityResult[] { capabilityId, rows/series/…, sourceStatus(live|empty|failed|gap), fields }
   │
   ▼  L3 视觉编排层 (LLM; 从组件库白名单挑/拼/配数据)
DashboardSpec { layout, theme, components[](type∈库, dataRef, visualSpec), bindings }
   │
   ▼  sanitizer (白名单 + token 消毒)
持久化资产 (SQLite) → 渲染器 (满屏布局引擎 + 组件库) → 发布/外链/画廊
```

要点：
- **L1 只决定数据，L2 只取真数据，L3 只决定视觉**。同一批告警数据，L3 这次可摆成"大数字 + Top5 柱"，下次"地图飞线 + 滚动流 + 风险脉冲"——AI 说了算。
- **一次取数、多处渲染**：L2 以 capability 为单位取一次，多个组件通过 `dataRef` 引用同一结果（消除现版每组件各查各的）。
- **改视觉不重新取数**：局部修改默认只重跑 L3；只有字段/时间范围变了才回到 L2（patch 又快又稳）。
- 关键词逻辑从"主路"降级为 L1 的**护栏/兜底**（例如 LLM 不可用时的降级、对 LLM 明显跑偏结果的纠偏），且其判断**可审计**（写入 reasoning，不再静默覆盖）。

---

## 3. 类型化领域模型 / 安全 DSL

把现版散落的 `dict[str, Any]` 收敛为**后端 Pydantic + 前端 TS 镜像**的单一 schema，读写都校验。消除 `capabilityId`/`pluginId` 双别名（统一 `capabilityId`）。

核心模型（字段示意，最终以代码为准）：

- `DataIntentPlan`：`capabilities: list[CapabilityIntent]`、`intentKind`、`timeRange`、`reasoning`、`fallbackUsed`。
  - `CapabilityIntent`：`capabilityId`、`intentKind(query|analysis|aggregate|trend|compare)`、`timeIntent(current|relative|latest-non-empty|absolute)`、`params`。
- `CapabilityResult`：`capabilityId`、`sourceStatus(live|empty|failed|gap)`、`rows|series|nodes|metrics`、`fields[]`、`message`、`fetchedAt`。
- `DashboardSpec`（持久化资产主体）：`id`、`name`、`status(draft|published|archived)`、`schemaVersion`、`layout`、`theme`、`components[]`、`dataRefs[]`、`versions[]`、`publishTargets[]`、`aiContext`、时间戳。
  - `Component`：`id`、`type ∈ 组件库白名单`、`title`、`layoutPosition`、`dataRef`（指向某 CapabilityResult + 字段映射）、`visualSpec`。
  - `VisualSpec`：`kind`、`motion`、`density`、`layoutPattern`、`composition`、`bindings`、`highlightRules[]`、`emphasisRules[]`、`layers[]`——**全部在渲染器中真正实现**。
- `ScreenTask`：`taskId`、`status(queued|running|succeeded|failed)`、`stage`、`message`、`spec?`、`error?`、时间戳。
- `CapabilityDescriptor`（注册表项，见 §5）。

Sanitizer：`type`/`palette`/`kind`/`motion`/`operator`/`tone` 走**严格白名单**（非法回退默认）；自由文本字段（字段名/标题）走 token 消毒（沿用现有反注入：截断 + 屏蔽 `< > script javascript: data: onerror onclick style= http(s)://` 等）；并补充实体编码/`vbscript:`/`expression(` 等遗漏项。渲染器**无 `dangerouslySetInnerHTML`、无任意 JS**。

---

## 4. 组件库（炫酷的来源）—— `portal/src/components/big-screen/`

AI 能挑的"白名单词汇表"。每个组件声明：`type`、`输入数据形状 (inputContract)`、`visualSpec → props 映射`、暗色样式。统一数据绑定，未知 type 不再静默降级成文字（而是显式占位 + 上报）。

- **容器/背景**：`GlassPanel`、`ScreenGrid`（满屏栅格）、`AuroraBackground`、`ParticleLayer`。
- **数值**：`FlipNumber`（翻牌）、`MetricKpi`、`LiquidBall`（水球）。
- **图表（基于 ECharts + echarts-gl，统一暗色主题封装 `darkChartTheme`）**：折线/柱/面积、`Donut/Gauge`、`Radar`、`Heatmap`、`GraphRelation`（关系图）、`Bar3D`、`MapFlyLines`（地图飞线，含中国地图 GeoJSON）。
- **列表/流**：`AlarmStream`（滚动告警流）、`TopNRank`、`RiskPulse`（风险脉冲）、`Funnel`、`Timeline`。
- **共性**：每组件支持 `sourceStatus` 角标（live/empty/failed/gap），空数据/失败有统一占位；`visualSpec.highlightRules/emphasisRules` 由统一规则引擎驱动条件着色与强调；`motion` 全部有实现。

> 现有 `EChartsBlock.tsx` 内含可执行 formatter 字面量的 mini-compiler——大屏路径**不使用** AI 生成的 chart-config 函数字面量；图表 option 由组件库内部按 typed props 构造，杜绝该面。

---

## 5. L2 取数层 —— capability 描述符注册表

把现版 7 个手写 `_query_*` + `_execute_data_capability` 的 `if` 阶梯，改成**描述符注册表**（数据已在 `DATA_CAPABILITIES` 元数据里）：

```
CapabilityDescriptor {
  id, displayName, domain,
  fetcher(params) -> CapabilityResult,   # 复用现有 integration
  inputSchema, availableFields, supportedVisuals,
  statusRule,                            # 统一裁决 live/empty/failed/gap
}
```

- 复用现有 integration：`portal_real_alarms`、`portal_monitoring_overview`（cmdb/alarm-top5/topology）、`nightingale_logs`、`order_workflow`。
- **诚实状态统一裁决**：修掉 `portal_real_alarms` "异常被吞成空 source=live" → 后端失败必须裁成 `failed`，与"真零告警"区分。保留工单 `source != live` 阻断、`capability-gap` honest-gap。
- **一次取数→缓存**：以 `(capabilityId, params)` 去重，多个组件共享同一结果。
- **async 正确性**：阻塞型 integration 调用走 `asyncio.to_thread`；每次取数 `wait_for` 超时，超时/异常 → `failed`。
- `USE_MOCK_DATA` 防漏：注册表 fetcher 走的是 `portal_*`/`order_workflow`，不复用会读 `mock_data.json` 的 skill 客户端；增加一条测试钉死"大屏路径在 `USE_MOCK_DATA=true` 下不出假数据"。

---

## 6. AI 管线（L1 + L3）

- **统一 LLM 抽象**：沿用 `create_model_and_formatter`（操作员配置的 active model）；**结构化输出**（schema/tool-calling 强约束 JSON），而非现版"prompt 里口述 JSON + 贪婪 `{...}` 切片"。
- **L1 调用**：输入 NL + capability 目录 → 输出 `DataIntentPlan`。关键词护栏在解析后做一致性校验（如"工单只能 workorders"），纠偏写入 reasoning。
- **L3 调用**：输入 `DataIntentPlan` + `CapabilityResult[]`（含字段与样例）+ 组件库白名单 + 意图 → 输出 `DashboardSpec`。
- **解析/校验**：响应过 schema 校验失败 → 有限重试（带超时）→ 仍失败则降级到护栏生成的最小可用方案，并在 task 里如实标注"AI 降级"。
- **超时/重试**：每个 LLM 调用 `wait_for`；重试沿用 model wrapper，外加管线级有限重规划（轮数/时间窗/返回量受限、可审计——沿用现版 data-planner 约束思想）。

---

## 7. 满屏布局引擎（一等公民）

- 基准设计坐标系（如 1920×1080）+ **scale-to-fit 自适应**：等比缩放铺满视口，无空白带；超宽/拼接屏按规则平铺。
- 工坊预览、外链全屏 `/big-screen/:id`、画廊嵌入 `?embed=1` 共用同一布局引擎，表现一致。
- 工坊左栏（prompt 台 + 生成 + 资产）为自然流可滚动容器，**输入与主操作按钮永不被挤出**（替换现版固定高 `overflow:hidden` + 冻结行那套）；预览区不再 `min-width:1120px` 强制横向滚动。
- 校验断点：1366×768 / 1440×900 / 1920×1080 / 4K 拼接。

---

## 8. 持久化与异步任务（稳态）

- **资产存储**：`registry.json 单文件大锁` → **SQLite**（`screens` 表每屏一行 + `screen_versions` 版本表）。并发安全、可检索、可回滚。存储路径仍在 `WORKING_DIR/extensions/ai_big_screen/`（`runtime_data_paths.py` 增加 db 路径）。
- **异步任务**：内存 dict → **SQLite 任务表**（重启不丢、可跨 worker 轮询、有 TTL 清理）。前端轮询接口契约不变。
- 移除"同步 `/draft`（600s）+ 异步 `/draft-tasks`"双路径，**统一走异步任务**；patch 也改为带超时的有界执行（复用同一任务模型/超时机制），不再内联无超时。
- 任务 `stage` 真实推进：`意图解析 → 取数 → 视觉编排 → 资产固化`；失败定位到具体 stage。

---

## 9. 局部修改（patch）

- 选区上下文：`selectedComponentId(s)`、`selectedRegion`、`selectionContext`、`baseVersionId`、`instruction`（沿用现契约，前端补齐 `selectedRegion` 框选）。
- **一套生成器**：业务规则只写一遍（消灭现版 L1 prompt / normalize / patch 三处重复 + 启发式与 LLM 互相打架的 `_component_patch_mentions_*` 守卫族）。
- 默认只重跑 L3（视觉），数据不动；字段/时间变才回 L2 重取。每次 patch 落版本快照，可回滚。

---

## 10. 工坊 UX 重构

拆掉 709 行单体 + 18 个 `useState`：
- `PromptConsole`（输入 + 生成）、`GenerationProgress`（真阶段 + 失败定位）、`ScreenPreview`（满屏渲染 + 选区）、`AssetManager`（列表/重命名/复制/删除/发布）、`RegionEditor`（局部修改）。
- 一个 `useAiBigScreen` orchestration hook 收编 state/effects/API/轮询；状态用 reducer，消除互相打架的布尔 flag（如生成中仍可点保存）。
- 列表加载改为按 id 取详情（不再信任 list 载荷）；改动后增量更新而非每次全量 reload。

---

## 11. 安全与 no-fake-data

- 保留三道闸：工单 `source != live` 阻断、`capability-gap` honest-gap、`visualSpec` 白名单 sanitizer。
- **新增诚实性修复**：后端失败裁成 `failed`（区别于 empty）；`USE_MOCK_DATA` 隔离测试。
- 渲染器无任意 HTML/JS；图表 option 由组件库构造，不接受 AI 函数字面量。

---

## 12. 测试

- 把现有 golden prompts 迁到新架构作回归（覆盖：能力路由、查询≠分析、无假数据、dataIntentPlan 解释时间与数据质量、局部修改只影响选中、视觉 sanitize）。
- **补现版盲区**：LLM 结构化输出契约（malformed/降级路径）、后端失败→`failed` 的状态映射、`USE_MOCK_DATA` 隔离、任务重启/跨 worker、布局断点快照。
- 单测可不调真 LLM（mock L1/L3），但**新增**少量针对结构化输出解析与降级的确定性用例。
- 前端：组件库可视回归（fixture 驱动）、满屏布局断点、工坊关键交互。

---

## 13. 文件结构（新增/替换）

后端 `src/qwenpaw/extensions/`：
- `api/ai_big_screen_api.py`（路由，统一异步；瘦身）
- `api/ai_big_screen_models.py`（typed Pydantic 模型，替换 `dict[str,Any]`）
- `ai_big_screen/`（拆分现 3866 行 service）：`intent.py`(L1)、`capabilities/`(L2 注册表 + descriptors)、`orchestration.py`(L3)、`sanitizer.py`、`tasks.py`、`store.py`(SQLite)、`patch.py`、`pipeline.py`(编排串联)。
- `runtime_data_paths.py`（增加 SQLite db 路径）

前端 `portal/src/`：
- `components/big-screen/`（组件库 + `darkChartTheme` + 布局引擎 `ScreenStage`）
- `components/big-screen/BigScreenRenderer.tsx`（替换现 `ai-big-screen/AiBigScreenRenderer.tsx`：DSL→组件，单一调度，规则引擎驱动高亮/动效）
- `pages/digital-employee/ai-big-screen/`（拆分现 `aiBigScreenPanel.tsx`：上述 5 组件 + `useAiBigScreen`）
- `types/aiBigScreen.ts`（与后端 schema 镜像）、`api/aiBigScreen.ts`（统一异步）
- 外链/画廊页复用新渲染器与布局引擎

---

## 14. 分期（P1–P4，完整四期）

依赖顺序推进，每期可独立验证。

- **P1 视觉地基**：组件库 + `darkChartTheme` + 满屏布局引擎 + `BigScreenRenderer`，用 fixture `DashboardSpec` 跑通。验收：D-max 各组件在 1366→4K 满屏正确、动效/高亮生效、`pnpm build` 通过。
- **P2 AI 三层管线 + typed DSL**：L1/L2/L3 + 结构化输出 + sanitizer + capability 注册表（先接告警/日志/工单，再补 cmdb/top5/topology），fetch-once。验收：`prompt → 真取数 → 满屏` 端到端；golden prompts 通过；无假数据；失败裁 `failed`。
- **P3 稳态 + 工坊重构**：SQLite 资产/版本 + SQLite 任务表 + 统一异步 + 全链路超时 + 工坊 5 组件 + hook/reducer + 发布/画廊/外链。验收：重启任务不丢、并发保存不互覆、布局断点全过、发布外链可开。
- **P4 加固**：全量 golden + 盲区补测 + `USE_MOCK_DATA` 隔离 + 超时回归 +（可选）沙箱逃生口设计落地。验收：测试套件绿、pre-commit 干净。

---

## 15. 风险与待决

- **结构化输出可靠性**依赖 active model 能力；降级路径必须好用（护栏生成的最小方案要"能看"）。
- **中国地图 GeoJSON 体积**与 echarts-gl 包体；按需懒加载，控制首屏。
- **active model 未配置**时的 UX（沿用并改进"请先设置默认 LLM"）。
- **L3 提示工程**是质量关键，需要 golden 集驱动迭代。
- 待决：沙箱逃生口是否纳入 P4（默认不做）；`dashboard-assembly` 是否后续收编。

---

## 16. 开发纪律（沿用经验沉淀）

1. 新视觉先扩 DSL + sanitizer，再扩组件库白名单渲染。
2. 新数据能力优先复用现有 integration，禁止 mock 填充。
3. 改字段/时间/分析方式必须重取或明确标注不可用。
4. 默认输入框/模板不写死"领导驾驶舱"等话术。
5. 生成/保存/发布/修改都保留版本与上下文，便于审计回滚。
6. 提交前至少跑：大屏单测、相关数据能力边界测试、`portal` 构建。
