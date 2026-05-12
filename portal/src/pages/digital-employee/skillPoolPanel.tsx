import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  type HubInstallTask,
  SkillConflictError,
  SkillScanError,
  type SkillScanErrorPayload,
  type SkillImportResult,
  skillsApi,
  type WorkspaceSkillInfo,
} from "../../api/skills";
import { portalGatewayAgentId } from "../../config/portalBranding";
import "../skill-pool.css";

const ERKAI_TAG = "二开";

type NoticeState =
  | { type: "success" | "error"; message: string }
  | null;

type FilterMode = "all" | "erkai" | "stock" | "enabled" | "disabled";
type ModalMode = "create" | "edit";

type SkillFormState = {
  name: string;
  content: string;
  tagsText: string;
  configText: string;
};

const EMPTY_SKILL_CONTENT = `---
name: new_skill
description: "请填写技能描述"
metadata:
  {
    "copaw": {
      "emoji": "⚡"
    }
  }
---

# 技能说明

请在这里编写技能能力、适用场景和执行约束。
`;

const EMPTY_FORM: SkillFormState = {
  name: "new_skill",
  content: EMPTY_SKILL_CONTENT,
  tagsText: "",
  configText: "",
};

function parseJsonObject(text: string, label: string) {
  const raw = text.trim();
  if (!raw) {
    return {};
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error(`${label} 必须是合法 JSON`);
  }

  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${label} 必须是 JSON 对象`);
  }

  return parsed as Record<string, unknown>;
}

function parseTags(text: string) {
  return Array.from(
    new Set(
      text
        .split(/[\n,，]/)
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  ).slice(0, 8);
}

function stripSkillFrontmatter(content: string) {
  const raw = String(content || "");
  if (!raw.startsWith("---")) {
    return raw;
  }

  const endIndex = raw.indexOf("\n---", 3);
  if (endIndex === -1) {
    return raw;
  }

  return raw.slice(endIndex + 4).trim();
}

function formatJson(value: Record<string, unknown> | undefined) {
  return value && Object.keys(value).length ? JSON.stringify(value, null, 2) : "";
}

function formatLastUpdated(value: string) {
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) {
    return value || "未记录";
  }

  return new Date(timestamp).toLocaleString("zh-CN", {
    hour12: false,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function getSkillEmoji(skill: WorkspaceSkillInfo) {
  if (skill.emoji?.trim()) {
    return skill.emoji.trim();
  }

  if (skill.source === "builtin") {
    return "🧩";
  }

  return "⚡";
}

function describeError(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

export function SkillPoolPanel() {
  const agentId = portalGatewayAgentId;

  const [skills, setSkills] = useState<WorkspaceSkillInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<NoticeState>(null);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<FilterMode>("all");
  const [selectedSkillName, setSelectedSkillName] = useState<string | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [modalMode, setModalMode] = useState<ModalMode>("create");
  const [editingSkill, setEditingSkill] = useState<WorkspaceSkillInfo | null>(null);
  const [form, setForm] = useState<SkillFormState>(EMPTY_FORM);

  // Import + per-skill busy state
  const [importMenuOpen, setImportMenuOpen] = useState(false);
  const importMenuRef = useRef<HTMLDivElement | null>(null);
  const [scanError, setScanError] = useState<SkillScanErrorPayload | null>(null);
  const [busySkill, setBusySkill] = useState<string | null>(null);

  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadTargetName, setUploadTargetName] = useState("");
  const [uploadError, setUploadError] = useState("");

  const [hubModalOpen, setHubModalOpen] = useState(false);
  const [hubUrl, setHubUrl] = useState("");
  const [hubVersion, setHubVersion] = useState("");
  const [hubTargetName, setHubTargetName] = useState("");
  const [hubError, setHubError] = useState("");
  const [hubInstall, setHubInstall] = useState<
    { taskId: string; status: HubInstallTask["status"] } | null
  >(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const list = await skillsApi.listAgentSkills(agentId);
      setSkills(list);
    } catch (error) {
      setNotice({
        type: "error",
        message: describeError(error, "技能列表加载失败"),
      });
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  useEffect(() => {
    if (!importMenuOpen) {
      return;
    }
    const handlePointerDown = (event: MouseEvent) => {
      if (!importMenuRef.current?.contains(event.target as Node)) {
        setImportMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handlePointerDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
    };
  }, [importMenuOpen]);

  const isErkai = (s: WorkspaceSkillInfo) => (s.tags || []).includes(ERKAI_TAG);

  const erkaiCount = useMemo(() => skills.filter(isErkai).length, [skills]);
  const enabledCount = useMemo(() => skills.filter((s) => s.enabled).length, [skills]);

  const filteredSkills = useMemo(() => {
    const keyword = search.trim().toLowerCase();

    return skills.filter((skill) => {
      const matchedFilter =
        filter === "all"
        || (filter === "erkai" && isErkai(skill))
        || (filter === "stock" && !isErkai(skill))
        || (filter === "enabled" && skill.enabled)
        || (filter === "disabled" && !skill.enabled);

      if (!matchedFilter) {
        return false;
      }

      if (!keyword) {
        return true;
      }

      return [
        skill.name,
        skill.description,
        skill.source,
        ...(skill.tags || []),
      ]
        .filter(Boolean)
        .some((value) => value.toLowerCase().includes(keyword));
    });
  }, [filter, search, skills]);

  useEffect(() => {
    if (!filteredSkills.length) {
      setSelectedSkillName(null);
      return;
    }

    if (!selectedSkillName || !filteredSkills.some((skill) => skill.name === selectedSkillName)) {
      setSelectedSkillName(filteredSkills[0].name);
    }
  }, [filteredSkills, selectedSkillName]);

  const selectedSkill = useMemo(
    () => skills.find((skill) => skill.name === selectedSkillName) || null,
    [selectedSkillName, skills],
  );

  const openCreateModal = () => {
    setModalMode("create");
    setEditingSkill(null);
    setForm(EMPTY_FORM);
    setIsModalOpen(true);
  };

  const openEditModal = (skill: WorkspaceSkillInfo) => {
    setModalMode("edit");
    setEditingSkill(skill);
    setForm({
      name: skill.name,
      content: skill.content || EMPTY_SKILL_CONTENT,
      tagsText: (skill.tags || []).join(", "),
      configText: formatJson(skill.config),
    });
    setIsModalOpen(true);
  };

  const closeModal = () => {
    if (saving) {
      return;
    }
    setIsModalOpen(false);
    setEditingSkill(null);
    setForm(EMPTY_FORM);
  };

  const resetModalState = () => {
    setIsModalOpen(false);
    setEditingSkill(null);
    setForm(EMPTY_FORM);
  };

  const handleRefresh = async () => {
    setNotice(null);
    try {
      setLoading(true);
      await skillsApi.refreshAgentSkills(agentId);
      await loadData();
      setNotice({ type: "success", message: "技能列表已刷新" });
    } catch (error) {
      setNotice({
        type: "error",
        message: describeError(error, "技能列表刷新失败"),
      });
    } finally {
      setLoading(false);
    }
  };

  // After an import, tag every freshly-appeared skill with ERKAI_TAG, then reload.
  const importThenTagErkai = async (doImport: () => Promise<unknown>) => {
    const prev = new Set(skills.map((s) => s.name));
    await doImport();
    let after = await skillsApi.listAgentSkills(agentId);
    setSkills(after);
    const fresh = after.filter((s) => !prev.has(s.name)).map((s) => s.name);
    let tagWarned = false;
    for (const name of fresh) {
      try {
        await skillsApi.updateAgentSkillTags(agentId, name, [ERKAI_TAG]);
      } catch {
        tagWarned = true;
      }
    }
    if (fresh.length) {
      after = await skillsApi.listAgentSkills(agentId);
      setSkills(after);
    }
    if (tagWarned) {
      setNotice({
        type: "error",
        message: "技能已导入，但部分「二开」标签写入失败，可在详情页手动补。",
      });
    }
    return fresh;
  };

  const handleSubmit = async () => {
    const nextName = form.name.trim();
    if (!nextName) {
      setNotice({ type: "error", message: "请填写技能名称" });
      return;
    }

    if (!form.content.trim()) {
      setNotice({ type: "error", message: "请填写 SKILL.md 内容" });
      return;
    }

    try {
      setSaving(true);
      const config = parseJsonObject(form.configText, "技能配置");
      const formTags = parseTags(form.tagsText);
      let finalName = nextName;

      if (modalMode === "edit" && editingSkill) {
        const result = await skillsApi.saveAgentSkill(agentId, {
          name: nextName,
          sourceName: editingSkill.name,
          content: form.content.trim(),
          config,
        });
        finalName = result.name || nextName;
        try {
          await skillsApi.updateAgentSkillTags(agentId, finalName, formTags);
        } catch (error) {
          resetModalState();
          await loadData();
          setSelectedSkillName(finalName);
          setNotice({
            type: "error",
            message: `技能已保存，但标签同步失败：${describeError(error, "未知错误")}`,
          });
          return;
        }
      } else {
        const result = await skillsApi.createAgentSkill(agentId, {
          name: nextName,
          content: form.content.trim(),
          config,
        });
        finalName = result.name || nextName;
        const tags = Array.from(new Set([...formTags, ERKAI_TAG]));
        try {
          await skillsApi.updateAgentSkillTags(agentId, finalName, tags);
        } catch (error) {
          resetModalState();
          await loadData();
          setSelectedSkillName(finalName);
          setNotice({
            type: "error",
            message: `技能已保存，但标签同步失败：${describeError(error, "未知错误")}`,
          });
          return;
        }
      }

      resetModalState();
      await loadData();
      setSelectedSkillName(finalName);
      setNotice({
        type: "success",
        message:
          modalMode === "create"
            ? `已新增技能：${finalName}（已标记为二开）`
            : `已更新技能：${finalName}`,
      });
    } catch (error) {
      if (error instanceof SkillScanError) {
        setScanError(error.payload);
      } else if (error instanceof SkillConflictError) {
        setNotice({
          type: "error",
          message: `技能名冲突：${error.conflicts.join(", ") || "已存在同名技能"}，请改名后重试`,
        });
      } else {
        setNotice({
          type: "error",
          message: describeError(error, "保存技能失败"),
        });
      }
    } finally {
      setSaving(false);
    }
  };

  // ---- Import: upload .zip ----
  const openUploadModal = () => {
    setUploadFile(null);
    setUploadTargetName("");
    setUploadError("");
    setUploadModalOpen(true);
  };

  const closeUploadModal = () => {
    if (saving) {
      return;
    }
    setUploadModalOpen(false);
  };

  const handleUploadSubmit = async () => {
    if (!uploadFile) {
      setUploadError("请选择一个技能压缩包 (.zip)");
      return;
    }
    setUploadError("");
    try {
      setSaving(true);
      let importResult: SkillImportResult | undefined;
      await importThenTagErkai(async () => {
        importResult = await skillsApi.uploadSkillZipToAgent(agentId, uploadFile, {
          targetName: uploadTargetName,
        });
      });
      setUploadModalOpen(false);
      setNotice({
        type: "success",
        message: `已导入 ${importResult?.count ?? 0} 个技能到「智观 AI」（已标记为二开）`,
      });
    } catch (error) {
      if (error instanceof SkillScanError) {
        setUploadModalOpen(false);
        setScanError(error.payload);
      } else if (error instanceof SkillConflictError) {
        setUploadError(
          `技能名冲突：${error.conflicts.join(", ") || "已存在同名技能"}。可填写「重命名为」后重试。`,
        );
      } else {
        setUploadError(describeError(error, "上传技能失败"));
      }
    } finally {
      setSaving(false);
    }
  };

  // ---- Import: from hub URL (async polling) ----
  const openHubModal = () => {
    setHubUrl("");
    setHubVersion("");
    setHubTargetName("");
    setHubError("");
    setHubInstall(null);
    setHubModalOpen(true);
  };

  const closeHubModal = () => {
    if (saving) {
      return;
    }
    setHubModalOpen(false);
  };

  const pollHubInstall = async (taskId: string): Promise<string | null> => {
    for (let i = 0; i < 60; i++) {
      await new Promise((r) => setTimeout(r, 1500));
      let task: HubInstallTask;
      try {
        task = await skillsApi.getHubInstallStatus(taskId);
      } catch (e) {
        setHubError(describeError(e, "查询导入进度失败"));
        return null;
      }
      setHubInstall({ taskId, status: task.status });
      if (task.status === "completed") {
        const r = task.result as { name?: string } | null;
        return (r && typeof r.name === "string" && r.name) || "";
      }
      if (task.status === "failed") {
        const r = task.result as SkillScanErrorPayload | { type?: string } | null;
        if (r && typeof r === "object" && (r as { type?: string }).type === "security_scan_failed") {
          setScanError(r as SkillScanErrorPayload);
        } else {
          setHubError(task.error || "导入失败");
        }
        return null;
      }
      if (task.status === "cancelled") {
        setHubError("导入已取消");
        return null;
      }
    }
    setHubError("导入超时，请稍后在面板「刷新」查看");
    return null;
  };

  const handleHubSubmit = async () => {
    if (!hubUrl.trim()) {
      setHubError("请填写技能链接");
      return;
    }
    setHubError("");
    try {
      setSaving(true);
      const prev = new Set(skills.map((s) => s.name));
      const task = await skillsApi.startHubInstallToAgent(agentId, {
        bundleUrl: hubUrl,
        version: hubVersion,
        targetName: hubTargetName,
      });
      setHubInstall({ taskId: task.task_id, status: task.status });
      const installedName = await pollHubInstall(task.task_id);
      if (installedName === null) {
        return;
      }

      await loadData();
      const after = await skillsApi.listAgentSkills(agentId);
      setSkills(after);
      const candidates = after.filter((s) => !prev.has(s.name)).map((s) => s.name);
      const names = installedName ? [installedName] : candidates;
      let tagWarned = false;
      for (const name of names) {
        try {
          await skillsApi.updateAgentSkillTags(agentId, name, [ERKAI_TAG]);
        } catch {
          tagWarned = true;
        }
      }
      setSkills(await skillsApi.listAgentSkills(agentId));

      setHubModalOpen(false);
      const display = installedName || candidates[0] || "技能";
      setSelectedSkillName(installedName || candidates[0] || null);
      if (tagWarned) {
        setNotice({
          type: "error",
          message: `已从链接导入技能：${display}，但部分「二开」标签写入失败，可在详情页手动补。`,
        });
      } else {
        setNotice({
          type: "success",
          message: `已从链接导入技能：${display}（已标记为二开）`,
        });
      }
    } catch (error) {
      if (error instanceof SkillScanError) {
        setHubModalOpen(false);
        setScanError(error.payload);
      } else {
        setHubError(describeError(error, "从链接导入失败"));
      }
    } finally {
      setSaving(false);
      setHubInstall(null);
    }
  };

  // ---- Enable / disable on the gateway agent ----
  const handleEnable = async (skill: WorkspaceSkillInfo) => {
    if (!window.confirm(`在「智观 AI」启用技能「${skill.name}」？`)) {
      return;
    }
    setBusySkill(skill.name);
    try {
      await skillsApi.enableWorkspaceSkill(skill.name, agentId);
      await loadData();
      setNotice({
        type: "success",
        message: `技能「${skill.name}」已在「智观 AI」启用（约 1–2 秒生效）`,
      });
    } catch (error) {
      if (error instanceof SkillScanError) {
        setScanError(error.payload);
      } else {
        setNotice({
          type: "error",
          message: describeError(error, "启用技能失败"),
        });
      }
    } finally {
      setBusySkill(null);
    }
  };

  const handleDisable = async (skill: WorkspaceSkillInfo) => {
    if (!window.confirm(`在「智观 AI」停用技能「${skill.name}」？`)) {
      return;
    }
    setBusySkill(skill.name);
    try {
      await skillsApi.disableWorkspaceSkill(skill.name, agentId);
      await loadData();
      setNotice({
        type: "success",
        message: `已在「智观 AI」停用技能「${skill.name}」`,
      });
    } catch (error) {
      setNotice({
        type: "error",
        message: describeError(error, "停用技能失败"),
      });
    } finally {
      setBusySkill(null);
    }
  };

  // ---- Delete ----
  const handleDelete = async (skill: WorkspaceSkillInfo) => {
    if (!window.confirm(`确认删除技能「${skill.name}」吗？删除前会先停用。`)) {
      return;
    }
    setBusySkill(skill.name);
    try {
      await skillsApi.deleteAgentSkill(agentId, skill.name);
      if (selectedSkillName === skill.name) {
        setSelectedSkillName(null);
      }
      await loadData();
      setNotice({ type: "success", message: `已删除技能：${skill.name}` });
    } catch (error) {
      setNotice({
        type: "error",
        message: describeError(error, "删除技能失败（若仍启用请先停用）"),
      });
    } finally {
      setBusySkill(null);
    }
  };

  // ---- Toggle 二开 tag (detail side card) ----
  const handleToggleErkai = async (skill: WorkspaceSkillInfo) => {
    const cur = skill.tags || [];
    const has = cur.includes(ERKAI_TAG);
    const next = has ? cur.filter((t) => t !== ERKAI_TAG) : [...cur, ERKAI_TAG];
    setBusySkill(skill.name);
    try {
      await skillsApi.updateAgentSkillTags(agentId, skill.name, next);
      await loadData();
      setNotice({
        type: "success",
        message: has ? `已取消「${skill.name}」的二开标记` : `已将「${skill.name}」标记为二开`,
      });
    } catch (e) {
      setNotice({
        type: "error",
        message: describeError(e, "更新标签失败"),
      });
    } finally {
      setBusySkill(null);
    }
  };

  return (
    <div className="skill-pool-panel">
      <div className="portal-model-page-header">
        <div className="portal-model-page-title">
          技能 <small>智观 AI 的能力</small>
        </div>
        <div className="portal-model-page-actions">
          <button type="button" className="portal-model-btn" onClick={openCreateModal}>
            <i className="fas fa-plus" />
            新建技能
          </button>
          <div
            ref={importMenuRef}
            className={importMenuOpen ? "skill-pool-import-menu open" : "skill-pool-import-menu"}
          >
            <button
              type="button"
              className="portal-model-btn"
              onClick={() => setImportMenuOpen((value) => !value)}
            >
              <i className="fas fa-file-import" />
              导入技能
              <i className={`fas ${importMenuOpen ? "fa-chevron-up" : "fa-chevron-down"}`} />
            </button>
            {importMenuOpen ? (
              <div className="skill-pool-import-dropdown">
                <button
                  type="button"
                  onClick={() => {
                    setImportMenuOpen(false);
                    openUploadModal();
                  }}
                >
                  <i className="fas fa-file-zipper" />
                  上传压缩包 (.zip)
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setImportMenuOpen(false);
                    openHubModal();
                  }}
                >
                  <i className="fas fa-link" />
                  从链接导入
                </button>
              </div>
            ) : null}
          </div>
          <button type="button" className="portal-model-btn" onClick={() => void handleRefresh()}>
            <i className={`fas ${loading ? "fa-spinner fa-spin" : "fa-rotate-right"}`} />
            刷新
          </button>
        </div>
      </div>

      <div className="skill-pool-content">
        <div className="portal-model-scope-bar skill-pool-scope-bar">
          <span>管理范围：智观 AI（对外入口）的技能</span>
          <span>技能总数：{skills.length}</span>
          <span>其中二开：{erkaiCount}</span>
          <span>已启用：{enabledCount}</span>
        </div>

        <div className="skill-pool-toolbar">
          <div className="skill-pool-search">
            <i className="ri-search-line" />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="搜索技能名称、描述、标签或来源"
            />
          </div>
          <div className="skill-pool-filter-group">
            {[
              ["all", "全部"],
              ["erkai", "二开"],
              ["stock", "出厂"],
              ["enabled", "已启用"],
              ["disabled", "未启用"],
            ].map(([value, label]) => (
              <button
                key={value}
                type="button"
                className={`skill-pool-filter ${filter === value ? "active" : ""}`}
                onClick={() => setFilter(value as FilterMode)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <div className="skill-pool-results">
          {notice ? (
            <div className={`skill-pool-notice ${notice.type}`}>{notice.message}</div>
          ) : null}

        {loading ? (
          <div className="skill-pool-empty">
            <div className="skill-pool-loading">
              <i className="ri-loader-4-line ri-spin" />
              正在加载技能...
            </div>
          </div>
        ) : filteredSkills.length ? (
          <div className="skill-pool-grid">
            {filteredSkills.map((skill) => {
              const isSelected = selectedSkillName === skill.name;
              return (
                <article
                  key={skill.name}
                  className={isSelected ? "skill-pool-card active" : "skill-pool-card"}
                  onClick={() => setSelectedSkillName(skill.name)}
                >
                  <div className="skill-pool-card-head">
                    <div className="skill-pool-card-title">
                      <span className="skill-pool-card-icon">{getSkillEmoji(skill)}</span>
                      <div className="skill-pool-card-copy">
                        <div className="skill-pool-card-title-row">
                          <h4>{skill.name}</h4>
                          <div className="skill-pool-card-badges">
                            {isErkai(skill) ? (
                              <span className="skill-pool-badge erkai">二开</span>
                            ) : (
                              <span className="skill-pool-badge stock">出厂</span>
                            )}
                            {skill.enabled ? (
                              <span className="skill-pool-badge enabled">已启用</span>
                            ) : (
                              <span className="skill-pool-badge">已停用</span>
                            )}
                          </div>
                        </div>
                        <p>{skill.description || "未填写技能描述"}</p>
                      </div>
                    </div>
                  </div>

                  <div className="skill-pool-card-body">
                    <div className="skill-pool-card-kv">
                      <span>版本</span>
                      <strong>{skill.version_text || "未标注"}</strong>
                    </div>
                    <div className="skill-pool-card-kv">
                      <span>状态</span>
                      <strong>{skill.enabled ? "已启用" : "已停用"}</strong>
                    </div>
                    <div className="skill-pool-card-kv">
                      <span>更新时间</span>
                      <strong>{formatLastUpdated(skill.last_updated)}</strong>
                    </div>
                    {skill.tags?.length ? (
                      <div className="skill-pool-tags">
                        {skill.tags.slice(0, 3).map((tag) => (
                          <span key={tag} className="skill-pool-tag">
                            {tag}
                          </span>
                        ))}
                        {skill.tags.length > 3 ? (
                          <span className="skill-pool-tag muted">+{skill.tags.length - 3}</span>
                        ) : null}
                      </div>
                    ) : (
                      <div className="skill-pool-card-hint">可通过标签补充场景分类</div>
                    )}
                  </div>

                  <div className="skill-pool-card-actions">
                   <button
                     type="button"
                     className="portal-model-btn secondary compact"
                     onClick={(event) => {
                       event.stopPropagation();
                        setSelectedSkillName(skill.name);
                      }}
                    >
                      详情
                    </button>
                    <button
                      type="button"
                      className="portal-model-btn secondary compact"
                      onClick={(event) => {
                        event.stopPropagation();
                        openEditModal(skill);
                     }}
                    >
                      编辑
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        ) : (
          <div className="skill-pool-empty">
            <i className="fas fa-bolt" />
            <strong>还没有匹配的技能</strong>
            <span>可以新建自定义技能，或通过「导入技能」上传压缩包 / 从链接导入。</span>
          </div>
        )}

          {selectedSkill ? (
          <section className="skill-pool-detail">
            <div className="skill-pool-detail-header">
              <div>
                <div className="skill-pool-detail-title">
                  <span className="skill-pool-card-icon large">{getSkillEmoji(selectedSkill)}</span>
                  <div>
                    <h3>{selectedSkill.name}</h3>
                    <p>{selectedSkill.description || "未填写技能描述"}</p>
                  </div>
                </div>
                <div className="skill-pool-detail-meta">
                  {isErkai(selectedSkill) ? (
                    <span className="skill-pool-badge erkai">二开</span>
                  ) : (
                    <span className="skill-pool-badge stock">出厂</span>
                  )}
                  <span className="skill-pool-badge info">版本 {selectedSkill.version_text || "未标注"}</span>
                  <span className="skill-pool-badge info">
                    更新于 {formatLastUpdated(selectedSkill.last_updated)}
                  </span>
                  {selectedSkill.enabled ? (
                    <span className="skill-pool-badge enabled">已启用</span>
                  ) : (
                    <span className="skill-pool-badge">已停用</span>
                  )}
                </div>
              </div>

              <div className="skill-pool-detail-actions">
                {selectedSkill.enabled ? (
                  <button
                    type="button"
                    className="portal-model-btn secondary danger"
                    disabled={busySkill === selectedSkill.name}
                    onClick={() => void handleDisable(selectedSkill)}
                  >
                    <i className={`fas ${busySkill === selectedSkill.name ? "fa-spinner fa-spin" : "fa-circle-stop"}`} />
                    在「智观 AI」停用
                  </button>
                ) : (
                  <button
                    type="button"
                    className="portal-model-btn success"
                    disabled={busySkill === selectedSkill.name}
                    onClick={() => void handleEnable(selectedSkill)}
                  >
                    <i className={`fas ${busySkill === selectedSkill.name ? "fa-spinner fa-spin" : "fa-circle-play"}`} />
                    在「智观 AI」启用
                  </button>
                )}
                <button
                  type="button"
                  className="portal-model-btn secondary"
                  onClick={() => openEditModal(selectedSkill)}
                >
                  <i className="fas fa-pen" />
                  编辑技能
                </button>
                <button
                  type="button"
                  className="portal-model-btn secondary danger"
                  disabled={busySkill === selectedSkill.name}
                  onClick={() => void handleDelete(selectedSkill)}
                >
                  <i className={`fas ${busySkill === selectedSkill.name ? "fa-spinner fa-spin" : "fa-trash"}`} />
                  删除
                </button>
              </div>
            </div>

            <div className="skill-pool-detail-grid">
              <div className="skill-pool-preview-card">
                <div className="skill-pool-section-header">
                  <h4>技能说明预览</h4>
                  <span>{selectedSkill.tags?.length ? `${selectedSkill.tags.length} 个标签` : "未设置标签"}</span>
                </div>
                {selectedSkill.tags?.length ? (
                  <div className="skill-pool-tags detail">
                    {selectedSkill.tags.map((tag) => (
                      <span key={tag} className="skill-pool-tag">
                        {tag}
                      </span>
                    ))}
                  </div>
                ) : null}
                <div className="skill-pool-markdown">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {stripSkillFrontmatter(selectedSkill.content)}
                  </ReactMarkdown>
                </div>
              </div>

              <aside className="skill-pool-side-column">
                <div className="skill-pool-side-card">
                  <div className="skill-pool-section-header">
                    <h4>二开标记</h4>
                    <span>{isErkai(selectedSkill) ? "二开" : "出厂"}</span>
                  </div>
                  <div className="skill-pool-tag-toggle">
                    <button
                      type="button"
                      className={
                        isErkai(selectedSkill)
                          ? "portal-model-btn secondary compact"
                          : "portal-model-btn success compact"
                      }
                      disabled={busySkill === selectedSkill.name}
                      onClick={() => void handleToggleErkai(selectedSkill)}
                    >
                      {isErkai(selectedSkill) ? "取消二开" : "标为二开"}
                    </button>
                  </div>
                  <div className="skill-pool-card-hint">
                    二开 = 通过本面板导入 / 新建的定制技能；出厂 = 随系统部署。识别有误可在此手动纠正。
                  </div>
                </div>

                <div className="skill-pool-side-card">
                  <div className="skill-pool-section-header">
                    <h4>技能配置</h4>
                    <span>{Object.keys(selectedSkill.config || {}).length} 项</span>
                  </div>
                  {Object.keys(selectedSkill.config || {}).length ? (
                    <pre>{JSON.stringify(selectedSkill.config, null, 2)}</pre>
                  ) : (
                    <div className="skill-pool-placeholder">当前没有附加配置</div>
                  )}
                </div>

                <div className="skill-pool-side-card">
                  <div className="skill-pool-section-header">
                    <h4>启用状态</h4>
                    <span>智观 AI</span>
                  </div>
                  <div className="skill-pool-assign-row">
                    <span>当前状态：{selectedSkill.enabled ? "已启用" : "已停用"}</span>
                    {selectedSkill.enabled ? (
                      <button
                        type="button"
                        className="portal-model-btn secondary danger compact"
                        disabled={busySkill === selectedSkill.name}
                        onClick={() => void handleDisable(selectedSkill)}
                      >
                        停用
                      </button>
                    ) : (
                      <button
                        type="button"
                        className="portal-model-btn success compact"
                        disabled={busySkill === selectedSkill.name}
                        onClick={() => void handleEnable(selectedSkill)}
                      >
                        启用
                      </button>
                    )}
                  </div>
                  <div className="skill-pool-card-hint">启停后约 1–2 秒生效。</div>
                </div>
              </aside>
            </div>
          </section>
          ) : null}
        </div>
      </div>

      {isModalOpen ? (
        <div className="skill-pool-modal-backdrop" onClick={closeModal}>
          <div className="skill-pool-modal" onClick={(event) => event.stopPropagation()}>
            <div className="skill-pool-modal-header">
              <div>
                <h3>{modalMode === "create" ? "新增技能" : "编辑技能"}</h3>
                <p>
                  作用于「智观 AI」（对外入口）的技能；保存后约 1–2 秒生效。新建的技能会自动标记为二开。
                </p>
              </div>
              <button type="button" className="skill-pool-modal-close" onClick={closeModal}>
                <i className="fas fa-xmark" />
              </button>
            </div>

            <div className="skill-pool-form-grid">
              <label className="skill-pool-form-field">
                <span>技能名称</span>
                <input
                  value={form.name}
                  onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
                  placeholder="例如：log_analyzer"
                />
              </label>
              <label className="skill-pool-form-field">
                <span>标签</span>
                <input
                  value={form.tagsText}
                  onChange={(event) => setForm((current) => ({ ...current, tagsText: event.target.value }))}
                  placeholder="故障诊断, 日志, 自动化"
                />
              </label>
            </div>

            <label className="skill-pool-form-field full">
              <span>技能配置 JSON</span>
              <textarea
                value={form.configText}
                onChange={(event) => setForm((current) => ({ ...current, configText: event.target.value }))}
                placeholder='{"timeout": 30}'
                rows={6}
              />
            </label>

            <label className="skill-pool-form-field full">
              <span>SKILL.md 内容</span>
              <textarea
                value={form.content}
                onChange={(event) => setForm((current) => ({ ...current, content: event.target.value }))}
                placeholder="输入完整的 SKILL.md 内容"
                rows={18}
              />
            </label>

            <div className="skill-pool-form-actions">
              <button type="button" className="portal-model-btn secondary" onClick={closeModal}>
                取消
              </button>
              <button
                type="button"
                className="portal-model-btn success"
                disabled={saving}
                onClick={() => void handleSubmit()}
              >
                <i className={`fas ${saving ? "fa-spinner fa-spin" : "fa-floppy-disk"}`} />
                {modalMode === "create" ? "创建技能" : "保存修改"}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {uploadModalOpen ? (
        <div className="skill-pool-modal-backdrop" onClick={closeUploadModal}>
          <div className="skill-pool-modal compact" onClick={(event) => event.stopPropagation()}>
            <div className="skill-pool-modal-header">
              <div>
                <h3>上传技能压缩包</h3>
                <p>
                  导入到「智观 AI」的技能，会先做网管领域校验与安全扫描，导入后自动标记为二开（最大 100MB）。
                </p>
              </div>
              <button type="button" className="skill-pool-modal-close" onClick={closeUploadModal}>
                <i className="fas fa-xmark" />
              </button>
            </div>

            <label className="skill-pool-form-field full">
              <span>技能压缩包 (.zip)</span>
              <input
                type="file"
                accept=".zip,application/zip,application/x-zip-compressed"
                onChange={(event) => {
                  setUploadFile(event.target.files?.[0] || null);
                  setUploadError("");
                }}
              />
            </label>
            <label className="skill-pool-form-field full">
              <span>重命名为（可选）</span>
              <input
                value={uploadTargetName}
                onChange={(event) => setUploadTargetName(event.target.value)}
                placeholder="包内只有一个技能时可重命名，避免与现有技能冲突"
              />
            </label>
            {uploadError ? <div className="skill-pool-notice error">{uploadError}</div> : null}

            <div className="skill-pool-form-actions">
              <button type="button" className="portal-model-btn secondary" onClick={closeUploadModal}>
                取消
              </button>
              <button
                type="button"
                className="portal-model-btn success"
                disabled={saving}
                onClick={() => void handleUploadSubmit()}
              >
                <i className={`fas ${saving ? "fa-spinner fa-spin" : "fa-upload"}`} />
                {saving ? "导入中..." : "上传并导入"}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {hubModalOpen ? (
        <div className="skill-pool-modal-backdrop" onClick={closeHubModal}>
          <div className="skill-pool-modal compact" onClick={(event) => event.stopPropagation()}>
            <div className="skill-pool-modal-header">
              <div>
                <h3>从链接导入技能</h3>
                <p>
                  支持技能 Hub / 仓库的发布链接；导入到「智观 AI」的技能，会先做领域校验与安全扫描，导入后自动标记为二开。
                </p>
              </div>
              <button type="button" className="skill-pool-modal-close" onClick={closeHubModal}>
                <i className="fas fa-xmark" />
              </button>
            </div>

            <label className="skill-pool-form-field full">
              <span>技能链接</span>
              <input
                value={hubUrl}
                onChange={(event) => {
                  setHubUrl(event.target.value);
                  setHubError("");
                }}
                placeholder="https://example.com/skills/my-skill"
              />
            </label>
            <div className="skill-pool-form-grid">
              <label className="skill-pool-form-field">
                <span>版本 / 标签（可选）</span>
                <input
                  value={hubVersion}
                  onChange={(event) => setHubVersion(event.target.value)}
                  placeholder="例如：v1.2.0"
                />
              </label>
              <label className="skill-pool-form-field">
                <span>重命名为（可选）</span>
                <input
                  value={hubTargetName}
                  onChange={(event) => setHubTargetName(event.target.value)}
                  placeholder="避免与现有技能重名"
                />
              </label>
            </div>
            {hubError ? <div className="skill-pool-notice error">{hubError}</div> : null}
            {hubInstall ? (
              <div className="skill-pool-hub-progress">
                <i className="ri-loader-4-line ri-spin" />
                导入中…（{hubInstall.status}）
              </div>
            ) : null}

            <div className="skill-pool-form-actions">
              <button type="button" className="portal-model-btn secondary" onClick={closeHubModal}>
                取消
              </button>
              <button
                type="button"
                className="portal-model-btn success"
                disabled={saving}
                onClick={() => void handleHubSubmit()}
              >
                <i className={`fas ${saving ? "fa-spinner fa-spin" : "fa-cloud-arrow-down"}`} />
                {saving ? "导入中..." : "导入"}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {scanError ? (() => {
        const findings = scanError.findings || [];
        const domainUnavailable = findings.some((f) => f.rule_id === "domain.check_unavailable");
        const domainReject =
          !domainUnavailable && findings.some((f) => (f.rule_id || "").startsWith("domain."));
        const domainFinding =
          findings.find((f) => (f.rule_id || "").startsWith("domain.")) || null;
        const title = domainUnavailable
          ? "技能领域审核未完成"
          : domainReject
            ? "无法导入：非网络管理领域"
            : "安全扫描未通过";
        const intro = domainUnavailable
          ? "技能领域审核失败，请稍后重试，或联系管理员处理。"
          : domainReject
            ? "当前系统暂不支持导入其他专业的技能。"
            : `技能「${scanError.skill_name}」被安全扫描拦截（最高风险：${scanError.max_severity}），未导入 / 未启用。请修复后重试。`;
        return (
        <div className="skill-pool-modal-backdrop" onClick={() => setScanError(null)}>
          <div className="skill-pool-modal compact" onClick={(event) => event.stopPropagation()}>
            <div className="skill-pool-modal-header">
              <div>
                <h3>{title}</h3>
                <p>{intro}</p>
              </div>
              <button type="button" className="skill-pool-modal-close" onClick={() => setScanError(null)}>
                <i className="fas fa-xmark" />
              </button>
            </div>

            {domainReject && domainFinding ? (
              <div className="skill-pool-scan-list">
                <div className="skill-pool-scan-item">
                  <p>{domainFinding.description}</p>
                </div>
              </div>
            ) : domainUnavailable ? null : (
              <div className="skill-pool-scan-list">
                {findings.length ? (
                  findings.map((finding, index) => (
                    <div key={`${finding.rule_id}-${index}`} className="skill-pool-scan-item">
                      <div className="skill-pool-scan-head">
                        <span className={`skill-pool-scan-severity ${finding.severity.toLowerCase()}`}>
                          {finding.severity}
                        </span>
                        <strong>{finding.title}</strong>
                        <span className="skill-pool-scan-rule">{finding.rule_id}</span>
                      </div>
                      <p>{finding.description}</p>
                      {finding.file_path ? (
                        <small>
                          {finding.file_path}
                          {finding.line_number ? `:${finding.line_number}` : ""}
                        </small>
                      ) : null}
                    </div>
                  ))
                ) : (
                  <div className="skill-pool-placeholder">{scanError.detail || "未提供详细信息"}</div>
                )}
              </div>
            )}

            <div className="skill-pool-form-actions">
              <button type="button" className="portal-model-btn secondary" onClick={() => setScanError(null)}>
                我知道了
              </button>
            </div>
          </div>
        </div>
        );
      })() : null}
    </div>
  );
}
