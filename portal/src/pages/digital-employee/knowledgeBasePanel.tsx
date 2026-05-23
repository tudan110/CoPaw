import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  archiveKnowledgeSources,
  createKnowledgeManualEntry,
  getKnowledgeBaseHealth,
  getKnowledgeIngestProgress,
  getKnowledgeSourceDetail,
  getKnowledgeSourceSummary,
  listKnowledgeSources,
  listKnowledgeBuiltinPacks,
  listKnowledgeIngestJobs,
  listKnowledgeUnits,
  queryKnowledgeBase,
  reindexKnowledgeEmbeddings,
  reloadKnowledgeBuiltinPacks,
  synthesizeKnowledgeAnswer,
  toggleKnowledgeEmbedding,
  unarchiveKnowledgeSources,
  updateKnowledgeSource,
  uploadKnowledgeFile,
  type KnowledgeBuiltinPack,
  type KnowledgeBaseHealth,
  type KnowledgeEvidence,
  type KnowledgeIngestJob,
  type KnowledgeQueryResponse,
  type KnowledgeSourceDetail,
  type KnowledgeSourceRecord,
  type KnowledgeSourceSummaryItem,
  type KnowledgeUnit,
} from "../../api/knowledgeBase";
import "./knowledge-base.css";

type AnswerMode = "evidence" | "plugin";

const ANSWER_MODE_OPTIONS: Array<{
  value: AnswerMode;
  label: string;
  title: string;
}> = [
  {
    value: "evidence",
    label: "证据检索",
    title: "只返回知识库命中的摘要和证据，不调用 LLM 合成答案。",
  },
  {
    value: "plugin",
    label: "插件合成答案",
    title: "先检索证据，再调用知识库插件的 RAG 合成接口生成答案。",
  },
];

const KNOWLEDGE_TIME_FORMATTER = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

function normalizeKnowledgeDate(value: string) {
  const trimmed = value.trim();
  if (!trimmed) {
    return "";
  }
  if (/[zZ]$|[+-]\d{2}:?\d{2}$/.test(trimmed)) {
    return trimmed;
  }
  return `${trimmed.replace(" ", "T")}Z`;
}

function formatDate(value?: string | null) {
  if (!value) {
    return "-";
  }
  const parsed = new Date(normalizeKnowledgeDate(String(value)));
  if (Number.isNaN(parsed.getTime())) {
    return String(value).slice(0, 16).replace("T", " ");
  }
  return KNOWLEDGE_TIME_FORMATTER.format(parsed).replace(/\//g, "-");
}

function scopeLabel(scope?: string, fallback?: string) {
  if (fallback) {
    return fallback;
  }
  if (scope === "system_builtin") {
    return "平台内置知识";
  }
  if (scope === "runtime_curated") {
    return "运行时沉淀";
  }
  return "企业内部经验";
}

function evidenceIds(result: KnowledgeQueryResponse | null) {
  return (result?.relevant_evidence || [])
    .map((item) => item.evidence_id)
    .filter(Boolean);
}

function compactText(value?: string | null, maxLength = 120) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (text.length <= maxLength) {
    return text || "-";
  }
  return `${text.slice(0, maxLength - 1)}…`;
}

