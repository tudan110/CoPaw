# Portal 技能面板：切换为 gateway 工作区视图 + "二开" tag

> 日期：2026-05-12 · 分支：cc_dev · 形态：前端为主，无后端改动

## 背景 / 问题

Portal 的「技能池」面板（`portal/src/pages/digital-employee/skillPoolPanel.tsx`）当前展示
QwenPaw 的**全局技能池**（`GET /skills/pool`），并用 `GET /skills/workspaces` 做"哪个
agent 引用了"的交叉。

但 Portal 对外只暴露一个入口 agent —— `gateway`（"智观 AI"）。它真正在用的技能
（`zgops-cmdb`、`web-availability-monitor`、`inspection-analyst`、`order-workflow`、
`monitoring-overview-query`、`private-line-business-monitor`、`resource-insight-query`、
`multi_agent_collaboration`）放在它自己的 workspace 里，**没有**进 QwenPaw 的 `skill_pool/`，
所以面板里看不到它们；面板里看到的反而是一堆 Portal 用户不关心的池内容。

目标：
1. 面板改为展示 **gateway 这个入口 agent 实际拥有的技能**（它的 workspace 那一份），暂时
   不再查询 QwenPaw 的全局池。
2. 引入「二开」tag —— 通过 Portal 这个面板"进来"的技能（上传 .zip / 新建表单 / 从链接导入）
   自动带上「二开」tag，与随系统部署的"出厂"技能区分开；tag 写进工作区 manifest（真实、可搜、
   可手动增删），不是纯前端派生。

非目标（本次不做）：把内部子 agent（query/fault/...）的技能也列出来；为子 agent 做技能分配；
重做 MCP 面板；改 QwenPaw 后端。

## 关键事实（已核对）

- `GET /skills`（header `X-Agent-Id`）→ 该 agent workspace 的 `SkillSpec[]`，字段含
  `name, description, emoji, version_text, content, references, scripts, source, tags,
  config, last_updated, enabled, channels`。`source` 对 workspace 技能默认 `customized`
  —— 出厂技能和导入技能的 `source` 都是 `customized`，无法据此区分，**只能靠「二开」tag**。
- workspace-scoped 端点都已存在且都带 `X-Agent-Id`：
  - `POST /skills`（建）、`POST /skills/upload?enable=&target_name=&rename_map=`（传 .zip，
    multipart `file`）、`PUT /skills/save`（编辑）、`DELETE /skills/{name}`（删，后端先 disable
    再 delete；删不掉返回 409）、`POST /skills/{name}/enable|disable`、`PUT /skills/{name}/tags?tags=…`
    （query 重复参数）、`PUT /skills/{name}/channels|config`、
    `POST /skills/hub/install/start` + `GET /skills/hub/install/status/{id}`（链接导入，异步任务）。
- 域守卫（`extensions/api/domain_guard`）以 `skill_scanner` analyzer 形式注册，`/skills/upload`
  与 `POST /skills` 都会经过 `SkillScanError`（`_scan_error_response` → 422 结构化 payload），
  所以这两条 ingress 路径**也会**触发网管领域校验，无需额外包装。
- gateway 的 agent id 在前端是 `portalGatewayAgentId`（`portal/src/config/portalBranding.ts`，
  默认 `"gateway"`，可被 `VITE_PORTAL_GATEWAY_AGENT_ID` / 运行时配置覆盖）。

## 设计

### A. 数据层（`portal/src/api/skills.ts`）

新增（旧的 `listPoolSkills` / `refreshPoolSkills` / `uploadSkillZipToPool` / … 一律保留，
Portal 面板只是不再用）：

- `listAgentSkills(agentId, signal?)` → `GET /skills`（`X-Agent-Id: agentId`），返回
  `WorkspaceSkillInfo[]`。
- `refreshAgentSkills(agentId)` → `POST /skills/refresh`（`X-Agent-Id`）。
- `createAgentSkill(agentId, {name, content, config?})` → `POST /skills`（`X-Agent-Id`，
  `enable: true`）。
- `uploadSkillZipToAgent(agentId, file, {targetName?})` → `POST /skills/upload?enable=true[&target_name=]`
  （`X-Agent-Id`，multipart `file`）。
- `saveAgentSkill(agentId, {name, sourceName?, content, config?, overwrite?})` → `PUT /skills/save`
  （`X-Agent-Id`）。
- `updateAgentSkillTags(agentId, name, tags)` → `PUT /skills/{name}/tags?tags=…`（`X-Agent-Id`）。
- `deleteAgentSkill(agentId, name)` → `DELETE /skills/{name}`（`X-Agent-Id`）。
- `enableWorkspaceSkill` / `disableWorkspaceSkill` 已有（带 `agentId`）—— 复用。
- 链接导入：`startHubInstallToAgent(agentId, {bundleUrl, version?, enable})` → `POST /skills/hub/install/start`
  + `getHubInstallStatus(taskId)` → `GET /skills/hub/install/status/{taskId}`；面板侧轮询直至
  `succeeded/failed/cancelled`，`failed` 时 `result` 若是 scan payload 走 `SkillScanError`。

