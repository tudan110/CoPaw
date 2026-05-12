# Portal 技能面板：gateway 工作区视图 + "二开" tag — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Portal 的「技能池」面板改为只展示 `gateway`（智观 AI）这个对外入口 agent 实际拥有的技能（它的 workspace 那一份），并给所有"通过 Portal 进来"的技能打上写入 manifest 的「二开」tag，与出厂技能区分开。

**Architecture:** 纯前端改动。面板从「全局技能池 `/skills/pool`」切到「workspace-scoped `/skills`（`X-Agent-Id: gateway`）」。所有需要的 workspace-scoped 端点已在 QwenPaw 后端存在（建/传/编/删/启停/改 tag/Hub 异步安装），域守卫在 `/skills/upload` 与 `POST /skills` 也会触发。`skills.ts` 旧的池方法保留不删。

**Tech Stack:** React + Vite（`portal/`，pnpm，tsconfig `strict: false`，无 eslint，build = `vite build`），TypeScript。

参考 spec：`docs/superpowers/specs/2026-05-12-portal-gateway-skill-view-design.md`。

**测试说明：** `portal/` 没有单测/测试 runner，"测试"= `pnpm build` 通过 + 文末手测清单。每个任务结束跑一次 build 即可。

---

## File Structure

- `portal/src/api/skills.ts` — **Modify**：新增 6 个带 `X-Agent-Id` 的 agent-scoped 方法 + 2 个 Hub 异步方法 + 相关 result 接口。旧的 `listPoolSkills` / `uploadSkillZipToPool` / `importSkillFromHub` / `listBuiltinSources` / `importBuiltinSkills` / `downloadPoolSkill` 等**保留**（Portal 不再用，但不删）。
- `portal/src/pages/skill-pool.css` — **Modify**：追加 `.skill-pool-badge.erkai` / `.skill-pool-badge.stock`、以及 hub-import 进度条的微样式。
- `portal/src/pages/digital-employee/skillPoolPanel.tsx` — **Rewrite**：数据源换成 `listAgentSkills(portalGatewayAgentId)`；删 `workspaces`/`usageMap`/"下发"那套；过滤改成 `全部/二开/出厂/已启用/未启用`；卡片与详情页按 spec §B 调整；导入下拉只留 `上传压缩包` + `从链接导入`，去掉 `导入内置技能`；每条"进来"的路径成功后补「二开」tag。
- 不动：`portal/src/pages/digital-employee/mcpPanel.tsx`、`portal/src/pages/DigitalEmployeePage.tsx`、QwenPaw 后端。

---

## Task 1: skills.ts — agent-scoped API 方法

**Files:**
- Modify: `portal/src/api/skills.ts`

- [ ] **Step 1: 在 `skills.ts` 末尾、`skillsApi` 对象之前，加 Hub 任务相关接口**

在文件中 `export interface PoolDownloadResult { ... }` 之后、`export const skillsApi = {` 之前插入：

```typescript
export type HubInstallTaskStatus =
  | "pending"
  | "importing"
  | "completed"
  | "failed"
  | "cancelled";

export interface HubInstallTask {
  task_id: string;
  bundle_url: string;
  version: string;
  enable: boolean;
  status: HubInstallTaskStatus;
  error: string | null;
  result:
    | { installed?: boolean; name?: string; enabled?: boolean; source_url?: string }
    | SkillScanErrorPayload
    | Record<string, unknown>
    | null;
  created_at: number;
  updated_at: number;
}
```

- [ ] **Step 2: 在 `skillsApi` 对象里追加 agent-scoped 方法**

在 `skillsApi` 对象内（`disableWorkspaceSkill` 之后即可）追加：

