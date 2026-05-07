# 故障分析员对话触发的故障场景根因分析设计

## 问题与目标

当前需要在 **故障分析员** 中新增一条可演示、可扩展的故障场景根因分析链路，首个落地场景为：

- 业务场景：CMDB 添加数据/设备新增失败
- 首版重点根因：MySQL 死锁导致插入失败
- 触发方式：在 portal 的故障分析员对话中，通过自然语言对话触发

本次设计的硬约束：

- 前端代码只写到 `portal`
- 后端代码只写到 `src/qwenpaw/extensions`
- 新增 skill 放到 `deploy-all/qwenpaw/working/workspaces/fault/skills`
- 不修改 qwenpaw 原本的主干代码
- 不修改旧版 `fault-disposal` skill
- 不重写同事已存在的 portal 故障处置逻辑，只增加一个非侵入式场景旁路

首版目标不是一次性打通所有故障类别，而是在保留后续扩展能力的前提下，先稳定打通“CMDB 添加失败 -> MySQL 死锁”这条真实诊断链路。

## 设计结论

在故障分析员对话中增加一个非侵入式的 **场景旁路**。当对话命中“CMDB 添加失败/插入报错/死锁”等关键词时，portal 不走旧版故障处置 skill，而是调用 `src/qwenpaw/extensions` 中新增的场景 API。该 API 编排一个新的通用根因分析 skill `scenario-root-cause-analyst`，由它通过 A2A 协作：

- 已存在的 `query/skills/zgops-cmdb`
- 新增的 `fault/skills/mysql-deadlock-inspector`

首版先输出结构化诊断结果、诊断步骤和完整日志侧板；“故障处置”按钮保留为占位动作。

## 整体架构

### 1. portal 对话层

portal 在故障分析员对话页新增一个“场景识别前置适配层”：

- 当前员工不是故障分析员：直接走旧逻辑
- 当前员工是故障分析员，但消息未命中目标场景：直接走旧逻辑
- 命中目标场景：调用新的场景 API，并在对话中展示结构化结果

该适配层只增加旁路，不改变原有对话主流程的语义和默认行为。

### 2. extensions 编排层

在 `src/qwenpaw/extensions` 下新增场景编排 API/服务，职责限定为：

1. 识别并规范化对话场景上下文
2. 发起诊断会话并维护步骤状态
3. 调用新的根因分析 skill
4. 将 skill 输出整理成 portal 固定消费协议
5. 持久化诊断步骤日志，供“查看诊断日志”使用

该层不承载具体领域分析规则，不复用旧 `fault-disposal` 的运行时内部逻辑，避免耦合和回归风险。

### 3. skill 能力层

#### 3.1 复用 skill

`deploy-all/qwenpaw/working/workspaces/query/skills/zgops-cmdb`

职责：

- 查询 CMDB 模型、实例、关系
- 补齐应用、服务、中间件、数据库等拓扑链路
- 为 portal 提供“分析链路拓扑”的结构化来源

#### 3.2 新增 skill：`mysql-deadlock-inspector`

目录：

`deploy-all/qwenpaw/working/workspaces/fault/skills/mysql-deadlock-inspector`

职责：

- 以 skill 方式只读查询 MySQL
- 提取死锁、锁等待、阻塞事务、相关 SQL、失败时间窗口证据
- 统一输出结构化数据库证据对象

该 skill 不关心业务场景命名，只关心数据库侧证据采集。

#### 3.3 新增 skill：`scenario-root-cause-analyst`

目录：

`deploy-all/qwenpaw/working/workspaces/fault/skills/scenario-root-cause-analyst`

职责：

- 作为通用场景根因分析入口，不在名字中固化 `cmdb`
- 通过 `scene_code` 或 playbook 标识区分具体业务场景
- A2A 协作 `zgops-cmdb` 与 `mysql-deadlock-inspector`
- 汇总多源证据，输出根因、拓扑、步骤、日志和建议动作

该 skill 的首个场景模板为：

- `scene_code=cmdb_add_failed_mysql_deadlock`

后续可扩展为其他业务系统或其他故障类型，而无需重命名 skill。

## 分析模型与演进策略

### 1. 通用分析模型

`scenario-root-cause-analyst` 内部采用两段式模型：

1. **场景识别**
   - 基础资源故障
   - 网络故障
   - 应用性能故障
   - 数据库故障
   - 中间件故障
   - 业务逻辑故障
2. **并行证据采集 + 汇总裁决**

### 2. 首版落地策略

V1 不要求真实打通上述全部分支，而是保留统一分析骨架，先优先实现：

- `resource-discovery`
- `topology-expansion`
- `database-analysis`
- `decision-merge`

其中：

- `resource-discovery` / `topology-expansion` 先由 `zgops-cmdb` 提供资源与关系证据
- `database-analysis` 由 `mysql-deadlock-inspector` 提供数据库证据
- `decision-merge` 由 `scenario-root-cause-analyst` 汇总裁决

预留但首版不强制打通的分支：

- `middleware-analysis`
- `application-analysis`
- `network-analysis`
- `infra-analysis`

### 3. 首版裁决逻辑

首版采用 **规则优先 + 证据打分**，避免过度依赖模糊大模型判断。若同时满足以下条件，则判定为“数据库死锁导致 CMDB 新增失败”：

- 失败时间窗口内存在死锁/锁等待记录
- 关联事务、表或 SQL 与新增操作相关
- `zgops-cmdb` 能映射出业务对象与数据库链路
- 失败现象与插入失败/超时等表现吻合

