import { Component, type ReactNode } from "react";

const RELOAD_FLAG_KEY = "portal:chunk-reload-attempt";
const RELOAD_FLAG_TTL_MS = 60_000;

function isChunkLoadError(error: unknown): boolean {
  if (!error) return false;
  const message = error instanceof Error ? error.message : String(error);
  const name = error instanceof Error ? error.name : "";
  return (
    name === "ChunkLoadError" ||
    /Loading chunk [\d]+ failed/i.test(message) ||
    /Loading CSS chunk/i.test(message) ||
    /Failed to fetch dynamically imported module/i.test(message) ||
    /error loading dynamically imported module/i.test(message) ||
    /import\(\) failed/i.test(message)
  );
}

function recentlyReloaded(): boolean {
  try {
    const raw = window.sessionStorage.getItem(RELOAD_FLAG_KEY);
    if (!raw) return false;
    const ts = Number(raw);
    return Number.isFinite(ts) && Date.now() - ts < RELOAD_FLAG_TTL_MS;
  } catch {
    return false;
  }
}

function markReload(): void {
  try {
    window.sessionStorage.setItem(RELOAD_FLAG_KEY, String(Date.now()));
  } catch {
    /* sessionStorage may be disabled — fall through to manual UI */
  }
}

interface State {
  hasError: boolean;
  isChunkError: boolean;
}

export class ChunkErrorBoundary extends Component<
  { children: ReactNode },
  State
> {
  state: State = { hasError: false, isChunkError: false };

  static getDerivedStateFromError(error: unknown): State {
    return { hasError: true, isChunkError: isChunkLoadError(error) };
  }

  componentDidCatch(error: unknown): void {
    if (isChunkLoadError(error)) {
      console.warn("[Portal] Chunk load error caught:", error);
      if (!recentlyReloaded()) {
        markReload();
        window.location.reload();
      }
    } else {
      console.error("[Portal] Unhandled render error:", error);
    }
  }

  private handleReload = (): void => {
    markReload();
    window.location.reload();
  };

  render(): ReactNode {
    if (!this.state.hasError) return this.props.children;

    const isChunk = this.state.isChunkError;
    return (
      <div
        style={{
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#f8fafc",
          color: "#0f172a",
          padding: 24,
          textAlign: "center",
        }}
      >
        <div style={{ maxWidth: 480 }}>
          <div style={{ fontSize: 48, marginBottom: 16 }}>
            <i className="fas fa-rotate" />
          </div>
          <h2 style={{ margin: "0 0 12px", fontSize: 20, fontWeight: 600 }}>
            {isChunk ? "页面资源已更新" : "页面加载失败"}
          </h2>
          <p style={{ margin: "0 0 24px", color: "#64748b", lineHeight: 1.6 }}>
            {isChunk
              ? "服务端版本已更新，本页面引用的旧资源不再可用。点击下方按钮重新加载即可恢复。"
              : "页面渲染过程中出现异常，请尝试刷新；若问题持续请联系管理员。"}
          </p>
          <button
            type="button"
            onClick={this.handleReload}
            style={{
              padding: "10px 28px",
              fontSize: 14,
              fontWeight: 500,
              color: "#fff",
              background: "#2563eb",
              border: "none",
              borderRadius: 8,
              cursor: "pointer",
            }}
          >
            重新加载
          </button>
        </div>
      </div>
    );
  }
}

export default ChunkErrorBoundary;
