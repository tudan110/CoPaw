import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  type BuiltinImportSpec,
  type PoolSkillInfo,
  SkillConflictError,
  SkillScanError,
  type SkillScanErrorPayload,
  skillsApi,
  type WorkspaceSkillSummary,
} from "../../api/skills";
import { portalGatewayAgentId } from "../../config/portalBranding";
import "../skill-pool.css";

type NoticeState =
  | { type: "success" | "error"; message: string }
  | null;

type FilterMode = "all" | "custom" | "builtin" | "used" | "unused";
type ModalMode = "create" | "edit" | "fork";

type SkillFormState = {
  name: string;
  content: string;
  tagsText: string;
  configText: string;
};

type WorkspaceUsage = {
  agentId: string;
  agentName: string;
  enabled: boolean;
  channels: string[];
};

type BuiltinSelection = {
  selected: boolean;
  language: string;
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

function getSkillEmoji(skill: PoolSkillInfo) {
  if (skill.emoji?.trim()) {
    return skill.emoji.trim();
  }

  if (skill.source === "builtin") {
    return "🧩";
  }

  return "⚡";
}

function getSkillSourceLabel(skill: PoolSkillInfo) {
  if (skill.source === "builtin") {
    return "内置";
  }
  return "自定义";
}

function buildCopyName(skillName: string, existingNames: string[]) {
  const existing = new Set(existingNames);
  let candidate = `${skillName}-copy`;
  let index = 2;
  while (existing.has(candidate)) {
    candidate = `${skillName}-copy-${index}`;
    index += 1;
  }
  return candidate;
}

function describeError(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

export function SkillPoolPanel() {
  const [skills, setSkills] = useState<PoolSkillInfo[]>([]);
  const [workspaces, setWorkspaces] = useState<WorkspaceSkillSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<NoticeState>(null);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<FilterMode>("all");
  const [selectedSkillName, setSelectedSkillName] = useState<string | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [modalMode, setModalMode] = useState<ModalMode>("create");
  const [editingSkill, setEditingSkill] = useState<PoolSkillInfo | null>(null);
  const [form, setForm] = useState<SkillFormState>(EMPTY_FORM);

  // Import + assign state
  const [importMenuOpen, setImportMenuOpen] = useState(false);
  const importMenuRef = useRef<HTMLDivElement | null>(null);
  const [scanError, setScanError] = useState<SkillScanErrorPayload | null>(null);
  const [assigningSkill, setAssigningSkill] = useState<string | null>(null);

  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadTargetName, setUploadTargetName] = useState("");
  const [uploadError, setUploadError] = useState("");

  const [hubModalOpen, setHubModalOpen] = useState(false);
  const [hubUrl, setHubUrl] = useState("");
  const [hubVersion, setHubVersion] = useState("");
  const [hubTargetName, setHubTargetName] = useState("");
  const [hubError, setHubError] = useState("");

  const [builtinModalOpen, setBuiltinModalOpen] = useState(false);
  const [builtinLoading, setBuiltinLoading] = useState(false);
  const [builtinSources, setBuiltinSources] = useState<BuiltinImportSpec[]>([]);
  const [builtinSelection, setBuiltinSelection] = useState<Record<string, BuiltinSelection>>({});
  const [builtinError, setBuiltinError] = useState("");

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [poolSkills, workspaceSkills] = await Promise.all([
        skillsApi.listPoolSkills(),
        skillsApi.listWorkspaceSkills(),
      ]);
      setSkills(poolSkills);
      setWorkspaces(workspaceSkills);
    } catch (error) {
      setNotice({
        type: "error",
        message: describeError(error, "技能池列表加载失败"),
      });
    } finally {
      setLoading(false);
    }
  }, []);

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

  const targetWorkspace = useMemo(() => {
    if (!workspaces.length) {
      return null;
    }
    return (
      workspaces.find((workspace) => workspace.agent_id === portalGatewayAgentId) ||
      workspaces.find((workspace) => workspace.agent_id === "default") ||
      workspaces[0]
    );
  }, [workspaces]);

  const targetAgentId = targetWorkspace?.agent_id || portalGatewayAgentId;
  const targetAgentName = targetWorkspace?.agent_name || targetWorkspace?.agent_id || portalGatewayAgentId;

  const usageMap = useMemo(() => {
    const next: Record<string, WorkspaceUsage[]> = {};

    for (const workspace of workspaces) {
      for (const skill of workspace.skills || []) {
        if (!next[skill.name]) {
          next[skill.name] = [];
        }
        next[skill.name].push({
          agentId: workspace.agent_id,
          agentName: workspace.agent_name || workspace.agent_id,
          enabled: Boolean(skill.enabled),
          channels: skill.channels || ["all"],
        });
      }
    }

    return next;
  }, [workspaces]);

  const filteredSkills = useMemo(() => {
    const keyword = search.trim().toLowerCase();

    return skills.filter((skill) => {
      const usageCount = usageMap[skill.name]?.length || 0;
      const matchedFilter =
        filter === "all"
        || (filter === "custom" && skill.source !== "builtin")
        || (filter === "builtin" && skill.source === "builtin")
        || (filter === "used" && usageCount > 0)
        || (filter === "unused" && usageCount === 0);

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
  }, [filter, search, skills, usageMap]);

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

  const selectedUsages = selectedSkill ? usageMap[selectedSkill.name] || [] : [];
  const selectedTargetUsage = selectedUsages.find((usage) => usage.agentId === targetAgentId) || null;
  const builtinCount = useMemo(
    () => skills.filter((skill) => skill.source === "builtin").length,
    [skills],
  );

  const openCreateModal = () => {
    setModalMode("create");
    setEditingSkill(null);
    setForm(EMPTY_FORM);
    setIsModalOpen(true);
  };

  const openEditModal = (skill: PoolSkillInfo) => {
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

  const openForkModal = (skill: PoolSkillInfo) => {
    setModalMode("fork");
    setEditingSkill(skill);
    setForm({
      name: buildCopyName(
        skill.name,
        skills.map((item) => item.name),
      ),
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
      await skillsApi.refreshPoolSkills();
      await loadData();
      setNotice({ type: "success", message: "技能池已刷新" });
    } catch (error) {
      setNotice({
        type: "error",
        message: describeError(error, "技能池刷新失败"),
      });
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (skill: PoolSkillInfo) => {
    if (skill.protected || skill.source === "builtin") {
      setNotice({
        type: "error",
        message: "内置技能不支持直接删除，可先复制为自定义技能后再维护",
      });
      return;
    }

    if (!window.confirm(`确认删除技能“${skill.name}”吗？`)) {
      return;
    }

    try {
      await skillsApi.deletePoolSkill(skill.name);
      setNotice({ type: "success", message: `已删除技能：${skill.name}` });
      if (selectedSkillName === skill.name) {
        setSelectedSkillName(null);
      }
      await loadData();
    } catch (error) {
      setNotice({
        type: "error",
        message: describeError(error, "删除技能失败"),
      });
    }
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
      let finalName = nextName;
      const config = parseJsonObject(form.configText, "技能配置");
      const tags = parseTags(form.tagsText);

      if (modalMode === "edit" && editingSkill) {
        const result = await skillsApi.savePoolSkill({
          name: nextName,
          content: form.content.trim(),
          sourceName: editingSkill.name,
          config,
        });
        finalName = result.name || nextName;
      } else {
        await skillsApi.createPoolSkill({
          name: nextName,
          content: form.content.trim(),
          config,
        });
      }

      try {
        await skillsApi.updatePoolSkillTags(finalName, tags);
      } catch (error) {
        resetModalState();
        await loadData();
        setSelectedSkillName(finalName);
        setNotice({
          type: "error",
          message: `技能主体已保存，但标签同步失败：${describeError(error, "未知错误")}`,
        });
        return;
      }

      resetModalState();
      await loadData();
      setSelectedSkillName(finalName);
      setNotice({
        type: "success",
        message:
          modalMode === "create"
            ? `已新增技能：${finalName}`
            : modalMode === "fork"
              ? `已复制技能：${finalName}`
              : `已更新技能：${finalName}`,
      });
    } catch (error) {
      if (error instanceof SkillScanError) {
        setScanError(error.payload);
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
      const result = await skillsApi.uploadSkillZipToPool(uploadFile, {
        targetName: uploadTargetName,
      });
      setUploadModalOpen(false);
      await loadData();
      setNotice({
        type: "success",
        message: `已导入 ${result.count} 个技能到技能池`,
      });
    } catch (error) {
      if (error instanceof SkillScanError) {
        setUploadModalOpen(false);
        setScanError(error.payload);
      } else if (error instanceof SkillConflictError) {
        setUploadError(
          `压缩包中的技能与现有技能冲突：${error.conflicts.join(", ") || "已存在同名技能"}。可填写「重命名为」后重试，或先删除同名技能。`,
        );
      } else {
        setUploadError(describeError(error, "上传技能失败"));
      }
    } finally {
      setSaving(false);
    }
  };

  // ---- Import: from hub URL ----
  const openHubModal = () => {
    setHubUrl("");
    setHubVersion("");
    setHubTargetName("");
    setHubError("");
    setHubModalOpen(true);
  };

  const closeHubModal = () => {
    if (saving) {
      return;
    }
    setHubModalOpen(false);
  };

  const handleHubSubmit = async () => {
    if (!hubUrl.trim()) {
      setHubError("请填写技能链接");
      return;
    }
    setHubError("");
    try {
      setSaving(true);
      const result = await skillsApi.importSkillFromHub({
        bundleUrl: hubUrl,
        version: hubVersion,
        targetName: hubTargetName,
      });
      setHubModalOpen(false);
      await loadData();
      setSelectedSkillName(result.name);
      setNotice({
        type: "success",
        message: `已从链接导入技能：${result.name}`,
      });
    } catch (error) {
      if (error instanceof SkillScanError) {
        setHubModalOpen(false);
        setScanError(error.payload);
      } else if (error instanceof SkillConflictError) {
        setHubError(
          `技能名冲突：${error.conflicts.join(", ") || "已存在同名技能"}。可填写「重命名为」后重试。`,
        );
      } else {
        setHubError(describeError(error, "从链接导入失败"));
      }
    } finally {
      setSaving(false);
    }
  };

  // ---- Import: builtin skills ----
  const openBuiltinModal = async () => {
    setBuiltinModalOpen(true);
    setBuiltinError("");
    setBuiltinLoading(true);
    try {
      const sources = await skillsApi.listBuiltinSources();
      setBuiltinSources(sources);
      const selection: Record<string, BuiltinSelection> = {};
      for (const source of sources) {
        selection[source.name] = {
          selected: false,
          language: source.current_language || source.available_languages?.[0] || "",
        };
      }
      setBuiltinSelection(selection);
    } catch (error) {
      setBuiltinError(describeError(error, "内置技能列表加载失败"));
    } finally {
      setBuiltinLoading(false);
    }
  };

  const closeBuiltinModal = () => {
    if (saving) {
      return;
    }
    setBuiltinModalOpen(false);
  };

  const toggleBuiltinSelection = (name: string) => {
    setBuiltinSelection((current) => ({
      ...current,
      [name]: {
        selected: !current[name]?.selected,
        language: current[name]?.language || "",
      },
    }));
  };

  const setBuiltinLanguage = (name: string, language: string) => {
    setBuiltinSelection((current) => ({
      ...current,
      [name]: {
        selected: current[name]?.selected ?? false,
        language,
      },
    }));
  };

  const runBuiltinImport = async (overwriteConflicts: boolean) => {
    const imports = Object.entries(builtinSelection)
      .filter(([, value]) => value.selected)
      .map(([name, value]) => ({ skill_name: name, language: value.language || "" }));

    if (!imports.length) {
      setBuiltinError("请至少勾选一个内置技能");
      return;
    }
    setBuiltinError("");
    try {
      setSaving(true);
      const result = await skillsApi.importBuiltinSkills({ imports, overwriteConflicts });
      setBuiltinModalOpen(false);
      await loadData();
      const addedCount = result.added?.length ?? 0;
      const skippedCount = result.skipped?.length ?? 0;
      setNotice({
        type: "success",
        message: `已导入 ${addedCount} 个内置技能${skippedCount ? `，跳过 ${skippedCount} 个已存在` : ""}`,
      });
    } catch (error) {
      if (error instanceof SkillScanError) {
        setBuiltinModalOpen(false);
        setScanError(error.payload);
      } else if (error instanceof SkillConflictError) {
        const conflicts = error.conflicts.join(", ") || "已存在同名技能";
        if (window.confirm(`以下内置技能与现有技能冲突：${conflicts}\n是否覆盖导入？`)) {
          await runBuiltinImport(true);
          return;
        }
        setBuiltinError(`已取消：存在冲突技能（${conflicts}）`);
      } else {
        setBuiltinError(describeError(error, "导入内置技能失败"));
      }
    } finally {
      setSaving(false);
    }
  };

  // ---- Assign pool skill to the gateway agent ----
  const handleAssign = async (skill: PoolSkillInfo) => {
    if (!targetAgentId) {
      setNotice({ type: "error", message: "未找到目标数字员工工作区" });
      return;
    }
    const usages = usageMap[skill.name] || [];
    const alreadyInWorkspace = usages.some((usage) => usage.agentId === targetAgentId);
    const confirmText = alreadyInWorkspace
      ? `在「${targetAgentName}」启用技能「${skill.name}」？`
      : `将技能「${skill.name}」下发到「${targetAgentName}」并启用？`;
    if (!window.confirm(confirmText)) {
      return;
    }
    try {
      setAssigningSkill(skill.name);
      if (!alreadyInWorkspace) {
        await skillsApi.downloadPoolSkill({
          skillName: skill.name,
          workspaceId: targetAgentId,
          overwrite: false,
        });
      }
      await skillsApi.enableWorkspaceSkill(skill.name, targetAgentId);
      await loadData();
      setNotice({
        type: "success",
        message: `技能「${skill.name}」已在「${targetAgentName}」启用（约 1–2 秒后生效）`,
      });
    } catch (error) {
      if (error instanceof SkillScanError) {
        setScanError(error.payload);
      } else {
        setNotice({
          type: "error",
          message: describeError(error, "下发并启用技能失败"),
        });
      }
    } finally {
      setAssigningSkill(null);
    }
  };

  const handleUnassign = async (skill: PoolSkillInfo) => {
    if (!targetAgentId) {
      return;
    }
    if (!window.confirm(`在「${targetAgentName}」停用技能「${skill.name}」？`)) {
      return;
    }
    try {
      setAssigningSkill(skill.name);
      await skillsApi.disableWorkspaceSkill(skill.name, targetAgentId);
      await loadData();
      setNotice({
        type: "success",
        message: `已在「${targetAgentName}」停用技能「${skill.name}」`,
      });
    } catch (error) {
      setNotice({
        type: "error",
        message: describeError(error, "停用技能失败"),
      });
    } finally {
      setAssigningSkill(null);
    }
  };

  const selectedBuiltinCount = Object.values(builtinSelection).filter((value) => value.selected).length;

  return (
    <div className="skill-pool-panel">
      <div className="portal-model-page-header">
        <div className="portal-model-page-title">
          技能池 <small>运维技能库</small>
        </div>
        <div className="portal-model-page-actions">
          <button type="button" className="portal-model-btn" onClick={openCreateModal}>
            <i className="fas fa-plus" />
            新增技能
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
                <button
                  type="button"
                  onClick={() => {
                    setImportMenuOpen(false);
                    void openBuiltinModal();
                  }}
                >
                  <i className="fas fa-cubes" />
                  导入内置技能
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
          <span>管理范围：全局技能池</span>
          <span>技能总数：{skills.length}</span>
          <span>内置技能：{builtinCount}</span>
          <span>下发目标：{targetAgentName}</span>
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
              ["custom", "自定义"],
              ["builtin", "内置"],
              ["used", "已引用"],
              ["unused", "未引用"],
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
              正在加载技能池...
            </div>
          </div>
        ) : filteredSkills.length ? (
          <div className="skill-pool-grid">
            {filteredSkills.map((skill) => {
              const usageCount = usageMap[skill.name]?.length || 0;
              const enabledOnTarget = (usageMap[skill.name] || []).some(
                (usage) => usage.agentId === targetAgentId && usage.enabled,
              );
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
                            <span className={`skill-pool-badge ${skill.source === "builtin" ? "builtin" : "custom"}`}>
                              {getSkillSourceLabel(skill)}
                            </span>
                            {skill.protected ? (
                              <span className="skill-pool-badge protected">受保护</span>
                            ) : null}
                            {enabledOnTarget ? (
                              <span className="skill-pool-badge enabled">已启用</span>
                            ) : null}
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
                      <span>工作区引用</span>
                      <strong>{usageCount ? `${usageCount} 个工作区` : "暂未下发"}</strong>
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
                        if (skill.protected || skill.source === "builtin") {
                          openForkModal(skill);
                        } else {
                          openEditModal(skill);
                        }
                     }}
                    >
                      {skill.protected || skill.source === "builtin" ? "复制" : "编辑"}
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
            <span>可以新建自定义技能，或通过「导入技能」上传压缩包 / 链接 / 内置技能。</span>
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
                  <span className={`skill-pool-badge ${selectedSkill.source === "builtin" ? "builtin" : "custom"}`}>
                    {getSkillSourceLabel(selectedSkill)}
                  </span>
                  <span className="skill-pool-badge info">版本 {selectedSkill.version_text || "未标注"}</span>
                  {selectedSkill.sync_status ? (
                    <span className="skill-pool-badge info">同步 {selectedSkill.sync_status}</span>
                  ) : null}
                  <span className="skill-pool-badge info">
                    更新于 {formatLastUpdated(selectedSkill.last_updated)}
                  </span>
                </div>
              </div>

              <div className="skill-pool-detail-actions">
                {selectedTargetUsage?.enabled ? (
                  <button
                    type="button"
                    className="portal-model-btn secondary danger"
                    disabled={assigningSkill === selectedSkill.name}
                    onClick={() => void handleUnassign(selectedSkill)}
                  >
                    <i className={`fas ${assigningSkill === selectedSkill.name ? "fa-spinner fa-spin" : "fa-circle-stop"}`} />
                    在「{targetAgentName}」停用
                  </button>
                ) : (
                  <button
                    type="button"
                    className="portal-model-btn success"
                    disabled={assigningSkill === selectedSkill.name}
                    onClick={() => void handleAssign(selectedSkill)}
                  >
                    <i className={`fas ${assigningSkill === selectedSkill.name ? "fa-spinner fa-spin" : "fa-circle-play"}`} />
                    {selectedTargetUsage ? `在「${targetAgentName}」启用` : `下发到「${targetAgentName}」并启用`}
                  </button>
                )}
                <button
                  type="button"
                  className="portal-model-btn secondary"
                  onClick={() => {
                    if (selectedSkill.protected || selectedSkill.source === "builtin") {
                      openForkModal(selectedSkill);
                    } else {
                      openEditModal(selectedSkill);
                    }
                  }}
                >
                  <i className="fas fa-pen" />
                  {selectedSkill.protected || selectedSkill.source === "builtin" ? "复制为自定义技能" : "编辑技能"}
                </button>
                <button
                  type="button"
                  className="portal-model-btn secondary danger"
                  disabled={selectedSkill.protected || selectedSkill.source === "builtin"}
                  onClick={() => void handleDelete(selectedSkill)}
                >
                  <i className="fas fa-trash" />
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
                    <h4>下发与启用</h4>
                    <span>{targetAgentName}</span>
                  </div>
                  <div className="skill-pool-assign-row">
                    <span>
                      当前状态：
                      {selectedTargetUsage
                        ? selectedTargetUsage.enabled
                          ? "已下发并启用"
                          : "已下发，未启用"
                        : "未下发到该数字员工"}
                    </span>
                    {selectedTargetUsage?.enabled ? (
                      <button
                        type="button"
                        className="portal-model-btn secondary danger compact"
                        disabled={assigningSkill === selectedSkill.name}
                        onClick={() => void handleUnassign(selectedSkill)}
                      >
                        停用
                      </button>
                    ) : (
                      <button
                        type="button"
                        className="portal-model-btn success compact"
                        disabled={assigningSkill === selectedSkill.name}
                        onClick={() => void handleAssign(selectedSkill)}
                      >
                        {selectedTargetUsage ? "启用" : "下发并启用"}
                      </button>
                    )}
                  </div>
                  <div className="skill-pool-card-hint">
                    下发后约 1–2 秒生效；如需更细粒度地分配到不同数字员工，可在后续版本扩展。
                  </div>
                </div>

                <div className="skill-pool-side-card">
                  <div className="skill-pool-section-header">
                    <h4>工作区引用</h4>
                    <span>{selectedUsages.length} 个</span>
                  </div>
                  {selectedUsages.length ? (
                    <div className="skill-pool-workspace-list">
                      {selectedUsages.map((usage) => (
                        <div key={`${selectedSkill.name}-${usage.agentId}`} className="skill-pool-workspace-item">
                          <div>
                            <strong>{usage.agentName}</strong>
                            <small>{usage.agentId}</small>
                          </div>
                          <div className="skill-pool-workspace-meta">
                            <span className={usage.enabled ? "online" : "offline"}>
                              {usage.enabled ? "已启用" : "未启用"}
                            </span>
                            <small>{usage.channels.join(", ")}</small>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="skill-pool-placeholder">当前还没有下发到任何工作区</div>
                  )}
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
                <h3>
                  {modalMode === "create"
                    ? "新增技能"
                    : modalMode === "fork"
                      ? "复制为自定义技能"
                      : "编辑技能"}
                </h3>
                <p>
                  当前采用原生 SKILL.md 格式，技能池为全局共享能力中心。
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
                {modalMode === "create" ? "创建技能" : modalMode === "fork" ? "保存副本" : "保存修改"}
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
                <p>选择一个符合 SKILL.md 规范的 .zip 包，导入到全局技能池（最大 100MB）。</p>
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
                <p>支持技能 Hub / 仓库的发布链接，导入后会落入全局技能池。</p>
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

      {builtinModalOpen ? (
        <div className="skill-pool-modal-backdrop" onClick={closeBuiltinModal}>
          <div className="skill-pool-modal" onClick={(event) => event.stopPropagation()}>
            <div className="skill-pool-modal-header">
              <div>
                <h3>导入内置技能</h3>
                <p>从随系统发布的内置技能库中挑选，导入到全局技能池后即可下发使用。</p>
              </div>
              <button type="button" className="skill-pool-modal-close" onClick={closeBuiltinModal}>
                <i className="fas fa-xmark" />
              </button>
            </div>

            {builtinLoading ? (
              <div className="skill-pool-loading">
                <i className="ri-loader-4-line ri-spin" />
                正在加载内置技能列表...
              </div>
            ) : builtinSources.length ? (
              <div className="skill-pool-builtin-list">
                {builtinSources.map((source) => {
                  const selection = builtinSelection[source.name];
                  const languages = source.available_languages || [];
                  return (
                    <label key={source.name} className="skill-pool-builtin-item">
                      <input
                        type="checkbox"
                        checked={Boolean(selection?.selected)}
                        onChange={() => toggleBuiltinSelection(source.name)}
                      />
                      <div className="skill-pool-builtin-copy">
                        <strong>{source.name}</strong>
                        <span>{source.description || "无描述"}</span>
                        <small>
                          {source.version_text ? `版本 ${source.version_text}` : "版本未标注"}
                          {source.status ? ` · ${source.status}` : ""}
                        </small>
                      </div>
                      {languages.length > 1 ? (
                        <select
                          value={selection?.language || languages[0]}
                          onClick={(event) => event.stopPropagation()}
                          onChange={(event) => setBuiltinLanguage(source.name, event.target.value)}
                        >
                          {languages.map((language) => (
                            <option key={language} value={language}>
                              {language}
                            </option>
                          ))}
                        </select>
                      ) : languages.length === 1 ? (
                        <span className="skill-pool-builtin-lang">{languages[0]}</span>
                      ) : null}
                    </label>
                  );
                })}
              </div>
            ) : (
              <div className="skill-pool-placeholder">没有可导入的内置技能</div>
            )}

            {builtinError ? <div className="skill-pool-notice error">{builtinError}</div> : null}

            <div className="skill-pool-form-actions">
              <span className="skill-pool-builtin-count">已选 {selectedBuiltinCount} 个</span>
              <button type="button" className="portal-model-btn secondary" onClick={closeBuiltinModal}>
                取消
              </button>
              <button
                type="button"
                className="portal-model-btn success"
                disabled={saving || builtinLoading || selectedBuiltinCount === 0}
                onClick={() => void runBuiltinImport(false)}
              >
                <i className={`fas ${saving ? "fa-spinner fa-spin" : "fa-download"}`} />
                {saving ? "导入中..." : "导入所选"}
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