```typescript
  // --- Agent-scoped (X-Agent-Id) workspace skill APIs ---

  listAgentSkills: (agentId: string, signal?: AbortSignal) =>
    requestSkills<WorkspaceSkillInfo[]>("/skills", { agentId, signal }),

  refreshAgentSkills: (agentId: string) =>
    requestSkills<WorkspaceSkillInfo[]>("/skills/refresh", {
      method: "POST",
      agentId,
    }),

  createAgentSkill: (
    agentId: string,
    payload: { name: string; content: string; config?: Record<string, unknown> },
  ) =>
    requestSkills<{ created: boolean; name: string }>("/skills", {
      method: "POST",
      agentId,
      body: {
        name: payload.name,
        content: payload.content,
        config: payload.config || {},
        enable: true,
      },
    }),

  saveAgentSkill: (
    agentId: string,
    payload: {
      name: string;
      sourceName?: string;
      content: string;
      config?: Record<string, unknown>;
      overwrite?: boolean;
    },
  ) =>
    requestSkills<SavePoolSkillResult>("/skills/save", {
      method: "PUT",
      agentId,
      body: {
        name: payload.name,
        source_name: payload.sourceName,
        content: payload.content,
        config: payload.config || {},
        overwrite: Boolean(payload.overwrite),
      },
    }),

  uploadSkillZipToAgent: (
    agentId: string,
    file: File,
    options: { targetName?: string; renameMap?: Record<string, string> } = {},
  ) => {
    const params = new URLSearchParams();
    params.set("enable", "true");
    if (options.targetName?.trim()) {
      params.set("target_name", options.targetName.trim());
    }
    if (options.renameMap && Object.keys(options.renameMap).length) {
      params.set("rename_map", JSON.stringify(options.renameMap));
    }
    const formData = new FormData();
    formData.append("file", file);
    return requestSkillsForm<SkillImportResult>(
      `/skills/upload?${params.toString()}`,
      formData,
      { agentId },
    );
  },

  updateAgentSkillTags: (agentId: string, skillName: string, tags: string[]) => {
    const params = new URLSearchParams();
    if (tags.length) {
      tags.forEach((tag) => params.append("tags", tag));
    } else {
      params.append("tags", "");
    }
    return requestSkills<{ updated: boolean; tags: string[] }>(
      `/skills/${encodeURIComponent(skillName)}/tags?${params.toString()}`,
      { method: "PUT", agentId },
    );
  },

  deleteAgentSkill: (agentId: string, skillName: string) =>
    requestSkills<{ deleted: boolean }>(`/skills/${encodeURIComponent(skillName)}`, {
      method: "DELETE",
      agentId,
    }),

  startHubInstallToAgent: (
    agentId: string,
    payload: { bundleUrl: string; version?: string; targetName?: string },
  ) =>
    requestSkills<HubInstallTask>("/skills/hub/install/start", {
      method: "POST",
      agentId,
      body: {
        bundle_url: payload.bundleUrl.trim(),
        version: payload.version?.trim() || "",
        target_name: payload.targetName?.trim() || "",
        enable: true,
      },
    }),

  getHubInstallStatus: (taskId: string, signal?: AbortSignal) =>
    requestSkills<HubInstallTask>(
      `/skills/hub/install/status/${encodeURIComponent(taskId)}`,
      { signal },
    ),
```

> 注：`requestSkillsForm` 的第三个参数已支持 `{ agentId }`（见现有签名）；`requestSkills` 的 `agentId` 选项已存在。`SkillImportResult` / `SavePoolSkillResult` / `WorkspaceSkillInfo` / `SkillScanErrorPayload` 都已在本文件定义。

- [ ] **Step 3: build 检查**

Run: `cd portal && pnpm install --frozen-lockfile && pnpm build`
Expected: 构建成功，无 TS 报错。

- [ ] **Step 4: Commit**

```bash
git add portal/src/api/skills.ts
git commit -m "feat(portal): agent-scoped workspace skill API methods"
```

---

## Task 2: skill-pool.css — 「二开 / 出厂」徽标 + hub 进度样式

