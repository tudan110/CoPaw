import { useCallback, useEffect, useMemo, useState } from "react";

import {
  McpClientCreateRequest,
  McpClientInfo,
  McpClientUpdateRequest,
  McpToolInfo,
  MCPAccessEffect,
  MCPAccessPolicy,
  MCPAccessRule,
  MCPToolAccessOverride,
  McpTransport,
  mcpApi,
} from "../../api/mcp";
import { parseMcpImportText } from "../../api/mcpImport";
import {
  MCP_CHANNEL_SOURCE_VALUES,
  addClientRule,
  addToolRule,
  buildMCPAccessToolGroups,
  normalizeMCPAccessPolicy,
  removeClientRule,
  removeToolRule,
  upsertClientRule,
  upsertToolDefault,
  upsertToolRule,
  validateMCPAccessPolicy,
} from "../../api/mcpAccessPolicy";
import { portalGatewayAgentId } from "../../config/portalBranding";
import "../mcp-panel.css";

type NoticeState =
  | { type: "success" | "error"; message: string }
  | null;

type FilterMode = "all" | "enabled" | "disabled";

type FormState = {
  clientKey: string;
  name: string;
  description: string;
  enabled: boolean;
  transport: McpTransport;
  url: string;
  headersText: string;
  command: string;
  argsText: string;
  envText: string;
  cwd: string;
};

const EMPTY_FORM: FormState = {
  clientKey: "",
  name: "",
  description: "",
  enabled: true,
  transport: "streamable_http",
  url: "",
  headersText: "",
  command: "",
  argsText: "",
  envText: "",
  cwd: "",
};

function serializeEntries(entries: Record<string, string>) {
  return Object.entries(entries)
    .map(([key, value]) => `${key}=${value}`)
    .join("\n");
}

function parseKeyValueLines(value: string, label: string) {
  const record: Record<string, string> = {};
  const lines = value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  for (const line of lines) {
    const separatorIndex = line.indexOf("=");
    if (separatorIndex <= 0) {
      throw new Error(`${label} 格式错误，请按 KEY=value 每行一条填写`);
    }

    const key = line.slice(0, separatorIndex).trim();
    const lineValue = line.slice(separatorIndex + 1).trim();
    if (!key) {
      throw new Error(`${label} 中存在空键名`);
    }
    record[key] = lineValue;
  }

  return record;
}

function parseLines(value: string) {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

function formatFormState(client?: McpClientInfo): FormState {
  if (!client) {
    return EMPTY_FORM;
  }

  return {
    clientKey: client.key,
    name: client.name,
    description: client.description || "",
    enabled: client.enabled,
    transport: client.transport,
    url: client.url || "",
    headersText: serializeEntries(client.headers || {}),
    command: client.command || "",
    argsText: (client.args || []).join("\n"),
    envText: serializeEntries(client.env || {}),
    cwd: client.cwd || "",
  };
}

function buildEditableJson(client: McpClientInfo) {
  return JSON.stringify(
    {
      key: client.key,
      name: client.name,
      description: client.description || "",
      enabled: client.enabled,
      transport: client.transport,
      url: client.url || "",
      headers: client.headers || {},
      command: client.command || "",
      args: client.args || [],
      env: client.env || {},
      cwd: client.cwd || "",
      tools: client.tools,
    },
    null,
    2,
  );
}

function parseEditableJson(value: string, clientKey?: string): McpClientCreateRequest | McpClientUpdateRequest {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    throw new Error("JSON 格式无效，请修正后再保存");
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("JSON 必须是一个 MCP 配置对象");
  }

  const source = parsed as Record<string, unknown>;
  if (source.key !== undefined && clientKey !== undefined && source.key !== clientKey) {
    throw new Error("MCP Key 创建后不可修改");
  }
  if (
    source.transport !== undefined &&
    source.transport !== "stdio" &&
    source.transport !== "streamable_http" &&
    source.transport !== "sse"
  ) {
    throw new Error("transport 仅支持 stdio、streamable_http 或 sse");
  }

  const updates: McpClientUpdateRequest = {};
  for (const key of [
    "name",
    "description",
    "enabled",
    "transport",
    "url",
    "headers",
    "command",
    "args",
    "env",
    "cwd",
    "tools",
  ] as const) {
    if (source[key] !== undefined) {
      Object.assign(updates, { [key]: source[key] });
    }
  }
  return updates;
}

