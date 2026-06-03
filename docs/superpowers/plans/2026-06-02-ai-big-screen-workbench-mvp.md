# AI Big Screen Workbench MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first working AI big-screen workbench slice: structured screen assets, built-in data plugin catalog, backend APIs, Portal preview/edit/publish UI, and standalone published-screen route.

**Architecture:** The backend owns `ScreenApp` persistence under `WORKING_DIR/extensions/ai_big_screen` using the same JSON-registry pattern as natural-language customization. AI behavior for the MVP is a deterministic service that converts natural-language prompts and component-scoped edit requests into validated screen configuration and patches; later LLM integration can replace that service boundary. Portal consumes the API and renders structured configuration through a dedicated big-screen renderer, without executing generated source code.

**Tech Stack:** Python FastAPI + Pydantic + JSON file registry; React 18 + Vite + TypeScript; ECharts through the existing `EChartsBlock` component; pytest for backend unit/API tests; `pnpm build` for frontend verification.

---

## File Structure

- Create `src/qwenpaw/extensions/api/ai_big_screen_models.py`: Pydantic request/response models and normalized field defaults for screen assets.
- Create `src/qwenpaw/extensions/ai_big_screen_registry.py`: atomic JSON registry storage for screens, versions, publish targets, and active snapshots.
- Create `src/qwenpaw/extensions/api/ai_big_screen_service.py`: built-in plugin catalog, deterministic draft generation, patch application, validation, publishing facade.
- Create `src/qwenpaw/extensions/api/ai_big_screen_api.py`: FastAPI router mounted under `/api/portal/ai-big-screens`.
- Modify `src/qwenpaw/extensions/runtime_data_paths.py`: add big-screen data paths.
- Modify `src/qwenpaw/extensions/api/portal_backend.py`: include the big-screen router.
- Create `tests/unit/extensions/api/test_ai_big_screen_api.py`: API and persistence coverage.
- Create `portal/src/types/aiBigScreen.ts`: frontend screen/plugin types.
- Create `portal/src/api/aiBigScreen.ts`: Portal API client.
- Create `portal/src/components/ai-big-screen/AiBigScreenRenderer.tsx`: structured screen renderer.
- Create `portal/src/components/ai-big-screen/ai-big-screen-renderer.css`: renderer styles.
- Create `portal/src/pages/digital-employee/aiBigScreenPanel.tsx`: workbench panel for prompt generation, component selection, edit prompt, save/publish, and preview.
- Create `portal/src/pages/digital-employee/ai-big-screen.css`: workbench panel styles.
- Create `portal/src/pages/AiBigScreenViewPage.tsx`: standalone published-screen route.
- Modify `portal/src/pages/digital-employee/helpers.ts`: add `ai-big-screen` advanced panel and route section.
- Modify `portal/src/pages/digital-employee/modelControls.tsx`: add sidebar entry and props for the big-screen workbench.
- Modify `portal/src/pages/DigitalEmployeePage.tsx`: lazy-load and render the panel.
- Modify `portal/src/App.tsx`: add `/ai-big-screen` panel route and `/big-screen/:screenId` standalone route.

## Task 1: Backend Models, Registry, and API Contract

**Files:**
- Create: `src/qwenpaw/extensions/api/ai_big_screen_models.py`
- Create: `src/qwenpaw/extensions/ai_big_screen_registry.py`
- Create: `src/qwenpaw/extensions/api/ai_big_screen_service.py`
- Create: `src/qwenpaw/extensions/api/ai_big_screen_api.py`
- Modify: `src/qwenpaw/extensions/runtime_data_paths.py`
- Modify: `src/qwenpaw/extensions/api/portal_backend.py`
- Test: `tests/unit/extensions/api/test_ai_big_screen_api.py`

- [ ] **Step 1: Write backend API tests**

Create tests that prove:

```python
def test_ai_big_screen_generate_persist_publish_and_get(monkeypatch, tmp_path):
    # Mount router under /api/portal.
    # Patch registry paths to tmp_path.
    # POST /ai-big-screens/draft with prompt "领导驾驶舱，关注告警、工单、资源"
    # Assert response has draft screen, >= 3 components, builtin plugin ids, version v1.
    # POST /ai-big-screens with returned screen.
    # POST /ai-big-screens/{screen_id}/publish.
    # GET /ai-big-screens/{screen_id}.
    # Assert status published and publishTargets contains external-link and iframe.

def test_ai_big_screen_patch_component_visual_config(monkeypatch, tmp_path):
    # Create draft from prompt.
    # Pick the first component id.
    # POST /ai-big-screens/{screen_id}/patch with selectedComponentId and instruction "颜色暖一点，标题改成今日重点风险".
    # Assert version increments, selected component title/visualConfig changes, and old version remains.

def test_ai_big_screen_plugins_route_returns_builtin_catalog():
    # GET /ai-big-screens/plugins.
    # Assert alarm, workorder, and resource plugin domains exist.
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/unit/extensions/api/test_ai_big_screen_api.py -q
```

Expected: FAIL because the new router and modules do not exist.

- [ ] **Step 3: Add runtime data paths**

Add constants:

```python
AI_BIG_SCREEN_DATA_DIR = EXTENSIONS_DATA_DIR / "ai_big_screen"
AI_BIG_SCREEN_REGISTRY_FILE = "registry.json"
AI_BIG_SCREEN_REGISTRY_PATH = AI_BIG_SCREEN_DATA_DIR / AI_BIG_SCREEN_REGISTRY_FILE
```

- [ ] **Step 4: Implement Pydantic models**

Define models for:

```python
AiBigScreenDraftRequest(prompt: str, title: str = "", requestedBy: str = "portal")
AiBigScreenPatchRequest(baseVersionId: str = "", selectedComponentId: str = "", instruction: str, requestedBy: str = "portal")
AiBigScreenPublishRequest(requestedBy: str = "portal", visibility: str = "internal")
AiBigScreenSaveRequest(screen: dict[str, Any], requestedBy: str = "portal")
AiBigScreenResponse(screen: dict[str, Any])
AiBigScreenListResponse(items: list[dict[str, Any]])
AiBigScreenPluginsResponse(items: list[dict[str, Any]])
AiBigScreenPatchResponse(screen: dict[str, Any], version: dict[str, Any], summary: str)
AiBigScreenPublishResponse(screen: dict[str, Any], publishTargets: list[dict[str, Any]])
```

- [ ] **Step 5: Implement registry storage**

Use the existing atomic write pattern:

```python
def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent), delete=False, suffix=".tmp") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        temp_path = Path(handle.name)
    temp_path.replace(path)
```

Expose:

```python
list_screens(limit=50)
get_screen(screen_id)
save_screen(screen, requested_by)
publish_screen(screen_id, requested_by, visibility)
patch_screen(screen_id, request)
```

- [ ] **Step 6: Implement service draft generation and patching**

Add a built-in plugin catalog with ids:

```text
alarm-overview
alarm-trend
workorder-risk
resource-utilization
system-health
topology-impact
```

Generate a default screen from a prompt:

```text
title: prompt title override or "AI 运维驾驶舱"
layout: 12-column grid
theme: professional dark dashboard
components: metric-card, line-chart, bar-chart, table cards chosen from prompt keywords
dataBindings: one binding per plugin-backed component
```

Patch rules:

```text
"暖色" -> selected component visualConfig.palette = "warm"
"冷色" -> "cool"
"柱状" -> type = "bar-chart" when chart-compatible
"折线" -> type = "line-chart"
"最近 7 天" -> queryParams.timeRange = "last_7_days"
"标题改成..." -> update title from the instruction tail
```

- [ ] **Step 7: Implement router and mount it**

Routes:

```text
GET /api/portal/ai-big-screens/plugins
GET /api/portal/ai-big-screens
POST /api/portal/ai-big-screens/draft
POST /api/portal/ai-big-screens
GET /api/portal/ai-big-screens/{screen_id}
POST /api/portal/ai-big-screens/{screen_id}/patch
POST /api/portal/ai-big-screens/{screen_id}/publish
```

Mount in `portal_backend.py` with:

```python
from qwenpaw.extensions.api.ai_big_screen_api import router as ai_big_screen_router
router.include_router(ai_big_screen_router)
```

- [ ] **Step 8: Run backend tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/extensions/api/test_ai_big_screen_api.py tests/unit/app/test_portal_router_registration.py -q
```

Expected: PASS.

## Task 2: Frontend API, Types, and Renderer

**Files:**
- Create: `portal/src/types/aiBigScreen.ts`
- Create: `portal/src/api/aiBigScreen.ts`
- Create: `portal/src/components/ai-big-screen/AiBigScreenRenderer.tsx`
- Create: `portal/src/components/ai-big-screen/ai-big-screen-renderer.css`

- [ ] **Step 1: Add frontend types**

Define TypeScript interfaces matching the backend:

```ts
export interface AiBigScreenApp {
  id: string;
  name: string;
  description?: string;
  status: "draft" | "published" | "archived" | string;
  layout: Record<string, unknown>;
  theme: Record<string, unknown>;
  components: AiBigScreenComponent[];
  dataBindings: AiBigScreenDataBinding[];
  versions: AiBigScreenVersion[];
  publishTargets: AiBigScreenPublishTarget[];
  updatedAt?: string;
}
```

- [ ] **Step 2: Add Portal API client**

Use the same fetch style as `naturalLanguageCustomization.ts` with base `/portal-api`.

Functions:

```ts
listAiBigScreenPlugins()
listAiBigScreens()
generateAiBigScreenDraft(payload)
saveAiBigScreen(screen)
getAiBigScreen(screenId)
patchAiBigScreen(screenId, payload)
publishAiBigScreen(screenId, payload)
```

- [ ] **Step 3: Add renderer component**

Renderer props:

```ts
interface AiBigScreenRendererProps {
  screen: AiBigScreenApp;
  selectedComponentId?: string;
  interactive?: boolean;
  onSelectComponent?: (componentId: string) => void;
}
```

Render component types:

```text
metric-card -> value + unit + trend
line-chart / bar-chart -> EChartsBlock with generated option
table -> HTML table
topology -> simple node list for MVP
text -> text block
```

- [ ] **Step 4: Add renderer CSS**

Use stable grid dimensions:

```css
.ai-big-screen-canvas { min-height: 720px; display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 12px; }
.ai-big-screen-card { min-height: 132px; border-radius: 8px; }
.ai-big-screen-card.selected { outline: 2px solid #38bdf8; }
```

- [ ] **Step 5: Run frontend build after renderer task**

Run:

```bash
cd portal && pnpm build
```

Expected: PASS.

## Task 3: Portal Workbench Panel

**Files:**
- Create: `portal/src/pages/digital-employee/aiBigScreenPanel.tsx`
- Create: `portal/src/pages/digital-employee/ai-big-screen.css`
- Modify: `portal/src/pages/digital-employee/helpers.ts`
- Modify: `portal/src/pages/digital-employee/modelControls.tsx`
- Modify: `portal/src/pages/DigitalEmployeePage.tsx`
- Modify: `portal/src/App.tsx`

- [ ] **Step 1: Add advanced panel route option**

Add `"ai-big-screen"` to `PORTAL_ADVANCED_PANEL_OPTIONS` and `PORTAL_ROUTE_SECTION_OPTIONS`.

- [ ] **Step 2: Add sidebar entry**

Add props to the sidebar component:

```ts
isAiBigScreenActive: boolean;
onOpenAiBigScreen: () => void;
```

Add a button near “轻应用工坊”:

```text
Name: AI 大屏工坊
Description: 自然语言定制运维大屏
Meta: 生成 / 修改 / 发布
```

- [ ] **Step 3: Add panel component**

Panel state:

```ts
prompt
editInstruction
screen
screens
plugins
selectedComponentId
loading
saving
publishing
notice
error
```

Primary actions:

```text
Generate draft -> generateAiBigScreenDraft
Save draft -> saveAiBigScreen
Patch selected component -> patchAiBigScreen
Publish -> publishAiBigScreen
Open published link -> window.open(target.url)
```

- [ ] **Step 4: Render panel in DigitalEmployeePage**

Lazy-load `AiBigScreenPanel`, add `isAiBigScreenMode`, include it in advanced-page-mode checks, and render it before the default chat/dashboard branch.

- [ ] **Step 5: Add `/ai-big-screen` app route**

In `App.tsx`, add:

```tsx
<Route path="/ai-big-screen" element={renderDeferredPage(<DigitalEmployeePage forcedSection="ai-big-screen" />)} />
```

- [ ] **Step 6: Run frontend build**

Run:

```bash
cd portal && pnpm build
```

Expected: PASS.

## Task 4: Standalone Published Screen Route

**Files:**
- Create: `portal/src/pages/AiBigScreenViewPage.tsx`
- Modify: `portal/src/App.tsx`

- [ ] **Step 1: Add standalone page**

Use `useParams` to read `screenId`, load `getAiBigScreen(screenId)`, render `AiBigScreenRenderer` with `interactive={false}`.

States:

```text
loading -> "正在加载大屏..."
error -> "大屏加载失败"
not published -> show warning but still render for internal MVP
```

- [ ] **Step 2: Add route**

In `App.tsx`:

```tsx
const AiBigScreenViewPage = lazyWithRetry(() => import("./pages/AiBigScreenViewPage"));
<Route path="/big-screen/:screenId" element={renderDeferredPage(<AiBigScreenViewPage />)} />
```

- [ ] **Step 3: Run frontend build**

Run:

```bash
cd portal && pnpm build
```

Expected: PASS.

## Task 5: Verification and Commit

**Files:**
- All changed files from Tasks 1-4.

- [ ] **Step 1: Run backend verification**

Run:

```bash
.venv/bin/python -m pytest tests/unit/extensions/api/test_ai_big_screen_api.py tests/unit/app/test_portal_router_registration.py -q
```

Expected: PASS.

- [ ] **Step 2: Run frontend verification**

Run:

```bash
cd portal && pnpm build
```

Expected: PASS.

- [ ] **Step 3: Inspect git status**

Run:

```bash
git status --short
```

Expected: implementation files are changed; pre-existing `portal/pnpm-lock.yaml` remains unstaged unless it was touched by this work.

- [ ] **Step 4: Commit implementation files only**

Use Lore protocol. Commit message intent:

```text
Establish a governed AI big-screen asset foundation

Constraint: AI must generate persistent screen configuration, not Portal source.
Rejected: Free-form generated frontend code | unsafe for non-technical users and hard to govern.
Confidence: medium
Scope-risk: moderate
Directive: Keep future data expansion behind plugin contracts and permission checks.
Tested: pytest targeted big-screen API tests; portal pnpm build.
Not-tested: Live production data plugins and visual circle-selection are outside MVP.
```

## Self-Review Notes

Spec coverage:

- Persistent big-screen asset: Task 1 registry/API.
- Data plugin library: Task 1 service catalog and Task 2 types.
- Portal renderer: Task 2 renderer.
- Natural-language creation: Task 1 draft generation and Task 3 panel.
- Click component then natural-language modification: Task 1 patch route and Task 3 panel.
- Publish/link/iframe shape: Task 1 publish targets and Task 4 standalone route.

Known MVP limits:

- Data plugins use built-in deterministic sample data, not live alarm/resource/workorder systems.
- AI behavior is deterministic keyword parsing to preserve the service boundary before LLM integration.
- Circle-selection and drag designer are intentionally excluded.