**Files:**
- Modify: `portal/src/pages/skill-pool.css`

- [ ] **Step 1: 在 `skill-pool.css` 末尾追加**

```css
/* --- gateway-scoped skill view --- */
.skill-pool-badge.erkai {
  background: rgba(124, 92, 255, 0.16);
  color: #7c5cff;
  border: 1px solid rgba(124, 92, 255, 0.32);
}
.skill-pool-badge.stock {
  background: rgba(120, 144, 156, 0.14);
  color: #607d8b;
  border: 1px solid rgba(120, 144, 156, 0.28);
}
.skill-pool-hub-progress {
  margin-top: 12px;
  font-size: 13px;
  color: #607d8b;
  display: flex;
  align-items: center;
  gap: 8px;
}
.skill-pool-tag-toggle {
  margin-top: 8px;
}
```

> 若现有 `.skill-pool-badge` 已统一控制圆角/字号/内边距，上面只覆盖配色即可；如果没有，补 `.skill-pool-badge.erkai, .skill-pool-badge.stock { border-radius: 999px; padding: 1px 8px; font-size: 11px; }`。

- [ ] **Step 2: Commit**

```bash
git add portal/src/pages/skill-pool.css
git commit -m "style(portal): erkai/stock skill badges + hub-import progress"
```

---

## Task 3: skillPoolPanel.tsx — 重写为 gateway 工作区视图

**Files:**
- Rewrite: `portal/src/pages/digital-employee/skillPoolPanel.tsx`

行为规格（spec §B/§C 的可执行版）：

**Imports / 常量**
- 删 `BuiltinImportSpec` 相关 import；保留 `WorkspaceSkillInfo`、`SkillConflictError`、`SkillScanError`、`SkillScanErrorPayload`、`skillsApi`、`HubInstallTask`。
- `import { portalGatewayAgentId } from "../../config/portalBranding";`
- `const ERKAI_TAG = "二开";`
- `const agentId = portalGatewayAgentId;`（组件内常量；它是入口 agent id）

**State**（删掉旧的 `workspaces` / `targetWorkspace` / `usageMap` / builtin* / hub* 用 `hubInstall` 取代）：
- `skills: WorkspaceSkillInfo[]`，`loading`、`saving`、`notice`、`search`、`filter`、`selectedSkillName`、`scanError`、`busySkill: string | null`（替代 `assigningSkill`，用于启停/删/改 tag 的 loading）。
- 新建/编辑表单：`isModalOpen`、`modalMode: "create" | "edit"`（不再有 `fork`）、`editingSkill: WorkspaceSkillInfo | null`、`form: { name; content; tagsText; configText }`（沿用旧的 `SkillFormState`）。
- 上传弹窗：`uploadModalOpen`、`uploadFile`、`uploadTargetName`、`uploadError`。
- 链接导入弹窗：`hubModalOpen`、`hubUrl`、`hubVersion`、`hubTargetName`、`hubError`、`hubInstall: { taskId: string; status: HubInstallTask["status"] } | null`（轮询期间显示进度）。
- 导入下拉：`importMenuOpen` + `importMenuRef`（沿用旧逻辑）。

**`FilterMode = "all" | "erkai" | "stock" | "enabled" | "disabled"`**

**派生函数 / memo**
- `const isErkai = (s: WorkspaceSkillInfo) => (s.tags || []).includes(ERKAI_TAG);`
- `erkaiCount = skills.filter(isErkai).length;` `enabledCount = skills.filter(s => s.enabled).length;`
- `filteredSkills`：先按 `filter`（`all` 全过 / `erkai` → `isErkai` / `stock` → `!isErkai` / `enabled` → `s.enabled` / `disabled` → `!s.enabled`），再按 `search` 关键字在 `[name, description, source, ...tags]` 里 `includes`。
- `selectedSkill = skills.find(s => s.name === selectedSkillName) || null`；`selectedSkillName` 跟随 `filteredSkills` 自动选首项（沿用旧 `useEffect`）。

