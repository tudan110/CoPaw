import { useEffect, useMemo, useState } from "react";
import { useLocation, useParams } from "react-router-dom";
import { getAiBigScreen } from "../api/aiBigScreen";
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
    </div>
  );
}
