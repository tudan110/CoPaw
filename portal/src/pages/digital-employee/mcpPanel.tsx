import { useCallback, useEffect, useMemo, useState } from "react";

import {
  McpClientCreateRequest,
  McpClientInfo,
  McpClientUpdateRequest,
  McpToolInfo,
  McpTransport,
  importMcpClient,
  mcpApi,
} from "../../api/mcp";
import { type McpImportEntry, parseMcpImportText } from "../../api/mcpImport";
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
  const [selectedClientKey, setSelectedClientKey] = useState<string | null>(null);
  const [tools, setTools] = useState<Record<string, McpToolInfo[]>>({});
  const [toolsLoadingKey, setToolsLoadingKey] = useState<string | null>(null);
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [importText, setImportText] = useState("");
  const [importBusy, setImportBusy] = useState(false);
  const [importError, setImportError] = useState("");

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
    setSelectedClientKey(null);
    setTools({});
    setNotice(null);
    void loadClients();
  }, [agentId, loadClients]);

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

  const selectedTools = selectedClientKey ? tools[selectedClientKey] : undefined;
  const selectedClient = selectedClientKey
    ? clients.find((client) => client.key === selectedClientKey) || null
    : null;

  const openCreateModal = () => {
    setEditingClient(null);
    setForm(EMPTY_FORM);
    setIsModalOpen(true);
  };

  const openEditModal = (client: McpClientInfo) => {
    setEditingClient(client);
    setForm(formatFormState(client));
    setIsModalOpen(true);
  };

  const closeModal = () => {
    if (saving) {
      return;
    }
    setIsModalOpen(false);
    setEditingClient(null);
    setForm(EMPTY_FORM);
  };

  const showTools = async (clientKey: string) => {
    setSelectedClientKey(clientKey);
    if (tools[clientKey]) {
      return;
    }

    setToolsLoadingKey(clientKey);
    try {
      const response = await mcpApi.listTools(clientKey, agentId);
      setTools((current) => ({
        ...current,
        [clientKey]: response,
      }));
    } catch (error) {
      setNotice({
        type: "error",
        message: error instanceof Error ? error.message : "工具列表加载失败",
      });
    } finally {
      setToolsLoadingKey(null);
    }
  };

  const handleSubmit = async () => {
    try {
      setSaving(true);
      const { clientKey, payload } = buildPayload(form);

      if (editingClient) {
        await mcpApi.updateClient(clientKey, payload, agentId);
        setNotice({ type: "success", message: `已更新 MCP：${payload.name}` });
      } else {
        // Domain-checked create: off-domain clients are rejected by the backend.
        await importMcpClient(clientKey, payload as McpClientCreateRequest, agentId);
        setNotice({ type: "success", message: `已新增 MCP：${payload.name}` });
      }

      closeModal();
      await loadClients();
    } catch (error) {
      setNotice({
        type: "error",
        message: error instanceof Error ? error.message : "保存 MCP 失败",
      });
    } finally {
      setSaving(false);
    }
  };

  const openImportModal = () => {
    setImportText("");
    setImportError("");
    setImportModalOpen(true);
  };

  const closeImportModal = () => {
    if (importBusy) {
      return;
    }
    setImportModalOpen(false);
  };

  const handleImportSubmit = async () => {
    let entries: McpImportEntry[];
    try {
      entries = parseMcpImportText(importText);
    } catch (error) {
      setImportError(error instanceof Error ? error.message : "解析 MCP 配置失败");
      return;
    }
    setImportError("");
    setImportBusy(true);
    const created: string[] = [];
    const skipped: string[] = [];
    const rejected: string[] = []; // 领域不符
    const unavailable: string[] = []; // 领域审核未完成 / 不可用，可重试
    const failed: string[] = [];
    for (const entry of entries) {
      try {
        // Domain-checked create — off-domain entries are rejected by the backend.
        await importMcpClient(entry.clientKey, entry.payload, agentId);
        created.push(entry.clientKey);
      } catch (error) {
        const message = error instanceof Error ? error.message : "";
        if (/exist/i.test(message) || message.includes("已存在")) {
          skipped.push(entry.clientKey);
        } else if (
          message.includes("领域审核失败") ||
          message.includes("审核未完成") ||
          message.includes("稍后重试")
        ) {
          unavailable.push(`${entry.clientKey}（${message}）`);
        } else if (
          message.includes("当前系统仅支持") ||
          message.includes("加入白名单")
        ) {
          rejected.push(`${entry.clientKey}（${message}）`);
        } else {
          failed.push(`${entry.clientKey}（${message || "未知错误"}）`);
        }
      }
    }
    setImportBusy(false);
    setImportModalOpen(false);
    await loadClients();
    const summary: string[] = [];
    if (created.length) {
      summary.push(`新增 ${created.length} 个`);
    }
    if (skipped.length) {
      summary.push(`跳过 ${skipped.length} 个（已存在）`);
    }
    if (rejected.length) {
      summary.push(`领域不符 ${rejected.length} 个`);
    }
    if (unavailable.length) {
      summary.push(`审核未完成 ${unavailable.length} 个（可重试）`);
    }
    if (failed.length) {
      summary.push(`失败 ${failed.length} 个`);
    }
    const details = [...rejected, ...unavailable, ...failed];
    setNotice({
      type: failed.length || rejected.length || unavailable.length ? "error" : "success",
      message:
        `MCP 导入完成：${summary.join("，") || "无变更"}` +
        (details.length ? `；${details.join("；")}` : ""),
    });
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
      if (selectedClientKey === client.key) {
        setSelectedClientKey(null);
      }
      await loadClients();
    } catch (error) {
      setNotice({
        type: "error",
        message: error instanceof Error ? error.message : "删除 MCP 失败",
      });
    }
  };

  const selectedToolsCount = selectedClientKey ? tools[selectedClientKey]?.length : 0;

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
          <button type="button" className="portal-model-btn" onClick={openImportModal}>
            <i className="fas fa-file-import" />
            JSON 导入
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
              const toolsCount = tools[client.key]?.length;
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
                    <button type="button" className="mcp-card-action" onClick={() => void showTools(client.key)}>
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

        {selectedClient ? (
          <section className="mcp-tool-panel">
            <div className="mcp-tool-header">
              <div>
                <h3>{selectedClient.name} · 工具能力</h3>
                <p>
                  协议：{selectedClient.transport} · 已读取 {selectedToolsCount || 0} 个工具
                </p>
              </div>
              <div className="mcp-panel-actions">
                <button
                  type="button"
                  className="mcp-panel-refresh"
                  onClick={() => {
                    setTools((current) => {
                      const next = { ...current };
                      delete next[selectedClient.key];
                      return next;
                    });
                    void showTools(selectedClient.key);
                  }}
                >
                  <i className="ri-refresh-line" />
                  重新读取
                </button>
              </div>
            </div>
            {toolsLoadingKey === selectedClient.key && !selectedTools ? (
              <div className="mcp-loading">
                <i className="ri-loader-4-line ri-spin" />
                正在读取工具列表...
              </div>
            ) : selectedTools?.length ? (
              <div className="mcp-tool-list">
                {selectedTools.map((tool) => (
                  <div key={tool.name} className="mcp-tool-item">
                    <strong>{tool.name}</strong>
                    <p>{tool.description || "未提供说明"}</p>
                    <pre className="mcp-tool-schema">
                      {JSON.stringify(tool.input_schema || {}, null, 2)}
                    </pre>
                  </div>
                ))}
              </div>
            ) : (
              <div className="mcp-empty" style={{ minHeight: 160 }}>
                <i className="ri-tools-line" />
                <strong>没有读取到工具</strong>
                <span>若服务已启用但仍为空，请检查 MCP 服务本身是否暴露了 tools/list。</span>
              </div>
            )}
          </section>
        ) : null}
      </div>

      {isModalOpen ? (
        <div className="mcp-modal-backdrop" onClick={closeModal}>
          <div className="mcp-modal" onClick={(event) => event.stopPropagation()}>
            <div className="mcp-modal-header">
              <div>
                <h3>{editingClient ? "编辑 MCP" : "新增 MCP"}</h3>
                <p>支持 streamable HTTP、SSE 与 stdio 三种协议接入。</p>
              </div>
              <button type="button" className="mcp-modal-close" onClick={closeModal}>
                <i className="ri-close-line" />
              </button>
            </div>

            <div className="mcp-form">
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
                  <div className="mcp-form-switch">
                    <input
                      id="mcp-enabled"
                      type="checkbox"
                      checked={form.enabled}
                      onChange={(event) =>
                        setForm((current) => ({ ...current, enabled: event.target.checked }))
                      }
                    />
                    <label htmlFor="mcp-enabled" style={{ margin: 0 }}>
                      创建后立即可用
                    </label>
                  </div>
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

      {importModalOpen ? (
        <div className="mcp-modal-backdrop" onClick={closeImportModal}>
          <div className="mcp-modal" onClick={(event) => event.stopPropagation()}>
            <div className="mcp-modal-header">
              <div>
                <h3>JSON 批量导入 MCP</h3>
                <p>
                  支持标准 <code>{"{ \"mcpServers\": { ... } }"}</code> 或直接的 <code>{"{ \"客户端名\": { ... } }"}</code> 映射；
                  会逐条创建到网关入口 Agent，并先做领域校验（非网管相关的会被拒绝）。
                </p>
              </div>
              <button type="button" className="mcp-modal-close" onClick={closeImportModal}>
                <i className="ri-close-line" />
              </button>
            </div>

            <div className="mcp-form">
              <div className="mcp-form-field full">
                <label>MCP 配置 JSON</label>
                <textarea
                  value={importText}
                  onChange={(event) => {
                    setImportText(event.target.value);
                    setImportError("");
                  }}
                  rows={16}
                  placeholder={
                    '{\n  "mcpServers": {\n    "filesystem": {\n      "command": "npx",\n      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/data"]\n    },\n    "monitoring": {\n      "transport": "streamable_http",\n      "url": "http://localhost:3001/mcp",\n      "headers": { "Authorization": "Bearer xxx" }\n    }\n  }\n}'
                  }
                />
                <span className="mcp-form-hint">
                  没写 transport 时：含 command 视为 stdio，含 url 视为 streamable_http；已存在的 Key 会跳过。
                </span>
              </div>

              {importError ? <div className="mcp-panel-notice error">{importError}</div> : null}

              <div className="mcp-form-actions">
                <button type="button" className="mcp-form-cancel" onClick={closeImportModal}>
                  取消
                </button>
                <button
                  type="button"
                  className="mcp-form-submit"
                  disabled={importBusy}
                  onClick={() => void handleImportSubmit()}
                >
                  {importBusy ? "导入中..." : "解析并导入"}
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
