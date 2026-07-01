// SSO enablement + where to send unauthenticated users, plus the bootstrap
// fallback guard.
//
// The guard is OFF by default (VITE_SSO_ENABLED / ssoEnabled runtime flag).
// During integration the colleague's "mint a code from the current INOE
// session" entry may not exist yet, so we must not bounce users to INOE
// before the loop is wired — flipping the flag on is a deliberate step.

import { tokenLogin } from "../api/sso";
import {
  clearSession,
  getSession,
  isAuthenticated,
  setSession,
} from "./ssoSession";

// INOE frontend NodePort on the same host. Standard k3s deploy: portal is
// :30083, INOE frontend :30081. Configurable (VITE_SSO_INOE_PORT / runtime
// ssoInoePort) in case the NodePort changes; defaults to 30081. Used to
// auto-derive the login URL, so VITE_SSO_LOGIN_URL stays optional (only
// needed when portal/INOE aren't same-host or the login path differs).
const DEFAULT_INOE_FRONTEND_PORT = "30081";

function getInoeFrontendPort(): string {
  const configured =
    import.meta.env.VITE_SSO_INOE_PORT ||
    (typeof window !== "undefined"
      ? window.__PORTAL_RUNTIME_CONFIG__?.ssoInoePort
      : "");
  return String(configured ?? "").trim() || DEFAULT_INOE_FRONTEND_PORT;
}

// Paths that must never be guarded, or we'd cause a redirect loop / break
// embedded views.
const GUARD_ALLOWLIST_EXACT = new Set(["/sso/callback"]);
const GUARD_ALLOWLIST_PREFIX = ["/sso/callback", "/embed/"];

function parseBool(value: string | undefined | null): boolean {
  if (!value) {
    return false;
  }
  return ["1", "true", "yes", "on"].includes(value.trim().toLowerCase());
}

export function isSsoEnabled(): boolean {
  if (parseBool(import.meta.env.VITE_SSO_ENABLED)) {
    return true;
  }
  if (typeof window !== "undefined") {
    return window.__PORTAL_RUNTIME_CONFIG__?.ssoEnabled === true;
  }
  return false;
}

export function getSsoLoginUrl(): string {
  const explicit =
    import.meta.env.VITE_SSO_LOGIN_URL ||
    (typeof window !== "undefined"
      ? window.__PORTAL_RUNTIME_CONFIG__?.ssoLoginUrl
      : "");
  if (explicit) {
    return explicit;
  }
  // Fallback (same-host deploy): the INOE login page on the same host + its
  // NodePort. Kept as /login (not /) so the redirect param we append survives
  // INOE's root-route guard. This makes VITE_SSO_LOGIN_URL unnecessary for the
  // standard k3s layout.
  const { protocol, hostname } = window.location;
  return `${protocol}//${hostname}:${getInoeFrontendPort()}/login`;
}

// Query param INOE's login page reads to redirect back after sign-in
// (RuoYi/vue-admin convention). NB: for the round-trip to actually return to
// portal, INOE must be extended to honor an *external* redirect target and
// gate it behind a host allowlist — a bare RuoYi only does in-app router
// pushes. See docs/sso.
const SSO_REDIRECT_PARAM = "redirect";

/**
 * INOE login URL with `?redirect=<target>` appended, so a successful login
 * bounces the user back to portal. `target` defaults to where the user
 * currently is (so they return to the same page). Falls back to the bare
 * login URL if it can't be parsed.
 */
export function getSsoLoginRedirectUrl(
  target: string = window.location.href,
): string {
  const base = getSsoLoginUrl();
  try {
    const url = new URL(base, window.location.href);
    url.searchParams.set(SSO_REDIRECT_PARAM, target);
    return url.toString();
  } catch {
    return base;
  }
}

function isAllowlisted(pathname: string): boolean {
  if (GUARD_ALLOWLIST_EXACT.has(pathname)) {
    return true;
  }
  return GUARD_ALLOWLIST_PREFIX.some((prefix) => pathname.startsWith(prefix));
}

// Set once we've started a re-login bounce, so concurrent 401s don't fire
// multiple redirects. The flag is moot after navigation (page unloads).
let reloginTriggered = false;

/**
 * The INOE login token died (expired / user logged out). Drop the stale
 * portal session and bounce to the INOE login. If the INOE cookie is still
 * valid, that login round-trips straight back and re-establishes the
 * session; if not, the user signs in again. Self-gated on SSO being enabled.
 */
export function triggerSsoRelogin(): void {
  if (!isSsoEnabled() || reloginTriggered) {
    return;
  }
  if (isAllowlisted(window.location.pathname)) {
    return;
  }
  reloginTriggered = true;
  clearSession();
  window.location.href = getSsoLoginRedirectUrl();
}

/**
 * Silently re-validate the stored session by re-checking the token it
 * actually holds (not whatever cookie happens to be present). On a genuine
 * auth failure (401) the token is dead → re-login. Transient errors
 * (network/timeout/config) are ignored so a blip doesn't bounce a
 * still-valid session.
 */
async function revalidateSession(): Promise<void> {
  const token = getSession()?.token;
  try {
    const result = await tokenLogin(token || undefined);
    setSession({
      token: result.access_token,
      user: result.user,
      expiresInSeconds: result.expires_in_seconds,
    });
  } catch (error) {
    if ((error as { status?: number })?.status === 401) {
      triggerSsoRelogin();
    }
  }
}

/**
 * Bootstrap guard. Call once before rendering; await it.
 *
 * Returns true when the app should render now (SSO disabled, allowlisted
 * path, already authenticated, or a cookie pass-through just succeeded).
 * Returns false when it has triggered a full-page redirect to the INOE
 * login (caller should skip rendering to avoid a flash).
 *
 * The cookie pass-through is what makes INOE's bare AI-icon redirect work:
 * it lands on portal "/" (not /sso/callback), and on the same host the
 * browser sends the INOE login cookie automatically — so we try a silent
 * token-login first, and only bounce to INOE if there's no valid session.
 */
export async function ensureSsoLogin(): Promise<boolean> {
  if (!isSsoEnabled()) {
    return true;
  }
  const pathname = window.location.pathname;
  if (isAllowlisted(pathname)) {
    return true;
  }
  if (isAuthenticated()) {
    // Render immediately, but re-validate the session against the live INOE
    // cookie in the background — if the token has since died, that triggers
    // a re-login. Keeps the cached session honest without blocking paint.
    void revalidateSession();
    return true;
  }
  // Not authenticated yet — try the INOE login cookie silently.
  try {
    const result = await tokenLogin();
    setSession({
      token: result.access_token,
      user: result.user,
      expiresInSeconds: result.expires_in_seconds,
    });
    return true;
  } catch (error) {
    if ((error as { status?: number })?.status === 401) {
      // No valid INOE session — send the user to log in, asking INOE to
      // bounce back to where they were.
      window.location.href = getSsoLoginRedirectUrl();
      return false;
    }
    // Config/network error: render the app rather than bounce-loop, so the
    // operator can reach settings to fix it.
    return true;
  }
}
