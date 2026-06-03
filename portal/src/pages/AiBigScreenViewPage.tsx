import { useEffect, useMemo, useState } from "react";
import { useLocation, useParams } from "react-router-dom";
import { getAiBigScreen } from "../api/aiBigScreen";
import AiBigScreenRenderer from "../components/ai-big-screen/AiBigScreenRenderer";
import type { AiBigScreenApp } from "../types/aiBigScreen";

function extractErrorMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error || "");
}

export default function AiBigScreenViewPage() {
  const { screenId = "" } = useParams();
  const location = useLocation();
  const searchParams = useMemo(() => new URLSearchParams(location.search), [location.search]);
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
    return (
      <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", color: "#64748b" }}>
        正在加载大屏...
      </div>
    );
  }

  if (error || !screen) {
    return (
      <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", color: "#ef4444" }}>
        {error || "大屏加载失败"}
      </div>
    );
  }

  return (
    <main
      style={{
        minHeight: "100vh",
        background: "#07111f",
        padding: embedded ? 0 : 16,
      }}
    >
      {screen.status !== "published" && !embedded ? (
        <div
          style={{
            marginBottom: 12,
            padding: "10px 12px",
            borderRadius: 8,
            background: "rgba(245, 158, 11, 0.14)",
            color: "#fbbf24",
          }}
        >
          当前大屏尚未发布，正在以内部预览方式打开。
        </div>
      ) : null}
      <AiBigScreenRenderer screen={screen} />
    </main>
  );
}
