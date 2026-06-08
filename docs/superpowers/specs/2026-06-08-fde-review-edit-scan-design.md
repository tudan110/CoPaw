# FDE 交付工作台 · 工作面一：审查 · 编辑 · 安全扫描可视化

> Spec · 2026-06-08 · 分支 `feat/ai-big-screen-redesign`（FDE 改造在此分支继续）
> 作者：与操作员（Vince）共同敲定，Opus 4.8
> 状态：**待实现**（已过设计评审，下一步交 `writing-plans` 出分阶段计划）

## 1. 背景与目标

FDE 交付工作台（Portal「FDE 交付中心」）是把"带客户需求去现场 → 给方案 → 研发落地"压成一个回路的元技能工作台：
**客户沟通 → 现状 → 生成 SKILL → 数字员工 → AI 自检 → 人工审查 → 确认安装 → 安全扫描**。

双脑架构已就位：LLM 智能体（`fde-onboarding` 元技能，跑在独立 `fde` 业务智能体里）做智能生成（`edit_file` 改 staged 产物）；确定性工具（`fde_tools.py` + 后端 `fde_workbench_service.py`）做 scaffold / selfcheck / probe / install。

九项能力盘点后，三项弱/缺，本轮（**工作面一**）补齐：

| 缺口 | 现状 | 本轮目标 |
| --- | --- | --- |
| **A 编辑能力** | staged 技能在工作台里只读 | 引导字段（常用旋钮）+ 高级直改（文件级 textarea），改完自动重检 |
| **B 安全扫描可视化** | 扫描结果数据齐全但被 `_scan()` 丢成 4 字段，前端渲染不出 | 富化 finding（片段/修复建议/规则名/类别/描述），前端「体检报告」逐条展示 |
| **C 人工审查工作流** | 只有只读代码查看器，无"人审过=可安装"的闸门 | 显式双闸门（AI 自检 ✓ + 人工审查 ✓），**持久化 + content_digest**，服务端强约束安装 |

**工作面二**（客户沟通 · 现状采集）单独一轮，见 §10，不在本 spec。

## 2. 范围

**在本轮**：
- 缺口B：`runtime/selfcheck.py::_scan()` 富化（工作区 runtime，单文件）。
- 缺口A：staged 技能编辑接口（引导字段 + 文件直改），路径安全，frontmatter 安全重写，改完自动重检。
- 缺口C：评审状态持久化（`_fde_meta.json` 内 `review` 块 + content_digest），评审接口，安装服务端双闸门强校验。
- 前端：`fdeWorkbenchPanel.tsx` 右栏重做为 **Layout A**（已视觉定稿），`fde.ts` 补类型与方法。
- 单测：`tests/unit/extensions/`，隔离、tmp_path、无共享全局态。

**不在本轮**：客户沟通/现状采集 UI（工作面二）；per-file 逐文件审查标记（v1 用 skill 级单闸门，见 §6）；代码编辑器库（Monaco/CodeMirror）——沿用 textarea，与 `skillPoolPanel.tsx` 既有做法一致。

## 3. 已敲定的设计决策

| # | 决策 | 取舍 |
| --- | --- | --- |
| D1 | 编辑走**混合**：引导字段（结构化旋钮）+ 高级直改（原始文件） | 常用操作不用碰代码；高级需求不被框死 |
| D2 | 安装走**显式门槛**：AI 自检 ✓ **且** 人工审查 ✓ 才能装 | 闸门语义清晰，安全可审计 |
| D3 | 评审状态走**方案 P：持久化 + content_digest** | 审过的就是装的那份；编辑后闸门自动失效；刷新/换人不丢状态。代价：每次校验算一次 digest |
| D4 | 凭证（token/密码/AK·SK）**不写进 staged 任何文件**，仍在「确认安装」时经现有 `env_values` 注入；引导字段里的密钥框是占位+install 时填，staged 阶段只把 key 名落到 `.env.example`。**后端写 `.env.example` 时对密钥型 key（名含 `TOKEN/SECRET/PASSWORD/KEY/AK/SK`，大小写不敏感）强制清空值**，前端密钥框只读占位、不随 `env` 上送——双重保证 | 守住元技能硬约束「凭证不进 SKILL.md/脚本」，复用既有 install-time 注入路径；服务端兜底不靠前端自觉 |
| D5 | 评审/digest/编辑逻辑全部放后端 `fde_workbench_service.py`（src/extensions），**不进工作区 runtime** | 逻辑单一来源，避免后端与 fde_tools 子进程两地重复；缺口B 富化是唯一进 runtime 的改动 |

