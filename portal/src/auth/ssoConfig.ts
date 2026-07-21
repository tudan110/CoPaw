// SSO enablement + where to send unauthenticated users, plus the bootstrap
// fallback guard.
//
// The guard is OFF by default (VITE_SSO_ENABLED / ssoEnabled runtime flag).
// During integration the colleague's "mint a code from the current INOE
// session" entry may not exist yet, so we must not bounce users to INOE
// before the loop is wired — flipping the flag on is a deliberate step.

import { clearSsoLoginCookie, tokenLogin } from "../api/sso";
import {
  clearSession,
  getSession,
  isAuthenticated,
  isSessionStorageKey,
  setSession,
} from "./ssoSession";

// INOE frontend NodePort on the same host. Standard k3s deploy: portal is
// :30083, INOE frontend :30081. Configurable (VITE_SSO_INOE_PORT / runtime
// ssoInoePort) in case the NodePort changes; defaults to 30081. Used to
// auto-derive the login URL, so VITE_SSO_LOGIN_URL stays optional (only
// needed when portal/INOE aren't same-host or the login path differs).
const DEFAULT_INOE_FRONTEND_PORT = "30081";

function normalizeOptionalString(value: string | undefined | null): string {
  return String(value ?? "").trim();
}

function getRuntimeFirstString(
  runtimeValue: string | undefined | null,
  envValue: string | undefined | null,
): string {
  return normalizeOptionalString(runtimeValue) || normalizeOptionalString(envValue);
}

function getEnvString(key: "VITE_SSO_INOE_PORT" | "VITE_SSO_LOGIN_URL" | "VITE_SSO_ENABLED"): string {
  return normalizeOptionalString(import.meta.env?.[key]);
}

function getInoeFrontendPort(): string {
  const configured = getRuntimeFirstString(
    typeof window !== "undefined"
      ? window.__PORTAL_RUNTIME_CONFIG__?.ssoInoePort
      : "",
    getEnvString("VITE_SSO_INOE_PORT"),
  );
  return configured || DEFAULT_INOE_FRONTEND_PORT;
}

// Full login-URL override (runtime ssoLoginUrl / VITE_SSO_LOGIN_URL), if any.
// Read once here so both getSsoLoginUrl() and getInoeFrontendOrigin() agree
// on whether an override is set.
function getInoeLoginUrlOverride(): string {
  return getRuntimeFirstString(
    typeof window !== "undefined"
      ? window.__PORTAL_RUNTIME_CONFIG__?.ssoLoginUrl
      : "",
    getEnvString("VITE_SSO_LOGIN_URL"),
  );
}

/**
 * Origin (protocol + host + port) of the INOE frontend — shared by the SSO
 * login-URL derivation and the "切换传统视图" button, since both point at the
 * same INOE frontend. If VITE_SSO_LOGIN_URL/ssoLoginUrl is set (portal and
 * INOE aren't same-host, or the NodePort mapping differs), its host wins;
 * otherwise same-host + VITE_SSO_INOE_PORT is assumed.
 */
export function getInoeFrontendOrigin(): string {
  const override = getInoeLoginUrlOverride();
  if (override) {
    try {
      return new URL(override, window.location.href).origin;
    } catch {
      // Malformed override — fall through to auto-derive rather than send
      // callers a garbage origin.
    }
  }
  const { protocol, hostname } = window.location;
  return `${protocol}//${hostname}:${getInoeFrontendPort()}`;
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
  const runtimeEnabled =
    typeof window !== "undefined"
      ? window.__PORTAL_RUNTIME_CONFIG__?.ssoEnabled
      : undefined;
  if (runtimeEnabled !== undefined) {
    return runtimeEnabled === true;
  }
  return parseBool(getEnvString("VITE_SSO_ENABLED"));
}

export function getSsoLoginUrl(): string {
  const explicit = getInoeLoginUrlOverride();
  if (explicit) {
    return explicit;
  }
  // Fallback (same-host deploy): the INOE login page on the same host + its
  // NodePort. Kept as /login (not /) so the redirect param we append survives
  // INOE's root-route guard. This makes VITE_SSO_LOGIN_URL unnecessary for the
  // standard k3s layout.
  return `${getInoeFrontendOrigin()}/login`;
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
let revalidateInFlight: Promise<boolean> | null = null;
let lastRevalidateAt = 0;
const REVALIDATE_COOLDOWN_MS = 3_000;
const REVALIDATE_INTERVAL_MS = 60_000;

function canCheckSession(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  if (!isSsoEnabled() || !isAuthenticated()) {
    return false;
  }
  if (isAllowlisted(window.location.pathname)) {
    return false;
  }
  return true;
}

function clearSessionWithoutRedirect(): void {
  clearSession();
}

async function clearStaleSsoState(): Promise<void> {
  clearSessionWithoutRedirect();
  try {
    await clearSsoLoginCookie();
  } catch {
    // Best-effort cleanup — a failed cookie clear should not block the
    // fallback re-login flow.
  }
}

function shouldSkipRevalidate(force: boolean): boolean {
  if (force) {
    return false;
  }
  return Date.now() - lastRevalidateAt < REVALIDATE_COOLDOWN_MS;
}

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
    clearSessionWithoutRedirect();
    return;
  }
  reloginTriggered = true;
  void clearStaleSsoState().finally(() => {
    window.location.href = getSsoLoginRedirectUrl();
  });
}

