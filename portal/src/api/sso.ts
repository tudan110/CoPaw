// Portal SSO API calls. Reuses requestPortalApi so the same /portal-api ->
// /api/portal base-URL resolution + same-origin fallback applies. Paths here
// are relative to /api/portal, and the SSO router mounts under /sso.

import type { SsoUser } from "../auth/ssoSession";
import { requestPortalApi } from "./portalWorkorders";

export interface SsoExchangeResult {
  access_token: string;
  token_type: string;
  expires_in_seconds: number;
  scope?: string | null;
  user: SsoUser;
}

/**
 * Token pass-through login: validate an existing INOE login token.
 *
 * Pass the token explicitly, or omit it to let the backend read the
 * Cnos-Inoe-Admin-Token cookie (works when portal shares INOE's hostname).
 */
export async function tokenLogin(
  token?: string | null,
): Promise<SsoExchangeResult> {
  return requestPortalApi<SsoExchangeResult>("/sso/token-login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(token ? { token } : {}),
  });
}

export async function clearSsoLoginCookie(): Promise<{ cleared: boolean }> {
  return requestPortalApi<{ cleared: boolean }>("/sso/clear-login-cookie", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
}

/** Trade the one-time authorization code for portal login material. */
export async function exchangeSsoCode(
  code: string,
  state?: string | null,
): Promise<SsoExchangeResult> {
  return requestPortalApi<SsoExchangeResult>("/sso/exchange", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code, state: state ?? "" }),
  });
}

/** Whether the backend has the credentials to perform an exchange. */
export async function getSsoStatus(): Promise<{ configured: boolean }> {
  return requestPortalApi<{ configured: boolean }>("/sso/status");
}