**`loadData()`**
```ts
setLoading(true);
try {
  const list = await skillsApi.listAgentSkills(agentId);
  setSkills(list);
} catch (error) {
  setNotice({ type: "error", message: describeError(error, "技能列表加载失败") });
} finally { setLoading(false); }
```
`useEffect(() => { void loadData(); }, [loadData]);`

**`handleRefresh()`**：`await skillsApi.refreshAgentSkills(agentId); await loadData();` notice `"技能列表已刷新"`。

**「二开」tag 写入助手**（成功后调；失败只 warn + notice，不抛）：
```ts
async function ensureErkaiTag(name: string) {
  // 重新读当前 tags（loadData 之后 skills 里就有），合并 ERKAI_TAG 写回
  const cur = skills.find(s => s.name === name)?.tags || [];
  if (cur.includes(ERKAI_TAG)) return;
  try {
    await skillsApi.updateAgentSkillTags(agentId, name, [...cur, ERKAI_TAG]);
  } catch (e) {
    setNotice({ type: "error", message: `技能「${name}」已导入，但「二开」标签写入失败：${describeError(e, "未知错误")}` });
  }
}
```
> 实操顺序：先 `await loadData()` 拿到最新 tags，再对每个新技能名 `await ensureErkaiTag(name)`，最后再 `await loadData()` 让徽标刷新。简单起见也可以：导入返回的 names → 直接 `updateAgentSkillTags(agentId, name, [ERKAI_TAG])`（后端 set 会覆盖；新导入技能通常没别的 tag），然后 `loadData()`。本计划采用后者（更少往返），上传/新建/Hub 三处一致。

**新建技能（表单）**
- `openCreateModal()`：`modalMode="create"`，`form = EMPTY_FORM`（沿用旧常量），开弹窗。
- `handleSubmit()`：
  - 校验 `name` / `content` 非空。
  - `create`：`await skillsApi.createAgentSkill(agentId, { name, content, config })`；成功后 tags = `parseTags(form.tagsText)` ∪ `ERKAI_TAG` → `await skillsApi.updateAgentSkillTags(agentId, name, [...tags除重])`。
  - `edit`：`await skillsApi.saveAgentSkill(agentId, { name, sourceName: editingSkill.name, content, config })`；成功后 tags = `parseTags(form.tagsText)`（**保留**用户在 tagsText 里写的；编辑时不强行加 ERKAI_TAG —— 若原来就有用户已经在 tagsText 看到并保留）→ `updateAgentSkillTags`。
  - `await loadData(); setSelectedSkillName(finalName);` notice。
  - `catch`：`SkillScanError` → `setScanError(error.payload)`；`SkillConflictError` → notice 提示重命名；否则 notice。
- `openEditModal(skill)`：`modalMode="edit"`，`form = { name: skill.name, content: skill.content || EMPTY_SKILL_CONTENT, tagsText: (skill.tags||[]).join(", "), configText: formatJson(skill.config) }`。
- 弹窗 JSX 沿用旧的（标题文案改成只有"新增技能/编辑技能"；说明文案改成"作用于智观 AI（对外入口）的技能；保存后约 1–2 秒生效"）。

