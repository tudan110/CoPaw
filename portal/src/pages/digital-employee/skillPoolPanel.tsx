import { useCallback, useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  type PoolSkillInfo,
  skillsApi,
  type WorkspaceSkillSummary,
} from "../../api/skills";
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
        message: error instanceof Error ? error.message : "技能池列表加载失败",
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData]);

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
        message: error instanceof Error ? error.message : "技能池刷新失败",
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
        message: error instanceof Error ? error.message : "删除技能失败",
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
          message: `技能主体已保存，但标签同步失败：${
            error instanceof Error ? error.message : "未知错误"
          }`,
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
      setNotice({
        type: "error",
        message: error instanceof Error ? error.message : "保存技能失败",
      });
    } finally {
      setSaving(false);
    }
  };

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
          <span>工作区：{workspaces.length} 个</span>
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
            <span>可以直接新建自定义技能，统一沉淀到全局技能池。</span>
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
    </div>
  );
}