## 4. 状态机

```
                       ┌──────────────── 任意编辑（fields / files 成功写入） ────────────────┐
                       │  → 重跑 selfcheck；content_digest 变 → 人工审查闸门自动失效         │
                       ▼                                                                      │
  staged ──selfcheck──▶ ready_for_review ──人工 approve──▶ approved ──install(双闸门校验)──▶ installed
   (生成后)              (AI自检 gate 1)     (要求 gate1 已过) (人工 gate 2)  (服务端再校验两闸门)   (打 二开 tag + 镜像 gateway)
```

**人工审查闸门的"有效性"是派生量，不是可漂移的存储位**：

```
effective_review =
    "approved"  if review.status == "approved" and review.content_digest == current_digest()
    "stale"     if review.status == "approved" and review.content_digest != current_digest()   # 审过但内容已改
    "pending"   otherwise
```

编辑天然让 `current_digest()` 变化 → `effective_review` 自动落回非 approved，**编辑路径无需触碰 review 块**。

## 5. 缺口B — 体检报告数据富化

**唯一进工作区 runtime 的改动。** 文件：`deploy-all/qwenpaw/working/workspaces/fde/skills/fde-onboarding/runtime/selfcheck.py`，函数 `_scan()`（当前第 40–49 行的 finding 序列化循环）。

现状只吐 `severity/title/file/line`。`Finding`（`src/qwenpaw/security/skill_scanner/models.py:130`）本身带 `id/rule_id/category/severity/title/description/file_path/line_number/snippet/remediation/analyzer/metadata`，且有 `to_dict()`。富化后每条 finding：

```python
findings.append({
    "severity": getattr(getattr(f, "severity", None), "value", str(getattr(f, "severity", ""))),
    "title": getattr(f, "title", ""),
    "file": getattr(f, "file_path", ""),
    "line": getattr(f, "line_number", None),
    # ↓ 新增（缺口B）
    "snippet": getattr(f, "snippet", None),
    "remediation": getattr(f, "remediation", None),
    "category": getattr(getattr(f, "category", None), "value", str(getattr(f, "category", "") or "")),
    "rule_id": getattr(f, "rule_id", ""),
    "description": getattr(f, "description", ""),
})
```

- 保持现有防御式 `getattr` 风格（不硬依赖 scanner 形状），不直接 `f.to_dict()`，以容忍形状漂移与缺省。
- 纯加字段，向后兼容；`status/is_safe/max_severity` 不变。
- **生效路径**：后端 `selfcheck_staged_skill` → `_run_fde_tools(["selfcheck", ...])` 子进程 → fde_tools.py → import 本文件。子进程每次新起，改完即生效，后端零改动。
- **同步**：改 repo seed（`deploy-all/...`）后需 `./sync-qwenpaw-working.sh` 同步到运行时 `~/.qwenpaw/workspaces/fde/...` 才对线上生效；单测直接 import deploy-all 这份。

## 6. 缺口A + C — 后端（src/qwenpaw/extensions/）

全部落在 **`fde_workbench_service.py`**（逻辑）+ **`portal_backend.py`**（路由）+ **`fde_workbench_models.py`**（模型）。上游 `src/qwenpaw/` 核心不动。

### 6.1 新增请求模型（`fde_workbench_models.py`）

```python
class FdeEditFieldsRequest(BaseModel):
    """引导字段：只改提供的键，未提供的保持原样。"""
    description: str | None = None
    triggers: list[str] | None = None
    category: str | None = None
    tags: list[str] | None = None
    # 非密配置（如 <UPPER>_BASE_URL / 接口URL）→ 写入 .env.example 模板；
    # 密钥仍在 install 时经 FdeInstallRequest.env_values 注入（D4）
    env: dict[str, str] | None = None

class FdeStagedFile(BaseModel):
    path: str       # skill_dir 相对路径
    content: str

class FdeEditFilesRequest(BaseModel):
    files: list[FdeStagedFile]   # 批量；代码 Tab 单文件保存时长度为 1

class FdeReviewRequest(BaseModel):
    action: Literal["approve", "reset"]
    approved_by: str | None = None   # 审计标签（portal 无强鉴权，best-effort）
```