**上传 .zip**
- `handleUploadSubmit()`：
```ts
if (!uploadFile) { setUploadError("请选择一个技能压缩包 (.zip)"); return; }
setSaving(true);
try {
  const result = await skillsApi.uploadSkillZipToAgent(agentId, uploadFile, { targetName: uploadTargetName });
  setUploadModalOpen(false);
  await loadData();
  // 给本次导入的技能补「二开」tag：upload 返回 { count, conflicts }，没给名字 → 用 targetName 或重新 diff。
  // 简化：upload-zip 包内通常是单技能；若填了 targetName 用它，否则取 loadData 后"刚出现的、还没有 ERKAI_TAG 的"那些。
  // 实现：在 upload 前记下 skills.map(s=>s.name) 的集合 prevNames；loadData 后 newNames = 当前 - prevNames；对 newNames 逐个 updateAgentSkillTags(agentId, name, [ERKAI_TAG])；再 loadData()。
  setNotice({ type: "success", message: `已导入 ${result.count} 个技能到「智观 AI」（已标记为二开）` });
} catch (error) {
  if (error instanceof SkillScanError) { setUploadModalOpen(false); setScanError(error.payload); }
  else if (error instanceof SkillConflictError) { setUploadError(`技能名冲突：${error.conflicts.join(", ") || "已存在同名技能"}。可填写「重命名为」后重试。`); }
  else { setUploadError(describeError(error, "上传技能失败")); }
} finally { setSaving(false); }
```
> "记下 prevNames → diff" 这段写成一个内部 helper：
> ```ts
> async function importThenTagErkai(doImport: () => Promise<void>) {
>   const prev = new Set(skills.map(s => s.name));
>   await doImport();
>   const after = await skillsApi.listAgentSkills(agentId);
>   setSkills(after);
>   const fresh = after.filter(s => !prev.has(s.name)).map(s => s.name);
>   for (const name of fresh) {
>     try { await skillsApi.updateAgentSkillTags(agentId, name, [ERKAI_TAG]); } catch { /* warn via notice */ }
>   }
>   if (fresh.length) setSkills(await skillsApi.listAgentSkills(agentId));
> }
> ```
> 上传 / 新建（create 分支）/ Hub 安装成功后都走 `importThenTagErkai`。新建表单里若用户填了别的 tag，create 分支单独处理（用 tagsText ∪ ERKAI_TAG 一次写完），不走这个 helper。

- 上传弹窗 JSX 沿用旧的（标题"上传技能压缩包"；说明改"导入到「智观 AI」的技能，会先做网管领域校验与安全扫描，导入后自动标记为二开（最大 100MB）。"）。

**从链接导入（Hub，异步轮询）**
- `handleHubSubmit()`：
```ts
if (!hubUrl.trim()) { setHubError("请填写技能链接"); return; }
setSaving(true); setHubError("");
try {
  const task = await skillsApi.startHubInstallToAgent(agentId, { bundleUrl: hubUrl, version: hubVersion, targetName: hubTargetName });
  setHubInstall({ taskId: task.task_id, status: task.status });
  // 轮询
  const installed = await pollHubInstall(task.task_id);  // 见下
  setHubInstall(null);
  if (!installed) return; // 失败/取消，错误已在 pollHubInstall 内 setHubError / setScanError
  setHubModalOpen(false);
  setNotice({ type: "success", message: `已从链接导入技能：${installed}（已标记为二开）` });
  // 给它补 ERKAI_TAG（installed 是技能名）
  await skillsApi.listAgentSkills(agentId).then(setSkills);
  try { await skillsApi.updateAgentSkillTags(agentId, installed, [ERKAI_TAG]); } catch { /* notice */ }
  await loadData();
  setSelectedSkillName(installed);
} catch (error) {
  if (error instanceof SkillScanError) { setHubModalOpen(false); setScanError(error.payload); }
  else { setHubError(describeError(error, "从链接导入失败")); }
} finally { setSaving(false); setHubInstall(null); }
```
- `pollHubInstall(taskId)`：每 1.5s `getHubInstallStatus(taskId)`，最多 ~60 次（90s）：
  - `status === "completed"`：返回 `task.result?.name`（string）。
  - `status === "failed"`：若 `task.result` 是 scan payload（`type === "security_scan_failed"` 或 `(result as any).type` 是 `domain_*` 之类——实际后端把域守卫 finding 包成 scan payload）→ `setScanError(task.result as SkillScanErrorPayload)`；否则 `setHubError(task.error || "导入失败")`。返回 `null`。
  - `status === "cancelled"`：`setHubError("已取消"); return null;`
  - 否则 `setHubInstall({ taskId, status: task.status })` 继续。
  - 超时：`setHubError("导入超时，请稍后在面板刷新查看"); return null;`