/**
 * Re-validate the stored session by re-checking the token it actually holds
 * (not whatever cookie happens to be present), and report whether it's safe
 * to render. Awaited by ensureSsoLogin() so a dead token never paints the app
 * first — if INOE logged the user out server-side, the tab must stay blank
 * until this resolves, not flash the last-known page before bouncing.
 * Transient errors (network/timeout/config) are treated as still-valid, so a
 * blip doesn't lock out a session that's actually fine.
 */
async function revalidateSession(): Promise<boolean> {
  const token = getSession()?.token;
  try {
    const result = await tokenLogin(token || undefined);
    setSession({
      token: result.access_token,
      user: result.user,
      expiresInSeconds: result.expires_in_seconds,
    });
    return true;
  } catch (error) {
    if ((error as { status?: number })?.status === 401) {
      await clearStaleSsoState();
      try {
        const result = await tokenLogin();
        setSession({
          token: result.access_token,
          user: result.user,
          expiresInSeconds: result.expires_in_seconds,
        });
        return true;
      } catch (retryError) {
        if ((retryError as { status?: number })?.status === 401) {
          triggerSsoRelogin();
          return false;
        }
      }
      return true;
    }
    return true;
  }
}

export function checkSsoSession(force = false): Promise<boolean> {
  if (!canCheckSession()) {
    return Promise.resolve(true);
  }
  if (revalidateInFlight) {
    return revalidateInFlight;
  }
  if (shouldSkipRevalidate(force)) {
    return Promise.resolve(true);
  }
  lastRevalidateAt = Date.now();
  revalidateInFlight = revalidateSession().finally(() => {
    revalidateInFlight = null;
  });
  return revalidateInFlight;
}

function scheduleVisibleSessionCheck(): void {
  void checkSsoSession();
}

export function setupSsoSessionMonitor(): () => void {
  if (typeof window === "undefined") {
    return () => {};
  }

  let intervalId: number | null = null;

  const refreshInterval = () => {
    if (intervalId !== null) {
      window.clearInterval(intervalId);
      intervalId = null;
    }
    if (!canCheckSession() || document.hidden) {
      return;
    }
    intervalId = window.setInterval(() => {
      void checkSsoSession();
    }, REVALIDATE_INTERVAL_MS);
  };

  const handleVisibilityChange = () => {
    if (!document.hidden) {
      scheduleVisibleSessionCheck();
    }
    refreshInterval();
  };

  const handleFocus = () => {
    scheduleVisibleSessionCheck();
    refreshInterval();
  };

  const handlePageShow = () => {
    scheduleVisibleSessionCheck();
    refreshInterval();
  };

  const handleStorage = (event: StorageEvent) => {
    if (event.storageArea !== window.localStorage) {
      return;
    }
    if (!isSessionStorageKey(event.key)) {
      return;
    }
    if (!isAuthenticated()) {
      triggerSsoRelogin();
      return;
    }
    refreshInterval();
  };

  document.addEventListener("visibilitychange", handleVisibilityChange);
  window.addEventListener("focus", handleFocus);
  window.addEventListener("pageshow", handlePageShow);
  window.addEventListener("storage", handleStorage);
  refreshInterval();

  return () => {
    document.removeEventListener("visibilitychange", handleVisibilityChange);
    window.removeEventListener("focus", handleFocus);
    window.removeEventListener("pageshow", handlePageShow);
    window.removeEventListener("storage", handleStorage);
    if (intervalId !== null) {
      window.clearInterval(intervalId);
    }
  };
}

/**
 * Bootstrap guard. Call once before rendering; await it.
 *
 * Returns true when the app should render now (SSO disabled, allowlisted
 * path, a cached session just revalidated OK, or a cookie pass-through just
 * succeeded). Returns false when it has triggered a full-page redirect to
 * the INOE login (caller should skip rendering to avoid a flash).
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
    // Must be awaited: if INOE logged the user out server-side, the cached
    // session looks valid locally but is dead upstream. Painting first and
    // revalidating after would flash the stale page before bouncing.
    return await revalidateSession();
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
      // No valid INOE session — clear stale local/cookie state first, then
      // send the user to log in and bounce back to where they were.
      await clearStaleSsoState();
      window.location.href = getSsoLoginRedirectUrl();
      return false;
    }
    // Config/network error: render the app rather than bounce-loop, so the
    // operator can reach settings to fix it.
    return true;
  }
}