### 6.2 新增/改动服务函数（`fde_workbench_service.py`）

| 函数 | 作用 |
| --- | --- |
| `_staged_content_digest(skill_dir) -> str` | sha256，覆盖 skill_dir 下**除** `_STAGED_INTERNAL_FILES`（`_fde_meta.json`/`GENERATION.md`）外所有文件，按相对路径排序、读字节拼接。跳过 `__pycache__`/`.pyc`（与 scaffolder 复制过滤一致）。排除 `_fde_meta.json` 避免"写 digest 改 digest"自指 |
| `_review_state(skill_dir, meta) -> dict` | 读 `meta["review"]`（缺省视为 pending），算 `digest_matches` 与 `effective`（§4 公式），返回 `{status, approved_by, approved_at, content_digest, digest_matches, effective}` |
| `_rewrite_frontmatter(skill_md, updates) -> str` | **外科式**行级重写 SKILL.md frontmatter：逐 key 替换/追加，保留正文与其它键原样。`description/category` 出标量（含特殊字符则双引号包裹），`triggers/tags` 出 flow 列表 `[a, b, c]`。**不引 PyYAML 全量 dump**（避免重排/改风格）。产物须仍是合法 YAML（单测用 `yaml.safe_load` 往返校验） |
| `_safe_staged_target(skill_dir, rel) -> Path` | 路径安全：resolve 后必须仍在 `skill_dir` 内（拒 `..`/绝对路径/越界）；拒 `_STAGED_INTERNAL_FILES`；拒符号链接；仅允许文本写入 |
| `edit_staged_fields(name, req) -> dict` | 校验名 → 改 SKILL.md frontmatter（`_rewrite_frontmatter`）+ 写 `.env.example`（`req.env` 的 key/value，密钥型 key 值强制清空，D4）→ 返回 §6.4 detail（含重跑 selfcheck） |
| `edit_staged_files(name, files) -> dict` | 校验名 → 逐文件 `_safe_staged_target` + 写入 → 返回 §6.4 detail（含重跑 selfcheck） |
| `set_staged_review(name, action, approved_by) -> dict` | `approve`：先重跑 selfcheck，`ready_for_review` 必须为 true，否则 `FdeWorkbenchError`；写 `meta["review"]={status:"approved", approved_by, approved_at:now_iso, content_digest:current_digest}`。`reset`：写 `{status:"pending", approved_by:null, approved_at:null, content_digest:null}`。返回 §6.4 detail |
| `staged_detail(name, *, with_selfcheck) -> dict` | 组合 `show_staged_skill`（bundle）+ `_review_state`（+ 可选 `selfcheck_staged_skill`），见 §6.4 |
| `install_staged_skill(...)` **改** | 读完 `_fde_meta.json`（现 1061–1069 行）后、`_read_staged_bundle` 前插入**双闸门**（§6.5） |

`_fde_meta.json` 的 `review` 块（追加到 scaffolder 现有 schema，缺省即 pending；不强制 bump schema 版本，读时容忍有无）：

```json
"review": {
  "status": "pending" | "approved",
  "approved_by": "<label or null>",
  "approved_at": "<ISO8601 or null>",
  "content_digest": "<sha256 hex or null>"
}
```

### 6.3 新增路由（`portal_backend.py`，prefix `/api/portal`，前端经 nginx `/portal-api/*`）

| 方法 · 路径 | body | 返回 |
| --- | --- | --- |
| `PUT /fde/staged/{name}/fields` | `FdeEditFieldsRequest` | §6.4 mutation result |
| `PUT /fde/staged/{name}/files` | `FdeEditFilesRequest` | §6.4 mutation result |
| `POST /fde/staged/{name}/review` | `FdeReviewRequest` | §6.4 mutation result |
| `GET /fde/staged/{name}` **改** | — | 现有 bundle **+ `review`**（`_review_state`） |

