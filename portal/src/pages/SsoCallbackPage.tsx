import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { exchangeSsoCode, tokenLogin } from "../api/sso";
import { getSsoLoginRedirectUrl } from "../auth/ssoConfig";
import { setSession } from "../auth/ssoSession";

type Phase = "exchanging" | "error";

// Only allow navigating to a same-origin relative path after login, so a
// crafted ?redirect= can't bounce the user to an external site.
function safeRedirectTarget(raw: string | null): string {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//")) {
    return "/";
  }
  return raw;
}

const wrapStyle: React.CSSProperties = {
  minHeight: "100vh",
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  justifyContent: "center",
  gap: 16,
  color: "#475569",
  background: "#f8fafc",
  fontSize: 15,
};

export default function SsoCallbackPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [phase, setPhase] = useState<Phase>("exchanging");
  const [message, setMessage] = useState("正在登录...");
  // React 18 StrictMode mounts effects twice in dev; guard the exchange so
  // the one-time code is only consumed once.
  const startedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current) {
      return;
    }
    startedRef.current = true;

    const token = (searchParams.get("token") || "").trim();
    const code = (searchParams.get("code") || "").trim();
    const state = searchParams.get("state");
    const target = safeRedirectTarget(searchParams.get("redirect"));

    // Token pass-through is the primary path: an explicit ?token=, or — when
    // portal shares INOE's hostname — no param at all, letting the backend
    // read the INOE login cookie. ?code= keeps the (currently unused)
    // authorization-code flow working.
    const login = token
      ? tokenLogin(token)
      : code
        ? exchangeSsoCode(code, state)
        : tokenLogin();

    login
      .then((result) => {
        setSession({
          token: result.access_token,
          user: result.user,
          expiresInSeconds: result.expires_in_seconds,
        });
        navigate(target, { replace: true });
      })
      .catch((error: unknown) => {
        setPhase("error");
        setMessage(
          error instanceof Error ? error.message : "单点登录失败,请重试。",
        );
      });
  }, [navigate, searchParams]);

  if (phase === "exchanging") {
    return (
      <div style={wrapStyle}>
        <div>{message}</div>
      </div>
    );
  }

  return (
    <div style={wrapStyle}>
      <div style={{ color: "#b91c1c", maxWidth: 420, textAlign: "center" }}>
        {message}
      </div>
      <button
        type="button"
        onClick={() => {
          // After login, come back to the portal home (this page has no code).
          window.location.href = getSsoLoginRedirectUrl(
            `${window.location.origin}/`,
          );
        }}
        style={{
          padding: "8px 20px",
          borderRadius: 8,
          border: "none",
          background: "#2563eb",
          color: "#fff",
          fontSize: 14,
          cursor: "pointer",
        }}
      >
        重新登录
      </button>
    </div>
  );
}
