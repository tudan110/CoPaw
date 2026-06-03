import { useEffect, useMemo, useState } from "react";
import {
  deleteAiBigScreen,
  generateAiBigScreenDraft,
  listAiBigScreenPlugins,
  listAiBigScreens,
  patchAiBigScreen,
  publishAiBigScreen,
  saveAiBigScreen,
} from "../../api/aiBigScreen";
import AiBigScreenRenderer from "../../components/ai-big-screen/AiBigScreenRenderer";
import type {
  AiBigScreenApp,
  AiBigScreenPlugin,
  AiBigScreenPublishTarget,
} from "../../types/aiBigScreen";
import { formatFriendlyDateTime } from "../../utils/dateTime";
import "./ai-big-screen.css";

function extractErrorMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error || "");
}

function getExternalTarget(screen: AiBigScreenApp | null): AiBigScreenPublishTarget | null {
  if (!screen?.publishTargets?.length) {
    return null;
  }
  return (
    screen.publishTargets.find((item) => item.type === "external-link")
    || screen.publishTargets[0]
  );
}

const GENERATION_STEPS = [
  "语义解析",
  "数据能力规划",
  "实时接口取数",
  "视觉编排",
  "资产固化",
];

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

function AiBigScreenGenerationStage() {
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
        <p>理解需求、调用数据能力并完成视觉排布。</p>
      </div>
      <div className="ai-big-screen-generation-flow">
        {GENERATION_STEPS.map((step, index) => (
          <div
            key={step}
            className="ai-big-screen-generation-step"
            style={{ animationDelay: `${index * 0.28}s` }}
          >
            <span>{String(index + 1).padStart(2, "0")}</span>
            <strong>{step}</strong>
          </div>
        ))}
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
  const [regionEditorOpen, setRegionEditorOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const selectedComponent = useMemo(
    () => screen?.components?.find((item) => item.id === selectedComponentId) || null,
    [screen, selectedComponentId],
  );
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
      const response = await generateAiBigScreenDraft({
        prompt: prompt.trim(),
        requestedBy: "portal",
      });
      setScreen(response.screen);
      setSelectedComponentId(response.screen.components?.[0]?.id || "");
      setRegionEditorOpen(false);
      setEditInstruction("");
      setNotice("已生成大屏草稿，可以点击组件后继续对话修改。");
    } catch (requestError) {
      setError(extractErrorMessage(requestError) || "生成大屏草稿失败");
    } finally {
      setLoading(false);
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
    try {
      const saved = await persistScreen(screen);
      const response = await patchAiBigScreen(saved.id, {
        baseVersionId: saved.versions?.[saved.versions.length - 1]?.versionId || "",
        selectedComponentId,
        instruction: editInstruction.trim(),
        requestedBy: "portal",
      });
      setScreen(response.screen);
      setEditInstruction("");
      setRegionEditorOpen(false);
      setNotice(response.summary || "组件已按自然语言要求修改。");
      await loadCatalog();
    } catch (requestError) {
      setError(extractErrorMessage(requestError) || "修改组件失败");
    } finally {
      setSaving(false);
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
      setNotice("大屏已发布，已进入展示中心，也可以通过链接打开或嵌入其他系统。");
      await loadCatalog();
    } catch (requestError) {
      setError(extractErrorMessage(requestError) || "发布大屏失败");
    } finally {
      setPublishing(false);
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
    setSelectedComponentId(item.components?.[0]?.id || "");
    setRegionEditorOpen(false);
    setEditInstruction("");
  };

  const handleSelectComponent = (componentId: string) => {
    setSelectedComponentId(componentId);
    setRegionEditorOpen(true);
    setEditInstruction("");
  };

  const handleDeleteScreen = async (item: AiBigScreenApp) => {
    const confirmed = window.confirm(`删除「${item.name}」？删除后该大屏不会再出现在管理台。`);
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
                disabled={loading}
                onClick={() => void handleGenerateDraft()}
              >
                <i className={`fas ${loading ? "fa-spinner fa-spin" : "fa-wand-magic-sparkles"}`} aria-hidden="true" />
                {loading ? "生成中..." : "确认生成大屏"}
                <i className="fas fa-arrow-right" aria-hidden="true" />
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
                <strong>{screen ? getStatusLabel(screen.status) : "未生成"}</strong>
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
                disabled={!externalTarget?.url}
                onClick={handleOpenPublished}
              >
                <i className="fas fa-arrow-up-right-from-square" aria-hidden="true" />
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

            {notice ? <div className="ai-big-screen-notice">{notice}</div> : null}
            {error ? <div className="ai-big-screen-notice error">{error}</div> : null}

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
              {screens.length ? (
                <div className="ai-big-screen-list">
                  {screens.map((item) => (
                    <article
                      key={item.id}
                      className={screen?.id === item.id ? "ai-big-screen-asset active" : "ai-big-screen-asset"}
                    >
                      <button
                        type="button"
                        className="ai-big-screen-asset-main"
                        onClick={() => handleLoadScreen(item)}
                      >
                        <span>{item.name}</span>
                        <small>
                          {getStatusLabel(item.status)} · {getComponentCount(item)} 组件 · {formatFriendlyDateTime(item.updatedAt || "")}
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
                          disabled={!getExternalTarget(item)?.url}
                          onClick={() => {
                            const target = getExternalTarget(item);
                            if (target?.url) {
                              window.open(target.url, "_blank", "noopener,noreferrer");
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

        <main className={loading ? "ai-big-screen-preview generating" : "ai-big-screen-preview"}>
          {loading ? (
            <AiBigScreenGenerationStage />
          ) : screen ? (
            <AiBigScreenRenderer
              screen={screen}
              interactive
              selectedComponentId={selectedComponentId}
              onSelectComponent={handleSelectComponent}
            />
          ) : (
            <AiBigScreenEmptyState />
          )}

          {!loading && screen && selectedComponent && regionEditorOpen ? (
            <section className="ai-big-screen-region-editor">
              <div className="ai-big-screen-region-editor-head">
                <div>
                  <span>选中区域</span>
                  <strong>{selectedComponent.title}</strong>
                  <small>{selectedComponent.type} · {selectedComponent.pluginId || "local"}</small>
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
                  onChange={(event) => setEditInstruction(event.target.value)}
                  placeholder="例如：这个区域颜色太冷，换成更有温度的风格"
                  rows={3}
                  autoFocus
                />
                <button
                  type="button"
                  className="ai-big-screen-region-submit"
                  disabled={!editInstruction.trim() || saving}
                  onClick={() => void handlePatch()}
                >
                  <i className={`fas ${saving ? "fa-spinner fa-spin" : "fa-paper-plane"}`} aria-hidden="true" />
                  {saving ? "修改中..." : "应用修改"}
                </button>
              </div>
            </section>
          ) : null}
        </main>
      </div>
    </div>
  );
}

export default AiBigScreenPanel;