- Hub 弹窗 JSX 沿用旧的（去掉"重命名为"也行，保留也行；说明改"支持技能 Hub / 仓库发布链接；导入到「智观 AI」的技能，会先做领域校验与安全扫描，导入后自动标记为二开。"）；轮询中在按钮区下方显示 `<div className="skill-pool-hub-progress"><i className="ri-loader-4-line ri-spin" />导入中… ({hubInstall.status})</div>`，按钮 disabled。

**启用 / 停用**（detail 主操作 + 侧栏小按钮 + 列表卡片可不放）
- `handleEnable(skill)`：`window.confirm(\`在「智观 AI」启用技能「${skill.name}」？\`)` → `setBusySkill(skill.name); await skillsApi.enableWorkspaceSkill(skill.name, agentId); await loadData();` notice "约 1–2 秒生效"；`catch` `SkillScanError` → `setScanError`，否则 notice；`finally setBusySkill(null)`。
- `handleDisable(skill)`：类似，`disableWorkspaceSkill`，无 scan 分支。

**删除**
- `handleDelete(skill)`：`window.confirm(\`确认删除技能「${skill.name}」吗？删除前会先停用。\`)` →
```ts
setBusySkill(skill.name);
try {
  await skillsApi.deleteAgentSkill(agentId, skill.name); // 后端先 disable 再 delete
  if (selectedSkillName === skill.name) setSelectedSkillName(null);
  await loadData();
  setNotice({ type: "success", message: `已删除技能：${skill.name}` });
} catch (error) {
  // 409 → SkillConflictError or 普通 Error("Only disabled workspace skills can be deleted")
  setNotice({ type: "error", message: describeError(error, "删除技能失败（如仍启用请先停用）") });
} finally { setBusySkill(null); }
```

**标为二开 / 取消二开**（详情侧栏）
- `handleToggleErkai(skill)`：
```ts
const cur = skill.tags || [];
const has = cur.includes(ERKAI_TAG);
const next = has ? cur.filter(t => t !== ERKAI_TAG) : [...cur, ERKAI_TAG];
setBusySkill(skill.name);
try {
  await skillsApi.updateAgentSkillTags(agentId, skill.name, next);
  await loadData();
  setNotice({ type: "success", message: has ? `已取消「${skill.name}」的二开标记` : `已将「${skill.name}」标记为二开` });
} catch (e) {
  setNotice({ type: "error", message: describeError(e, "更新标签失败") });
} finally { setBusySkill(null); }
```

**渲染**
- 顶部 `portal-model-page-header`：标题 `技能 <small>智观 AI 的能力</small>`；actions：`新建技能`、`导入技能 ▾`（下拉只有 `上传压缩包 (.zip)` + `从链接导入`，**删 `导入内置技能`**）、`刷新`。
- `portal-model-scope-bar skill-pool-scope-bar`：`管理范围：智观 AI（对外入口）的技能` · `技能总数：{skills.length}` · `其中二开：{erkaiCount}` · `已启用：{enabledCount}`。
- 工具条：搜索框（placeholder "搜索技能名称、描述、标签或来源"）；filter chip `[["all","全部"],["erkai","二开"],["stock","出厂"],["enabled","已启用"],["disabled","未启用"]]`。
- 卡片：
  - 角标区：`{isErkai(skill) ? <span className="skill-pool-badge erkai">二开</span> : <span className="skill-pool-badge stock">出厂</span>}` + `{skill.enabled ? <span className="skill-pool-badge enabled">已启用</span> : <span className="skill-pool-badge">已停用</span>}`。
  - KV：`版本`/`skill.version_text || "未标注"`；`状态`/`skill.enabled ? "已启用" : "已停用"`；`更新时间`/`formatLastUpdated(skill.last_updated)`。去掉"工作区引用"。
  - tags 区沿用旧的（前 3 个 + `+N`）。
  - 卡片底部按钮：`详情`（选中）、`编辑`（`openEditModal`）。
