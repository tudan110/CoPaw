import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useParams } from "react-router-dom";
import { getAiBigScreen, refreshAiBigScreen } from "../api/aiBigScreen";
import { BigScreenRenderer } from "../components/big-screen/BigScreenRenderer.tsx";
import { adaptLegacyScreen } from "../components/big-screen/adaptLegacyScreen.ts";
import "../components/big-screen/big-screen.css";
import type { AiBigScreenApp } from "../types/aiBigScreen";

function extractErrorMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error || "");
}

const MIN_REFRESH_MS = 30_000;
const MAX_REFRESH_MS = 600_000;

/** Pick the screen's data heartbeat from its components' refresh
 * policies — the fastest interval wins, clamped to [30s, 10min]. */
function resolveRefreshMs(screen: AiBigScreenApp | null): number {
  const intervals = (screen?.components ?? [])
    .map((component) => Number(component.refreshInterval))
    .filter((seconds) => Number.isFinite(seconds) && seconds > 0);
  const fastest = intervals.length > 0 ? Math.min(...intervals) : 120;
  return Math.max(MIN_REFRESH_MS, Math.min(MAX_REFRESH_MS, fastest * 1000));
}

function fullscreenNote(color: string, text: string) {
  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        display: "grid",
        placeItems: "center",
        background: "#070c16",
        color,
        fontSize: 14,
      }}
    >
      {text}
    </div>
  );
}

export default function AiBigScreenViewPage() {
  const { screenId = "" } = useParams();
  const location = useLocation();
  const searchParams = useMemo(
    () => new URLSearchParams(location.search),
    [location.search],
  );
  const embedded = searchParams.get("embed") === "1";
  const [screen, setScreen] = useState<AiBigScreenApp | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [lastRefreshAt, setLastRefreshAt] = useState("");
  const refreshingRef = useRef(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    void getAiBigScreen(screenId)
      .then((response) => {
        if (!cancelled) {
          setScreen(response.screen);
        }
      })
      .catch((requestError) => {
        if (!cancelled) {
          setError(extractErrorMessage(requestError) || "大屏加载失败");
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
  }, [screenId]);

  // Live-data heartbeat: periodically re-hydrate the screen's data
  // (backend re-runs L2 only). Failures keep the previous data on
  // screen; the tab pauses while hidden.
  const refreshMs = resolveRefreshMs(screen);
  useEffect(() => {
    if (!screen || !screenId) {
      return undefined;
    }
    const timer = window.setInterval(() => {
      if (document.hidden || refreshingRef.current) {
        return;
      }
      refreshingRef.current = true;
      refreshAiBigScreen(screenId)
        .then((response) => {
          setScreen(response.screen);
          setLastRefreshAt(new Date().toLocaleTimeString());
        })
        .catch(() => {
          // keep stale data; next tick retries
        })
        .finally(() => {
          refreshingRef.current = false;
        });
    }, refreshMs);
    return () => window.clearInterval(timer);
  }, [screenId, refreshMs, screen ? screen.id : ""]);

  if (loading) {
    return fullscreenNote("#9fb2cc", "正在加载大屏...");
  }
  if (error || !screen) {
    return fullscreenNote("#f87171", error || "大屏加载失败");
  }

  // Adapt the legacy real-data spec into the typed DashboardSpec; grid coords
  // are dropped so the auto-layout engine positions panels by visual weight.
  const spec = adaptLegacyScreen(screen);

  return (
    <div style={{ position: "fixed", inset: 0, background: "#070c16" }}>
      <BigScreenRenderer spec={spec} />
      {screen.status !== "published" && !embedded ? (
        <div
          style={{
            position: "absolute",
            top: 12,
            left: 12,
            zIndex: 20,
            padding: "6px 10px",
            borderRadius: 8,
            background: "rgba(245, 158, 11, 0.16)",
            color: "#fbbf24",
            fontSize: 12,
            backdropFilter: "blur(4px)",
          }}
        >
          未发布 · 内部预览
        </div>
      ) : null}
      {lastRefreshAt ? (
        <div
          style={{
            position: "absolute",
            bottom: 10,
            right: 14,
            zIndex: 20,
            padding: "3px 8px",
            borderRadius: 6,
            background: "rgba(10, 20, 36, 0.55)",
            color: "#5c7a99",
            fontSize: 11,
            pointerEvents: "none",
          }}
        >
          数据更新于 {lastRefreshAt}
        </div>
      ) : null}
    </div>
  );
}
