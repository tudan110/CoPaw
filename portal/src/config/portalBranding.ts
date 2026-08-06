const DEFAULT_PORTAL_APP_TITLE = "智观 Paw";
const DEFAULT_PORTAL_GATEWAY_AGENT_ID = "gateway";

function normalizeAppTitle(value: string | undefined): string | undefined {
  const trimmedValue = value?.trim();
  return trimmedValue ? trimmedValue : undefined;
}

function normalizeAgentId(value: string | undefined): string | undefined {
  const trimmedValue = value?.trim();
  return trimmedValue ? trimmedValue : undefined;
}

export const portalAppTitle =
  normalizeAppTitle(window.__PORTAL_RUNTIME_CONFIG__?.appTitle) ??
  normalizeAppTitle(import.meta.env.VITE_PORTAL_APP_TITLE) ??
  DEFAULT_PORTAL_APP_TITLE;

export const portalGatewayAgentId =
  normalizeAgentId(window.__PORTAL_RUNTIME_CONFIG__?.gatewayAgentId) ??
  normalizeAgentId(import.meta.env.VITE_PORTAL_GATEWAY_AGENT_ID) ??
  DEFAULT_PORTAL_GATEWAY_AGENT_ID;

export function applyPortalDocumentTitle() {
  document.title = portalAppTitle;
}