export function KnowledgeBasePanel() {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [health, setHealth] = useState<KnowledgeBaseHealth | null>(null);
  const [sources, setSources] = useState<KnowledgeSourceRecord[]>([]);
  const [summary, setSummary] = useState<KnowledgeSourceSummaryItem[]>([]);
  const [builtinPacks, setBuiltinPacks] = useState<KnowledgeBuiltinPack[]>([]);
  const [jobs, setJobs] = useState<KnowledgeIngestJob[]>([]);
  const [units, setUnits] = useState<Array<KnowledgeUnit & { filename?: string }>>([]);
  const [includeArchived, setIncludeArchived] = useState(false);
  const [sourceKeyword, setSourceKeyword] = useState("");
  const [sourceScope, setSourceScope] = useState("");
  const [sourceType, setSourceType] = useState("");
  const [query, setQuery] = useState("");
  const [queryResult, setQueryResult] = useState<KnowledgeQueryResponse | null>(null);
  const [ragAnswer, setRagAnswer] = useState("");
  const [answerMode, setAnswerMode] = useState<AnswerMode>("evidence");
  const [manualTitle, setManualTitle] = useState("");
  const [manualContent, setManualContent] = useState("");
  const [manualTags, setManualTags] = useState("");
  const [job, setJob] = useState<KnowledgeIngestJob | null>(null);
  const [selectedSource, setSelectedSource] = useState<KnowledgeSourceDetail | null>(null);
  const [editorTitle, setEditorTitle] = useState("");
  const [editorTags, setEditorTags] = useState("");
  const [editorNote, setEditorNote] = useState("");
  const [editorScope, setEditorScope] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setError("");
    const sourceFilters = {
      includeArchived,
      filename: sourceKeyword.trim() || undefined,
      sourceScope: sourceScope || undefined,
      sourceType: sourceType || undefined,
    };
    const requests = [
      getKnowledgeBaseHealth().then((value) => setHealth(value)),
      listKnowledgeSources({ limit: 100, ...sourceFilters }).then((value) => setSources(value.items || [])),
      getKnowledgeSourceSummary().then((value) => setSummary(value.items || [])),
      listKnowledgeBuiltinPacks().then((value) => setBuiltinPacks(value.items || [])),
      listKnowledgeIngestJobs(20).then((value) => setJobs(value.items || [])),
      listKnowledgeUnits({ limit: 50, ...sourceFilters }).then((value) => setUnits(value.items || [])),
    ];
    const results = await Promise.allSettled(requests);
    const failed = results
      .filter((item) => item.status === "rejected")
      .map((item) => (item as PromiseRejectedResult).reason?.message || "加载失败");
    if (failed.length) {
      setError(`部分管理数据加载失败：${Array.from(new Set(failed)).join("；")}`);
    }
  }, [includeArchived, sourceKeyword, sourceScope, sourceType]);

  useEffect(() => {
    void refresh().catch((err) => setError(err?.message || "知识库状态加载失败"));
  }, [refresh]);

  useEffect(() => {
    if (!job?.job_id && !job?.id) {
      return undefined;
    }
    const jobId = String(job.job_id || job.id);
    if (job.status === "completed" || job.status === "failed") {
      return undefined;
    }
    const timerId = window.setInterval(() => {
      void getKnowledgeIngestProgress(jobId)
        .then((nextJob) => {
          setJob(nextJob);
          if (nextJob.status === "completed") {
            setNotice("文件已入库");
            void refresh();
          }
          if (nextJob.status === "failed") {
            setError(nextJob.note || "文件入库失败");
          }
        })
        .catch((err) => setError(err?.message || "入库进度获取失败"));
    }, 1500);
    return () => window.clearInterval(timerId);
  }, [job?.id, job?.job_id, job?.status, refresh]);

  const stats = useMemo(() => {
    const active = sources.filter((item) => !item.archived_at);
    const archived = sources.length - active.length;
    const chunks = sources.reduce((sum, item) => sum + Number(item.unit_count || 0), 0);
    const builtinUnits = builtinPacks.reduce((sum, item) => sum + Number(item.imported_unit_count || 0), 0);
    return { active: active.length, archived, chunks, builtinUnits };
  }, [builtinPacks, sources]);

  async function runQuery() {
    const text = query.trim();
    if (!text) {
      setError("请输入检索问题");
      return;
    }
    setLoading(true);
    setError("");
    setNotice("");
    setRagAnswer("");
    try {
      const result = await queryKnowledgeBase(text);
      setQueryResult(result);
      if (answerMode === "plugin") {
        const ids = evidenceIds(result);
        if (ids.length) {
          const answer = await synthesizeKnowledgeAnswer(text, ids.slice(0, 6));
          setRagAnswer(answer.answer || "");
        }
      }
    } catch (err: any) {
      setError(err?.message || "检索失败");
    } finally {
      setLoading(false);
    }
  }

  async function handleUpload(file?: File | null) {
    if (!file) {
      return;
    }
    setLoading(true);
    setError("");
    setNotice("");
    try {
      const nextJob = await uploadKnowledgeFile(file);
      setJob(nextJob);
      setNotice("文件已提交入库");
    } catch (err: any) {
      setError(err?.message || "文件上传失败");
    } finally {
      setLoading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  }

  async function handleManualEntry() {
    if (!manualTitle.trim() || !manualContent.trim()) {
      setError("标题和内容都需要填写");
      return;
    }
    setLoading(true);
    setError("");
    try {
      await createKnowledgeManualEntry({
        title: manualTitle.trim(),
        content: manualContent.trim(),
        tags: manualTags.split(",").map((item) => item.trim()).filter(Boolean),
      });
      setManualTitle("");
      setManualContent("");
      setManualTags("");
      setNotice("知识已沉淀");
      await refresh();
    } catch (err: any) {
      setError(err?.message || "手动录入失败");
    } finally {
      setLoading(false);
    }
  }

  async function handleArchive(source: KnowledgeSourceRecord) {
    setLoading(true);
    setError("");
    try {
      await archiveKnowledgeSources([source.id], "portal archive");
      setNotice("资料已归档");
      await refresh();
    } catch (err: any) {
      setError(err?.message || "归档失败");
    } finally {
      setLoading(false);
    }
  }

  async function handleUnarchive(source: KnowledgeSourceRecord) {
    setLoading(true);
    setError("");
    try {
      await unarchiveKnowledgeSources([source.id]);
      setNotice("资料已恢复");
      await refresh();
    } catch (err: any) {
      setError(err?.message || "恢复失败");
    } finally {
      setLoading(false);
    }
  }

  async function openSourceDetail(source: KnowledgeSourceRecord) {
    setLoading(true);
    setError("");
    try {
      const detail = await getKnowledgeSourceDetail(source.id, true);
      setSelectedSource(detail);
      setEditorTitle(detail.meta?.display_title || "");
      setEditorTags((detail.meta?.tags || []).join(", "));
      setEditorNote(detail.note || "");
      setEditorScope(detail.source_scope || "tenant_private");
    } catch (err: any) {
      setError(err?.message || "资料详情读取失败");
    } finally {
      setLoading(false);
    }
  }

  async function handleSaveSource() {
    if (!selectedSource) {
      return;
    }
    setLoading(true);
    setError("");
    try {
      await updateKnowledgeSource({
        sourceRecordId: selectedSource.id,
        displayTitle: editorTitle.trim(),
        tags: editorTags.split(",").map((item) => item.trim()).filter(Boolean),
        note: editorNote,
        sourceScope: editorScope,
      });
      setNotice("资料元数据已更新");
      const detail = await getKnowledgeSourceDetail(selectedSource.id, true);
      setSelectedSource(detail);
      await refresh();
    } catch (err: any) {
      setError(err?.message || "资料编辑失败");
    } finally {
      setLoading(false);
    }
  }

  async function handleReloadBuiltinPack(packId?: string) {
    setLoading(true);
    setError("");
    try {
      await reloadKnowledgeBuiltinPacks({ force: true, packId });
      setNotice(packId ? `内置知识包 ${packId} 已重载` : "内置知识包已重载");
      await refresh();
    } catch (err: any) {
      setError(err?.message || "内置知识包重载失败");
    } finally {
      setLoading(false);
    }
  }

  async function handleEmbeddingToggle() {
    setLoading(true);
    setError("");
    try {
      const enabled = !health?.embedding?.enabled;
      await toggleKnowledgeEmbedding(enabled);
      setNotice(enabled ? "向量检索已开启" : "向量检索已关闭");
      await refresh();
    } catch (err: any) {
      setError(err?.message || "向量开关更新失败");
    } finally {
      setLoading(false);
    }
  }

  async function handleReindex() {
    setLoading(true);
    setError("");
    try {
      const result = await reindexKnowledgeEmbeddings(false);
      setNotice(`向量回填完成：${result.embedded || 0}/${result.requested || 0}`);
      await refresh();
    } catch (err: any) {
      setError(err?.message || "向量回填失败");
    } finally {
      setLoading(false);
    }
  }

  const evidence = queryResult?.relevant_evidence || [];

  return (
    <div className="knowledge-base-panel">
      <div className="portal-model-page-header">
        <div className="portal-model-page-title">
          <small>Knowledge Base</small>
          <h2>知识库管理</h2>
          <p>管理资料入库、沉淀、内置包、索引和检索可用性。</p>
        </div>
        <div className="portal-model-page-actions">
          <button type="button" className="portal-model-btn secondary" onClick={() => void refresh()}>
            <i className="fas fa-rotate" />
            刷新
          </button>
        </div>
      </div>

      <div className="kb-status-strip">
        <div>
          <span>资料</span>
          <strong>{stats.active}</strong>
        </div>
        <div>
          <span>切片</span>
          <strong>{stats.chunks}</strong>
        </div>
        <div>
          <span>归档</span>
          <strong>{stats.archived}</strong>
        </div>
        <div>
          <span>内置切片</span>
          <strong>{stats.builtinUnits}</strong>
        </div>
        <div>
          <span>Embedding</span>
          <strong>{health?.embedding?.enabled ? "开启" : "关闭"}</strong>
        </div>
      </div>

      <section className="kb-primary-row">
        <section className="kb-source-section">
          <div className="kb-section-title kb-source-title">
            <h3>资料列表</h3>
            <div className="kb-source-tools">
              <input
                value={sourceKeyword}
                onChange={(event) => setSourceKeyword(event.target.value)}
                placeholder="按文件名过滤"
              />
              <select value={sourceScope} onChange={(event) => setSourceScope(event.target.value)}>
                <option value="">全部层级</option>
                <option value="tenant_private">企业内部经验</option>
                <option value="runtime_curated">运行时沉淀</option>
                <option value="system_builtin">平台内置知识</option>
              </select>
              <select value={sourceType} onChange={(event) => setSourceType(event.target.value)}>
                <option value="">全部类型</option>
                <option value="document">文档</option>
                <option value="pdf">PDF</option>
                <option value="spreadsheet">表格</option>
                <option value="image">图片</option>
              </select>
              <label>
                <input
                  type="checkbox"
                  checked={includeArchived}
                  onChange={(event) => setIncludeArchived(event.target.checked)}
                />
                含归档
              </label>
              <button
                type="button"
                className="portal-model-btn compact"
                disabled={loading}
                onClick={() => fileInputRef.current?.click()}
              >
                <i className="fas fa-upload" />
                上传文件
              </button>
              <input
                ref={fileInputRef}
                className="kb-file-input"
                type="file"
                onChange={(event) => void handleUpload(event.target.files?.[0])}
              />
            </div>
          </div>

          {notice || error || job ? (
            <div className="kb-source-feedback">
              {notice ? <div className="kb-notice">{notice}</div> : null}
              {error ? <div className="kb-error">{error}</div> : null}
              {job ? (
                <div className="kb-job">
                  <strong>{job.filename}</strong>
                  <span>{job.status || "-"} · {job.progress_pct ?? 0}% · {job.note || job.current_stage}</span>
                </div>
              ) : null}
            </div>
          ) : null}

          <div className="kb-source-table">
            <table>
              <thead>
                <tr>
                  <th>资料</th>
                  <th>类型</th>
                  <th>层级</th>
                  <th>切片</th>
                  <th>时间</th>
                  <th>状态</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {sources.map((source) => (
                  <tr key={source.id}>
                    <td>
                      <strong>{source.meta?.display_title || source.filename}</strong>
                      <small>{source.note || source.meta?.tags?.join(", ") || "-"}</small>
                    </td>
                    <td>{source.source_type || "-"}</td>
                    <td>{scopeLabel(source.source_scope, source.meta?.scope_label)}</td>
                    <td>{source.unit_count || 0}</td>
                    <td>{formatDate(source.uploaded_at)}</td>
                    <td>{source.archived_at ? "已归档" : "有效"}</td>
                    <td>
                      <button type="button" onClick={() => void openSourceDetail(source)}>详情</button>
                      {source.archived_at ? (
                        <button type="button" onClick={() => void handleUnarchive(source)}>恢复</button>
                      ) : (
                        <button type="button" onClick={() => void handleArchive(source)}>归档</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!sources.length ? <div className="kb-empty-state">暂无资料</div> : null}
          </div>
        </section>

        <aside className="kb-ingest-card">
          <div className="kb-section-title">
            <h3>资料入库</h3>
          </div>
          <div className="kb-manual-form">
            <input value={manualTitle} onChange={(event) => setManualTitle(event.target.value)} placeholder="标题" />
            <input value={manualTags} onChange={(event) => setManualTags(event.target.value)} placeholder="标签，逗号分隔" />
            <textarea value={manualContent} onChange={(event) => setManualContent(event.target.value)} placeholder="知识内容" />
            <button type="button" className="portal-model-btn" disabled={loading} onClick={() => void handleManualEntry()}>
              <i className="fas fa-plus" />
              手动沉淀
            </button>
          </div>

          <div className="kb-maintenance">
            <button type="button" className="portal-model-btn secondary" disabled={loading} onClick={() => void handleEmbeddingToggle()}>
              {health?.embedding?.enabled ? "关闭向量检索" : "开启向量检索"}
            </button>
            <button type="button" className="portal-model-btn secondary" disabled={loading} onClick={() => void handleReindex()}>
              回填向量
            </button>
            <small>{health?.storage?.dataDir}</small>
          </div>
        </aside>
      </section>

      <section className="kb-admin-grid">
        <div className="kb-admin-card">
          <div className="kb-section-title">
            <h3>来源分布</h3>
          </div>
          <div className="kb-summary-grid">
            {summary.length ? summary.map((item, index) => (
              <div key={`${item.source_scope || "scope"}-${item.source_type || "type"}-${index}`} className="kb-summary-item">
                <strong>{scopeLabel(item.source_scope)}</strong>
                <span>{item.source_type || "-"} · {item.builtin_pack_id || "企业知识"}</span>
                <small>{item.source_count || 0} 份资料 / {item.unit_count || 0} 个切片</small>
              </div>
            )) : <div className="kb-empty-line">暂无来源统计</div>}
          </div>
        </div>

        <div className="kb-admin-card">
          <div className="kb-section-title">
            <h3>内置知识包</h3>
            <button type="button" className="portal-model-btn secondary" disabled={loading} onClick={() => void handleReloadBuiltinPack()}>
              全量重载
            </button>
          </div>
          <div className="kb-pack-list">
            {builtinPacks.length ? builtinPacks.map((pack) => (
              <article key={pack.pack_id} className="kb-pack-item">
                <div>
                  <strong>{pack.title || pack.pack_id}</strong>
                  <span>{pack.pack_id} · v{pack.version || "-"} · {pack.enabled ? "启用" : "停用"}</span>
                  <small>{pack.description || pack.scope_label || "平台内置知识"}</small>
                </div>
                <div>
                  <span>{pack.imported_source_count || 0} 份</span>
                  <span>{pack.imported_unit_count || 0} 切片</span>
                  <button type="button" disabled={loading} onClick={() => void handleReloadBuiltinPack(pack.pack_id)}>
                    重载
                  </button>
                </div>
              </article>
            )) : <div className="kb-empty-line">没有发现内置知识包</div>}
          </div>
        </div>

        <div className="kb-admin-card">
          <div className="kb-section-title">
            <h3>最近入库任务</h3>
          </div>
          <div className="kb-job-table">
            {jobs.length ? (
              <table>
                <thead>
                  <tr>
                    <th>文件</th>
                    <th>状态</th>
                    <th>进度</th>
                    <th>创建时间</th>
                    <th>阶段</th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.slice(0, 12).map((item) => (
                    <tr key={item.id || item.job_id}>
                      <td>
                        <strong>{compactText(item.filename || item.id || item.job_id, 48)}</strong>
                      </td>
                      <td>{item.status || "-"}</td>
                      <td>{item.progress_pct ?? 0}%</td>
                      <td>{formatDate(item.created_at)}</td>
                      <td>{compactText(item.current_stage || item.note || "-", 64)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : <div className="kb-empty-line">暂无入库任务</div>}
          </div>
        </div>
      </section>

      <section className="kb-admin-card kb-unit-section">
        <div className="kb-section-title">
          <h3>最近知识切片</h3>
        </div>
        <div className="kb-unit-table">
          {units.length ? (
            <table>
              <thead>
                <tr>
                  <th>标题</th>
                  <th>来源</th>
                  <th>层级</th>
                  <th>位置</th>
                  <th>内容预览</th>
                  <th>时间</th>
                </tr>
              </thead>
              <tbody>
                {units.slice(0, 16).map((unit) => (
                  <tr key={unit.id}>
                    <td>
                      <strong>{compactText(unit.title || unit.id, 64)}</strong>
                    </td>
                    <td>{compactText(unit.filename || "-", 42)}</td>
                    <td>{scopeLabel(unit.source_scope)}</td>
                    <td>{compactText(unit.locator || "-", 42)}</td>
                    <td>{compactText(unit.content, 150)}</td>
                    <td>{formatDate(unit.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <div className="kb-empty-line">暂无知识切片</div>}
        </div>
      </section>

      <section className="kb-workbench">
        <div className="kb-query-area">
          <div className="kb-section-title">
            <h3>检索验证</h3>
            <div className="kb-segmented">
              {ANSWER_MODE_OPTIONS.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  className={answerMode === item.value ? "active" : ""}
                  title={item.title}
                  onClick={() => setAnswerMode(item.value)}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
          <textarea
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="输入要从知识库检索的问题"
          />
          <button type="button" className="portal-model-btn success" disabled={loading} onClick={() => void runQuery()}>
            <i className="fas fa-magnifying-glass" />
            检索
          </button>
          {queryResult ? (
            <div className="kb-answer">
              <strong>{ragAnswer ? "合成答案" : "检索摘要"}</strong>
              <p>{ragAnswer || queryResult.summary || queryResult.evidence_boundary_statement}</p>
            </div>
          ) : null}
          {evidence.length ? (
            <div className="kb-evidence-table">
              <table>
                <thead>
                  <tr>
                    <th>来源</th>
                    <th>位置</th>
                    <th>置信度</th>
                    <th>命中片段</th>
                  </tr>
                </thead>
                <tbody>
                  {evidence.map((item: KnowledgeEvidence) => (
                    <tr key={item.evidence_id}>
                      <td>
                        <strong>{compactText(item.citation?.source_label || item.chunk_summary || item.evidence_id, 54)}</strong>
                        <small>{item.citation?.source_scope_label || item.source_type || "-"}</small>
                      </td>
                      <td>{compactText(item.citation?.locator || "-", 54)}</td>
                      <td>{typeof item.confidence_score === "number" ? `${Math.round(item.confidence_score * 100)}%` : "-"}</td>
                      <td>{compactText(item.chunk_text || item.chunk_summary, 180)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      </section>

      {selectedSource ? (
        <section className="kb-source-detail">
          <div className="kb-section-title">
            <h3>资料详情</h3>
            <button type="button" className="portal-model-btn secondary" onClick={() => setSelectedSource(null)}>
              关闭
            </button>
          </div>
          <div className="kb-detail-grid">
            <div className="kb-detail-editor">
              <strong>{selectedSource.filename}</strong>
              <small>{selectedSource.builtin_pack_id ? `内置包：${selectedSource.builtin_pack_id}` : "用户资料"} · {selectedSource.units?.length || 0} 个切片</small>
              <label>
                显示标题
                <input value={editorTitle} onChange={(event) => setEditorTitle(event.target.value)} placeholder="留空则使用文件名" />
              </label>
              <label>
                标签
                <input value={editorTags} onChange={(event) => setEditorTags(event.target.value)} placeholder="逗号分隔" />
              </label>
              <label>
                备注
                <textarea value={editorNote} onChange={(event) => setEditorNote(event.target.value)} />
              </label>
              <label>
                来源层级
                <select
                  value={editorScope}
                  disabled={Boolean(selectedSource.builtin_pack_id)}
                  onChange={(event) => setEditorScope(event.target.value)}
                >
                  <option value="tenant_private">企业内部经验</option>
                  <option value="runtime_curated">运行时沉淀</option>
                  <option value="system_builtin">平台内置知识</option>
                </select>
              </label>
              <button type="button" className="portal-model-btn" disabled={loading} onClick={() => void handleSaveSource()}>
                保存资料设置
              </button>
            </div>
            <div className="kb-unit-list">
              {(selectedSource.units || []).slice(0, 20).map((unit) => (
                <article key={unit.id} className="kb-unit-item">
                  <strong>{unit.title || unit.id}</strong>
                  <small>{unit.locator || unit.source_type || "-"}</small>
                  <p>{unit.content}</p>
                </article>
              ))}
            </div>
          </div>
        </section>
      ) : null}
    </div>
  );
}
