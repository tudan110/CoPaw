import { useCallback, useEffect, useMemo, useState } from "react";
import {
  listAlarmRegistryRecords,
  updateAlarmRegistryStatus,
  getAlarmRegistryStats,
  exportAlarmRegistryRecords,
  type AlarmRegistryRecord,
  type AlarmRegistryStatsResponse,
} from "../../api/alarmRegistry";
import "./alarmRegistryPanel.css";

type AlarmRegistryPanelProps = {
  pageTheme: "light" | "dark";
  onOpenChat?: (chatId: string) => void;
};

type StatusFilter = "all" | "active" | "resolved" | "ignored";

const STATUS_LABELS: Record<string, string> = {
  new: "新建",
  taken_over: "已接管",
  analyzing: "分析中",
  analyzed: "已分析",
  manual_pending: "人工待处理",
  manual_recovered: "人工已恢复",
  manual_unrecovered: "人工未恢复",
  manual_unknown: "人工未知",
  resolved: "已处理",
  ignored: "已忽略",
};

const STATUS_TONES: Record<string, string> = {
  new: "blue",
  taken_over: "amber",
  analyzing: "amber",
  analyzed: "cyan",
  manual_pending: "amber",
  manual_recovered: "green",
  manual_unrecovered: "red",
  manual_unknown: "slate",
  resolved: "green",
  ignored: "slate",
};

const FILTER_TO_STATUSES: Record<StatusFilter, string> = {
  all: "",
  active: "new,taken_over,analyzing,analyzed,manual_pending",
  resolved: "manual_recovered,resolved",
  ignored: "manual_unrecovered,manual_unknown,ignored",
};

function formatTime(iso: string) {
  if (!iso) return "--";
  // If already in "YYYY-MM-DD HH:mm:ss" format, return as-is
  if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(iso)) return iso;
  try {
    const d = new Date(iso);
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  } catch {
    return iso;
  }
}

