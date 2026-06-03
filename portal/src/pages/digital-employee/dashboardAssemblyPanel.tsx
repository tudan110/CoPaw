import { useCallback, useEffect, useState } from "react";
import "../dashboard-assembly.css";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface WidgetOption {
  id: string;
  title: string;
  description: string;
  type: string;
  tags: string[];
}

interface DashboardItem {
  widget_id: string;
  widget_title: string;
  position_x: number;
  position_y: number;
  width: number;
  height: number;
}

interface DashboardInfo {
  id: string;
  title: string;
  items: DashboardItem[];
}

/* ------------------------------------------------------------------ */
/*  API                                                                */
/* ------------------------------------------------------------------ */

async function fetchWidgets(): Promise<WidgetOption[]> {
  const res = await fetch("/portal-api/app-artifacts/widgets");
  if (!res.ok) throw new Error(`请求失败: ${res.status}`);
  const data = await res.json();
  return data.items || [];
}

async function createDashboard(payload: {
  title: string;
  description: string;
  items: Omit<DashboardItem, "widget_title">[];
  tags: string[];
}): Promise<any> {
  const res = await fetch("/portal-api/app-artifacts/dashboards", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`创建失败: ${res.status}`);
  return res.json();
}

async function updateDashboardItems(dashboardId: string, items: Omit<DashboardItem, "widget_title">[]): Promise<any> {
  const res = await fetch(`/portal-api/app-artifacts/dashboards/${dashboardId}/items`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items }),
  });
  if (!res.ok) throw new Error(`更新失败: ${res.status}`);
  return res.json();
}

