/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_COPAW_API_BASE_URL?: string;
  readonly VITE_COPAW_FALLBACK_AGENT_ID?: string;
  readonly VITE_COPAW_PROXY_TARGET?: string;
  readonly VITE_PORTAL_APP_TITLE?: string;
  readonly VITE_PORTAL_GATEWAY_AGENT_ID?: string;
  readonly VITE_PORTAL_GATEWAY_DEFAULT_PROVIDER_ID?: string;
  readonly VITE_PORTAL_GATEWAY_DEFAULT_MODEL_ID?: string;
  readonly VITE_PORTAL_API_BASE_URL?: string;
  readonly VITE_PORTAL_PROXY_TARGET?: string;
  readonly VITE_PORTAL_REAL_ALARM_POLL_ENABLED?: string;
  readonly VITE_SSO_ENABLED?: string;
  readonly VITE_SSO_LOGIN_URL?: string;
  readonly VITE_SSO_INOE_PORT?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

interface Window {
  __PORTAL_RUNTIME_CONFIG__?: {
    appTitle?: string;
    gatewayAgentId?: string;
    gatewayDefaultProviderId?: string;
    gatewayDefaultModelId?: string;
    portalApiBaseUrl?: string;
    realAlarmPollEnabled?: boolean;
    ssoEnabled?: boolean;
    ssoLoginUrl?: string;
    ssoInoePort?: string;
  };
}