### 4. 后续扩展方式

新增场景时保持前端协议不变，仅新增：

- 新的 analyzer skill 或探针
- 新的规则模板
- 新的场景标识

即：**前端协议一次定型，后端分析能力增量扩容。**

## portal 交互设计

### 1. 触发与过程态

故障分析员对话命中新场景后，portal 交互按以下节奏推进：

1. 5 秒内立即返回：`正在关联分析...`
2. 按步骤更新进度：
   - 资源关系采集中
   - 数据库锁信息采集中
   - 根因归纳中
   - 结果生成完成
3. 在同一会话中渲染结构化结果，而不是仅输出一大段自然语言

### 2. 会话内结果块

对话中新增四类结构化展示块：

1. **结果摘要卡**
   - 明确说明是否定位为数据库死锁导致新增失败
2. **分析链路拓扑**
   - 服务/应用 -> 组件 -> 数据库
   - 异常节点高亮
3. **根因卡片**
   - 根因大类
   - 根因类型
   - 根因对象
   - 故障可能原因
   - 根因佐证
4. **操作区**
   - `查看诊断日志`
   - `故障处置`

### 3. 诊断日志侧板

“查看诊断日志”首版按完整弹层/侧板实现，内容包括：

- 诊断步骤时间线
- 每一步输入/输出摘要
- `zgops-cmdb` 的关系查询摘要
- `mysql-deadlock-inspector` 的数据库证据摘要
- 最终根因归纳过程

### 4. 故障处置按钮

首版保留按钮，但不实现真实自动化处置。点击后可提示“自动化处置能力待补充”，以保证演示闭环完整。

## 返回协议设计

portal 不解析长文本，而只消费固定结构对象。建议 `src/qwenpaw/extensions` 对 portal 统一返回如下结构：

```json
{
  "scene": "cmdb_add_failed_mysql_deadlock",
  "sessionId": "diag-xxx",
  "requestId": "req-xxx",
  "summary": "已定位为数据库死锁导致 CMDB 新增失败",
  "topology": {},
  "rootCause": {
    "category": "组件层状态异常",
    "type": "数据库异常",
    "object": "CMDB 关联数据库表",
    "reason": "事务锁等待超时，导致插入失败",
    "evidence": []
  },
  "steps": [],
  "logEntries": [],
  "actions": []
}
```

其中：

- `summary`：对话中的一句话结论
- `topology`：用于绘制链路拓扑
- `rootCause`：根因主卡片
- `steps`：过程态和时间线
- `logEntries`：日志侧板原始数据
- `actions`：操作区按钮和扩展动作

extensions 必须保证这个协议稳定，portal 只负责渲染。

## 代码落点

### 1. portal

新增代码只落在 `portal` 中，建议按职责拆分为：

- 场景识别适配层
- 场景 API 调用模块
- 诊断结果渲染组件
- 日志侧板组件

要求：

- 不重写旧故障处置逻辑
- 不替换旧入口
- 只在故障分析员对话中增加一个“命中特定场景时改走新 API”的旁路

### 2. extensions

新增代码只落在 `src/qwenpaw/extensions` 中，建议拆为：

- API 路由层
- 场景服务层
- 结构化数据模型层
- skill 调用适配层

要求：

- 不修改 qwenpaw 主干目录其他代码
- 不侵入旧 `fault-disposal`
- 只做新增能力封装

### 3. skills

新增 skill 目录：

- `deploy-all/qwenpaw/working/workspaces/fault/skills/mysql-deadlock-inspector`
- `deploy-all/qwenpaw/working/workspaces/fault/skills/scenario-root-cause-analyst`

复用 skill 目录：

- `deploy-all/qwenpaw/working/workspaces/query/skills/zgops-cmdb`

## 首版范围界定

### 首版必须完成

- 故障分析员对话触发新场景旁路
- “正在关联分析...” 和步骤进度反馈
- `zgops-cmdb` 查询资源/拓扑
- `mysql-deadlock-inspector` 查询数据库死锁证据
- 结构化根因结果卡片
- 完整诊断日志侧板
- “故障处置”按钮占位

### 首版明确不做

- 六大类故障分支全部真实接通
- 自动执行修复动作
- 替换旧 `fault-disposal`
- 重构 portal 旧对话链路

## 风险与处理

### 1. 部分证据获取失败

需要显式结构化返回状态，而不是笼统报错：

- `topology_unavailable`
- `db_evidence_unavailable`
- `diagnosis_partial`
- `diagnosis_failed`

portal 需按状态提示“部分分析完成”或“关键证据缺失”。

### 2. 演示稳定性

首版应优先保证：

- 对话命中场景后能稳定切入新旁路
- MySQL 死锁时能稳定给出结构化结论
- 日志侧板能清楚展示“哪个 skill 提供了什么证据”

### 3. 后续演进风险

如果后续故障类型增多，必须继续保持：

- 场景模板增量扩展
- portal 协议不随场景新增而频繁变动
- analyzer skill 边界清晰，不将业务编排重新塞回 portal

## 备注

- 本设计默认以 `CMDB 添加失败 -> MySQL 死锁` 作为首个验证场景
- skill 名称不绑定 `cmdb`，以便后续复用到其他业务系统
- `zgops-cmdb` 继续保留在 query workspace，由新根因分析 skill 通过 A2A 协作使用