export function AlarmRegistryPanel({ pageTheme, onOpenChat }: AlarmRegistryPanelProps) {
  const [records, setRecords] = useState<AlarmRegistryRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [stats, setStats] = useState<AlarmRegistryStatsResponse | null>(null);
  const [updatingId, setUpdatingId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [jumpInput, setJumpInput] = useState("");

  const fetchRecords = useCallback(async (opts?: { p?: number; ps?: number; s?: string; f?: StatusFilter }) => {
    setLoading(true);
    setError("");
    try {
      const currentPage = opts?.p ?? page;
      const currentPageSize = opts?.ps ?? pageSize;
      const currentSearch = opts?.s ?? search;
      const currentFilter = opts?.f ?? statusFilter;
      const res = await listAlarmRegistryRecords({
        page: currentPage,
        pageSize: currentPageSize,
        search: currentSearch,
        status: FILTER_TO_STATUSES[currentFilter],
      });
      setRecords(res.items);
      setTotal(res.total);
      setTotalPages(res.totalPages);
    } catch (err: any) {
      setError(err?.message || "加载失败");
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, search, statusFilter]);

  const fetchStats = useCallback(async () => {
    try {
      const res = await getAlarmRegistryStats();
      setStats(res);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    void fetchRecords();
    void fetchStats();
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  const handleFilterChange = (f: StatusFilter) => {
    setStatusFilter(f);
    setPage(1);
    void fetchRecords({ p: 1, f });
  };

  const handleSearch = () => {
    setSearch(searchInput);
    setPage(1);
    void fetchRecords({ p: 1, s: searchInput });
  };

  const handlePageChange = (p: number) => {
    setPage(p);
    void fetchRecords({ p });
  };

  const handlePageSizeChange = (ps: number) => {
    setPageSize(ps);
    setPage(1);
    void fetchRecords({ p: 1, ps });
  };

  const handleJump = () => {
    const target = parseInt(jumpInput, 10);
    if (!isNaN(target) && target >= 1 && target <= totalPages) {
      handlePageChange(target);
    }
    setJumpInput("");
  };

  const handleStatusUpdate = async (alarmId: string, newStatus: string) => {
    setUpdatingId(alarmId);
    try {
      await updateAlarmRegistryStatus(alarmId, newStatus);
      void fetchRecords();
      void fetchStats();
    } catch (err: any) {
      setError(err?.message || "状态更新失败");
    } finally {
      setUpdatingId(null);
    }
  };

  const handleExport = async () => {
    try {
      const data = await exportAlarmRegistryRecords({
        status: FILTER_TO_STATUSES[statusFilter],
      });
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `alarm_registry_export_${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err: any) {
      setError(err?.message || "导出失败");
    }
  };

  const statsBar = useMemo(() => {
    if (!stats) return null;
    const activeCount =
      (stats.byStatus["new"] || 0) +
      (stats.byStatus["taken_over"] || 0) +
      (stats.byStatus["analyzing"] || 0) +
      (stats.byStatus["manual_pending"] || 0);
    const analyzedCount =
      (stats.byStatus["analyzed"] || 0);
    const resolvedCount =
      (stats.byStatus["manual_recovered"] || 0) +
      (stats.byStatus["resolved"] || 0);
    const ignoredCount =
      (stats.byStatus["manual_unrecovered"] || 0) +
      (stats.byStatus["manual_unknown"] || 0) +
      (stats.byStatus["ignored"] || 0);
    return { total: stats.total, activeCount, analyzedCount, resolvedCount, ignoredCount };
  }, [stats]);

  return (
    <div className="alarm-registry-page">
      <div className="portal-model-page-header">
        <div className="portal-model-page-title">
          告警处理台账 <small>全部告警处置状态一览</small>
        </div>
      </div>

      {statsBar && (
        <div className="alarm-registry-stats-bar">
          <span className="alarm-registry-stat">
            <strong>{statsBar.total}</strong> 总计
          </span>
          <span className="alarm-registry-stat tone-amber">
            <strong>{statsBar.activeCount}</strong> 进行中
          </span>
          <span className="alarm-registry-stat tone-cyan">
            <strong>{statsBar.analyzedCount}</strong> 已分析
          </span>
          <span className="alarm-registry-stat tone-green">
            <strong>{statsBar.resolvedCount}</strong> 已处理
          </span>
          <span className="alarm-registry-stat tone-slate">
            <strong>{statsBar.ignoredCount}</strong> 已忽略/未恢复
          </span>
        </div>
      )}

      <div className="alarm-registry-toolbar">
        <div className="alarm-registry-filter-tabs">
          {(["all", "active", "resolved", "ignored"] as StatusFilter[]).map((f) => (
            <button
              key={f}
              className={statusFilter === f ? "alarm-registry-tab active" : "alarm-registry-tab"}
              onClick={() => handleFilterChange(f)}
            >
              {f === "all" ? "全部" : f === "active" ? "进行中" : f === "resolved" ? "已处理" : "已忽略"}
            </button>
          ))}
        </div>
        <div className="alarm-registry-search-group">
          <input
            type="text"
            className="alarm-registry-search-input"
            placeholder="搜索标题/设备/IP/告警ID"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") handleSearch(); }}
          />
          <button className="portal-model-btn alarm-registry-btn" onClick={handleSearch} disabled={loading}>
            <i className={`fas ${loading ? "fa-spinner fa-spin" : "fa-search"}`} />
          </button>
          {/* <button className="portal-model-btn alarm-registry-btn" onClick={handleExport} title="导出">
            <i className="fas fa-download" />
          </button> */}
          <button
            className="portal-model-btn alarm-registry-btn"
            onClick={() => { void fetchRecords(); void fetchStats(); }}
            disabled={loading}
            title="刷新"
          >
            <i className={`fas ${loading ? "fa-spinner fa-spin" : "fa-sync-alt"}`} />
          </button>
        </div>
      </div>

      {error && <div className="alarm-registry-error">{error}</div>}

      <div className="alarm-registry-table-wrapper">
        <table className="alarm-registry-table">
          <thead>
            <tr>
              <th>告警标题</th>
              <th>资源名称</th>
              <th>IP</th>
              <th>状态</th>
              <th>告警时间</th>
              <th>处理时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {records.length === 0 && !loading && (
              <tr>
                <td colSpan={7} className="alarm-registry-empty">
                  暂无数据
                </td>
              </tr>
            )}
            {records.map((record) => (
              <tr key={record.alarmId} className={updatingId === record.alarmId ? "updating" : ""}>
                <td className="alarm-registry-cell-title" title={record.visibleContent || record.title}>
                  {record.title || record.alarmId}
                </td>
                <td title={record.deviceName || ""}>{record.deviceName || "--"}</td>
                <td>{record.manageIp || "--"}</td>
                <td>
                  <span className={`alarm-registry-status-badge tone-${STATUS_TONES[record.status] || "slate"}`}>
                    {STATUS_LABELS[record.status] || record.status}
                  </span>
                </td>
                <td>{formatTime(record.eventTime)}</td>
                <td>{formatTime(record.handledAt || record.takenOverAt || record.updatedAt)}</td>
                <td className="alarm-registry-cell-actions">
                  {record.status !== "resolved" && (
                    <button
                      className="alarm-registry-action-btn tone-green"
                      title="标记为已处理"
                      disabled={updatingId === record.alarmId}
                      onClick={() => handleStatusUpdate(record.alarmId, "resolved")}
                    >
                      <i className="fas fa-check" />
                    </button>
                  )}
                  {record.status !== "ignored" && record.status !== "resolved" && record.status !== "analyzed" && (
                    <button
                      className="alarm-registry-action-btn tone-slate"
                      title="忽略"
                      disabled={updatingId === record.alarmId}
                      onClick={() => handleStatusUpdate(record.alarmId, "ignored")}
                    >
                      <i className="fas fa-eye-slash" />
                    </button>
                  )}
                  {record.chatId && onOpenChat && (
                    <button
                      className="alarm-registry-action-btn tone-blue"
                      title="查看关联对话"
                      onClick={() => onOpenChat(record.chatId)}
                    >
                      <i className="fas fa-comments" />
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {totalPages >= 1 && (
        <div className="alarm-registry-pagination">
          <span className="alarm-registry-pagination-total">共 {total} 条</span>
          <button disabled={page <= 1} onClick={() => handlePageChange(page - 1)}>&lt;</button>
          {(() => {
            const pages: (number | "...")[] = [];
            if (totalPages <= 7) {
              for (let i = 1; i <= totalPages; i++) pages.push(i);
            } else {
              pages.push(1);
              if (page > 4) pages.push("...");
              const start = Math.max(2, page - 1);
              const end = Math.min(totalPages - 1, page + 1);
              for (let i = start; i <= end; i++) pages.push(i);
              if (page < totalPages - 3) pages.push("...");
              pages.push(totalPages);
            }
            return pages.map((p, i) =>
              p === "..." ? (
                <span key={`ellipsis-${i}`} className="alarm-registry-pagination-ellipsis">···</span>
              ) : (
                <button
                  key={p}
                  className={p === page ? "alarm-registry-pagination-page active" : "alarm-registry-pagination-page"}
                  onClick={() => handlePageChange(p as number)}
                >
                  {p}
                </button>
              )
            );
          })()}
          <button disabled={page >= totalPages} onClick={() => handlePageChange(page + 1)}>&gt;</button>
          <select
            className="alarm-registry-pagination-size"
            value={pageSize}
            onChange={(e) => handlePageSizeChange(Number(e.target.value))}
          >
            <option value={10}>10 条/页</option>
            <option value={20}>20 条/页</option>
            <option value={50}>50 条/页</option>
          </select>
          <span className="alarm-registry-pagination-jump">
            跳至
            <input
              type="text"
              value={jumpInput}
              onChange={(e) => setJumpInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") handleJump(); }}
              onBlur={handleJump}
            />
            页
          </span>
        </div>
      )}
    </div>
  );
}
