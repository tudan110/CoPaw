import { useCallback, useEffect, useMemo, useState } from "react";
import {
  createAiBigScreenDraftTask,
  deleteAiBigScreen,
  duplicateAiBigScreen,
  getAiBigScreenCapabilityConfig,
  getAiBigScreenDraftTask,
  getAiBigScreenMetrics,
  listAiBigScreenPlugins,
  listAiBigScreens,
  patchAiBigScreen,
  publishAiBigScreen,
  refreshAiBigScreen,
  renameAiBigScreen,
  saveAiBigScreen,
} from "../../api/aiBigScreen";
import {
  BigScreenRenderer,
  TITLE_SELECTION_ID,
} from "../../components/big-screen/BigScreenRenderer.tsx";
import { adaptLegacyScreen } from "../../components/big-screen/adaptLegacyScreen.ts";
import { summarizePatchDiff } from "../../components/big-screen/patchDiff.ts";
import {
  formatPercent,
  formatDurationMs,
  topFailingCapabilities,
  hasMetrics,
} from "../../components/big-screen/metricsFormat.ts";
import {
  groupByDomain,
  unconfiguredCount,
} from "../../components/big-screen/capabilityCatalog.ts";
import "../../components/big-screen/big-screen.css";
import type {
  AiBigScreenApp,
  AiBigScreenCapabilityConfigItem,
  AiBigScreenMetricsResponse,
  AiBigScreenPlugin,
  AiBigScreenPublishTarget,
  AiBigScreenTask,
} from "../../types/aiBigScreen";
import { formatFriendlyDateTime } from "../../utils/dateTime";
import "./ai-big-screen.css";

function extractErrorMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error || "");
}

function getExternalTarget(
  screen: AiBigScreenApp | null,
): AiBigScreenPublishTarget | null {
  if (!screen?.publishTargets?.length) {
    return null;
  }
  return (
    screen.publishTargets.find((item) => item.type === "external-link") ||
    screen.publishTargets[0]
  );
}

// Must match the backend pipeline stage names (DRAFT_STAGES in
// extensions/ai_big_screen/pipeline.py); "planning" is the legacy
// backend's only mid-flight stage, kept as an alias of step 1.
const GENERATION_STEPS = ["意图解析", "取数", "视觉编排", "资产固化"];

function generationStepIndex(stage: string): number {
  if (stage === "planning") {
    return 0;
  }
  return GENERATION_STEPS.indexOf(stage);
}

function getStatusLabel(status: string) {
  if (status === "published") {
    return "已发布";
  }
  if (status === "archived") {
    return "已归档";
  }
  return "草稿";
}

function getComponentCount(screen: AiBigScreenApp) {
  return screen.components?.length || 0;
}

// connection settings-tab key → friendly name for the unconfigured hint.
function describeSettingsTab(tab: string): string {
  const labels: Record<string, string> = {
    inoe: "INOE 网关",
    n9e: "夜莺日志",
    cmdb: "CMDB 对接",
    proxy: "自定义连接器",
  };
  return labels[tab] || tab;
}

function AiBigScreenGenerationStage({
  task,
}: {
  task: AiBigScreenTask | null;
}) {
  const activeStage = String(task?.stage || "queued");
  return (
    <section className="ai-big-screen-generation-stage" aria-live="polite">
      <div className="ai-big-screen-generation-orbit">
        <div className="ai-big-screen-generation-core">
          <i className="fas fa-wand-magic-sparkles" aria-hidden="true" />
        </div>
        <span />
        <span />
        <span />
      </div>
      <div className="ai-big-screen-generation-copy">
        <span>AI 编排进行中</span>
        <h2>正在生成大屏草稿</h2>
        <p>
          {task?.message ||
            "复杂大屏会持续调用模型和数据接口，可能需要数分钟。"}
        </p>
      </div>
      <div className="ai-big-screen-generation-flow">
        {GENERATION_STEPS.map((step, index) => {
          const activeIndex = generationStepIndex(activeStage);
          const allDone = activeStage === "completed";
          return (
            <div
              key={step}
              className={[
                "ai-big-screen-generation-step",
                !allDone && index === activeIndex ? "active" : "",
                allDone || (activeIndex >= 0 && index < activeIndex)
                  ? "done"
                  : "",
              ]
                .filter(Boolean)
                .join(" ")}
              style={{ animationDelay: `${index * 0.28}s` }}
            >
              <span>{String(index + 1).padStart(2, "0")}</span>
              <strong>{step}</strong>
            </div>
          );
        })}
      </div>
      <div className="ai-big-screen-generation-grid" aria-hidden="true">
        <span />
        <span />
        <span />
        <span />
        <span />
        <span />
        <span />
        <span />
      </div>
    </section>
  );
}