错误：`FdeWorkbenchError` → 现有处理（4xx + message）。路径安全/非法名 → 400；安装闸门不满足 → 422，message 指明缺哪道闸门。

### 6.4 统一返回形（编辑/评审三个 mutator）

让面板一次响应即可重渲染状态条 + 体检报告 + 代码：

```jsonc
// FdeStagedMutationResult
{
  "staged":    { /* show-staged bundle: tree/content/files/meta */ "review": { /* _review_state */ } },
  "selfcheck": { /* run_selfcheck 全量：ready_for_review/scan(富)/domain/syntax/todo/blocked_reasons */ }
}
```

`GET /fde/staged/{name}` 仍只回 `staged`（含 `review`）；selfcheck 维持独立 `POST .../selfcheck`（与现前端调用习惯一致，减少 churn）。

### 6.5 安装双闸门（服务端强约束，不靠前端禁用按钮）

`install_staged_skill` 内，读 meta 之后：

```python
sc = selfcheck_staged_skill(name)            # gate 1：AI 自检（权威，子进程重跑）
if not sc.get("ready_for_review"):
    raise FdeWorkbenchError("AI 自检未通过，不能安装：" + "；".join(sc.get("blocked_reasons") or []))
rv = _review_state(skill_dir, meta)          # gate 2：人工审查
if rv["effective"] != "approved":
    raise FdeWorkbenchError("人工审查未通过或内容已改需复审，不能安装")
```

- gate 1 在 `service.create_skill` 的真实扫描之前 fail-fast，给友好 message；真实扫描（`SkillScanError`）仍是最后兜底。
- `skip_domain_check` 语义不变：仅覆盖 install 路径自身的域审查不可用，不影响这两道闸门（`ready_for_review` 不因域**不可用**而 false，只因域 **reject** 而 false）。

## 7. 前端（portal/）— Layout A

视觉已定稿（`.superpowers/brainstorm/1627988-1780886257/content/layout-A-detail.html`）。

### 7.1 `src/api/fde.ts`

```ts
export interface FdeScanFinding {
  severity: string; title: string; file: string; line: number | null;
  snippet?: string | null; remediation?: string | null;   // 缺口B
  category?: string; rule_id?: string; description?: string;
}
export interface FdeReviewState {
  status: "pending" | "approved";
  approved_by: string | null; approved_at: string | null;
  content_digest: string | null;
  digest_matches: boolean;
  effective: "approved" | "stale" | "pending";
}
// FdeStagedDetail += review: FdeReviewState
// 新方法：
//   editFields(name, body: FdeEditFieldsRequest): Promise<FdeStagedMutationResult>
//   editFiles(name, files: FdeStagedFile[]): Promise<FdeStagedMutationResult>
//   review(name, action: "approve"|"reset", approvedBy?): Promise<FdeStagedMutationResult>
```

### 7.2 `src/pages/digital-employee/fdeWorkbenchPanel.tsx`

右栏重做：

- **常驻状态条**：技能名 + 安装目标下拉 + 两枚闸门徽章——AI 自检（`selfcheck.ready_for_review` → ✓通过/✗未过）；人工审查（`review.effective` → ✓通过 / ⚠审查已失效·内容已改请复审 / ○待审）。
- **Tabs**：概览 ｜ 代码·N ｜ 试跑。
- **概览**：
  - 体检报告 card：`scan.findings` 逐条渲染（等级徽章 / 文件:行 / `snippet` 代码片段 / `remediation` 修复建议 / `rule_id` 规则名）；域审查 verdict（decision/category/confidence/reason）；语法（n/n 通过 + errors）；待补全（`todo`）。
  - 引导字段 card：描述 / 触发词 / 接口URL（= `<UPPER>_BASE_URL` env）/ .env key → 「保存并重检」调 `editFields`。
- **代码**：文件树（来自 bundle）+ 选中文件 textarea 直改 → 「保存并重检」调 `editFiles`。
- **试跑**：复用现有 probe。
- **Sticky footer**：保存并重检 ｜ 审查通过（调 `review("approve")`）｜ 确认安装（两闸门皆绿才 enable；服务端 §6.5 仍强校验）。编辑后 `effective` 落回非 approved，安装键自动变灰。

