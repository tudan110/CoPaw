import { useCallback, useEffect, useRef, useState } from "react";
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

  /* ---- Drag-and-drop reorder state ---- */
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null);

  /* ---- Resize state ---- */
  const [resizing, setResizing] = useState<{
    index: number;
    axis: "width" | "height" | "both";
    startX: number;
    startY: number;
    startWidth: number;
    startHeight: number;
  } | null>(null);
  const gridRef = useRef<HTMLDivElement>(null);

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

  /* ---- Drag-and-drop reorder ---- */
  const handleDragStart = useCallback((e: React.DragEvent, index: number) => {
    setDragIndex(index);
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", String(index));
    // Make the drag image slightly transparent
    if (e.currentTarget instanceof HTMLElement) {
      e.currentTarget.style.opacity = "0.5";
    }
  }, []);

  const handleDragEnd = useCallback((e: React.DragEvent) => {
    if (e.currentTarget instanceof HTMLElement) {
      e.currentTarget.style.opacity = "1";
    }
    setDragIndex(null);
    setDragOverIndex(null);
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent, index: number) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    setDragOverIndex(index);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent, dropIndex: number) => {
    e.preventDefault();
    const fromIndex = dragIndex;
    if (fromIndex === null || fromIndex === dropIndex) {
      setDragIndex(null);
      setDragOverIndex(null);
      return;
    }
    setGridItems((prev) => {
      const items = [...prev];
      const [moved] = items.splice(fromIndex, 1);
      items.splice(dropIndex, 0, moved);
      return items;
    });
    setDragIndex(null);
    setDragOverIndex(null);
  }, [dragIndex]);

  /* ---- Mouse-based resize ---- */
  const handleResizeStart = useCallback(
    (e: React.MouseEvent, index: number, axis: "width" | "height" | "both") => {
      e.preventDefault();
      e.stopPropagation();
      const item = gridItems[index];
      setResizing({
        index,
        axis,
        startX: e.clientX,
        startY: e.clientY,
        startWidth: item.width,
        startHeight: item.height,
      });
    },
    [gridItems],
  );

  useEffect(() => {
    if (!resizing) return;
    document.body.classList.add("dashboard-resizing");
    const handleMouseMove = (e: MouseEvent) => {
      if (!gridRef.current) return;
      // Calculate grid cell width from grid container
      const gridRect = gridRef.current.getBoundingClientRect();
      const gap = 12;
      const cellWidth = (gridRect.width - gap * 3) / 4;
      const cellHeight = 200; // approximate row height

      const deltaX = e.clientX - resizing.startX;
      const deltaY = e.clientY - resizing.startY;

      setGridItems((prev) =>
        prev.map((item, i) => {
          if (i !== resizing.index) return item;
          let newWidth = item.width;
          let newHeight = item.height;
          if (resizing.axis === "width" || resizing.axis === "both") {
            newWidth = Math.max(1, Math.min(4, Math.round(resizing.startWidth + deltaX / cellWidth)));
          }
          if (resizing.axis === "height" || resizing.axis === "both") {
            newHeight = Math.max(1, Math.min(3, Math.round(resizing.startHeight + deltaY / cellHeight)));
          }
          if (newWidth === item.width && newHeight === item.height) return item;
          return { ...item, width: newWidth, height: newHeight };
        }),
      );
    };
    const handleMouseUp = () => {
      setResizing(null);
      document.body.classList.remove("dashboard-resizing");
    };
    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [resizing]);

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
              <div className="dashboard-assembly__grid" ref={gridRef}>
                {gridItems.map((item, idx) => (
                  <div
                    key={`${item.widget_id}-${idx}`}
                    className={`dashboard-assembly__grid-item${
                      dragIndex === idx ? " dragging" : ""
                    }${dragOverIndex === idx && dragIndex !== idx ? " drag-over" : ""}`}
                    style={{
                      gridColumn: `span ${item.width}`,
                      minHeight: `${item.height * 160 + (item.height - 1) * 12}px`,
                    }}
                    draggable
                    onDragStart={(e) => handleDragStart(e, idx)}
                    onDragEnd={handleDragEnd}
                    onDragOver={(e) => handleDragOver(e, idx)}
                    onDrop={(e) => handleDrop(e, idx)}
                  >
                    <div className="dashboard-assembly__grid-item-header">
                      <span className="dashboard-assembly__drag-handle" title="拖动排序">
                        <i className="fas fa-grip-vertical" />
                      </span>
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
                      <button onClick={() => handleResizeItem(idx, "width", -1)} disabled={item.width <= 1} title="缩小宽度">
                        <i className="fas fa-compress-arrows-alt" />
                      </button>
                      <button onClick={() => handleResizeItem(idx, "width", 1)} disabled={item.width >= 4} title="放大宽度">
                        <i className="fas fa-expand-arrows-alt" />
                      </button>
                      <button onClick={() => handleRemoveItem(idx)} className="danger" title="移除">
                        <i className="fas fa-trash" />
                      </button>
                    </div>
                    {/* Resize handles */}
                    <div
                      className="dashboard-assembly__resize-handle-right"
                      onMouseDown={(e) => handleResizeStart(e, idx, "width")}
                    />
                    <div
                      className="dashboard-assembly__resize-handle-bottom"
                      onMouseDown={(e) => handleResizeStart(e, idx, "height")}
                    />
                    <div
                      className="dashboard-assembly__resize-handle-corner"
                      onMouseDown={(e) => handleResizeStart(e, idx, "both")}
                    />
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