function AiBigScreenEmptyState() {
  return (
    <section className="ai-big-screen-empty">
      <div className="ai-big-screen-empty-mark">
        <i className="fas fa-display" aria-hidden="true" />
      </div>
      <h2>等待编排任务</h2>
      <p>需求提交后，这里会进入实时生成流程。</p>
    </section>
  );
}

export function AiBigScreenPanel() {
  const [prompt, setPrompt] = useState("");
  const [editInstruction, setEditInstruction] = useState("");
  const [screen, setScreen] = useState<AiBigScreenApp | null>(null);
  const [screens, setScreens] = useState<AiBigScreenApp[]>([]);
  const [plugins, setPlugins] = useState<AiBigScreenPlugin[]>([]);
  const [selectedComponentId, setSelectedComponentId] = useState("");
  const [selectedComponentIds, setSelectedComponentIds] = useState<string[]>(
    [],
  );
  // Actual on-screen geometry (grid-unit equivalent), reported by
  // BigScreenRenderer after each layout pass — real ground truth for
  // components whose stored layoutPosition is un-pinned (auto-laid-out)
  // and therefore not reliable for relative sizing instructions.
  const [renderedLayout, setRenderedLayout] = useState<
    Record<string, { x: number; y: number; w: number; h: number }>
  >({});
  const handleLayoutComputed = useCallback(
    (rects: Record<string, { x: number; y: number; w: number; h: number }>) => {
      setRenderedLayout(rects);
    },
    [],
  );
  const [generationTask, setGenerationTask] = useState<AiBigScreenTask | null>(
    null,
  );
  const [regionEditorOpen, setRegionEditorOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [extending, setExtending] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  // Inline receipt for the region-editor edit loop so a modification is never
  // "石沉大海": acknowledges instantly, then honestly reports applied / no-op /
  // error right where the user clicked.
  const [patchStatus, setPatchStatus] = useState<{
    kind: "pending" | "success" | "warn" | "error";
    text: string;
  } | null>(null);
  const [previewLines, setPreviewLines] = useState<string[]>([]);
  const [previewing, setPreviewing] = useState(false);
  const [metrics, setMetrics] = useState<AiBigScreenMetricsResponse | null>(
    null,
  );
  const [capabilityConfig, setCapabilityConfig] = useState<
    AiBigScreenCapabilityConfigItem[]
  >([]);

  const capabilityGroups = useMemo(
    () => groupByDomain(capabilityConfig),
    [capabilityConfig],
  );
  const capabilityUnconfigured = useMemo(
    () => unconfiguredCount(capabilityConfig),
    [capabilityConfig],
  );

  const selectedComponent = useMemo(
    () =>
      screen?.components?.find((item) => item.id === selectedComponentId) ||
      null,
    [screen, selectedComponentId],
  );
  // The screen-title banner is selectable via a sentinel id — it is not a
  // component, so the region editor must recognize it explicitly or the
  // editor never opens for a selected title (the "点击标题没反应" bug).
  const titleSelected =
    selectedComponentId === TITLE_SELECTION_ID ||
    selectedComponentIds.includes(TITLE_SELECTION_ID);
  const externalTarget = getExternalTarget(screen);
  const screenStats = useMemo(
    () => ({
      total: screens.length,
      published: screens.filter((item) => item.status === "published").length,
      draft: screens.filter((item) => item.status !== "published").length,
    }),
    [screens],
  );

  const loadCatalog = async () => {
    try {
      const [screensResponse, pluginsResponse] = await Promise.all([
        listAiBigScreens(),
        listAiBigScreenPlugins(),
      ]);
      setScreens(screensResponse.items || []);
      setPlugins(pluginsResponse.items || []);
    } catch (requestError) {
      setError(extractErrorMessage(requestError) || "加载 AI 大屏工坊失败");
    }
    // generation quality is supplementary — its failure never blocks the
    // catalog, so it is loaded separately and swallowed on error.
    try {
      setMetrics(await getAiBigScreenMetrics());
    } catch {
      setMetrics(null);
    }
    // data-source health is likewise supplementary.
    try {
      const config = await getAiBigScreenCapabilityConfig();
      setCapabilityConfig(config.items || []);
    } catch {
      setCapabilityConfig([]);
    }
  };

  useEffect(() => {
    void loadCatalog();
  }, []);

  const handleGenerateDraft = async () => {
    if (!prompt.trim()) {
      setError("请先输入大屏需求");
      return;
    }
    setLoading(true);
    setError("");
    setNotice("");
    try {
      const taskResponse = await createAiBigScreenDraftTask({
        prompt: prompt.trim(),
        requestedBy: "portal",
      });
      setGenerationTask(taskResponse.task);
      let task = taskResponse.task;
      for (let attempt = 0; attempt < 240; attempt += 1) {
        if (task.status === "succeeded" || task.status === "failed") {
          break;
        }
        await new Promise((resolve) => window.setTimeout(resolve, 1500));
        const taskStatusResponse = await getAiBigScreenDraftTask(task.taskId);
        task = taskStatusResponse.task;
        setGenerationTask(task);
      }
      if (task.status !== "succeeded" || !task.screen) {
        throw new Error(task.error || task.message || "生成大屏草稿失败");
      }
      const response = { screen: task.screen };
      setScreen(response.screen);
      const firstComponentId = response.screen.components?.[0]?.id || "";
      setSelectedComponentId(firstComponentId);
      setSelectedComponentIds(firstComponentId ? [firstComponentId] : []);
      setRegionEditorOpen(false);
      setEditInstruction("");
      setNotice("已生成大屏草稿，可以点击组件后继续对话修改。");
    } catch (requestError) {
      setError(extractErrorMessage(requestError) || "生成大屏草稿失败");
    } finally {
      setLoading(false);
      setGenerationTask(null);
    }
  };

  const persistScreen = async (candidate: AiBigScreenApp) => {
    const response = await saveAiBigScreen(candidate, "portal");
    setScreen(response.screen);
    await loadCatalog();
    return response.screen;
  };

  const handleSave = async () => {
    if (!screen) {
      return;
    }
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await persistScreen(screen);
      setNotice("大屏草稿已保存。");
    } catch (requestError) {
      setError(extractErrorMessage(requestError) || "保存大屏失败");
    } finally {
      setSaving(false);
    }
  };

  const handlePatch = async () => {
    if (!screen || !selectedComponentId || !editInstruction.trim()) {
      setError("请先选择组件并输入修改要求");
      return;
    }
    setSaving(true);
    setError("");
    setNotice("");
    // Instant receipt — the user sees their instruction was received before
    // the (possibly slow) model call returns.
    setPatchStatus({
      kind: "pending",
      text: "已收到指令，正在修改…模型较慢时可能需要数十秒，请稍候。",
    });
    try {
      const saved = await persistScreen(screen);
      const response = await patchAiBigScreen(saved.id, {
        baseVersionId:
          saved.versions?.[saved.versions.length - 1]?.versionId || "",
        selectedComponentId,
        selectedComponentIds,
        renderedLayout,
        selectionContext: {
          selectedTitles: selectedComponentIds
            .map((componentId) =>
              componentId === TITLE_SELECTION_ID
                ? "大屏主标题"
                : saved.components?.find(
                    (component) => component.id === componentId,
                  )?.title,
            )
            .filter(Boolean),
        },
        instruction: editInstruction.trim(),
        requestedBy: "portal",
      });
      setScreen(response.screen);
      setPreviewLines([]);
      await loadCatalog();
      // Honest outcome, driven by the real diff — not a silent no-op.
      const changes = summarizePatchDiff(response.diff);
      if (changes.length > 0) {
        setEditInstruction("");
        setRegionEditorOpen(false);
        setNotice(`已应用 ${changes.length} 项修改。`);
        setPatchStatus({
          kind: "success",
          text: `已应用 ${changes.length} 项修改：${
            response.summary || "组件已更新。"
          }`,
        });
      } else {
        // Keep the editor open. Distinguish a model flake (retry-able — not
        // the user's wording) from a genuine no-op, so we never wrongly tell
        // the user to "换种说法".
        const degraded = /降级|未生成可执行/.test(response.summary || "");
        setPatchStatus({
          kind: "warn",
          text: degraded
            ? "AI 本次没能给出具体改动（模型偶发/繁忙）。直接再点一次「应用修改」重试即可，多数情况下重试就成功——不是你的说法问题。"
            : `本次没有产生可见变化。可以再点一次重试，或把要求说得更具体些（如“放大到 1.5 倍”“换成暖色调”“标题改成运维总览”）。${
                response.summary ? `（${response.summary}）` : ""
              }`,
        });
      }
    } catch (requestError) {
      const message = extractErrorMessage(requestError) || "修改组件失败";
      setError(message);
      setPatchStatus({ kind: "error", text: `修改失败：${message}` });
    } finally {
      setSaving(false);
    }
  };

  const handlePreviewPatch = async () => {
    if (!screen || !selectedComponentId || !editInstruction.trim()) {
      setError("请先选择组件并输入修改要求");
      return;
    }
    setPreviewing(true);
    setError("");
    setNotice("");
    setPreviewLines([]);
    setPatchStatus({
      kind: "pending",
      text: "已收到，正在预览本次修改会产生哪些变更…",
    });
    try {
      const saved = await persistScreen(screen);
      const response = await patchAiBigScreen(saved.id, {
        baseVersionId:
          saved.versions?.[saved.versions.length - 1]?.versionId || "",
        selectedComponentId,
        selectedComponentIds,
        renderedLayout,
        selectionContext: {
          selectedTitles: selectedComponentIds
            .map((componentId) =>
              componentId === TITLE_SELECTION_ID
                ? "大屏主标题"
                : saved.components?.find(
                    (component) => component.id === componentId,
                  )?.title,
            )
            .filter(Boolean),
        },
        instruction: editInstruction.trim(),
        requestedBy: "portal",
        preview: true,
      });
      const lines = summarizePatchDiff(response.diff);
      setPreviewLines(lines);
      setNotice(
        lines.length
          ? `预览：将产生 ${lines.length} 项变更，确认后再应用。`
          : "预览：AI 未生成可执行的变更。",
      );
      setPatchStatus(
        lines.length
          ? {
              kind: "success",
              text: `预览：将产生 ${lines.length} 项变更，点“确认应用”生效。`,
            }
          : {
              kind: "warn",
              text: "预览：本次没有可执行的变更。可以换种说法，或直接调整尺寸/配色/字段/布局等。",
            },
      );
    } catch (requestError) {
      const message = extractErrorMessage(requestError) || "预览变更失败";
      setError(message);
      setPatchStatus({ kind: "error", text: `预览失败：${message}` });
    } finally {
      setPreviewing(false);
    }
  };

  const handleAppendPrompt = async () => {
    if (!screen) {
      setError("请先生成或载入一个大屏");
      return;
    }
    if (!prompt.trim()) {
      setError("请输入要追加的模块需求");
      return;
    }
    setExtending(true);
    setError("");
    setNotice("");
    try {
      const saved = await persistScreen(screen);
      const response = await patchAiBigScreen(saved.id, {
        baseVersionId:
          saved.versions?.[saved.versions.length - 1]?.versionId || "",
        selectedComponentId: "",
        instruction: prompt.trim(),
        requestedBy: "portal",
      });
      const nextComponents = response.screen.components || [];
      setScreen(response.screen);
      const appendedComponentId =
        nextComponents[nextComponents.length - 1]?.id || "";
      setSelectedComponentId(appendedComponentId);
      setSelectedComponentIds(appendedComponentId ? [appendedComponentId] : []);
      setRegionEditorOpen(false);
      setNotice(response.summary || "已在当前大屏基础上追加模块。");
      await loadCatalog();
    } catch (requestError) {
      setError(extractErrorMessage(requestError) || "追加模块失败");
    } finally {
      setExtending(false);
    }
  };

  const handlePublish = async () => {
    if (!screen) {
      return;
    }
    setPublishing(true);
    setError("");
    setNotice("");
    try {
      const saved = await persistScreen(screen);
      const response = await publishAiBigScreen(saved.id, {
        requestedBy: "portal",
        visibility: "internal",
      });
      setScreen(response.screen);
      setNotice(
        "大屏已发布，已进入展示中心，也可以通过链接打开或嵌入其他系统。",
      );
      await loadCatalog();
    } catch (requestError) {
      setError(extractErrorMessage(requestError) || "发布大屏失败");
    } finally {
      setPublishing(false);
    }
  };

  const handleRefreshData = async () => {
    if (!screen) {
      return;
    }
    setError("");
    setNotice("");
    try {
      // refresh works on persisted screens; persist first so a fresh
      // draft can be refreshed too (no-op when already saved).
      const saved = await persistScreen(screen);
      const response = await refreshAiBigScreen(saved.id);
      setScreen(response.screen);
      setNotice("已重新拉取各组件实时数据。");
    } catch (requestError) {
      setError(extractErrorMessage(requestError) || "刷新数据失败");
    }
  };

  const handleOpenPublished = () => {
    if (!externalTarget?.url) {
      return;
    }
    window.open(externalTarget.url, "_blank", "noopener,noreferrer");
  };

  const handleOpenGallery = () => {
    window.open("/big-screens", "_blank", "noopener,noreferrer");
  };

  const handleLoadScreen = (item: AiBigScreenApp) => {
    setScreen(item);
    const firstComponentId = item.components?.[0]?.id || "";
    setSelectedComponentId(firstComponentId);
    setSelectedComponentIds(firstComponentId ? [firstComponentId] : []);
    setRegionEditorOpen(false);
    setEditInstruction("");
  };

  const handleSelectComponent = (
    componentId: string,
    options?: { additive?: boolean },
  ) => {
    setSelectedComponentId(componentId);
    setSelectedComponentIds((current) => {
      if (!options?.additive) {
        return [componentId];
      }
      if (current.includes(componentId)) {
        const next = current.filter((item) => item !== componentId);
        return next.length ? next : [componentId];
      }
      return [...current, componentId];
    });
    setRegionEditorOpen(true);
    setEditInstruction("");
    setPatchStatus(null);
  };

  const handleDeleteScreen = async (item: AiBigScreenApp) => {
    const confirmed = window.confirm(
      `删除「${item.name}」？删除后该大屏不会再出现在管理台。`,
    );
    if (!confirmed) {
      return;
    }
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await deleteAiBigScreen(item.id);
      if (screen?.id === item.id) {
        setScreen(null);
        setSelectedComponentId("");
        setSelectedComponentIds([]);
        setRegionEditorOpen(false);
        setEditInstruction("");
      }
      await loadCatalog();
      setNotice("大屏资产已删除。");
    } catch (requestError) {
      setError(extractErrorMessage(requestError) || "删除大屏失败");
    } finally {
      setSaving(false);
    }
  };

  const handleRenameScreen = async (item: AiBigScreenApp) => {
    const nextName = window.prompt("输入新的大屏名称", item.name);
    if (!nextName?.trim() || nextName.trim() === item.name) {
      return;
    }
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const response = await renameAiBigScreen(item.id, {
        name: nextName.trim(),
        requestedBy: "portal",
      });
      if (screen?.id === item.id) {
        setScreen(response.screen);
      }
      await loadCatalog();
      setNotice("大屏名称已更新。");
    } catch (requestError) {
      setError(extractErrorMessage(requestError) || "重命名大屏失败");
    } finally {
      setSaving(false);
    }
  };

  const handleDuplicateScreen = async (item: AiBigScreenApp) => {
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const response = await duplicateAiBigScreen(item.id, {
        name: `${item.name} 副本`,
        requestedBy: "portal",
      });
      const firstComponentId = response.screen.components?.[0]?.id || "";
      setScreen(response.screen);
      setSelectedComponentId(firstComponentId);
      setSelectedComponentIds(firstComponentId ? [firstComponentId] : []);
      await loadCatalog();
      setNotice("已复制为新的草稿大屏。");
    } catch (requestError) {
      setError(extractErrorMessage(requestError) || "复制大屏失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="ai-big-screen-panel">
      <div className="portal-model-page-header">
        <div className="portal-model-page-title">
          AI 大屏工坊 <small>数据驱动的大屏设计与发布</small>
        </div>
      </div>

      <div className="ai-big-screen-workspace">
        <aside className="ai-big-screen-sidebar">
          <section className="ai-big-screen-control ai-big-screen-command-panel">
            <div className="ai-big-screen-control-title">
              <span>Prompt Console</span>
              <strong>自然语言编排</strong>
            </div>
            <label htmlFor="ai-big-screen-prompt">大屏需求</label>
            <textarea
              id="ai-big-screen-prompt"
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder="输入你想看的数据、时间范围和页面风格"
              rows={5}
            />
            <div className="ai-big-screen-prompt-action">
              <button
                type="button"
                className="ai-big-screen-run-btn"
                disabled={loading || extending}
                onClick={() => void handleGenerateDraft()}
              >
                <i
                  className={`fas ${
                    loading ? "fa-spinner fa-spin" : "fa-wand-magic-sparkles"
                  }`}
                  aria-hidden="true"
                />
                {loading ? "生成中..." : "确认生成大屏"}
                <i className="fas fa-arrow-right" aria-hidden="true" />
              </button>
              <button
                type="button"
                className="ai-big-screen-run-btn secondary"
                disabled={!screen || loading || extending || !prompt.trim()}
                onClick={() => void handleAppendPrompt()}
              >
                <i
                  className={`fas ${
                    extending ? "fa-spinner fa-spin" : "fa-layer-group"
                  }`}
                  aria-hidden="true"
                />
                {extending ? "追加中..." : "追加到当前大屏"}
              </button>
            </div>
            <div className="ai-big-screen-mini-flow" aria-hidden="true">
              <span>Intent</span>
              <i />
              <span>Data</span>
              <i />
              <span>Design</span>
              <i />
              <span>Render</span>
            </div>
          </section>

          <div className="ai-big-screen-sidebar-scroll">
            <section className="ai-big-screen-actions">
              <div className="ai-big-screen-action-head">
                <span>当前资产</span>
                <strong>
                  {screen ? getStatusLabel(screen.status) : "未生成"}
                </strong>
              </div>
              <button
                type="button"
                className="ai-big-screen-action-btn"
                disabled={!screen || saving}
                onClick={() => void handleSave()}
              >
                <i className="fas fa-floppy-disk" aria-hidden="true" />
                {saving ? "保存中..." : "保存草稿"}
              </button>
              <button
                type="button"
                className="ai-big-screen-action-btn primary"
                disabled={!screen || publishing}
                onClick={() => void handlePublish()}
              >
                <i className="fas fa-satellite-dish" aria-hidden="true" />
                {publishing ? "发布中..." : "发布大屏"}
              </button>
              <button
                type="button"
                className="ai-big-screen-action-btn"
                disabled={!screen}
                onClick={() => void handleRefreshData()}
              >
                <i className="fas fa-rotate" aria-hidden="true" />
                刷新数据
              </button>
              <button
                type="button"
                className="ai-big-screen-action-btn"
                disabled={!externalTarget?.url}
                onClick={handleOpenPublished}
              >
                <i
                  className="fas fa-arrow-up-right-from-square"
                  aria-hidden="true"
                />
                打开发布链接
              </button>
              <button
                type="button"
                className="ai-big-screen-action-btn"
                onClick={handleOpenGallery}
              >
                <i className="fas fa-table-cells-large" aria-hidden="true" />
                打开展示中心
              </button>
            </section>

            {notice ? (
              <div className="ai-big-screen-notice">{notice}</div>
            ) : null}
            {error ? (
              <div className="ai-big-screen-notice error">{error}</div>
            ) : null}

            <section className="ai-big-screen-library ai-big-screen-admin">
              <div className="ai-big-screen-section-head">
                <h3>管理后台</h3>
                <span>{screenStats.total} 个资产</span>
              </div>
              <div className="ai-big-screen-admin-metrics">
                <span>
                  <strong>{screenStats.total}</strong>
                  全部
                </span>
                <span>
                  <strong>{screenStats.published}</strong>
                  已发布
                </span>
                <span>
                  <strong>{screenStats.draft}</strong>
                  草稿
                </span>
              </div>
              {hasMetrics(metrics ?? undefined) && metrics ? (
                <div className="ai-big-screen-quality">
                  <div className="ai-big-screen-quality-head">
                    <span>生成质量</span>
                    <span>近 {metrics.total} 次</span>
                  </div>
                  <div className="ai-big-screen-quality-row">
                    <span>
                      <strong>{formatPercent(metrics.successRate)}</strong>
                      成功率
                    </span>
                    <span>
                      <strong>{formatPercent(metrics.degradedRate)}</strong>
                      降级率
                    </span>
                    <span>
                      <strong>{formatDurationMs(metrics.avgDurationMs)}</strong>
                      平均耗时
                    </span>
                  </div>
                  {topFailingCapabilities(metrics.capabilityFailureRates, 3)
                    .length ? (
                    <ul className="ai-big-screen-quality-fail">
                      {topFailingCapabilities(
                        metrics.capabilityFailureRates,
                        3,
                      ).map((item) => (
                        <li key={item.capabilityId}>
                          {item.capabilityId}
                          <em>{formatPercent(item.rate)} 失败</em>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              ) : null}
              {capabilityGroups.length ? (
                <div className="ai-big-screen-datasource">
                  <div className="ai-big-screen-datasource-head">
                    <span>数据源配置</span>
                    {capabilityUnconfigured ? (
                      <span className="ai-big-screen-datasource-warn">
                        {capabilityUnconfigured} 项待配置
                      </span>
                    ) : (
                      <span className="ai-big-screen-datasource-ok">
                        全部已配置
                      </span>
                    )}
                  </div>
                  {capabilityGroups.map((group) => (
                    <div
                      key={group.key}
                      className="ai-big-screen-datasource-group"
                    >
                      <h4>{group.label}</h4>
                      <ul>
                        {group.items.map((item) => (
                          <li
                            key={item.id}
                            className={
                              item.configured
                                ? "ds-cap configured"
                                : "ds-cap unconfigured"
                            }
                          >
                            <span className="ds-cap-name">{item.name}</span>
                            <span className="ds-cap-conn">
                              {item.connection}
                            </span>
                            {item.configured ? (
                              <span className="ds-cap-badge ok">已配置</span>
                            ) : (
                              <span
                                className="ds-cap-badge warn"
                                title={
                                  item.reason
                                    ? `${item.reason}${
                                        item.settingsTab
                                          ? `（到设置 → ${describeSettingsTab(
                                              item.settingsTab,
                                            )} 配置）`
                                          : ""
                                      }`
                                    : "未配置"
                                }
                              >
                                未配置
                              </span>
                            )}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              ) : null}
              {screens.length ? (
                <div className="ai-big-screen-list">
                  {screens.map((item) => (
                    <article
                      key={item.id}
                      className={
                        screen?.id === item.id
                          ? "ai-big-screen-asset active"
                          : "ai-big-screen-asset"
                      }
                    >
                      <button
                        type="button"
                        className="ai-big-screen-asset-main"
                        onClick={() => handleLoadScreen(item)}
                      >
                        <span>{item.name}</span>
                        <small>
                          {getStatusLabel(item.status)} ·{" "}
                          {getComponentCount(item)} 组件 ·{" "}
                          {formatFriendlyDateTime(item.updatedAt || "")}
                        </small>
                      </button>
                      <div className="ai-big-screen-asset-actions">
                        <button
                          type="button"
                          onClick={() => handleLoadScreen(item)}
                          disabled={saving}
                        >
                          <i className="fas fa-crosshairs" aria-hidden="true" />
                          载入
                        </button>
                        <button
                          type="button"
                          disabled={saving}
                          onClick={() => void handleRenameScreen(item)}
                        >
                          <i className="fas fa-pen" aria-hidden="true" />
                          重命名
                        </button>
                        <button
                          type="button"
                          disabled={saving}
                          onClick={() => void handleDuplicateScreen(item)}
                        >
                          <i className="fas fa-copy" aria-hidden="true" />
                          复制
                        </button>
                        <button
                          type="button"
                          disabled={!getExternalTarget(item)?.url}
                          onClick={() => {
                            const target = getExternalTarget(item);
                            if (target?.url) {
                              window.open(
                                target.url,
                                "_blank",
                                "noopener,noreferrer",
                              );
                            }
                          }}
                        >
                          <i className="fas fa-link" aria-hidden="true" />
                          链接
                        </button>
                        <button
                          type="button"
                          className="danger"
                          disabled={saving}
                          onClick={() => void handleDeleteScreen(item)}
                        >
                          <i className="fas fa-trash-can" aria-hidden="true" />
                          删除
                        </button>
                      </div>
                    </article>
                  ))}
                </div>
              ) : (
                <p>暂无已保存大屏。</p>
              )}
            </section>

            <section className="ai-big-screen-library">
              <div className="ai-big-screen-section-head">
                <h3>可用数据能力</h3>
                <span>{plugins.length} 项</span>
              </div>
              <div className="ai-big-screen-plugin-tags">
                {plugins.map((plugin) => (
                  <span key={plugin.id}>
                    <strong>{plugin.name}</strong>
                    <small>{plugin.domain}</small>
                  </span>
                ))}
              </div>
            </section>
          </div>
        </aside>

        <main
          className={
            loading
              ? "ai-big-screen-preview generating"
              : "ai-big-screen-preview"
          }
        >
          {loading ? (
            <AiBigScreenGenerationStage task={generationTask} />
          ) : screen ? (
            <div
              style={{
                width: "100%",
                aspectRatio: "16 / 9",
                margin: "auto",
                position: "relative",
              }}
            >
              <BigScreenRenderer
                spec={adaptLegacyScreen(screen)}
                interactive
                selectedComponentId={selectedComponentId}
                selectedComponentIds={selectedComponentIds}
                onSelectComponent={handleSelectComponent}
                onLayoutComputed={handleLayoutComputed}
              />
              {(screen.aiConversationContext as Record<string, unknown>)
                ?.degraded === true ? (
                <div
                  style={{
                    position: "absolute",
                    top: 12,
                    right: 12,
                    zIndex: 20,
                    padding: "6px 10px",
                    borderRadius: 8,
                    background: "rgba(245, 158, 11, 0.16)",
                    color: "#fbbf24",
                    fontSize: 12,
                    backdropFilter: "blur(4px)",
                  }}
                  title="大模型未能生成结构化方案，本屏由关键词护栏兜底生成"
                >
                  AI 降级 · 护栏方案
                </div>
              ) : null}
            </div>
          ) : (
            <AiBigScreenEmptyState />
          )}

          {!loading &&
          screen &&
          (selectedComponent || titleSelected) &&
          regionEditorOpen ? (
            <section className="ai-big-screen-region-editor">
              <div className="ai-big-screen-region-editor-head">
                <div>
                  <span>选中区域</span>
                  <strong>
                    {selectedComponent
                      ? selectedComponent.title
                      : `大屏主标题「${screen.title || "未命名"}」`}
                  </strong>
                  <small>
                    {selectedComponent
                      ? `${selectedComponent.type} · ${
                          selectedComponent.pluginId || "local"
                        }`
                      : "屏幕主标题 · 可改文字/颜色/大小或去掉"}
                    {selectedComponentIds.length > 1
                      ? ` · 已选 ${selectedComponentIds.length} 个区域`
                      : ""}
                  </small>
                </div>
                <button
                  type="button"
                  className="ai-big-screen-icon-btn"
                  onClick={() => setRegionEditorOpen(false)}
                  aria-label="关闭修改框"
                >
                  <i className="fas fa-times" aria-hidden="true" />
                </button>
              </div>
              <div className="ai-big-screen-region-editor-body">
                <textarea
                  value={editInstruction}
                  onChange={(event) => {
                    setEditInstruction(event.target.value);
                    if (previewLines.length) setPreviewLines([]);
                    if (patchStatus) setPatchStatus(null);
                  }}
                  placeholder="例如：这个区域颜色太冷，换成更有温度的风格"
                  rows={3}
                  autoFocus
                />
                {previewLines.length ? (
                  <ul className="ai-big-screen-preview-diff">
                    {previewLines.map((line, index) => (
                      <li key={index}>{line}</li>
                    ))}
                  </ul>
                ) : null}
                {patchStatus ? (
                  <div
                    className={`ai-big-screen-patch-status ${patchStatus.kind}`}
                    role="status"
                    aria-live="polite"
                  >
                    <i
                      className={`fas ${
                        patchStatus.kind === "pending"
                          ? "fa-spinner fa-spin"
                          : patchStatus.kind === "success"
                            ? "fa-check-circle"
                            : patchStatus.kind === "warn"
                              ? "fa-info-circle"
                              : "fa-exclamation-triangle"
                      }`}
                      aria-hidden="true"
                    />
                    <span>{patchStatus.text}</span>
                  </div>
                ) : null}
                <div className="ai-big-screen-region-actions">
                  <button
                    type="button"
                    className="ai-big-screen-region-preview"
                    disabled={!editInstruction.trim() || previewing || saving}
                    onClick={() => void handlePreviewPatch()}
                  >
                    <i
                      className={`fas ${
                        previewing ? "fa-spinner fa-spin" : "fa-eye"
                      }`}
                      aria-hidden="true"
                    />
                    {previewing ? "预览中..." : "预览变更"}
                  </button>
                  <button
                    type="button"
                    className="ai-big-screen-region-submit"
                    disabled={!editInstruction.trim() || saving}
                    onClick={() => void handlePatch()}
                  >
                    <i
                      className={`fas ${
                        saving ? "fa-spinner fa-spin" : "fa-paper-plane"
                      }`}
                      aria-hidden="true"
                    />
                    {saving
                      ? "修改中..."
                      : previewLines.length
                        ? "确认应用"
                        : "应用修改"}
                  </button>
                </div>
              </div>
            </section>
          ) : null}
        </main>
      </div>
    </div>
  );
}

export default AiBigScreenPanel;
