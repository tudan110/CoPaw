import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import PortalTraditionalViewButton from "../components/PortalTraditionalViewButton";
import {
  applyNlCustomizationVersion,
  deleteNlCustomizationVersion,
  getNlCustomizationVersion,
  getActiveNlCustomization,
  listNlCustomizationVersions,
  previewNlCustomization,
  publishNlCustomization,
  updateNlCustomizationListing,
} from "../api/naturalLanguageCustomization";
import { formatFriendlyDateTime } from "../utils/dateTime";
import type {
  NlCustomizationActiveResponse,
  NlCustomizationPreviewResponse,
  NlCustomizationVersionRecord,
} from "../types/naturalLanguageCustomization";
import "./natural-language-customization.css";

function formatJsonBlock(value: unknown) {
  return JSON.stringify(value, null, 2);
}

function extractErrorMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error || "");
}

export function NaturalLanguageCustomizationWorkspace({
  embedded = false,
}: {
  embedded?: boolean;
}) {
  const [needsModelConfig, setNeedsModelConfig] = useState(false);
  const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [preview, setPreview] = useState<NlCustomizationPreviewResponse | null>(null);
  const [activeInfo, setActiveInfo] = useState<NlCustomizationActiveResponse | null>(null);
  const [versions, setVersions] = useState<NlCustomizationVersionRecord[]>([]);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [applyingVersionId, setApplyingVersionId] = useState("");
  const [listingVersionId, setListingVersionId] = useState("");
  const [loadingEditVersionId, setLoadingEditVersionId] = useState("");
  const [deletingVersionId, setDeletingVersionId] = useState("");
  const [versionsLoading, setVersionsLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [editingVersionId, setEditingVersionId] = useState("");
  const [editingAppId, setEditingAppId] = useState("");
  const [expandedAppId, setExpandedAppId] = useState("");
  const [previewSnapshot, setPreviewSnapshot] = useState<{ title: string; prompt: string } | null>(null);

  const canPreview = prompt.trim().length > 0 && !loadingPreview;
  const isPreviewDirty = Boolean(
    previewSnapshot
    && (
      previewSnapshot.title !== title.trim()
      || previewSnapshot.prompt !== prompt.trim()
    ),
  );
  const canPublish = Boolean(preview) && !loadingPreview && !publishing && !isPreviewDirty;

  const loadActiveInfo = async () => {
    try {
      const response = await getActiveNlCustomization();
      setActiveInfo(response);
    } catch (requestError) {
      setError(extractErrorMessage(requestError) || "加载当前生效版本失败");
    }
  };

  const loadVersions = async () => {
    setVersionsLoading(true);
    try {
      const response = await listNlCustomizationVersions();
      setVersions(response.items || []);
    } catch (requestError) {
      setError(extractErrorMessage(requestError) || "加载发布记录失败");
    } finally {
      setVersionsLoading(false);
    }
  };

  useEffect(() => {
    void loadVersions();
    void loadActiveInfo();
  }, []);

  const previewBundleEntries = useMemo(() => {
    if (!preview?.bundle || typeof preview.bundle !== "object") {
      return [];
    }
    return Object.entries(preview.bundle);
  }, [preview]);

  const appGroups = useMemo(() => {
    const groups = new Map<string, {
      appId: string;
      versions: NlCustomizationVersionRecord[];
      latestVersion: NlCustomizationVersionRecord;
      activeVersion: NlCustomizationVersionRecord | null;
      listedVersion: NlCustomizationVersionRecord | null;
      title: string;
      description: string;
    }>();

    for (const item of versions) {
      const appId = item.appId || item.versionId;
      const current = groups.get(appId);
      if (!current) {
        groups.set(appId, {
          appId,
          versions: [item],
          latestVersion: item,
          activeVersion: item.isActive ? item : null,
          listedVersion: item.isListed ? item : null,
          title: item.title,
          description: item.description || "",
        });
        continue;
      }

      current.versions.push(item);
      if ((item.publishedAt || "") > (current.latestVersion.publishedAt || "")) {
        current.latestVersion = item;
      }
      if (item.isActive) {
        current.activeVersion = item;
      }
      if (item.isListed) {
        current.listedVersion = item;
      }
    }

    return Array.from(groups.values())
      .map((group) => {
        group.versions.sort((left, right) =>
          String(right.publishedAt || "").localeCompare(String(left.publishedAt || "")),
        );
        const preferredVersion = group.activeVersion || group.listedVersion || group.latestVersion;
        return {
          ...group,
          title: preferredVersion.title,
          description: preferredVersion.description || "",
        };
      })
      .sort((left, right) => {
        const leftRank = Number(Boolean(left.listedVersion)) * 2 + Number(Boolean(left.activeVersion));
        const rightRank = Number(Boolean(right.listedVersion)) * 2 + Number(Boolean(right.activeVersion));
        if (leftRank !== rightRank) {
          return rightRank - leftRank;
        }
        return String(right.latestVersion.publishedAt || "").localeCompare(
          String(left.latestVersion.publishedAt || ""),
        );
      });
  }, [versions]);

  useEffect(() => {
    if (!expandedAppId) {
      return;
    }
    if (appGroups.some((group) => group.appId === expandedAppId)) {
      return;
    }
    setExpandedAppId("");
  }, [appGroups, expandedAppId]);

  const handlePreview = async () => {
    if (!prompt.trim()) {
      setError("请先输入一段客户定制需求");
      return;
    }
    setLoadingPreview(true);
    setNotice("");
    setError("");
    setNeedsModelConfig(false);
    try {
      const response = await previewNlCustomization({
        prompt: prompt.trim(),
        title: title.trim(),
        appId: editingAppId,
      });
      setPreview(response);
      setPreviewSnapshot({
        title: title.trim(),
        prompt: prompt.trim(),
      });
      setNotice("结构化预览已生成，可以检查意图、模板和配置草案。");
    } catch (requestError) {
      const message = extractErrorMessage(requestError) || "生成预览失败";
      setError(message);
      setNeedsModelConfig(message.includes("未配置默认大模型"));
    } finally {
      setLoadingPreview(false);
    }
  };

  const handlePublish = async () => {
    if (!preview) {
      return;
    }
    setPublishing(true);
    setNotice("");
    setError("");
    try {
      const response = await publishNlCustomization({
        preview,
        requestedBy: "portal",
        title: title.trim(),
      });
      setNotice(`已发布版本 ${response.versionId}`);
      setEditingVersionId("");
      setEditingAppId(response.record.appId || editingAppId);
      await loadVersions();
      await loadActiveInfo();
    } catch (requestError) {
      setError(extractErrorMessage(requestError) || "发布失败");
    } finally {
      setPublishing(false);
    }
  };

  const handleApplyVersion = async (versionId: string) => {
    if (!versionId) {
      return;
    }
    setApplyingVersionId(versionId);
    setNotice("");
    setError("");
    try {
      const response = await applyNlCustomizationVersion({
        versionId,
        requestedBy: "portal",
      });
      setNotice(`已应用版本 ${response.versionId}。如需对用户开放，可继续上架到“应用中心”。`);
      await Promise.all([loadVersions(), loadActiveInfo()]);
    } catch (requestError) {
      setError(extractErrorMessage(requestError) || "应用版本失败");
    } finally {
      setApplyingVersionId("");
    }
  };

  const handleUpdateListing = async (versionId: string, listed: boolean) => {
    if (!versionId) {
      return;
    }
    setListingVersionId(versionId);
    setNotice("");
    setError("");
    try {
      const response = await updateNlCustomizationListing({
        versionId,
        listed,
        requestedBy: "portal",
      });
      setNotice(
        response.listed
          ? `已上架版本 ${response.versionId}，用户现在可以在“应用中心”里直接使用。`
          : `已下架版本 ${response.versionId}，该应用将不再显示在“应用中心”。`,
      );
      await Promise.all([loadVersions(), loadActiveInfo()]);
    } catch (requestError) {
      setError(extractErrorMessage(requestError) || (listed ? "上架应用失败" : "下架应用失败"));
    } finally {
      setListingVersionId("");
    }
  };

  const handleLoadVersionForEdit = async (versionId: string) => {
    if (!versionId) {
      return;
    }
    setLoadingEditVersionId(versionId);
    setNotice("");
    setError("");
    setNeedsModelConfig(false);
    try {
      const response = await getNlCustomizationVersion(versionId);
      const nextTitle = response.preview.title || response.record.title || "";
      const nextPrompt = response.preview.prompt || response.record.prompt || "";
      const nextAppId = response.preview.appId || response.record.appId || "";
      setEditingVersionId(versionId);
      setEditingAppId(nextAppId);
      setExpandedAppId(nextAppId);
      setTitle(nextTitle);
      setPrompt(nextPrompt);
      setPreview(response.preview);
      setPreviewSnapshot({
        title: nextTitle,
        prompt: nextPrompt,
      });
      setNotice(`已载入版本 ${versionId}，你可以修改需求后重新生成预览，再发布为新版本。`);
    } catch (requestError) {
      setError(extractErrorMessage(requestError) || "载入版本失败");
    } finally {
      setLoadingEditVersionId("");
    }
  };

  const handleDeleteVersion = async (versionId: string) => {
    if (!versionId) {
      return;
    }
    if (!window.confirm(`确认删除版本 ${versionId} 吗？删除后不可恢复。`)) {
      return;
    }
    setDeletingVersionId(versionId);
    setNotice("");
    setError("");
    try {
      const response = await deleteNlCustomizationVersion(versionId);
      if (editingVersionId === versionId) {
        setEditingVersionId("");
      }
      if (editingVersionId === versionId) {
        setEditingAppId("");
      }
      setNotice(`已删除版本 ${response.versionId}`);
      await Promise.all([loadVersions(), loadActiveInfo()]);
    } catch (requestError) {
      setError(extractErrorMessage(requestError) || "删除版本失败");
    } finally {
      setDeletingVersionId("");
    }
  };

  return (
    <div className={embedded ? "nl-customization-shell embedded" : "nl-customization-shell"}>
      <div className={embedded ? "nl-customization-page embedded" : "nl-customization-page"}>
        <header className={embedded ? "portal-model-page-header nl-customization-header embedded" : "nl-customization-header"}>
          <div>
            {embedded ? (
              <div className="portal-model-page-title">
                自然语言定制 <small>客户需求配置工作台</small>
              </div>
            ) : (
              <>
                <h1>自然语言定制工作台</h1>
                <p>
                  客户只需描述业务需求，系统会在受控边界内生成结构化意图、模板匹配结果和配置草案。
                  当前页面实现 MVP1：预览、发布留档和版本回看。
                </p>
              </>
            )}
          </div>
          {!embedded ? (
            <div className="nl-customization-actions">
              <Link to="/agent-center" className="ghost-btn nl-customization-link">
                返回智能体中心
              </Link>
              <PortalTraditionalViewButton />
            </div>
          ) : null}
        </header>
        <div className={embedded ? "nl-customization-content" : undefined}>
          <div className={embedded ? "nl-customization-scroll" : undefined}>
            <div className="nl-customization-grid">
              <section className="nl-card">
                <div className="nl-card-header">
                  <h2>需求输入</h2>
                  <p>输入一句自然语言需求，先生成结构化预览，再决定是否发布到客户实例配置目录。</p>
                </div>
                <div className="nl-card-body">
                  <div className="nl-form-grid">
                    {editingVersionId ? (
                      <div className="nl-version-hint">正在修改版本：{editingVersionId}</div>
                    ) : null}
                    <label>
                      <span>方案名称（可选）</span>
                      <input
                        value={title}
                        onChange={(event) => setTitle(event.target.value)}
                        placeholder="例如：网络设备报表助手"
                      />
                    </label>
                    <label>
                      <span>客户需求</span>
                      <textarea
                        value={prompt}
                        onChange={(event) => setPrompt(event.target.value)}
                        placeholder="请输入客户的自然语言需求"
                      />
                    </label>
                    <div className="nl-form-actions">
                      <button
                        type="button"
                        className="primary-btn"
                        onClick={() => void handlePreview()}
                        disabled={!canPreview}
                      >
                        {loadingPreview ? "正在生成预览..." : "生成结构化预览"}
                      </button>
                      <button
                        type="button"
                        className="ghost-btn"
                        onClick={() => {
                          setPreview(null);
                          setPreviewSnapshot(null);
                          setEditingVersionId("");
                          setEditingAppId("");
                          setTitle("");
                          setPrompt("");
                          setNotice("");
                          setError("");
                          setNeedsModelConfig(false);
                        }}
                      >
                        重置
                      </button>
                    </div>
                    {notice ? <div className="nl-status-text success">{notice}</div> : null}
                    {error ? <div className="nl-status-text error">{error}</div> : null}
                    {needsModelConfig ? (
                      <div className="nl-status-actions">
                        <Link to="/model-config" className="ghost-btn nl-customization-link">
                          去配置默认大模型
                        </Link>
                      </div>
                    ) : null}
                    {preview && isPreviewDirty ? (
                      <div className="nl-status-text error">你已经修改了标题或需求，请重新生成结构化预览后再发布。</div>
                    ) : null}
                  </div>
                </div>
              </section>

              <section className="nl-card">
                <div className="nl-card-header">
                  <h2>应用与版本管理</h2>
                  <p>按应用分组维护版本，每个应用都可以独立生效、上架、修改和删除。</p>
                </div>
                <div className="nl-card-body">
                  {versionsLoading ? <div className="nl-empty-state">正在加载版本记录...</div> : null}
                  {!versionsLoading && appGroups.length === 0 ? (
                    <div className="nl-empty-state">当前还没有应用记录。</div>
                  ) : null}
                  {!versionsLoading && appGroups.length ? (
                    <>
                      <div className="nl-app-summary-grid">
                        <div className="nl-app-summary-item">
                          <span>应用数</span>
                          <strong>{appGroups.length}</strong>
                        </div>
                        <div className="nl-app-summary-item">
                          <span>当前生效</span>
                          <strong>{appGroups.filter((group) => group.activeVersion).length}</strong>
                        </div>
                        <div className="nl-app-summary-item">
                          <span>已上架</span>
                          <strong>{appGroups.filter((group) => group.listedVersion).length}</strong>
                        </div>
                      </div>
                        <div className="nl-app-group-list">
                          {appGroups.map((group) => (
                            <article
                              key={group.appId}
                              className={`nl-app-group${expandedAppId === group.appId ? " expanded" : ""}`}
                            >
                              <div className="nl-app-group-head">
                                <div className="nl-app-group-head-main">
                                  <h3>{group.title}</h3>
                                  {group.description ? <p>{group.description}</p> : null}
                                  <div className="nl-app-compact-meta">
                                    <span>最新发布时间：{formatFriendlyDateTime(group.latestVersion.publishedAt)}</span>
                                    <span>{group.versions.length} 个版本</span>
                                    {group.activeVersion ? <span>生效中</span> : <span>未应用</span>}
                                    {group.listedVersion ? <span>已上架</span> : <span>未上架</span>}
                                  </div>
                                </div>
                                <div className="nl-app-group-head-side">
                                  <div className="nl-version-meta">
                                    {group.activeVersion ? <span className="nl-tag active">当前生效</span> : null}
                                    {group.listedVersion ? <span className="nl-tag">已上架</span> : null}
                                    <span className="nl-tag">{group.versions.length} 个版本</span>
                                  </div>
                                  <button
                                    type="button"
                                    className="ghost-btn nl-app-group-toggle"
                                    onClick={() =>
                                      setExpandedAppId((current) => (current === group.appId ? "" : group.appId))
                                    }
                                  >
                                    {expandedAppId === group.appId ? "收起版本" : "展开版本"}
                                  </button>
                                </div>
                              </div>
                              {expandedAppId === group.appId ? (
                                <div className="nl-app-group-body">
                                  <div className="nl-app-group-hints">
                                    {group.activeVersion ? (
                                      <div className="nl-version-hint">
                                        生效版本：{group.activeVersion.versionId} · 应用时间：
                                        {formatFriendlyDateTime(group.activeVersion.appliedAt)}
                                      </div>
                                    ) : (
                                      <div className="nl-version-hint">当前还没有生效版本。</div>
                                    )}
                                    {group.listedVersion ? (
                                      <div className="nl-version-hint">
                                        上架版本：{group.listedVersion.versionId} · 上架时间：
                                        {formatFriendlyDateTime(group.listedVersion.listedAt)}
                                      </div>
                                    ) : (
                                      <div className="nl-version-hint">当前还没有上架到应用中心。</div>
                                    )}
                                  </div>
                                  <div className="nl-version-scroll">
                                    <div className="nl-version-list">
                                      {group.versions.map((item) => (
                                        <article key={item.versionId} className="nl-version-item">
                                          <div className="nl-version-head">
                                            <h4>{item.title}</h4>
                                            <div className="nl-version-meta">
                                              {item.isActive ? <span className="nl-tag active">当前生效</span> : null}
                                              {item.isListed ? <span className="nl-tag">已上架</span> : null}
                                            </div>
                                          </div>
                                          <div className="nl-version-meta">
                                            <span className="nl-tag">{item.versionId}</span>
                                            <span className="nl-tag">{item.scenarioType || "generic"}</span>
                                            {item.matchedSkillId ? <span className="nl-tag">{item.matchedSkillId}</span> : null}
                                          </div>
                                          <div className="nl-version-hint">发布时间：{formatFriendlyDateTime(item.publishedAt)}</div>
                                          <p className="nl-version-prompt">{item.prompt}</p>
                                          <div className="nl-version-actions">
                                            <button
                                              type="button"
                                              className={item.isActive ? "ghost-btn" : "primary-btn"}
                                              disabled={Boolean(item.isActive) || applyingVersionId === item.versionId}
                                              onClick={() => void handleApplyVersion(item.versionId)}
                                            >
                                              {item.isActive
                                                ? "当前生效中"
                                                : applyingVersionId === item.versionId
                                                  ? "正在应用..."
                                                  : "应用版本"}
                                            </button>
                                            {item.isListed ? (
                                              <button
                                                type="button"
                                                className="ghost-btn"
                                                disabled={listingVersionId === item.versionId}
                                                onClick={() => void handleUpdateListing(item.versionId, false)}
                                              >
                                                {listingVersionId === item.versionId ? "正在下架..." : "下架应用"}
                                              </button>
                                            ) : item.isActive ? (
                                              <button
                                                type="button"
                                                className="primary-btn"
                                                disabled={listingVersionId === item.versionId}
                                                onClick={() => void handleUpdateListing(item.versionId, true)}
                                              >
                                                {listingVersionId === item.versionId ? "正在上架..." : "上架到应用中心"}
                                              </button>
                                            ) : null}
                                            <button
                                              type="button"
                                              className="ghost-btn"
                                              disabled={loadingEditVersionId === item.versionId}
                                              onClick={() => void handleLoadVersionForEdit(item.versionId)}
                                            >
                                              {loadingEditVersionId === item.versionId ? "正在载入..." : "修改应用"}
                                            </button>
                                            <button
                                              type="button"
                                              className="ghost-btn"
                                              disabled={Boolean(item.isActive) || deletingVersionId === item.versionId}
                                              onClick={() => void handleDeleteVersion(item.versionId)}
                                            >
                                              {item.isActive
                                                ? "当前生效不可删"
                                                : deletingVersionId === item.versionId
                                                  ? "正在删除..."
                                                  : "删除版本"}
                                            </button>
                                          </div>
                                          {item.listedAt ? (
                                            <div className="nl-version-hint">上架时间：{formatFriendlyDateTime(item.listedAt)}</div>
                                          ) : null}
                                        </article>
                                      ))}
                                    </div>
                                  </div>
                                </div>
                              ) : null}
                            </article>
                          ))}
                        </div>
                    </>
                  ) : null}
                </div>
              </section>
            </div>

            <section className="nl-card nl-preview-card">
              <div className="nl-card-header">
                <h2>结构化预览</h2>
                <p>这里展示 MVP1 生成的意图、模板匹配和配置草案。确认无误后再发布。</p>
              </div>
              <div className="nl-card-body">
                {!preview ? (
                  <div className="nl-empty-state">生成预览后，这里会展示结构化意图、模板匹配和配置草案。</div>
                ) : (
                  <div className="nl-preview-section">
                    <div className="nl-section-title">
                      <h3>{preview.title}</h3>
                      <button
                        type="button"
                        className="primary-btn"
                        onClick={() => void handlePublish()}
                        disabled={!canPublish}
                      >
                        {publishing ? "正在发布..." : editingVersionId ? "发布新版本" : "发布版本"}
                      </button>
                    </div>

                    <div className="nl-kv-grid">
                      <div className="nl-kv-item">
                        <span>场景类型</span>
                        <strong>{preview.intent.scenarioType || "generic"}</strong>
                      </div>
                      <div className="nl-kv-item">
                        <span>目标对象</span>
                        <strong>{preview.intent.targetType || "未识别"}</strong>
                      </div>
                      <div className="nl-kv-item">
                        <span>触发方式</span>
                        <strong>{preview.intent.triggerLabel || "手动触发"}</strong>
                      </div>
                      <div className="nl-kv-item">
                        <span>匹配模板</span>
                        <strong>{preview.matchedTemplate.templateName || "通用模板"}</strong>
                      </div>
                    </div>

                    <div>
                      <div className="nl-section-title">
                        <strong>动作与限制</strong>
                      </div>
                      <div className="nl-tag-list">
                        {preview.intent.actions.map((item) => (
                          <span key={item} className="nl-tag">
                            {item}
                          </span>
                        ))}
                        {preview.intent.restrictions.map((item) => (
                          <span key={item} className="nl-tag">
                            {item}
                          </span>
                        ))}
                      </div>
                    </div>

                    <div>
                      <div className="nl-section-title">
                        <strong>警告与待补信息</strong>
                      </div>
                      <div className="nl-warning-list">
                        {preview.warnings.length === 0 && preview.missingInputs.length === 0 ? (
                          <div className="nl-warning-item warning-empty">当前没有额外风险提示。</div>
                        ) : null}
                        {preview.warnings.map((item) => (
                          <div key={item} className="nl-warning-item">
                            {item}
                          </div>
                        ))}
                        {preview.missingInputs.map((item) => (
                          <div key={item} className="nl-warning-item">
                            {item}
                          </div>
                        ))}
                      </div>
                    </div>

                    <div>
                      <div className="nl-section-title">
                        <strong>配置草案</strong>
                      </div>
                      <div className="nl-json-grid">
                        {previewBundleEntries.map(([key, value]) => (
                          <div key={key} className="nl-json-block">
                            <h4>{key}</h4>
                            <pre>{formatJsonBlock(value)}</pre>
                          </div>
                        ))}
                      </div>
                    </div>

                    <div className="nl-json-block">
                      <h4>方案说明</h4>
                      <pre className="nl-summary-markdown">{preview.summaryMarkdown}</pre>
                    </div>
                  </div>
                )}
              </div>
            </section>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function NaturalLanguageCustomizationPage() {
  return <NaturalLanguageCustomizationWorkspace />;
}