技术约束（沿用现状）：antd + 无代码编辑器库 → textarea；`HEAVY_TIMEOUT_MS=120000` 用于 selfcheck/install/probe 这类慢调用，编辑后重检亦走此超时。

## 8. 测试策略（`tests/unit/extensions/`）

> ⚠️ 既有记忆：`fde_workbench` 测试**顺序敏感**（`project_extensions_test_flakiness`）。新测试一律独立模块、`tmp_path` 造 staged 夹具、不碰共享全局态/真实 `~/.qwenpaw`。

| 用例 | 断言 |
| --- | --- |
| 富化 finding 形状（缺口B） | 扫一个含已知 finding 的夹具，`snippet/remediation/category/rule_id/description` 均在；旧字段不丢 |
| `_staged_content_digest` 稳定性 | 同内容→同 digest；改任一受管文件→变；改 `_fde_meta.json`/`GENERATION.md`→不变 |
| `_safe_staged_target` 路径安全 | 拒 `../x`、绝对路径、`_fde_meta.json`、`GENERATION.md`、符号链接 |
| `_rewrite_frontmatter` | 改 description/triggers/tags/category，保留正文+其它键；`yaml.safe_load` 往返合法；幂等 |
| 评审生命周期 | `approve` 要求 `ready_for_review`；写入 status/digest/approved_at；`reset` 清空 |
| 编辑后失效（D3 核心） | approve 后 `editFiles` 改一字节 → `_review_state.effective == "stale"`（非 approved） |
| 安装双闸门（§6.5） | `ready_for_review=false` → 拒；评审非 approved → 拒；两者皆满足 → 放行（mock 真实 create_skill/镜像，避免重依赖） |

## 9. 变更面汇总（守住内部 delta 边界）

| 层 | 文件 | 改动 |
| --- | --- | --- |
| 工作区 runtime（deploy-all seed + sync） | `.../fde-onboarding/runtime/selfcheck.py` | `_scan()` 富化（缺口B），唯一 runtime 改动 |
| 后端 extensions | `fde_workbench_models.py` | +4 请求模型 |
| | `fde_workbench_service.py` | +digest/review/rewrite/safe-path/edit×2/review/staged_detail；改 install 双闸门 |
| | `portal_backend.py` | +3 路由；GET detail 带 review |
| 前端 portal | `src/api/fde.ts` | 富化 finding 类型；+review 类型与字段；+editFields/editFiles/review |
| | `src/pages/digital-employee/fdeWorkbenchPanel.tsx` | Layout A 右栏重做 |
| 测试 | `tests/unit/extensions/` | 新独立模块（§8） |

上游 `src/qwenpaw/`（`extensions/` 除外）零改动；全部落在 `extensions/` + `portal/` + `deploy-all/` 工作区资产，符合内部分支约定。

## 10. 工作面二（下一轮，不在本 spec）

客户沟通 · 现状采集：把"访谈→需求单→现状"前移到工作台引导（目前靠 FDE 智能体对话承载）。单独 brainstorm + spec，复用本轮的 staged/审查/安装回路。

## 11. 风险与开放点

- **selfcheck 双份同步**：缺口B 改 deploy-all seed 后必须 sync 到运行时才线上生效——实现计划里列为显式步骤，避免"改了没效果"。
- **frontmatter 重写脆弱性**：外科式行级重写对畸形 frontmatter 可能不鲁棒；用 `yaml.safe_load` 往返单测兜底，畸形输入回退为"整体不动 + 报错"而非写坏。
- **digest 非确定性来源**：digest 只覆盖文件字节（确定性）；selfcheck 的域审查含 LLM 非确定性，但 `ready_for_review` 不依赖域**可用性**，approve 时已要求其为 true，install 再权威重跑——三重保证下 approve→install 间的翻转窗口可忽略。
- **portal 无强鉴权**：`approved_by` 是审计标签非身份凭证；内部工具可接受，工作面二若引入操作员身份再收紧。