`requestSkillsForm` 已支持 `agentId` → `X-Agent-Id`。错误处理（`throwForErrorBody`：422 scan →
`SkillScanError`、409 → `SkillConflictError`）原样复用。

### B. 面板（`skillPoolPanel.tsx`）重写要点

- 常量 `ERKAI_TAG = "二开"`；`const agentId = portalGatewayAgentId`。
- `skills` 状态类型 `PoolSkillInfo` → `WorkspaceSkillInfo`。删除 `workspaces` / `usageMap` /
  `targetWorkspace` / `targetAgentId` / "下发"相关一切。
- `loadData()`：`skillsApi.listAgentSkills(agentId)`。
- 派生：`isErkai(skill) = (skill.tags || []).includes(ERKAI_TAG)`；`enabledCount` /
  `erkaiCount` 直接数。
- 过滤 `FilterMode = "all" | "erkai" | "stock" | "enabled" | "disabled"`；chip：
  `全部` / `二开` / `出厂` / `已启用` / `未启用`。
- 卡片角标：`isErkai` → `二开`（高亮色 `.skill-pool-badge.erkai`），否则 `出厂`
  （`.skill-pool-badge.stock`）；外加 `已启用` / `已停用`。`受保护` 角标可去掉（workspace 技能
  没有 `protected`）。卡片 KV 去掉"工作区引用"，保留版本 / 更新时间 / tag。
- 详情页：
  - 头部去掉"同步"徽标、"复制为自定义技能"那套（无池概念）。保留：emoji、名称、描述、
    `二开/出厂` 徽标、版本、更新时间、`已启用/已停用`。
  - 主操作：`启用` / `停用`（`enableWorkspaceSkill` / `disableWorkspaceSkill`，约 1–2 秒生效）；
    `编辑技能`（`saveAgentSkill`）；`删除`（`deleteAgentSkill`，前端提示"会先停用再删除"，
    409 → 提示"请先停用"）。
  - 侧栏卡片：① 技能说明预览（markdown，去 frontmatter）+ tag 列表 + 「标为二开 / 取消二开」
    小按钮（`updateAgentSkillTags` 加/减 `ERKAI_TAG`）；② 技能配置 JSON（只读展示）；
    去掉"工作区引用"卡片。
- 顶部 scope 条：`管理范围：智观 AI（对外入口）的技能` · `技能总数 N` · `其中二开 M`。
- 头部按钮：`新建技能`（表单弹窗，复用现有的）、`导入技能 ▾`（下拉：`上传压缩包 (.zip)` /
  `从链接导入`）、`刷新`。**去掉「导入内置技能」**（纯池操作，无干净的 workspace 等价物）。

### C. "二开" tag 写入流程

每条"进来"的路径，成功后立即补 tag（读回该技能现有 tags，确保含 `ERKAI_TAG` 再写回；
失败只 warn，不阻断主流程，给个 notice）：

| 路径 | 主调用 | 补 tag |
|---|---|---|
| 上传 .zip | `uploadSkillZipToAgent` | 对返回的每个新技能名 `updateAgentSkillTags(agentId, name, [...tags, ERKAI_TAG])` |
| 新建表单 | `createAgentSkill` | 同上（用表单里填的 tags ∪ ERKAI_TAG）|
| 从链接导入 | `startHubInstallToAgent` + 轮询 | 任务 `succeeded` 后对安装的技能名补 tag |

出厂的 8 个技能不动。已导入的历史技能（昨天那一两个）：用户在编辑/详情页手动加 tag，或后续
一次性脚本补；本设计不自动回填。

### D. 校验失败 / 冲突的弹窗

`scanError` 弹窗逻辑原样保留（域守卫 `domain.off_topic` / `domain.check_unavailable` 分支照旧）；
`SkillConflictError` → 弹窗里提示重命名后重试。

## 测试 / 验证

无后端改动 → 不新增 pytest。前端：

- `pnpm build`（`portal/`）通过（tsconfig 宽松，无 eslint）。
- 手测：① 打开面板看到 gateway 的 8 个技能、过滤/搜索可用；② 上传一个网管相关 .zip → 出现
  且带「二开」徽标、可启用；③ 上传一个非网管 .zip → 域守卫弹窗拦下；④ 详情页「取消二开」→
  徽标变「出厂」，「标为二开」→ 变回；⑤ 停用→删除一条二开技能成功；⑥ 直接对已启用技能点删除
  → 提示先停用。

## 回滚

纯前端；`skills.ts` 旧的池方法都保留。要回退就是把 `skillPoolPanel.tsx` 的数据源换回
`listPoolSkills` + `listWorkspaceSkills`。
