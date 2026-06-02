import { useEffect, useState } from "react";
import "./app-artifacts.css";

interface AppArtifact {
  id: string;
  title: string;
  description: string;
  type: "app" | "widget" | "dashboard";
  status: string;
  author: string;
  url: string;
  tags: string[];
  version: number;
  created_at: string;
  updated_at: string;
}

interface ListResponse {
  items: AppArtifact[];
  total: number;
  page: number;
  page_size: number;
}

const TYPE_LABELS: Record<string, string> = {
  app: "应用",
  widget: "卡片",
  dashboard: "仪表盘",
};

const TYPE_ICONS: Record<string, string> = {
  app: "🌐",
  widget: "🧩",
  dashboard: "📊",
};

async function fetchArtifacts(params: {
  type?: string;
  search?: string;
  page?: number;
}): Promise<ListResponse> {
  const searchParams = new URLSearchParams();
  if (params.type) searchParams.set("type", params.type);
  if (params.search) searchParams.set("search", params.search);
  if (params.page) searchParams.set("page", String(params.page));
  searchParams.set("status", "published");

  const response = await fetch(`/portal-api/app-artifacts?${searchParams.toString()}`);
  if (!response.ok) {
    throw new Error(`请求失败: ${response.status}`);
  }
  return response.json();
}

async function deleteArtifact(id: string): Promise<void> {
  const response = await fetch(`/portal-api/app-artifacts/${id}`, { method: "DELETE" });
  if (!response.ok) {
    throw new Error(`删除失败: ${response.status}`);
  }
}

export function AppArtifactsPanel({ onOpenWorkbench, onEditApp }: {
  onOpenWorkbench?: () => void;
  onEditApp?: (appId: string) => void;
}) {
  const [items, setItems] = useState<AppArtifact[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filterType, setFilterType] = useState<string>("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);

  const loadData = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await fetchArtifacts({ type: filterType || undefined, search: search || undefined, page });
      setItems(data.items);
      setTotal(data.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadData();
  }, [filterType, page]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    void loadData();
  };

  const handleDelete = async (id: string, title: string) => {
    if (!confirm(`确定要删除「${title}」吗？`)) return;
    try {
      await deleteArtifact(id);
      void loadData();
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除失败");
    }
  };

  const handleOpen = (artifact: AppArtifact) => {
    window.open(`/portal-api/app-artifacts/${artifact.id}/preview`, "_blank");
  };

  const totalPages = Math.ceil(total / 20);

  return (
    <div className="app-artifacts-panel">
      <div className="portal-model-page-header">
        <div className="portal-model-page-title">
          成果应用 <small>AI 生成的 HTML 应用与卡片</small>
        </div>
        {onOpenWorkbench && (
          <button className="app-artifacts-create-btn" onClick={onOpenWorkbench}>
            <i className="fas fa-wand-magic-sparkles" /> 新建应用
          </button>
        )}
      </div>

      <div className="app-artifacts-toolbar">
        <div className="app-artifacts-filters">
          <button
            className={`app-artifacts-filter-btn ${filterType === "" ? "active" : ""}`}
            onClick={() => { setFilterType(""); setPage(1); }}
          >
            全部
          </button>
          <button
            className={`app-artifacts-filter-btn ${filterType === "app" ? "active" : ""}`}
            onClick={() => { setFilterType("app"); setPage(1); }}
          >
            🌐 应用
          </button>
          <button
            className={`app-artifacts-filter-btn ${filterType === "widget" ? "active" : ""}`}
            onClick={() => { setFilterType("widget"); setPage(1); }}
          >
            🧩 卡片
          </button>
          <button
            className={`app-artifacts-filter-btn ${filterType === "dashboard" ? "active" : ""}`}
            onClick={() => { setFilterType("dashboard"); setPage(1); }}
          >
            📊 仪表盘
          </button>
        </div>
        <form className="app-artifacts-search" onSubmit={handleSearch}>
          <input
            type="text"
            placeholder="搜索应用名称..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <button type="submit">搜索</button>
        </form>
      </div>

      {error && <div className="app-artifacts-notice error">{error}</div>}

      <div className="app-artifacts-content">
        {loading ? (
          <div className="app-artifacts-empty">
            <span className="app-artifacts-spinner" />
            <p>正在加载...</p>
          </div>
        ) : !items.length ? (
          <div className="app-artifacts-empty">
            <span className="app-artifacts-empty-icon">📭</span>
            <p>暂无已发布的成果应用</p>
            <p className="app-artifacts-empty-hint">在对话中让 AI 帮你开发 HTML 应用，发布后将展示在这里</p>
          </div>
        ) : (
          <div className="app-artifacts-grid">
            {items.map((item) => (
              <article key={item.id} className="app-artifacts-card">
                <div className="app-artifacts-card-header">
                  <span className="app-artifacts-card-icon">
                    {TYPE_ICONS[item.type] || "🌐"}
                  </span>
                  <div className="app-artifacts-card-title-group">
                    <h3>{item.title}</h3>
                    <span className="app-artifacts-card-type">
                      {TYPE_LABELS[item.type] || item.type}
                    </span>
                  </div>
                </div>
                {item.description && (
                  <p className="app-artifacts-card-desc">{item.description}</p>
                )}
                {item.tags.length > 0 && (
                  <div className="app-artifacts-card-tags">
                    {item.tags.map((tag) => (
                      <span key={tag} className="app-artifacts-tag">{tag}</span>
                    ))}
                  </div>
                )}
                <div className="app-artifacts-card-footer">
                  <span className="app-artifacts-card-meta">
                    v{item.version} · {item.updated_at.slice(0, 10)}
                  </span>
                  <div className="app-artifacts-card-actions">
                    <button
                      className="app-artifacts-btn-open"
                      onClick={() => handleOpen(item)}
                      title="在新标签页打开"
                    >
                      打开
                    </button>
                    {onEditApp && (
                      <button
                        className="app-artifacts-btn-edit"
                        onClick={() => onEditApp(item.id)}
                        title="编辑应用"
                      >
                        编辑
                      </button>
                    )}
                    <button
                      className="app-artifacts-btn-delete"
                      onClick={() => handleDelete(item.id, item.title)}
                      title="删除应用"
                    >
                      删除
                    </button>
                  </div>
                </div>
              </article>
            ))}
          </div>
        )}

        {totalPages > 1 && (
          <div className="app-artifacts-pagination">
            <button disabled={page <= 1} onClick={() => setPage(page - 1)}>
              上一页
            </button>
            <span>{page} / {totalPages}</span>
            <button disabled={page >= totalPages} onClick={() => setPage(page + 1)}>
              下一页
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export default AppArtifactsPanel;
