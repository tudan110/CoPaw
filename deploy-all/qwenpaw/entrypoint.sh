#!/bin/sh
# Substitute QWENPAW_PORT in supervisord template and start supervisord.
# Default port 8088; override at runtime with -e QWENPAW_PORT=3000.
set -e
export QWENPAW_PORT="${QWENPAW_PORT:-8088}"

WORKING_DIR="${QWENPAW_WORKING_DIR:-/app/working}"
SECRET_DIR="${QWENPAW_SECRET_DIR:-/app/working.secret}"
WORKING_BACKUP="/app/.working.backup"
SECRET_BACKUP="/app/.working.secret.backup"
PORTAL_CUSTOM_CHANNEL_DIR="${WORKING_DIR}/custom_channels"
PORTAL_CUSTOM_CHANNEL_FILE="${PORTAL_CUSTOM_CHANNEL_DIR}/portal_api.py"

if [ -d "$WORKING_BACKUP" ] && [ -z "$(ls -A "$WORKING_DIR" 2>/dev/null)" ]; then
  echo "Initializing working directory from backup..."
  cp -r "$WORKING_BACKUP"/* "$WORKING_DIR"/ 2>/dev/null || true
fi

# Always refresh the built-in knowledge-base skill *code* from the image
# backup. The PVC persists across image upgrades and is only seeded when
# empty, so an existing PVC otherwise keeps stale parser code and re-introduces
# bugs like xlsx/docx mojibake even after a fix ships in a new image. Only code
# is refreshed; the ingested DB under .../knowledge-base/data/ and any user
# content are left untouched.
KB_REL="workspaces/knowledge/skills/knowledge-base"
KB_SRC="${WORKING_BACKUP}/${KB_REL}"
KB_DST="${WORKING_DIR}/${KB_REL}"
if [ -d "$KB_SRC" ] && [ -d "$KB_DST" ]; then
  echo "Refreshing knowledge-base skill code from backup..."
  for item in api core domain providers retrieval server.py SKILL.md requirements.txt; do
    if [ -e "$KB_SRC/$item" ]; then
      rm -rf "$KB_DST/$item" 2>/dev/null || true
      cp -r "$KB_SRC/$item" "$KB_DST/" 2>/dev/null || true
    fi
  done
fi

if [ -d "$SECRET_BACKUP" ] && [ -z "$(ls -A "$SECRET_DIR" 2>/dev/null)" ]; then
  echo "Initializing secret directory from backup..."
  cp -r "$SECRET_BACKUP"/* "$SECRET_DIR"/ 2>/dev/null || true
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
