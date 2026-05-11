import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import PortalTraditionalViewButton from "../components/PortalTraditionalViewButton";
import {
  listNlCustomizationVersions,
  previewNlCustomization,
  publishNlCustomization,
} from "../api/naturalLanguageCustomization";
import type {
  NlCustomizationPreviewResponse,
  NlCustomizationVersionRecord,
} from "../types/naturalLanguageCustomization";
import "./natural-language-customization.css";

const SAMPLE_PROMPTS = [
  "给我一个 Oracle 巡检助手，每天 8 点执行，异常自动建单，但不能自动变更。",
  "首页加一个待处理工单卡片，领导只能看汇总，运维能看明细。",
  "收到 P1 告警时，先查 CMDB 负责人，再自动建 ITSM 工单。",
];

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
  const [prompt, setPrompt] = useState(SAMPLE_PROMPTS[0]);
  const [preview, setPreview] = useState<NlCustomizationPreviewResponse | null>(null);
  const [versions, setVersions] = useState<NlCustomizationVersionRecord[]>([]);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [versionsLoading, setVersionsLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const canPreview = prompt.trim().length > 0 && !loadingPreview;
  const canPublish = Boolean(preview) && !publishing;

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
  }, []);

  const previewBundleEntries = useMemo(() => {
    if (!preview?.bundle || typeof preview.bundle !== "object") {
      return [];
    }
    return Object.entries(preview.bundle);
  }, [preview]);

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
      });
      setPreview(response);
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
      await loadVersions();
    } catch (requestError) {
      setError(extractErrorMessage(requestError) || "发布失败");
    } finally {
      setPublishing(false);
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
                    <label>
                      <span>方案名称（可选）</span>
                      <input
                        value={title}
                        onChange={(event) => setTitle(event.target.value)}
                        placeholder="例如：Oracle 巡检助手"
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
                    <div>
                      <div className="nl-section-title">
                        <strong>示例需求</strong>
                      </div>
                      <div className="nl-sample-list">
                        {SAMPLE_PROMPTS.map((sample) => (
                          <button
                            key={sample}
                            type="button"
                            className="nl-sample-chip"
                            onClick={() => setPrompt(sample)}
                          >
                            {sample}
                          </button>
                        ))}
                      </div>
                    </div>
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
                  </div>
                </div>
              </section>

              <section className="nl-card">
                <div className="nl-card-header">
                  <h2>已发布版本</h2>
                  <p>发布动作会把草案落成工作目录中的版本化 JSON 资产，便于后续审批、比对和回滚。</p>
                </div>
                <div className="nl-card-body">
                  {versionsLoading ? <div className="nl-empty-state">正在加载版本记录...</div> : null}
                  {!versionsLoading && versions.length === 0 ? (
                    <div className="nl-empty-state">当前还没有发布记录。</div>
                  ) : null}
                  <div className="nl-version-list">
                    {versions.map((item) => (
                      <article key={item.versionId} className="nl-version-item">
                        <h4>{item.title}</h4>
                        <div className="nl-version-meta">
                          <span className="nl-tag">{item.versionId}</span>
                          <span className="nl-tag">{item.scenarioType || "generic"}</span>
                          {item.matchedSkillId ? <span className="nl-tag">{item.matchedSkillId}</span> : null}
                        </div>
                        <p className="nl-version-prompt">{item.prompt}</p>
                      </article>
                    ))}
                  </div>
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
                        {publishing ? "正在发布..." : "发布版本"}
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
