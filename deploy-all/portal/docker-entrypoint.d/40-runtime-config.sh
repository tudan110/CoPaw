#!/bin/sh
set -eu

# Emit runtime-config.js from container env at pod startup, so these knobs are
# tunable via `helm upgrade` (edit values env + restart) WITHOUT rebuilding the
# portal image. The frontend reads window.__PORTAL_RUNTIME_CONFIG__ at load.

esc() {
  # JSON-string-escape: backslash and double-quote.
  printf '%s' "${1:-}" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

PORTAL_APP_TITLE_ESCAPED=$(esc "${PORTAL_APP_TITLE:-}")
SSO_INOE_PORT_ESCAPED=$(esc "${PORTAL_SSO_INOE_PORT:-}")
SSO_LOGIN_URL_ESCAPED=$(esc "${PORTAL_SSO_LOGIN_URL:-}")

# ssoEnabled must be a real JS boolean (the frontend checks `=== true`).
case "$(printf '%s' "${PORTAL_SSO_ENABLED:-}" | tr '[:upper:]' '[:lower:]')" in
  1 | true | yes | on) SSO_ENABLED=true ;;
  *) SSO_ENABLED=false ;;
esac

cat >/usr/share/nginx/html/runtime-config.js <<EOF
window.__PORTAL_RUNTIME_CONFIG__ = Object.freeze({
  appTitle: "${PORTAL_APP_TITLE_ESCAPED}",
  ssoEnabled: ${SSO_ENABLED},
  ssoInoePort: "${SSO_INOE_PORT_ESCAPED}",
  ssoLoginUrl: "${SSO_LOGIN_URL_ESCAPED}"
});
EOF