- 详情页 `skill-pool-detail`：
  - header：emoji + name + description；meta 徽标：`二开/出厂`、`版本 X`、`更新于 X`、`已启用/已停用`。去掉"同步"、去掉"复制为自定义技能"。
  - `skill-pool-detail-actions`：`selectedSkill.enabled` → 显示 `停用`（红 secondary）；否则 `启用`（success）。再 `编辑技能`（secondary）。再 `删除`（红 secondary，无 disabled 条件——后端会先停用）。
  - `skill-pool-detail-grid`：
    - 左 `skill-pool-preview-card`：标题"技能说明预览" + tag 数；tag 列表（detail）；`ReactMarkdown` 渲染 `stripSkillFrontmatter(selectedSkill.content)`。
    - 右 `skill-pool-side-column`：
      - 卡片①「二开标记」：当前是 `二开 / 出厂`；按钮 `标为二开` 或 `取消二开`（`handleToggleErkai`），`disabled={busySkill === selectedSkill.name}`；hint："二开 = 通过本面板导入/新建的定制技能；出厂 = 随系统部署。误判可在此手动纠正。"
      - 卡片②「技能配置」：`Object.keys(selectedSkill.config||{}).length` 项；有则 `<pre>{JSON.stringify(...,2)}</pre>` 否则 placeholder。
      - 卡片③「启用状态」：当前 `已启用/已停用`；启停按钮（`compact`）。hint："启停后约 1–2 秒生效。"
      - **删** 旧的"工作区引用"卡片。
- 弹窗：`isModalOpen`（新建/编辑，沿用旧 JSX 改文案）、`uploadModalOpen`（沿用旧 JSX 改文案 + `agentId` 走新 api）、`hubModalOpen`（沿用旧 JSX 改文案 + 加进度条）、`scanError`（**整段沿用旧的**，域守卫 `domain.off_topic` / `domain.check_unavailable` 分支不变）。**删** `builtinModalOpen` 整块。

- [ ] **Step 1: 按上面规格重写 `skillPoolPanel.tsx`**

实际产出一份完整的新文件（结构沿用旧文件，按规格替换数据层/过滤/卡片/详情/弹窗、删 builtin 块、新建/编辑/上传/Hub 走 agent-scoped api、加 ERKAI_TAG 逻辑）。保留的纯工具函数：`parseJsonObject`、`parseTags`、`stripSkillFrontmatter`、`formatJson`、`formatLastUpdated`、`getSkillEmoji`、`describeError`、`EMPTY_SKILL_CONTENT`、`EMPTY_FORM`、`SkillFormState`。删：`getSkillSourceLabel`（改成 erkai/stock 内联）、`buildCopyName`、`WorkspaceUsage`、`BuiltinSelection`、`ModalMode` 的 `fork`。

- [ ] **Step 2: build 检查**

Run: `cd portal && pnpm build`
Expected: 构建成功，无 TS 报错（注意：`portal/tsconfig.json` 宽松，但 vite 仍会做基本类型检查 / 未用变量不报错；确认没有真正的类型错误，如把 `WorkspaceSkillInfo` 当 `PoolSkillInfo` 用导致字段缺失）。

- [ ] **Step 3: Commit**

```bash
git add portal/src/pages/digital-employee/skillPoolPanel.tsx
git commit -m "feat(portal): skill panel shows gateway workspace skills with 二开 tag"
```

---

## Task 4: 手测 + 收尾

- [ ] **Step 1: 起 portal dev（或用已构建产物 + 后端）**

