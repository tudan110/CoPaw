import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listLightApps } from "../../api/lightApps";
import { getEmployeeById } from "../../data/portalData";
import { buildEmployeePagePath } from "./helpers";
import type { PortalLocationState } from "./pageHelpers";
import type { LightAppRecord } from "../../types/lightApps";
import { formatFriendlyDateTime } from "../../utils/dateTime";
import "./app-market.css";

const KIND_LABELS: Record<string, string> = {
  page: "页面应用",
  task: "任务应用",
};

function extractErrorMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error || "");
}

export function AppMarketPanel() {
  const navigate = useNavigate();
  const [items, setItems] = useState<LightAppRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    void listLightApps()
      .then((response) => {
        if (cancelled) {
          return;
        }
        setItems(response.items || []);
      })
      .catch((requestError) => {
        if (cancelled) {
          return;
        }
        setError(extractErrorMessage(requestError) || "加载应用中心失败");
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleLaunchApp = (item: LightAppRecord) => {
    if (item.launch.type === "open-url") {
      if (!item.launch.url) {
        setError(`应用「${item.title}」缺少访问地址`);
        return;
      }
      window.open(item.launch.url, "_blank", "noopener");
      return;
    }

    const employee = getEmployeeById(item.launch.employeeId);
    if (!employee) {
      setError(`未找到应用对应的员工入口：${item.launch.employeeId}`);
      return;
    }
    navigate(
      buildEmployeePagePath(employee, {
        view: "chat",
        panel: null,
      }),
      {
        state: {
          gatewayPresentationEmployeeId: employee.id,
          pendingPortalDispatch: {
            token: `app-market-${item.id}-${Date.now()}`,
            targetEmployeeId: employee.id,
            content: item.launch.prompt,
            visibleContent: `执行应用：${item.title}`,
            forceNewChat: true,
          },
        } satisfies PortalLocationState,
      },
    );
  };

  return (
    <div className="app-market-panel">
      <div className="portal-model-page-header">
        <div className="portal-model-page-title">
          应用中心 <small>已上架的定制应用</small>
        </div>
      </div>

      <div className="app-market-content">
        {error ? <div className="app-market-notice error">{error}</div> : null}
        {loading ? (
          <div className="app-market-empty">
            <i className="fas fa-spinner fa-spin" />
            <p>正在加载应用列表...</p>
          </div>
        ) : null}
        {!loading && !items.length ? (
          <div className="app-market-empty">
            <i className="fas fa-store-slash" />
            <p>
              当前还没有上架的应用。在“轻应用工坊”发布任务应用，
              或在“我的应用”里上架页面应用。
            </p>
          </div>
        ) : null}

        {!loading && items.length ? (
          <div className="app-market-grid">
            {items.map((item) => {
              const isPage = item.kind === "page";
              const employee = isPage
                ? null
                : getEmployeeById(item.launch.employeeId);
              const employeeName = isPage
                ? ""
                : employee?.name || item.launch.employeeId || "统一入口";
              return (
                <article key={`${item.kind}-${item.id}`} className="app-market-card">
                  <div className="app-market-card-head">
                    <div>
                      <h3>{item.title}</h3>
                      <p>{item.description || (isPage ? "AI 生成的页面应用" : "固化任务应用")}</p>
                    </div>
                    <span
                      className={`app-market-kind-badge app-market-kind-badge--${item.kind}`}
                    >
                      {KIND_LABELS[item.kind] || item.kind}
                    </span>
                  </div>

                  <div className="app-market-tags">
                    {isPage ? (
                      <>
                        {item.artifactType ? <span>{item.artifactType}</span> : null}
                        {item.tags.map((tag) => (
                          <span key={tag}>{tag}</span>
                        ))}
                      </>
                    ) : (
                      <>
                        <span>{item.scenarioType || "generic"}</span>
                        <span>{employeeName}</span>
                      </>
                    )}
                  </div>

                  <div className="app-market-footer">
                    <div className="app-market-meta-inline">
                      <span>上架时间：{formatFriendlyDateTime(item.listedAt)}</span>
                    </div>
                  </div>
                  <div className="app-market-actions">
                    <button
                      type="button"
                      className="primary-btn app-market-launch-btn"
                      onClick={() => handleLaunchApp(item)}
                    >
                      {isPage ? "打开" : "使用"}
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export default AppMarketPanel;
