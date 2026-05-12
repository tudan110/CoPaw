import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listNlCustomizationApps } from "../../api/naturalLanguageCustomization";
import { getEmployeeById } from "../../data/portalData";
import { buildEmployeePagePath } from "./helpers";
import type { PortalLocationState } from "./pageHelpers";
import type { NlCustomizationAppRecord } from "../../types/naturalLanguageCustomization";
import { formatFriendlyDateTime } from "../../utils/dateTime";
import "./app-market.css";

function extractErrorMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error || "");
}

export function AppMarketPanel() {
  const navigate = useNavigate();
  const [items, setItems] = useState<NlCustomizationAppRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    void listNlCustomizationApps()
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

  const handleLaunchApp = (item: NlCustomizationAppRecord) => {
    const employee = getEmployeeById(item.launchEmployeeId);
    if (!employee) {
      setError(`未找到应用对应的员工入口：${item.launchEmployeeId}`);
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
            token: `app-market-${item.appId}-${Date.now()}`,
            targetEmployeeId: employee.id,
            content: item.launchPrompt,
            visibleContent: `使用应用：${item.title}`,
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
            <p>当前还没有上架的应用。先在“自然语言定制”里应用一个版本，再上架到应用中心。</p>
          </div>
        ) : null}

        {!loading && items.length ? (
          <div className="app-market-grid">
            {items.map((item) => {
              const employee = getEmployeeById(item.launchEmployeeId);
              const employeeName = employee?.name || item.launchEmployeeId || "统一入口";
              return (
                <article key={item.appId} className="app-market-card">
                  <div className="app-market-card-head">
                    <div>
                      <h3>{item.title}</h3>
                      <p>{item.description || item.prompt}</p>
                    </div>
                    <span className="app-market-badge">已上架</span>
                  </div>

                  <div className="app-market-tags">
                    <span>{item.scenarioType || "generic"}</span>
                    <span>{employeeName}</span>
                    {item.matchedSkillId ? <span>{item.matchedSkillId}</span> : null}
                  </div>

                  <div className="app-market-meta">
                    <div>
                      <span>发布时间</span>
                      <strong>{formatFriendlyDateTime(item.publishedAt)}</strong>
                    </div>
                    <div>
                      <span>上架时间</span>
                      <strong>{formatFriendlyDateTime(item.listedAt || item.installedAt)}</strong>
                    </div>
                  </div>

                  <div className="app-market-actions">
                    <button
                      type="button"
                      className="primary-btn"
                      onClick={() => handleLaunchApp(item)}
                    >
                      立即使用
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