Run: `cd portal && pnpm dev`（后端 `qwenpaw app` 在 8088；vite proxy 已配 `/copaw-api` → 8088）。

- [ ] **Step 2: 手测清单**

1. 打开「数字员工 → 技能」面板：看到 `gateway` 的 8 个技能（`zgops-cmdb`、`web-availability-monitor`、`inspection-analyst`、`order-workflow`、`monitoring-overview-query`、`private-line-business-monitor`、`resource-insight-query`、`multi_agent_collaboration`），都带「出厂」徽标；过滤 `二开` 时为空，`出厂` 时 8 个；搜索可用。
2. `导入技能 → 上传压缩包`：传 `../resource/qwenpaw-import-test/skill_2_netops_port_inspection.zip` → 导入成功，列表出现 `port_traffic_inspection`，带「二开」徽标；详情页可「启用」，约 1–2 秒后徽标变「已启用」。
3. `导入技能 → 上传压缩包`：传 `../resource/qwenpaw-import-test/skill_1_offtopic_recipe.zip` → 弹「无法导入：非网络管理领域」弹窗，列表无变化。
4. 选中第 2 步那个二开技能 → 详情侧栏「二开标记」点「取消二开」→ 徽标变「出厂」；再点「标为二开」→ 变回。
5. 详情页对那个二开技能：先「停用」→ 再「删除」→ 成功消失。（或直接对一个仍启用的技能点「删除」：后端会先 disable 再 delete，应也成功；若返回 409 则 notice 提示先停用。）
6. `新建技能`：填个网管相关的 SKILL.md（name `link_health_probe`，description "链路健康巡检"）→ 创建成功，带「二开」徽标。填个非网管的（description "菜谱推荐"）→ 域守卫弹窗拦下。
7. `导入技能 → 从链接导入`：填一个无效 URL → 进度条转一会儿 → 失败提示（不崩）。

- [ ] **Step 3:（可选）回填昨天已导入的技能**

若昨天有技能已经在 gateway workspace 但没「二开」tag，在详情侧栏点「标为二开」逐个补；或不补（无害）。

- [ ] **Step 4: 文档/spec 状态**

无需改 `website/docs`（内部 dev 改动）。spec 已在 `docs/superpowers/specs/2026-05-12-portal-gateway-skill-view-design.md`。

---

## Self-Review notes

- **Spec 覆盖**：§A 数据层 → Task 1；§B 面板重写 → Task 3；§C 二开 tag 写入 → Task 3（`importThenTagErkai` / create 分支 / Hub 分支 / `ensureErkaiTag` 取舍：采用 prev/after diff 版）；§D scanError 弹窗 → Task 3（沿用旧块）；CSS 徽标 → Task 2；测试/验证 → Task 4。无遗漏。
- **去掉的功能**：「导入内置技能」「复制为自定义技能(fork)」「下发到 X 并启用」「工作区引用」「同步状态」——都在 spec 非目标/明确去掉范围内。
- **类型一致性**：`listAgentSkills` 返回 `WorkspaceSkillInfo[]`；面板 `skills` 状态、`selectedSkill`、`isErkai`、卡片/详情渲染全部按 `WorkspaceSkillInfo`（有 `enabled`/`channels`，无 `protected`/`sync_status`/`latest_version_text`）。`updateAgentSkillTags` / `enableWorkspaceSkill` / `disableWorkspaceSkill` / `deleteAgentSkill` 均 `(agentId, ...)` 签名。`HubInstallTask.status` 取值 `pending|importing|completed|failed|cancelled`（注意是 `completed` 不是 `succeeded`）。
- **无 placeholder**：API 方法给了完整代码；CSS 给了完整代码；面板给了逐 handler 行为 + 关键代码片段 + 渲染结构清单（component 重写不逐行抄旧文件 700 行，但每个 handler 的输入/调用/分支/notice 都已写明，渲染区块逐一列出）。