export { parseEditableJson };

function getTransportIcon(transport: McpTransport) {
  if (transport === "stdio") {
    return "ri-terminal-box-line";
  }
  if (transport === "sse") {
    return "ri-broadcast-line";
  }
  return "ri-links-line";
}

function getTransportColor(transport: McpTransport) {
  if (transport === "stdio") {
    return {
      background: "rgba(139, 92, 246, 0.12)",
      color: "#7c3aed",
    };
  }
  if (transport === "sse") {
    return {
      background: "rgba(245, 158, 11, 0.12)",
      color: "#d97706",
    };
  }
  return {
    background: "rgba(59, 130, 246, 0.12)",
    color: "#2563eb",
  };
}

function getClientEndpoint(client: McpClientInfo) {
  if (client.transport === "stdio") {
    const args = client.args?.length ? ` ${client.args.join(" ")}` : "";
    return `${client.command}${args}`.trim() || "未配置命令";
  }
  return client.url || "未配置地址";
}

function buildPayload(form: FormState): {
  clientKey: string;
  payload: McpClientCreateRequest | McpClientUpdateRequest;
} {
  const clientKey = form.clientKey.trim();
  if (!clientKey) {
    throw new Error("请填写 MCP Key");
  }
  if (!form.name.trim()) {
    throw new Error("请填写 MCP 名称");
  }

  if (form.transport === "stdio" && !form.command.trim()) {
    throw new Error("stdio 类型必须填写 command");
  }

  if (form.transport !== "stdio" && !form.url.trim()) {
    throw new Error("HTTP / SSE 类型必须填写 URL");
  }

  const payload = {
    name: form.name.trim(),
    description: form.description.trim(),
    enabled: form.enabled,
    transport: form.transport,
    url: form.transport === "stdio" ? "" : form.url.trim(),
    headers: form.transport === "stdio" ? {} : parseKeyValueLines(form.headersText, "Headers"),
    command: form.transport === "stdio" ? form.command.trim() : "",
    args: form.transport === "stdio" ? parseLines(form.argsText) : [],
    env: form.transport === "stdio" ? parseKeyValueLines(form.envText, "Env") : {},
    cwd: form.transport === "stdio" ? form.cwd.trim() : "",
  };

  return { clientKey, payload };
}

const MCP_VISIBLE_CHANNEL_SOURCE_VALUES = ["console", "feishu", "dingtalk"] as const;

function getChannelSourceLabel(sourceValue: string) {
  const labels: Record<string, string> = {
    console: "控制台",
    dingtalk: "钉钉",
    feishu: "飞书",
  };
  return labels[sourceValue] || sourceValue;
}

function EffectSelector({ value, onChange }: { value: MCPAccessEffect; onChange: (effect: MCPAccessEffect) => void }) {
  return <div className="mcp-effect-selector">{([['ask', '审批'], ['allow', '允许'], ['deny', '拒绝']] as const).map(([effect, label]) => <button key={effect} type="button" className={value === effect ? 'active' : ''} onClick={() => onChange(effect)}>{label}</button>)}</div>;
}

function AccessRuleRow({ rule, onChange, onDelete }: { rule: MCPAccessRule | MCPToolAccessOverride; onChange: (rule: typeof rule) => void; onDelete: () => void }) {
  const update = (patch: Partial<MCPAccessRule>) => {
    const nextSubjectType = (patch.subject_type ?? rule.subject_type) as MCPAccessRule['subject_type'];
    onChange({
      ...rule,
      ...patch,
      subject_type: nextSubjectType,
      subject_value: nextSubjectType === 'all' ? '' : patch.subject_value ?? rule.subject_value ?? '',
    });
  };

  return <div className="mcp-access-rule-row">
    <label className="mcp-access-field">
      <span>来源</span>
      <select value={rule.source_value} onChange={(event) => update({ source_value: event.target.value })}>
        {MCP_VISIBLE_CHANNEL_SOURCE_VALUES.map((sourceValue) => (
          <option key={sourceValue} value={sourceValue}>{getChannelSourceLabel(sourceValue)}</option>
        ))}
      </select>
    </label>
    <label className="mcp-access-field">
      <span>对象</span>
      <select value={rule.subject_type} onChange={(event) => update({ subject_type: event.target.value as MCPAccessRule['subject_type'] })}>
        <option value="all">全部</option>
        <option value="user">用户</option>
      </select>
    </label>
    {rule.subject_type === 'user' ? <label className="mcp-access-field">
      <span>用户 ID</span>
      <input value={rule.subject_value} onChange={(event) => update({ subject_value: event.target.value })} placeholder="用户 ID" />
    </label> : <div className="mcp-access-field">
      <span>范围</span>
      <span className="mcp-access-all">全部对象</span>
    </div>}
    <div className="mcp-access-field mcp-access-effect-field">
      <span>策略</span>
      <EffectSelector value={rule.effect} onChange={(effect) => update({ effect })} />
    </div>
    <button type="button" className="mcp-rule-delete" onClick={onDelete} aria-label="删除规则">×</button>
  </div>;
}

