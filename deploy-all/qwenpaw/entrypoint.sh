#!/bin/sh
# Substitute QWENPAW_PORT in supervisord template and start supervisord.
# Default port 8088; override at runtime with -e QWENPAW_PORT=3000.
set -e
export QWENPAW_PORT="${QWENPAW_PORT:-8088}"

WORKING_DIR="${QWENPAW_WORKING_DIR:-/app/working}"
SECRET_DIR="${QWENPAW_SECRET_DIR:-/app/working.secret}"
WORKING_SEED="/app/share/qwenpaw-seed"
SECRET_BACKUP="/app/.working.secret.backup"
PORTAL_CUSTOM_CHANNEL_DIR="${WORKING_DIR}/custom_channels"
PORTAL_CUSTOM_CHANNEL_FILE="${PORTAL_CUSTOM_CHANNEL_DIR}/portal_api.py"

mkdir -p "$WORKING_DIR" "$SECRET_DIR"
if [ -d "$WORKING_SEED" ] && [ -z "$(ls -A "$WORKING_DIR" 2>/dev/null)" ]; then
  echo "Initializing working directory from universal image seed..."
  cp -a "$WORKING_SEED/." "$WORKING_DIR/"
fi

if [ -d "$SECRET_BACKUP" ] && [ -z "$(ls -A "$SECRET_DIR" 2>/dev/null)" ]; then
  echo "Initializing model configuration from image backup..."
  cp -a "$SECRET_BACKUP/." "$SECRET_DIR/"
fi

echo "Syncing portal_api custom channel..."
mkdir -p "$PORTAL_CUSTOM_CHANNEL_DIR"
cat > "$PORTAL_CUSTOM_CHANNEL_FILE" <<'PY'
from qwenpaw.extensions.api.portal_backend import register_app_routes


__all__ = ["register_app_routes"]
PY

envsubst '${QWENPAW_PORT}' \
  < /etc/supervisor/conf.d/supervisord.conf.template \
  > /etc/supervisor/conf.d/supervisord.conf
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
