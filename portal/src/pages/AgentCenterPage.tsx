import { useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import DigitalEmployeeAvatar from "../components/DigitalEmployeeAvatar";
import PortalTraditionalViewButton from "../components/PortalTraditionalViewButton";
import {
  agentTypeNames,
  getEmployeeById,
  portalAgents,
  portalStats,
} from "../data/portalData";
import { buildEmployeePagePath } from "./digital-employee/helpers";

const categories = [
  { id: "all", label: "全部" },
  { id: "planned", label: "更多待规划" },
];

export default function AgentCenterPage() {
  const [filterType, setFilterType] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [activeCategory, setActiveCategory] = useState("all");
  const [showCreate, setShowCreate] = useState(false);
  const [toast, setToast] = useState("");
  const toastTimerRef = useRef<number | null>(null);

  const enrichedAgents = useMemo(
    () =>
      portalAgents.map((agent) => {
        const employee = getEmployeeById(agent.employeeId);
        return {
          ...agent,
          employee,
          displayStatus: employee?.status === "running" ? "active" : "stopped",
          isUrgent: Boolean(employee?.urgent),
        };
      }),
    [],
  );

  const filteredAgents = useMemo(() => {
    if (activeCategory === "planned") {
      return [];
    }
    return enrichedAgents.filter((agent) => {
      const matchedType = !filterType || agent.type === filterType;
      const matchedStatus =
        !filterStatus || agent.displayStatus === filterStatus;
      return matchedType && matchedStatus;
    });
  }, [activeCategory, enrichedAgents, filterStatus, filterType]);

  const showToast = (message: string) => {
    setToast(message);
    if (toastTimerRef.current) {
      window.clearTimeout(toastTimerRef.current);
    }
    toastTimerRef.current = window.setTimeout(() => {
      setToast("");
    }, 1800);
  };

  return (
    <div className="agent-center-shell">
      <div className="agent-center-page">
        {toast ? <div className="toast-message">{toast}</div> : null}
        <div className="page-header">
          <div className="header-actions">
            <button className="primary-btn" onClick={() => setShowCreate(true)}>
              <i className="fa-solid fa-plus" />
              创建智能体
            </button>
            <button className="ghost-btn" onClick={() => showToast("已刷新")}>
              <i className="fa-solid fa-rotate-right" />
              刷新
            </button>
            <Link className="ghost-btn" to="/nl-customization" style={{ textDecoration: "none" }}>
              <i className="fa-solid fa-wand-magic-sparkles" />
              轻应用工坊
            </Link>
            <PortalTraditionalViewButton />
          </div>
        </div>

        <div className="stats-row">
          <StatCard icon="fa-regular fa-calendar-check" label="智能体总数" value={portalStats.total} variant="blue" />
          <StatCard icon="fa-solid fa-circle-play" label="运行中" value={portalStats.active} variant="green" />
          <StatCard icon="fa-regular fa-file-lines" label="今日执行任务" value={portalStats.tasksToday} variant="amber" />
          <StatCard icon="fa-solid fa-chart-line" label="执行成功率" value={`${portalStats.efficiency}%`} variant="purple" />
        </div>

        <div className="filter-card">
          <div className="filters-inline">
            <label>
              <span>智能体类型</span>
              <select value={filterType} onChange={(event) => setFilterType(event.target.value)}>
                <option value="">全部</option>
                {Object.entries(agentTypeNames).map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>状态</span>
              <select value={filterStatus} onChange={(event) => setFilterStatus(event.target.value)}>
                <option value="">全部</option>
                <option value="active">运行中</option>
                <option value="stopped">已停止</option>
              </select>
            </label>
            <div className="filter-buttons">
              <button className="primary-btn" onClick={() => showToast("筛选条件已应用")}>
                查询
              </button>
              <button
                className="ghost-btn"
                onClick={() => {
                  setFilterType("");
                  setFilterStatus("");
                  setActiveCategory("all");
                  showToast("筛选条件已重置");
                }}
              >
                重置
              </button>
            </div>
          </div>
        </div>

        <div className="category-tabs">
          {categories.map((item) => (
            <button
              key={item.id}
              className={item.id === activeCategory ? "tab-btn active" : "tab-btn"}
              onClick={() => setActiveCategory(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>

        {activeCategory === "planned" ? (
          <div className="planned-placeholder">
            <div className="planned-placeholder-icon">
              <i className="fa-solid fa-compass-drafting" />
            </div>
            <h3>更多待规划</h3>
            <p>这里会放后续扩展的数字员工入口，当前先保留统一的 6 个核心角色。</p>
          </div>
        ) : (
          <div className="agent-grid">
            {filteredAgents.map((agent) => (
                <Link
                  key={agent.id}
                  to={buildEmployeePagePath(agent.employee)}
                  className={
                    agent.isUrgent
                      ? "agent-card-link urgent-agent-link"
                    : "agent-card-link"
                }
              >
                <div
                  className={
                    agent.isUrgent ? "agent-card urgent-agent-card" : "agent-card"
                  }
                >
                  {agent.isUrgent ? (
                    <div className="agent-card-urgent-beacon" aria-hidden="true">
                      <span className="agent-card-urgent-dot" />
                    </div>
                  ) : null}
                  <div className="agent-card-head">
                    <DigitalEmployeeAvatar
                      employee={agent.employee}
                      className="agent-center-avatar"
                    />
                    <div className="agent-card-title">
                      <h3>{agent.name}</h3>
                      <span>{agentTypeNames[agent.type]}</span>
                    </div>
                    <span
                      className={
                        agent.isUrgent
                          ? "status-pill urgent"
                          : agent.displayStatus === "active"
                          ? "status-pill active"
                          : "status-pill"
                      }
                    >
                      {agent.isUrgent
                        ? "紧急"
                        : agent.displayStatus === "active"
                        ? "运行中"
                        : "已停止"}
                    </span>
                  </div>

                  <p className="agent-card-desc">
                    {agent.employee?.desc || agent.description}
                  </p>

                  <div className="agent-metrics">
                    <div>
                      <span>执行次数</span>
                      <strong>{agent.execCount}</strong>
                    </div>
                    <div>
                      <span>成功率</span>
                      <strong className="success-text">{agent.successRate}%</strong>
                    </div>
                    <div>
                      <span>平均耗时</span>
                      <strong>{agent.avgDuration}</strong>
                    </div>
                  </div>

                  <div className="agent-card-footer">
                    <span>最后执行: {agent.lastRunTime}</span>
                    <div className="agent-card-actions">
                      <span>进入数字员工</span>
                      <i className="fa-solid fa-arrow-right" />
                    </div>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        )}

        {showCreate ? (
          <div className="overlay-mask" onClick={() => setShowCreate(false)}>
            <div className="dialog-card" onClick={(event) => event.stopPropagation()}>
              <div className="dialog-header">
                <h3>创建智能体</h3>
                <button className="icon-btn" onClick={() => setShowCreate(false)}>
                  <i className="fa-solid fa-xmark" />
                </button>
              </div>
              <div className="dialog-body">
                <label>
                  <span>智能体名称</span>
                  <input placeholder="请输入智能体名称" />
                </label>
                <label>
                  <span>智能体类型</span>
                  <select defaultValue="">
                    <option value="" disabled>
                      请选择类型
                    </option>
                    {Object.entries(agentTypeNames).map(([key, label]) => (
                      <option key={key} value={key}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>描述</span>
                  <textarea rows={4} placeholder="请输入智能体描述" />
                </label>
              </div>
              <div className="dialog-footer">
                <button className="ghost-btn" onClick={() => setShowCreate(false)}>
                  取消
                </button>
                <button
                  className="primary-btn"
                  onClick={() => {
                    setShowCreate(false);
                    showToast("智能体创建成功");
                  }}
                >
                  创建
                </button>
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
  variant,
}: {
  icon: string;
  label: string;
  value: string | number;
  variant: string;
}) {
  return (
    <div className={`stats-card ${variant}`}>
      <div className="stats-icon">
        <i className={icon} />
      </div>
      <div>
        <div className="stats-value">{value}</div>
        <div className="stats-label">{label}</div>
      </div>
    </div>
  );
}
