import { useEffect, useState } from "react";
import "./proxy-datasources.css";

interface DatasourceSummary {
  id: string;
  name: string;
  description: string;
  url_template: string;
  method: string;
  default_params: Record<string, unknown>;
  timeout: number;
  enabled: boolean;
}

interface DatasourceForm {
  id: string;
  name: string;
  description: string;
  url_template: string;
  method: string;
  headers: Record<string, string>;
  default_params: Record<string, unknown>;
  body_template: unknown;
  timeout: number;
  enabled: boolean;
}

const METHOD_OPTIONS = ["GET", "POST", "PUT", "DELETE"];

const emptyForm: DatasourceForm = {
  id: "",
  name: "",
  description: "",
  url_template: "",
  method: "GET",
  headers: {},
  default_params: {},
  body_template: null,
  timeout: 15,
  enabled: true,
};

async function fetchDatasources(): Promise<DatasourceSummary[]> {
  const res = await fetch("/portal-api/proxy/datasources");
  if (!res.ok) throw new Error(`请求失败: ${res.status}`);
  const data = await res.json();
  return data ?? [];
}

async function createDatasource(form: DatasourceForm): Promise<DatasourceSummary> {
  const res = await fetch("/portal-api/proxy/datasources", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(form),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail ?? `创建失败: ${res.status}`);
  }
  return res.json();
}

async function updateDatasource(id: string, form: DatasourceForm): Promise<DatasourceSummary> {
  const res = await fetch(`/portal-api/proxy/datasources/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(form),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail ?? `更新失败: ${res.status}`);
  }
  return res.json();
}

async function deleteDatasource(id: string): Promise<void> {
  const res = await fetch(`/portal-api/proxy/datasources/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`删除失败: ${res.status}`);
}

async function testDatasource(id: string): Promise<{ status: number; body: string }> {
  const res = await fetch(`/portal-api/proxy/${id}`, { method: "GET" });
  const body = await res.text();
  return { status: res.status, body: body.slice(0, 500) };
}

