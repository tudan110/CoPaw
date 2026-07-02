// Portal SSO login state, persisted in localStorage.
//
// Phase 1 keeps the login state on the client: after the backend exchanges
// the INOE authorization code for an access token + user info, we store both
// here. The token is the user's own INOE credential (the same thing INOE
// keeps in its own cookie), so holding it client-side is acceptable — what we
// deliberately avoid is ever putting the *phone number* in a browser URL.

export interface SsoUser {
  userId?: string;
  username?: string;
  nickName?: string;
  phonenumber?: string;
  deptId?: string;
  email?: string;
}

export interface SsoSession {
  token: string;
  user: SsoUser;
  expireAt: number; // epoch ms; 0 means "no known expiry"
}

const TOKEN_KEY = "qwenpaw.sso.token";
const USER_KEY = "qwenpaw.sso.user";
const EXPIRE_KEY = "qwenpaw.sso.expireAt";

function safeGet(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeSet(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* storage unavailable (private mode / quota) — non-fatal */
  }
}

function safeRemove(key: string): void {
  try {
    window.localStorage.removeItem(key);
  } catch {
    /* non-fatal */
  }
}

export function getSession(): SsoSession | null {
  const token = safeGet(TOKEN_KEY);
  if (!token) {
    return null;
  }
  let user: SsoUser = {};
  const rawUser = safeGet(USER_KEY);
  if (rawUser) {
    try {
      user = JSON.parse(rawUser) as SsoUser;
    } catch {
      user = {};
    }
  }
  const expireAt = Number(safeGet(EXPIRE_KEY) || 0) || 0;
  return { token, user, expireAt };
}

export function setSession(input: {
  token: string;
  user?: SsoUser | null;
  expiresInSeconds?: number;
}): void {
  // INOE's expires_in is a countdown from when *it* issued the token, not
  // from "now" — the value doesn't change as time passes. If we recomputed
  // expireAt as Date.now() + expiresInSeconds on every revalidation of the
  // *same* token, the deadline would keep sliding into the future and never
  // actually arrive. Anchor it once, the first time we see a given token,
  // and keep that fixed point on subsequent calls for the same token.
  const previous = getSession();
  safeSet(TOKEN_KEY, input.token);
  safeSet(USER_KEY, JSON.stringify(input.user ?? {}));
  if (previous && previous.token === input.token && previous.expireAt > 0) {
    safeSet(EXPIRE_KEY, String(previous.expireAt));
    return;
  }
  const expiresInSeconds = Number(input.expiresInSeconds || 0);
  const expireAt =
    expiresInSeconds > 0 ? Date.now() + expiresInSeconds * 1000 : 0;
  safeSet(EXPIRE_KEY, String(expireAt));
}

export function clearSession(): void {
  safeRemove(TOKEN_KEY);
  safeRemove(USER_KEY);
  safeRemove(EXPIRE_KEY);
}

export function isAuthenticated(): boolean {
  const session = getSession();
  if (!session) {
    return false;
  }
  if (session.expireAt > 0 && Date.now() >= session.expireAt) {
    clearSession();
    return false;
  }
  return true;
}