async function fetchDashboard(dashboardId: string): Promise<DashboardInfo | null> {
  const res = await fetch(`/portal-api/app-artifacts/dashboards/${dashboardId}`);
  if (!res.ok) return null;
  return res.json();
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export function DashboardAssemblyPanel({
  onBack,
  editDashboardId,
}: {
  onBack?: () => void;
  editDashboardId?: string;
}) {
  /* ---- State ---- */
  const [widgets, setWidgets] = useState<WidgetOption[]>([]);
  const [gridItems, setGridItems] = useState<DashboardItem[]>([]);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [tags, setTags] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [previewMode, setPreviewMode] = useState(false);
  const [loadingWidgets, setLoadingWidgets] = useState(true);
  const [editingDashboardId, setEditingDashboardId] = useState(editDashboardId || "");

  /* ---- Widget size selector for adding ---- */
  const [selectedWidget, setSelectedWidget] = useState<WidgetOption | null>(null);
  const [addWidth, setAddWidth] = useState(2);
  const [addHeight, setAddHeight] = useState(1);

  /* ---- Load data ---- */
  useEffect(() => {
    (async () => {
      setLoadingWidgets(true);
      try {
        const data = await fetchWidgets();
        setWidgets(data);
      } catch (e) {
        setError(e instanceof Error ? e.message : "加载卡片失败");
      } finally {
        setLoadingWidgets(false);
      }
    })();
  }, []);

  useEffect(() => {
    if (!editDashboardId) return;
    (async () => {
      const dashboard = await fetchDashboard(editDashboardId);
      if (dashboard) {
        setTitle(dashboard.title);
        setGridItems(dashboard.items || []);
        setEditingDashboardId(dashboard.id);
      }
    })();
  }, [editDashboardId]);

  /* ---- Add widget to grid ---- */
  const handleAddWidget = useCallback(() => {
    if (!selectedWidget) return;
    // Find next available position
    const maxY = gridItems.reduce((max, item) => Math.max(max, item.position_y + item.height), 0);
    const newItem: DashboardItem = {
      widget_id: selectedWidget.id,
      widget_title: selectedWidget.title,
      position_x: 0,
      position_y: maxY,
      width: addWidth,
      height: addHeight,
    };
    setGridItems((prev) => [...prev, newItem]);
    setSelectedWidget(null);
  }, [selectedWidget, addWidth, addHeight, gridItems]);

  /* ---- Remove widget from grid ---- */
  const handleRemoveItem = useCallback((index: number) => {
    setGridItems((prev) => prev.filter((_, i) => i !== index));
  }, []);

  /* ---- Move item ---- */
  const handleMoveItem = useCallback((index: number, direction: "up" | "down") => {
    setGridItems((prev) => {
      const items = [...prev];
      if (direction === "up" && index > 0) {
        [items[index - 1], items[index]] = [items[index], items[index - 1]];
      } else if (direction === "down" && index < items.length - 1) {
        [items[index], items[index + 1]] = [items[index + 1], items[index]];
      }
      return items;
    });
  }, []);

  /* ---- Resize item ---- */
  const handleResizeItem = useCallback((index: number, field: "width" | "height", delta: number) => {
    setGridItems((prev) =>
      prev.map((item, i) => {
        if (i !== index) return item;
        const newVal = Math.max(1, Math.min(4, item[field] + delta));
        return { ...item, [field]: newVal };
      }),
    );
  }, []);

  /* ---- Save ---- */
  const handleSave = useCallback(async () => {
    if (!title.trim()) {
      setError("请填写仪表盘标题");
      return;
    }
    if (gridItems.length === 0) {
      setError("请至少添加一个卡片");
      return;
    }

    setSaving(true);
    setError("");
    setSuccess("");

    // Recalculate positions based on order
    const positionedItems = gridItems.map((item, idx) => ({
      widget_id: item.widget_id,
      position_x: 0,
      position_y: idx,
      width: item.width,
      height: item.height,
    }));

    try {
      if (editingDashboardId) {
        await updateDashboardItems(editingDashboardId, positionedItems);
        setSuccess("仪表盘已更新！");
      } else {
        const result = await createDashboard({
          title: title.trim(),
          description: description.trim(),
          items: positionedItems,
          tags: tags.split(/[,，\s]+/).map((t) => t.trim()).filter(Boolean),
        });
        setEditingDashboardId(result.id);
        setSuccess("仪表盘已创建！");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }, [title, description, tags, gridItems, editingDashboardId]);

  /* ---- Preview URL ---- */
  const previewUrl = editingDashboardId
    ? `/portal-api/app-artifacts/${editingDashboardId}/preview`
    : "";

  /* ================================================================ */
  /*  Render                                                           */
  /* ================================================================ */

  return (
    <div className="dashboard-assembly">
      {/* ---- Header ---- */}
      <header className="dashboard-assembly__header">
        <div className="dashboard-assembly__header-left">
          {onBack && (
            <button className="dashboard-assembly__back-btn" onClick={onBack} title="返回">
              <i className="fas fa-arrow-left" />
            </button>
          )}
          <h2 className="dashboard-assembly__title">
            <i className="fas fa-th-large" />
            {editingDashboardId ? "编辑仪表盘" : "组装仪表盘"}
          </h2>
        </div>
        <div className="dashboard-assembly__header-right">
          {editingDashboardId && (
            <button
              className={`dashboard-assembly__preview-toggle ${previewMode ? "active" : ""}`}
              onClick={() => setPreviewMode(!previewMode)}
            >
              <i className={`fas ${previewMode ? "fa-edit" : "fa-eye"}`} />
              {previewMode ? "编辑" : "预览"}
            </button>
          )}
          <button
            className="dashboard-assembly__save-btn"
            onClick={() => void handleSave()}
            disabled={saving}
          >
            <i className="fas fa-save" />
            {saving ? "保存中..." : "保存"}
          </button>
        </div>
      </header>

      {error && <div className="dashboard-assembly__notice error">{error}</div>}
      {success && <div className="dashboard-assembly__notice success">{success}</div>}

      {/* ---- Preview mode ---- */}
      {previewMode && previewUrl ? (
        <div className="dashboard-assembly__preview-container">
          <iframe
            src={previewUrl}
            className="dashboard-assembly__preview-iframe"
            sandbox="allow-scripts allow-same-origin"
            title="仪表盘预览"
          />
        </div>
      ) : (
        /* ---- Edit mode ---- */
        <div className="dashboard-assembly__body">
          {/* ---- Left: Config ---- */}
          <section className="dashboard-assembly__config">
            <div className="dashboard-assembly__form">
              <label className="dashboard-assembly__field">
                <span>仪表盘标题 *</span>
                <input
                  type="text"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="如：运维总览大屏"
                  disabled={saving}
                />
              </label>
              <label className="dashboard-assembly__field">
                <span>描述</span>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="仪表盘用途说明"
                  rows={2}
                  disabled={saving}
                />
              </label>
              <label className="dashboard-assembly__field">
                <span>标签</span>
                <input
                  type="text"
                  value={tags}
                  onChange={(e) => setTags(e.target.value)}
                  placeholder="逗号分隔，如：监控, 大屏"
                  disabled={saving}
                />
              </label>
            </div>

            {/* ---- Widget Picker ---- */}
            <div className="dashboard-assembly__widget-picker">
              <h3>📦 可用卡片</h3>
              {loadingWidgets ? (
                <p className="dashboard-assembly__loading">加载中...</p>
              ) : widgets.length === 0 ? (
                <p className="dashboard-assembly__empty-widgets">
                  暂无可用卡片，请先在工作台中发布 widget 类型的应用
                </p>
              ) : (
                <div className="dashboard-assembly__widget-list">
                  {widgets.map((w) => (
                    <div
                      key={w.id}
                      className={`dashboard-assembly__widget-card ${selectedWidget?.id === w.id ? "selected" : ""}`}
                      onClick={() => setSelectedWidget(selectedWidget?.id === w.id ? null : w)}
                    >
                      <span className="dashboard-assembly__widget-icon">
                        {w.type === "widget" ? "🧩" : "🌐"}
                      </span>
                      <div className="dashboard-assembly__widget-info">
                        <strong>{w.title}</strong>
                        {w.description && <small>{w.description.slice(0, 40)}</small>}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {selectedWidget && (
                <div className="dashboard-assembly__add-controls">
                  <span>尺寸：</span>
                  <select value={addWidth} onChange={(e) => setAddWidth(Number(e.target.value))}>
                    <option value={1}>1列</option>
                    <option value={2}>2列</option>
                    <option value={3}>3列</option>
                    <option value={4}>4列</option>
                  </select>
                  <span>×</span>
                  <select value={addHeight} onChange={(e) => setAddHeight(Number(e.target.value))}>
                    <option value={1}>1行</option>
                    <option value={2}>2行</option>
                    <option value={3}>3行</option>
                  </select>
                  <button className="dashboard-assembly__add-btn" onClick={handleAddWidget}>
                    <i className="fas fa-plus" /> 添加
                  </button>
                </div>
              )}
            </div>
          </section>

          {/* ---- Right: Layout preview ---- */}
          <section className="dashboard-assembly__layout">
            <h3>📐 布局预览</h3>
            {gridItems.length === 0 ? (
              <div className="dashboard-assembly__layout-empty">
                <i className="fas fa-th-large" />
                <p>从左侧选择卡片添加到仪表盘</p>
              </div>
            ) : (
              <div className="dashboard-assembly__grid">
                {gridItems.map((item, idx) => (
                  <div
                    key={`${item.widget_id}-${idx}`}
                    className="dashboard-assembly__grid-item"
                    style={{
                      gridColumn: `span ${item.width}`,
                    }}
                  >
                    <div className="dashboard-assembly__grid-item-header">
                      <span className="dashboard-assembly__grid-item-title">
                        {item.widget_title}
                      </span>
                      <span className="dashboard-assembly__grid-item-size">
                        {item.width}×{item.height}
                      </span>
                    </div>
                    <div className="dashboard-assembly__grid-item-preview">
                      <iframe
                        src={`/portal-api/app-artifacts/${item.widget_id}/preview`}
                        className="dashboard-assembly__mini-iframe"
                        sandbox="allow-scripts allow-same-origin"
                        loading="lazy"
                        title={item.widget_title}
                      />
                    </div>
                    <div className="dashboard-assembly__grid-item-actions">
                      <button onClick={() => handleMoveItem(idx, "up")} disabled={idx === 0} title="上移">
                        <i className="fas fa-chevron-up" />
                      </button>
                      <button onClick={() => handleMoveItem(idx, "down")} disabled={idx === gridItems.length - 1} title="下移">
                        <i className="fas fa-chevron-down" />
                      </button>
                      <button onClick={() => handleResizeItem(idx, "width", -1)} disabled={item.width <= 1} title="缩小">
                        <i className="fas fa-compress-arrows-alt" />
                      </button>
                      <button onClick={() => handleResizeItem(idx, "width", 1)} disabled={item.width >= 4} title="放大">
                        <i className="fas fa-expand-arrows-alt" />
                      </button>
                      <button onClick={() => handleRemoveItem(idx)} className="danger" title="移除">
                        <i className="fas fa-trash" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

export default DashboardAssemblyPanel;
