import { useEffect, useMemo, useState } from "react";
import { listAiBigScreens } from "../api/aiBigScreen";
import type { AiBigScreenApp, AiBigScreenPublishTarget } from "../types/aiBigScreen";
import { formatFriendlyDateTime } from "../utils/dateTime";
import "./ai-big-screen-gallery.css";

function extractErrorMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error || "");
}

function getTarget(screen: AiBigScreenApp, type: string): AiBigScreenPublishTarget | null {
  return screen.publishTargets?.find((item) => item.type === type) || null;
}

export default function AiBigScreenGalleryPage() {
  const [screens, setScreens] = useState<AiBigScreenApp[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    void listAiBigScreens(200)
      .then((response) => {
        if (!cancelled) {
          setScreens(response.items || []);
        }
      })
      .catch((requestError) => {
        if (!cancelled) {
          setError(extractErrorMessage(requestError) || "大屏展示中心加载失败");
        }
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

  const publishedScreens = useMemo(
    () => screens.filter((item) => item.status === "published"),
    [screens],
  );

  return (
    <main className="ai-big-screen-gallery">
      <header className="ai-big-screen-gallery-header">
        <div>
          <p>AI Big Screen Center</p>
          <h1>AI 大屏展示中心</h1>
        </div>
        <a href="/ai-big-screen">返回工坊</a>
      </header>

      {loading ? <div className="ai-big-screen-gallery-state">正在加载...</div> : null}
      {error ? <div className="ai-big-screen-gallery-state error">{error}</div> : null}
      {!loading && !error && !publishedScreens.length ? (
        <div className="ai-big-screen-gallery-state">暂无已发布大屏。</div>
      ) : null}

      <section className="ai-big-screen-gallery-grid">
        {publishedScreens.map((screen) => {
          const externalTarget = getTarget(screen, "external-link");
          const iframeTarget = getTarget(screen, "iframe");
          return (
            <article key={screen.id} className="ai-big-screen-gallery-card">
              <div className="ai-big-screen-gallery-card-head">
                <div>
                  <h2>{screen.name}</h2>
                  <p>{screen.description || "AI 生成的大屏资产"}</p>
                </div>
                <span>{screen.permissions?.visibility === "internal" ? "内部" : "公开"}</span>
              </div>
              <dl>
                <div>
                  <dt>组件</dt>
                  <dd>{screen.components?.length || 0}</dd>
                </div>
                <div>
                  <dt>更新</dt>
                  <dd>{formatFriendlyDateTime(screen.updatedAt || "")}</dd>
                </div>
              </dl>
              <div className="ai-big-screen-gallery-actions">
                <a href={externalTarget?.url || `/big-screen/${screen.id}`}>打开大屏</a>
                <a href={iframeTarget?.url || `/big-screen/${screen.id}?embed=1`}>嵌入预览</a>
              </div>
            </article>
          );
        })}
      </section>
    </main>
  );
}