export function McpPanel() {
  // The Portal only exposes a single public entry agent ("gateway"); MCP
  // clients are always read from / written to that agent. The internal
  // per-employee agents are intentionally not surfaced here.
  const agentId = portalGatewayAgentId;

  const [clients, setClients] = useState<McpClientInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<NoticeState>(null);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<FilterMode>("all");
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingClient, setEditingClient] = useState<McpClientInfo | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [editMode, setEditMode] = useState<"form" | "json">("form");
  const [editJson, setEditJson] = useState("");
  const [editJsonError, setEditJsonError] = useState("");
  const [accessClient, setAccessClient] = useState<McpClientInfo | null>(null);
  const [accessTools, setAccessTools] = useState<McpToolInfo[]>([]);
  const [accessPolicy, setAccessPolicy] = useState<MCPAccessPolicy | null>(null);
  const [accessLoading, setAccessLoading] = useState(false);
  const [accessSaving, setAccessSaving] = useState(false);
  const [accessError, setAccessError] = useState("");

  const loadClients = useCallback(async () => {
    setLoading(true);
    try {
      const response = await mcpApi.listClients(agentId);
      setClients(response);
    } catch (error) {
      setNotice({
        type: "error",
        message: error instanceof Error ? error.message : "MCP 列表加载失败",
      });
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    setNotice(null);
    void loadClients();
  }, [loadClients]);

  const filteredClients = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    return clients.filter((client) => {
      const matchedFilter =
        filter === "all" ||
        (filter === "enabled" && client.enabled) ||
        (filter === "disabled" && !client.enabled);

      if (!matchedFilter) {
        return false;
      }

      if (!keyword) {
        return true;
      }

      return [client.key, client.name, client.description, client.transport, client.url, client.command]
        .filter(Boolean)
        .some((value) => value.toLowerCase().includes(keyword));
    });
  }, [clients, filter, search]);


  const openCreateModal = () => {
    setEditingClient(null);
    setForm(EMPTY_FORM);
    setEditMode("form");
    setEditJson("");
    setEditJsonError("");
    setIsModalOpen(true);
  };

  const openEditModal = (client: McpClientInfo) => {
    setEditingClient(client);
    setForm(formatFormState(client));
    setEditMode("form");
    setEditJson(buildEditableJson(client));
    setEditJsonError("");
    setIsModalOpen(true);
  };

  const closeModal = () => {
    if (saving) {
      return;
    }
    setIsModalOpen(false);
    setEditingClient(null);
    setForm(EMPTY_FORM);
    setEditMode("form");
    setEditJson("");
    setEditJsonError("");
  };

  const openAccessModal = async (client: McpClientInfo) => {
    setAccessClient(client);
    setAccessLoading(true);
    setAccessError("");
    try {
      const [toolsResponse, policyResponse] = await Promise.all([
        mcpApi.listTools(client.key, agentId),
        mcpApi.getPolicy(client.key, agentId),
      ]);
      setAccessTools(toolsResponse);
      setAccessPolicy(normalizeMCPAccessPolicy(policyResponse));
    } catch (error) {
      setAccessError(error instanceof Error ? error.message : "工具与权限加载失败");
    } finally {
      setAccessLoading(false);
    }
  };

  const closeAccessModal = () => {
    if (!accessSaving) {
      setAccessClient(null);
      setAccessPolicy(null);
      setAccessError("");
    }
  };

  const saveAccessPolicy = async () => {
    if (!accessClient || !accessPolicy) return;
    const validation = validateMCPAccessPolicy(accessPolicy);
    if (validation) {
      setAccessError("规则中的来源或用户值无效，请补全后再保存");
      return;
    }
    setAccessSaving(true);
    setAccessError("");
    try {
      const saved = await mcpApi.updatePolicy(accessClient.key, accessPolicy, agentId);
      setAccessPolicy(normalizeMCPAccessPolicy(saved));
      setNotice({ type: "success", message: `已保存 ${accessClient.name} 的工具权限` });
      await loadClients();
      closeAccessModal();
    } catch (error) {
      setAccessError(error instanceof Error ? error.message : "权限保存失败");
    } finally {
      setAccessSaving(false);
    }
  };

  const switchEditMode = (nextMode: "form" | "json") => {
    if (nextMode === editMode) {
      return;
    }
    if (nextMode === "json") {
      try {
        if (editingClient) {
          const { clientKey, payload } = buildPayload(form);
          setEditJson(
            JSON.stringify(
              { key: clientKey, ...payload, tools: editingClient.tools ?? null },
              null,
              2,
            ),
          );
        } else {
          setEditJson("");
        }
        setEditJsonError("");
        setEditMode("json");
      } catch (error) {
        setEditJsonError(error instanceof Error ? error.message : "表单配置无效");
      }
      return;
    }

    try {
      const updates = parseEditableJson(editJson, editingClient?.key);
      const clientKey = typeof JSON.parse(editJson).key === "string"
        ? JSON.parse(editJson).key
        : "";
      setForm(
        formatFormState({
          ...editingClient,
          ...updates,
          key: editingClient?.key || clientKey,
        } as McpClientInfo),
      );
      setEditJsonError("");
      setEditMode("form");
    } catch (error) {
      setEditJsonError(error instanceof Error ? error.message : "JSON 配置无效");
    }
  };

  const parseCreateJson = () => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(editJson);
    } catch {
      throw new Error("JSON 格式无效，请修正后再创建");
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("JSON 必须是一个 MCP 配置对象");
    }
    const source = parsed as Record<string, unknown>;
    const clientKey = typeof source.key === "string" ? source.key.trim() : "";
    if (!clientKey) {
      throw new Error("JSON 配置必须包含 MCP Key");
    }
    const payload = parseEditableJson(editJson) as McpClientCreateRequest;
    if (!payload.name || !payload.transport) {
      throw new Error("JSON 配置必须包含 name 和 transport");
    }
    return { clientKey, payload };
  };

  const parseJsonCreateEntries = () => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(editJson);
    } catch {
      throw new Error("JSON 格式无效，请修正后再创建");
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("JSON 必须是一个 MCP 配置对象");
    }
    const source = parsed as Record<string, unknown>;
    if (source.mcpServers !== undefined || !source.key) {
      return parseMcpImportText(editJson);
    }
    return [parseCreateJson()];
  };

  const handleSubmit = async () => {
    try {
      setSaving(true);
      if (editingClient) {
        const { clientKey, payload } = editMode === "json"
          ? {
              clientKey: editingClient.key,
              payload: parseEditableJson(editJson, editingClient.key),
            }
          : buildPayload(form);
        await mcpApi.updateClient(clientKey, payload, agentId);
        setNotice({ type: "success", message: `已更新 MCP：${payload.name || editingClient.name}` });
      } else {
        const entries = editMode === "json"
          ? parseJsonCreateEntries()
          : [buildPayload(form)];
        const created: string[] = [];
        const failed: string[] = [];
        for (const entry of entries) {
          try {
            await mcpApi.createClient(
              entry.clientKey,
              entry.payload as McpClientCreateRequest,
              agentId,
            );
            created.push(entry.clientKey);
          } catch (error) {
            const message = error instanceof Error ? error.message : "未知错误";
            failed.push(`${entry.clientKey}（${message}）`);
          }
        }
        if (failed.length) {
          throw new Error(
            `MCP 导入未全部完成：已新增 ${created.length} 个` +
              `；失败 ${failed.length} 个：${failed.join("；")}`,
          );
        }
        setNotice({
          type: "success",
          message: entries.length === 1
            ? `已新增 MCP：${created[0]}`
            : `已新增 ${created.length} 个 MCP：${created.join("、")}`,
        });
      }

      closeModal();
      await loadClients();
    } catch (error) {
      setNotice({
        type: "error",
        message: error instanceof Error ? error.message : "保存 MCP 失败",
      });
      await loadClients();
    } finally {
      setSaving(false);
    }
  };

  const handleToggle = async (client: McpClientInfo) => {
    try {
      await mcpApi.toggleClient(client.key, agentId);
      setNotice({
        type: "success",
        message: `${client.name} 已${client.enabled ? "停用" : "启用"}`,
      });
      await loadClients();
    } catch (error) {
      setNotice({
        type: "error",
        message: error instanceof Error ? error.message : "切换 MCP 状态失败",
      });
    }
  };

  const handleDelete = async (client: McpClientInfo) => {
    if (!window.confirm(`确认删除 MCP “${client.name}” 吗？`)) {
      return;
    }

    try {
      await mcpApi.deleteClient(client.key, agentId);
      setNotice({ type: "success", message: `已删除 MCP：${client.name}` });
      await loadClients();
    } catch (error) {
      setNotice({
        type: "error",
        message: error instanceof Error ? error.message : "删除 MCP 失败",
      });
    }
  };

  return (
    <div className="mcp-panel">
      <div className="portal-model-page-header">
        <div className="portal-model-page-title">
          MCP管理 <small>Model Context Protocol</small>
        </div>
        <div className="portal-model-page-actions">
          <button type="button" className="portal-model-btn" onClick={openCreateModal}>
            <i className="fas fa-plus" />
            新增MCP
          </button>
          <button
            type="button"
            className="portal-model-btn"
            onClick={() => {
              setNotice(null);
              void loadClients();
            }}
          >
            <i className={`fas ${loading ? "fa-spinner fa-spin" : "fa-rotate-right"}`} />
            刷新
          </button>
        </div>
      </div>

      <div className="mcp-panel-content">
        <div className="portal-model-scope-bar mcp-scope-bar">
          <span>管理范围：网关入口 Agent 的 MCP 配置</span>
          <span>所有导入 / 新增的 MCP 都接入到该入口</span>
        </div>

        <div className="mcp-panel-toolbar">
          <div className="mcp-panel-search">
            <i className="ri-search-line" />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="搜索 MCP 名称、Key、协议或地址"
            />
          </div>
          <div className="mcp-panel-filter-group">
            {[
              ["all", "全部"],
              ["enabled", "已启用"],
              ["disabled", "已停用"],
            ].map(([value, label]) => (
              <button
                key={value}
                type="button"
                className={`mcp-panel-filter ${filter === value ? "active" : ""}`}
                onClick={() => setFilter(value as FilterMode)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {notice ? (
          <div className={`mcp-panel-notice ${notice.type}`}>{notice.message}</div>
        ) : null}

        {loading ? (
          <div className="mcp-empty">
            <div className="mcp-loading">
              <i className="ri-loader-4-line ri-spin" />
              正在加载 MCP 列表...
            </div>
          </div>
        ) : filteredClients.length ? (
          <div className="mcp-grid">
            {filteredClients.map((client) => {
              const transportStyle = getTransportColor(client.transport);
              const toolsCount = null;
              return (
                <article key={client.key} className="mcp-card">
                  <div className="mcp-card-head">
                    <div style={{ display: "flex", gap: 12 }}>
                      <span className="mcp-icon" style={transportStyle}>
                        <i className={getTransportIcon(client.transport)} />
                      </span>
                      <div className="mcp-card-title">
                        <h4>{client.name}</h4>
                        <p>{client.key}</p>
                      </div>
                    </div>
                    <div className="mcp-card-badges">
                      <span className={`mcp-badge ${client.enabled ? "enabled" : "disabled"}`}>
                        <span className={`mcp-dot ${client.enabled ? "enabled" : "disabled"}`} />
                        {client.enabled ? "运行中" : "已停用"}
                      </span>
                      <span className="mcp-badge transport">{client.transport}</span>
                    </div>
                  </div>

                  <div className="mcp-card-body">
                    <div className="mcp-card-kv">
                      <span>描述</span>
                      <strong>{client.description || "未填写描述"}</strong>
                    </div>
                    <div className="mcp-card-kv">
                      <span>{client.transport === "stdio" ? "Command" : "Endpoint"}</span>
                      <strong>{getClientEndpoint(client)}</strong>
                    </div>
                    <div className="mcp-card-status">
                      <span className={`mcp-dot ${client.enabled ? "enabled" : "disabled"}`} />
                      {client.enabled ? "当前可参与工具编排" : "当前不会被调用"}
                    </div>
                    <div className="mcp-card-tools-summary">
                      <span>工具能力 {typeof toolsCount === "number" ? `${toolsCount} 项` : "未读取"}</span>
                      <span>{client.transport === "stdio" ? "本地进程" : "远程协议"}</span>
                    </div>
                  </div>

                  <div className="mcp-card-actions">
                    <button type="button" className="mcp-card-action" onClick={() => void openAccessModal(client)}>
                      工具
                    </button>
                    <button type="button" className="mcp-card-action" onClick={() => openEditModal(client)}>
                      编辑
                    </button>
                    <button type="button" className="mcp-card-action" onClick={() => void handleToggle(client)}>
                      {client.enabled ? "停用" : "启用"}
                    </button>
                    <button type="button" className="mcp-card-action danger" onClick={() => void handleDelete(client)}>
                      删除
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        ) : (
          <div className="mcp-empty">
            <i className="ri-links-line" />
            <strong>还没有匹配的 MCP 配置</strong>
            <span>可以直接新增一个 streamable HTTP / SSE / stdio 客户端。</span>
          </div>
        )}

      </div>

      {accessClient ? (
        <div className="mcp-modal-backdrop" onClick={closeAccessModal}>
          <div className="mcp-modal mcp-access-modal" onClick={(event) => event.stopPropagation()}>
            <div className="mcp-modal-header">
              <div>
                <h3>{accessClient.name} · 工具与权限</h3>
                <p>配置整体策略、调用规则和每个工具的权限。</p>
              </div>
              <button type="button" className="mcp-modal-close" onClick={closeAccessModal} aria-label="关闭">×</button>
            </div>
            {accessLoading || !accessPolicy ? (
              <div className="mcp-loading">正在读取工具与权限...</div>
            ) : (
              <div className="mcp-access-body">
                <section className="mcp-access-section">
                  <div className="mcp-access-control-row">
                    <div className="mcp-access-heading"><h4>整体权限</h4><span>默认策略</span></div>
                    <EffectSelector value={accessPolicy.default_effect} onChange={(effect) => setAccessPolicy({ ...accessPolicy, default_effect: effect })} />
                    <button type="button" className="mcp-add-rule mcp-access-add-rule" onClick={() => setAccessPolicy(addClientRule(accessPolicy))}>＋ 新增规则</button>
                  </div>
                  <div className="mcp-rule-list">
                    {accessPolicy.client_overrides.map((rule) => (
                      <AccessRuleRow key={`${rule.source_value}:${rule.subject_type}:${rule.subject_value}`} rule={rule} onChange={(next) => setAccessPolicy(upsertClientRule(accessPolicy, next, rule))} onDelete={() => setAccessPolicy(removeClientRule(accessPolicy, rule))} />
                    ))}
                  </div>
                </section>
                <section className="mcp-access-section">
                  <div className="mcp-access-heading"><h4>工具权限</h4><span>{accessTools.length} 个工具</span></div>
                  <div className="mcp-access-tools">
                    {buildMCPAccessToolGroups(accessTools, accessPolicy).map((tool) => (
                      <article className="mcp-access-tool" key={tool.toolName}>
                        <div className="mcp-access-tool-header">
                          <div className="mcp-access-tool-info"><strong>{tool.toolName}</strong>{tool.stale ? <em>已失效规则</em> : null}<p>{tool.description || "未提供说明"}</p></div>
                          <div className="mcp-access-tool-actions">
                            <EffectSelector value={tool.defaultEffect} onChange={(effect) => setAccessPolicy(upsertToolDefault(accessPolicy, tool.toolName, effect))} />
                            <button type="button" className="mcp-add-rule mcp-access-add-rule" onClick={() => setAccessPolicy(addToolRule(accessPolicy, tool.toolName))}>＋ 新增规则</button>
                          </div>
                        </div>
                        <details><summary>描述与参数</summary><pre className="mcp-tool-schema">{JSON.stringify(tool.inputSchema, null, 2)}</pre></details>
                        {tool.rules.map((rule) => <AccessRuleRow key={`${tool.toolName}:${rule.source_value}:${rule.subject_type}:${rule.subject_value}`} rule={rule} onChange={(next) => setAccessPolicy(upsertToolRule(accessPolicy, next as MCPToolAccessOverride, rule))} onDelete={() => setAccessPolicy(removeToolRule(accessPolicy, rule))} />)}
                      </article>
                    ))}
                  </div>
                </section>
                {accessPolicy.unmanaged_rules_count ? <div className="mcp-access-warning">有 {accessPolicy.unmanaged_rules_count} 条高级规则会被保留，不能在此编辑。</div> : null}
                {accessError ? <div className="mcp-panel-notice error">{accessError}</div> : null}
                <div className="mcp-form-actions"><button type="button" className="mcp-form-cancel" onClick={closeAccessModal}>取消</button><button type="button" className="mcp-form-submit" onClick={() => void saveAccessPolicy()} disabled={accessSaving}>{accessSaving ? "保存中..." : "保存"}</button></div>
              </div>
            )}
          </div>
        </div>
      ) : null}

      {isModalOpen ? (
        <div className="mcp-modal-backdrop" onClick={closeModal}>
          <div className="mcp-modal" onClick={(event) => event.stopPropagation()}>
            <div className="mcp-modal-header">
              <div>
                <h3>{editingClient ? "编辑 MCP" : "新增 MCP"}</h3>
                <p>支持 streamable HTTP、SSE 与 stdio 三种协议接入。</p>
              </div>
              <button
                type="button"
                className="mcp-modal-close"
                onClick={closeModal}
                aria-label="关闭"
                title="关闭"
              >
                ×
              </button>
            </div>

            <div className="mcp-edit-tabs" role="tablist" aria-label="MCP 配置模式">
                <button
                  type="button"
                  className={editMode === "form" ? "active" : ""}
                  onClick={() => switchEditMode("form")}
                  role="tab"
                  aria-selected={editMode === "form"}
                >
                  表单模式
                </button>
                <button
                  type="button"
                  className={editMode === "json" ? "active" : ""}
                  onClick={() => switchEditMode("json")}
                  role="tab"
                  aria-selected={editMode === "json"}
                >
                  JSON 编辑
                </button>
            </div>

            <div className="mcp-form">
              {editMode === "json" ? (
                <div className="mcp-form-field full">
                  <label>完整 MCP 配置</label>
                  <textarea
                    className="mcp-json-editor"
                    value={editJson}
                    onChange={(event) => {
                      setEditJson(event.target.value);
                      setEditJsonError("");
                    }}
                    rows={18}
                    placeholder={'{\n  "mcpServers": {\n    "example-client": {\n      "command": "npx",\n      "args": ["-y", "@example/mcp-server"],\n      "env": {\n        "API_KEY": "<YOUR_API_KEY>"\n      }\n    }\n  }\n}'}
                    spellCheck={false}
                  />
                  <span className="mcp-form-hint">
                    {editingClient
                      ? "MCP Key 仅供查看，保存时不可修改；Header 与 Env 的掩码值保持原样即可保留现有凭证。"
                      : "支持单个 MCP 配置或 QwenPaw 标准 { \"mcpServers\": { ... } } 格式；可一次创建多个配置。"}
                  </span>
                  {editJsonError ? <div className="mcp-panel-notice error">{editJsonError}</div> : null}
                </div>
              ) : (
                <div className="mcp-form-grid">
                <div className="mcp-form-field">
                  <label>MCP Key</label>
                  <input
                    value={form.clientKey}
                    disabled={Boolean(editingClient)}
                    onChange={(event) => setForm((current) => ({ ...current, clientKey: event.target.value }))}
                    placeholder="例如：monitoring_center"
                  />
                  <span className="mcp-form-hint">唯一标识，创建后不建议修改。</span>
                </div>

                <div className="mcp-form-field">
                  <label>MCP 名称</label>
                  <input
                    value={form.name}
                    onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
                    placeholder="例如：监控中心"
                  />
                </div>

                <div className="mcp-form-field full">
                  <label>描述</label>
                  <textarea
                    value={form.description}
                    onChange={(event) =>
                      setForm((current) => ({ ...current, description: event.target.value }))
                    }
                    placeholder="说明这个 MCP 提供的能力边界"
                  />
                </div>

                <div className="mcp-form-field">
                  <label>协议类型</label>
                  <select
                    value={form.transport}
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        transport: event.target.value as McpTransport,
                      }))
                    }
                  >
                    <option value="streamable_http">streamable_http</option>
                    <option value="sse">sse</option>
                    <option value="stdio">stdio</option>
                  </select>
                </div>

                <div className="mcp-form-field">
                  <label>启用状态</label>
                  <label className="mcp-form-switch" htmlFor="mcp-enabled">
                    <input
                      id="mcp-enabled"
                      type="checkbox"
                      checked={form.enabled}
                      onChange={(event) =>
                        setForm((current) => ({ ...current, enabled: event.target.checked }))
                      }
                    />
                    <span className="mcp-form-switch-track" aria-hidden="true" />
                    <span>
                      <strong>{form.enabled ? "已启用" : "已停用"}</strong>
                      <small>{form.enabled ? "保存后可参与工具编排" : "保存后不会被 Agent 调用"}</small>
                    </span>
                  </label>
                </div>

                {form.transport === "stdio" ? (
                  <>
                    <div className="mcp-form-field full">
                      <label>Command</label>
                      <input
                        value={form.command}
                        onChange={(event) =>
                          setForm((current) => ({ ...current, command: event.target.value }))
                        }
                        placeholder="例如：npx"
                      />
                    </div>
                    <div className="mcp-form-field">
                      <label>Args</label>
                      <textarea
                        value={form.argsText}
                        onChange={(event) =>
                          setForm((current) => ({ ...current, argsText: event.target.value }))
                        }
                        placeholder={"每行一个参数\n例如：-y\n@modelcontextprotocol/server-filesystem"}
                      />
                      <span className="mcp-form-hint">按行填写，提交时会转换为 args 数组。</span>
                    </div>
                    <div className="mcp-form-field">
                      <label>Env</label>
                      <textarea
                        value={form.envText}
                        onChange={(event) =>
                          setForm((current) => ({ ...current, envText: event.target.value }))
                        }
                        placeholder={"每行一个 KEY=value\n例如：API_KEY=******"}
                      />
                      <span className="mcp-form-hint">支持保留后端返回的掩码值。</span>
                    </div>
                    <div className="mcp-form-field full">
                      <label>CWD</label>
                      <input
                        value={form.cwd}
                        onChange={(event) => setForm((current) => ({ ...current, cwd: event.target.value }))}
                        placeholder="可选，例如：/Users/me/workspace"
                      />
                    </div>
                  </>
                ) : (
                  <>
                    <div className="mcp-form-field full">
                      <label>URL</label>
                      <input
                        value={form.url}
                        onChange={(event) => setForm((current) => ({ ...current, url: event.target.value }))}
                        placeholder="例如：http://localhost:3001/mcp"
                      />
                    </div>
                    <div className="mcp-form-field full">
                      <label>Headers</label>
                      <textarea
                        value={form.headersText}
                        onChange={(event) =>
                          setForm((current) => ({ ...current, headersText: event.target.value }))
                        }
                        placeholder={"每行一个 KEY=value\n例如：Authorization=Bearer xxx"}
                      />
                      <span className="mcp-form-hint">需要鉴权时可在这里配置请求头。</span>
                    </div>
                  </>
                )}
                </div>
              )}

              <div className="mcp-form-actions">
                <button type="button" className="mcp-form-cancel" onClick={closeModal}>
                  取消
                </button>
                <button
                  type="button"
                  className="mcp-form-submit"
                  disabled={saving}
                  onClick={() => void handleSubmit()}
                >
                  {saving ? "保存中..." : editingClient ? "保存修改" : "创建 MCP"}
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
