import { useEffect, useMemo, useState } from "react";
import {
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

export function AiBigScreenPanel() {
  const [prompt, setPrompt] = useState("领导驾驶舱，关注今日告警、待处理工单、资源利用率和重点系统健康度");
  const [editInstruction, setEditInstruction] = useState("");
  const [screen, setScreen] = useState<AiBigScreenApp | null>(null);
  const [screens, setScreens] = useState<AiBigScreenApp[]>([]);
  const [plugins, setPlugins] = useState<AiBigScreenPlugin[]>([]);
  const [selectedComponentId, setSelectedComponentId] = useState("");
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

  return (
    <div className="ai-big-screen-panel">
      <div className="portal-model-page-header">
        <div className="portal-model-page-title">
          AI 大屏工坊 <small>自然语言生成、修改和发布运维大屏</small>
        </div>
      </div>

      <div className="ai-big-screen-workspace">
        <aside className="ai-big-screen-sidebar">
          <section className="ai-big-screen-control">
            <label htmlFor="ai-big-screen-prompt">大屏需求</label>
            <textarea
              id="ai-big-screen-prompt"
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              rows={5}
            />
            <button
              type="button"
              className="primary-btn"
              disabled={loading}
              onClick={() => void handleGenerateDraft()}
            >
              {loading ? "生成中..." : "生成大屏草稿"}
            </button>
          </section>

          <section className="ai-big-screen-control">
            <div className="ai-big-screen-control-head">
              <label htmlFor="ai-big-screen-edit">组件修改</label>
              <span>{selectedComponent ? selectedComponent.title : "未选择"}</span>
            </div>
            <textarea
              id="ai-big-screen-edit"
              value={editInstruction}
              onChange={(event) => setEditInstruction(event.target.value)}
              placeholder="例如：这个大屏太丑了，帮我调成更适合领导看的风格"
              rows={4}
            />
            <button
              type="button"
              className="secondary-btn"
              disabled={!screen || !selectedComponentId || saving}
              onClick={() => void handlePatch()}
            >
              {saving ? "处理中..." : "修改选中组件"}
            </button>
          </section>

          <section className="ai-big-screen-actions">
            <button
              type="button"
              className="secondary-btn"
              disabled={!screen || saving}
              onClick={() => void handleSave()}
            >
              保存草稿
            </button>
            <button
              type="button"
              className="primary-btn"
              disabled={!screen || publishing}
              onClick={() => void handlePublish()}
            >
              {publishing ? "发布中..." : "发布大屏"}
            </button>
            <button
              type="button"
              className="secondary-btn"
              disabled={!externalTarget?.url}
              onClick={handleOpenPublished}
            >
              打开发布链接
            </button>
            <button
              type="button"
              className="secondary-btn"
              onClick={handleOpenGallery}
            >
              打开展示中心
            </button>
          </section>

          {notice ? <div className="ai-big-screen-notice">{notice}</div> : null}
          {error ? <div className="ai-big-screen-notice error">{error}</div> : null}

          <section className="ai-big-screen-library">
            <h3>已保存大屏</h3>
            {screens.length ? (
              <div className="ai-big-screen-list">
                {screens.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className={screen?.id === item.id ? "active" : ""}
                    onClick={() => {
                      setScreen(item);
                      setSelectedComponentId(item.components?.[0]?.id || "");
                    }}
                  >
                    <span>{item.name}</span>
                    <small>{item.status} · {formatFriendlyDateTime(item.updatedAt || "")}</small>
                  </button>
                ))}
              </div>
            ) : (
              <p>暂无已保存大屏。</p>
            )}
          </section>

          <section className="ai-big-screen-library">
            <h3>内置数据插件</h3>
            <div className="ai-big-screen-plugin-tags">
              {plugins.map((plugin) => (
                <span key={plugin.id}>{plugin.name}</span>
              ))}
            </div>
          </section>
        </aside>

        <main className="ai-big-screen-preview">
          {screen ? (
            <AiBigScreenRenderer
              screen={screen}
              interactive
              selectedComponentId={selectedComponentId}
              onSelectComponent={setSelectedComponentId}
            />
          ) : (
            <div className="ai-big-screen-empty">
              <i className="fas fa-display" />
              <p>输入需求后生成大屏草稿。</p>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

export default AiBigScreenPanel;