export function ProxyDatasourcesPanel() {
  const [items, setItems] = useState<DatasourceSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // form state
  const [editing, setEditing] = useState<DatasourceForm | null>(null);
  const [editId, setEditId] = useState<string | null>(null); // original id for update
  const [formError, setFormError] = useState("");

  // test state
  const [testResult, setTestResult] = useState<{ status: number; body: string } | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);

  const loadData = async () => {
    setLoading(true);
    setError("");
    try {
      setItems(await fetchDatasources());
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void loadData(); }, []);

  const handleCreate = () => {
    setEditing({ ...emptyForm });
    setEditId(null);
    setFormError("");
    setTestResult(null);
  };

  const handleEdit = (item: DatasourceSummary) => {
    // fetch full config (with headers) via a separate call
    // For simplicity, we load the summary; headers need to be re-entered on edit
    setEditing({
      ...emptyForm,
      id: item.id,
      name: item.name,
      description: item.description,
      url_template: item.url_template,
      method: item.method,
      headers: {},
      default_params: item.default_params,
      body_template: null,
      timeout: item.timeout,
      enabled: item.enabled,
    });
    setEditId(item.id);
    setFormError("");
    setTestResult(null);
  };

  const handleSave = async () => {
    if (!editing) return;
    setFormError("");
    try {
      if (editId) {
        await updateDatasource(editId, editing);
      } else {
        await createDatasource(editing);
      }
      setEditing(null);
      setEditId(null);
      void loadData();
    } catch (e) {
      setFormError(e instanceof Error ? e.message : "保存失败");
    }
  };

  const handleDelete = async (id: string, name: string) => {
    if (!confirm(`确定要删除「${name}」吗？`)) return;
    try {
      await deleteDatasource(id);
      void loadData();
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除失败");
    }
  };

  const handleTest = async (id: string) => {
    setTestingId(id);
    setTestResult(null);
    try {
      setTestResult(await testDatasource(id));
    } catch (e) {
      setTestResult({ status: 0, body: e instanceof Error ? e.message : "测试失败" });
    } finally {
      setTestingId(null);
    }
  };

  const handleToggleEnabled = async (item: DatasourceSummary) => {
    const form: DatasourceForm = {
      ...emptyForm,
      id: item.id,
      name: item.name,
      description: item.description,
      url_template: item.url_template,
      method: item.method,
      headers: {},
      default_params: item.default_params,
      body_template: null,
      timeout: item.timeout,
      enabled: !item.enabled,
    };
    try {
      await updateDatasource(item.id, form);
      void loadData();
    } catch (e) {
      setError(e instanceof Error ? e.message : "更新失败");
    }
  };

  // dynamic header entry for headers dict
  const [newHeaderKey, setNewHeaderKey] = useState("");
  const [newHeaderVal, setNewHeaderVal] = useState("");

  const addHeader = () => {
    if (!editing || !newHeaderKey.trim()) return;
    setEditing({
      ...editing,
      headers: { ...editing.headers, [newHeaderKey.trim()]: newHeaderVal },
    });
    setNewHeaderKey("");
    setNewHeaderVal("");
  };

  const removeHeader = (key: string) => {
    if (!editing) return;
    const next = { ...editing.headers };
    delete next[key];
    setEditing({ ...editing, headers: next });
  };

  return (
    <div className="proxy-datasources-panel">
      <div className="portal-model-page-header">
        <div className="portal-model-page-title">
          外部数据源 <small>配置外部 API 接口供应用调用</small>
        </div>
        <button className="proxy-datasources-create-btn" onClick={handleCreate}>
          <i className="fas fa-plus" /> 新增数据源
        </button>
      </div>

      {error && <div className="proxy-datasources-notice error">{error}</div>}

      {/* ─── Form ─── */}
      {editing && (
        <div className="proxy-datasources-form">
          <h3>{editId ? `编辑 · ${editId}` : "新增数据源"}</h3>
          {formError && <div className="proxy-datasources-notice error">{formError}</div>}

          <label>
            <span>ID</span>
            <input
              value={editing.id}
              onChange={(e) => setEditing({ ...editing, id: e.target.value })}
              disabled={!!editId}
              placeholder="唯一标识,如 alarm-api"
            />
          </label>
          <label>
            <span>名称</span>
            <input
              value={editing.name}
              onChange={(e) => setEditing({ ...editing, name: e.target.value })}
              placeholder="告警实时数据"
            />
          </label>
          <label>
            <span>描述</span>
            <input
              value={editing.description}
              onChange={(e) => setEditing({ ...editing, description: e.target.value })}
              placeholder="获取系统实时告警列表"
            />
          </label>
          <label>
            <span>URL 模板</span>
            <input
              value={editing.url_template}
              onChange={(e) => setEditing({ ...editing, url_template: e.target.value })}
              placeholder="https://api.example.com/alarms?limit={limit}"
            />
          </label>
          <label>
            <span>方法</span>
            <select
              value={editing.method}
              onChange={(e) => setEditing({ ...editing, method: e.target.value })}
            >
              {METHOD_OPTIONS.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </label>
          <label>
            <span>超时(秒)</span>
            <input
              type="number"
              value={editing.timeout}
              onChange={(e) => setEditing({ ...editing, timeout: Number(e.target.value) })}
              min={1}
              max={120}
            />
          </label>

          {/* Headers */}
          <div className="proxy-datasources-form-section">
            <span className="proxy-datasources-form-section-title">请求头 (鉴权信息)</span>
            {Object.entries(editing.headers).map(([k, v]) => (
              <div key={k} className="proxy-datasources-header-row">
                <span className="proxy-datasources-header-key">{k}</span>
                <span className="proxy-datasources-header-val">
                  {k.toLowerCase().includes("auth") || k.toLowerCase().includes("token")
                    ? "••••••••"
                    : v}
                </span>
                <button
                  className="proxy-datasources-header-remove"
                  onClick={() => removeHeader(k)}
                  title="移除"
                >
                  ×
                </button>
              </div>
            ))}
            <div className="proxy-datasources-header-row add">
              <input
                value={newHeaderKey}
                onChange={(e) => setNewHeaderKey(e.target.value)}
                placeholder="Header 名称"
              />
              <input
                value={newHeaderVal}
                onChange={(e) => setNewHeaderVal(e.target.value)}
                placeholder="Header 值"
              />
              <button onClick={addHeader} title="添加">
                <i className="fas fa-plus" />
              </button>
            </div>
          </div>

          <div className="proxy-datasources-form-actions">
            <button className="proxy-datasources-btn-save" onClick={handleSave}>
              保存
            </button>
            <button
              className="proxy-datasources-btn-cancel"
              onClick={() => { setEditing(null); setEditId(null); setFormError(""); }}
            >
              取消
            </button>
          </div>
        </div>
      )}

      {/* ─── List ─── */}
      <div className="proxy-datasources-content">
        {loading ? (
          <div className="proxy-datasources-empty">
            <span className="proxy-datasources-spinner" />
            <p>正在加载...</p>
          </div>
        ) : !items.length ? (
          <div className="proxy-datasources-empty">
            <span className="proxy-datasources-empty-icon">🔌</span>
            <p>暂无数据源配置</p>
            <p className="proxy-datasources-empty-hint">点击「新增数据源」添加外部 API 接口</p>
          </div>
        ) : (
          <div className="proxy-datasources-grid">
            {items.map((item) => (
              <article key={item.id} className={`proxy-datasources-card ${item.enabled ? "" : "disabled"}`}>
                <div className="proxy-datasources-card-header">
                  <span className="proxy-datasources-card-icon">🔌</span>
                  <div className="proxy-datasources-card-title-group">
                    <h3>{item.name}</h3>
                    <span className="proxy-datasources-card-method">{item.method}</span>
                    {!item.enabled && <span className="proxy-datasources-card-badge">已禁用</span>}
                  </div>
                </div>
                {item.description && (
                  <p className="proxy-datasources-card-desc">{item.description}</p>
                )}
                <div className="proxy-datasources-card-url">{item.url_template}</div>
                <div className="proxy-datasources-card-footer">
                  <span className="proxy-datasources-card-meta">
                    超时 {item.timeout}s · ID: {item.id}
                  </span>
                  <div className="proxy-datasources-card-actions">
                    <button
                      className="proxy-datasources-btn-toggle"
                      onClick={() => handleToggleEnabled(item)}
                      title={item.enabled ? "禁用" : "启用"}
                    >
                      <i className={`fas ${item.enabled ? "fa-toggle-on" : "fa-toggle-off"}`} />
                    </button>
                    <button
                      className="proxy-datasources-btn-test"
                      onClick={() => handleTest(item.id)}
                      title="测试连接"
                      disabled={testingId === item.id}
                    >
                      <i className="fas fa-bolt" />
                    </button>
                    <button
                      className="proxy-datasources-btn-edit-card"
                      onClick={() => handleEdit(item)}
                      title="编辑"
                    >
                      <i className="fas fa-pen" />
                    </button>
                    <button
                      className="proxy-datasources-btn-delete-card"
                      onClick={() => handleDelete(item.id, item.name)}
                      title="删除"
                    >
                      <i className="fas fa-trash" />
                    </button>
                  </div>
                </div>
              </article>
            ))}
          </div>
        )}

        {/* ─── Test result ─── */}
        {testResult && (
          <div className="proxy-datasources-test-result">
            <div className="proxy-datasources-test-header">
              测试结果 · HTTP {testResult.status}
              <button onClick={() => setTestResult(null)} title="关闭">×</button>
            </div>
            <pre className="proxy-datasources-test-body">{testResult.body}</pre>
          </div>
        )}
      </div>
    </div>
  );
}

export default ProxyDatasourcesPanel;