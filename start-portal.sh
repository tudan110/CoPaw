#!/usr/bin/env bash

# 兼容 sh 调用：若非 bash 则自动切换到 bash 执行
if [ -z "$BASH_VERSION" ]; then
    exec bash "$0" "$@"
fi

set -euo pipefail
trap '' HUP

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORTAL_DIR="$ROOT_DIR/portal"
PORT="${PORT:-5173}"
CLEAN_START="${CLEAN_START:-0}"

run_portal_dev() {
  local -a cmd=("pnpm" "dev" "--host" "0.0.0.0" "--strictPort" "--port" "$PORT")
  if [[ "${1:-}" == "--force" ]]; then
    cmd=("pnpm" "dev" "--force" "--host" "0.0.0.0" "--strictPort" "--port" "$PORT")
  fi

  if [[ ! -t 0 ]]; then
    echo "[start] Detected detached/non-interactive launch; shielding Vite from SIGHUP."
    exec nohup "${cmd[@]}" </dev/null
  fi

  exec "${cmd[@]}"
}

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "[start] Missing required command: $cmd"
    exit 1
  fi
}

require_cmd pnpm

if [[ ! -d "$PORTAL_DIR" ]]; then
  echo "[start] Portal directory not found: $PORTAL_DIR"
  exit 1
fi

echo "[start] Installing dependencies with pnpm install..."
cd "$PORTAL_DIR"
pnpm install

# ---------------------------------------------------------------------------
# Auto-detect dependency drift to invalidate Vite's optimizeDeps cache.
#
# When package.json or pnpm-lock.yaml change, the pre-bundled deps under
# node_modules/.vite/deps/ keep their old hash query strings, but the new
# dev server emits a fresh hash. Long-lived browser tabs then request URLs
# that no longer exist (".../deps/react.js?v=OLDHASH") and white-screen on
# "Failed to fetch dynamically imported module".
#
# We hash both manifests, store the digest at .vite/.deps-stamp, and force
# a clean re-optimization whenever the digest moves. CLEAN_START=1 still
# wins as an explicit override.
# ---------------------------------------------------------------------------

DEPS_FINGERPRINT_FILE="$PORTAL_DIR/node_modules/.vite/.deps-stamp"
AUTO_CLEAN=0

compute_deps_fingerprint() {
  local hasher
  if command -v sha256sum >/dev/null 2>&1; then
    hasher="sha256sum"
  elif command -v shasum >/dev/null 2>&1; then
    hasher="shasum -a 256"
  else
    echo ""
    return
  fi
  cat "$PORTAL_DIR/package.json" "$PORTAL_DIR/pnpm-lock.yaml" 2>/dev/null \
    | $hasher | awk '{print $1}'
}

CURRENT_FINGERPRINT="$(compute_deps_fingerprint || true)"
if [[ -n "$CURRENT_FINGERPRINT" ]]; then
  PREVIOUS_FINGERPRINT=""
  if [[ -f "$DEPS_FINGERPRINT_FILE" ]]; then
    PREVIOUS_FINGERPRINT="$(cat "$DEPS_FINGERPRINT_FILE" 2>/dev/null || true)"
  fi
  if [[ "$CURRENT_FINGERPRINT" != "$PREVIOUS_FINGERPRINT" ]]; then
    AUTO_CLEAN=1
    echo "[start] Dependency fingerprint changed — Vite cache will be cleared."
  fi
fi

if [[ "$CLEAN_START" == "1" || "$AUTO_CLEAN" == "1" ]]; then
  if [[ "$CLEAN_START" == "1" ]]; then
    echo "[start] CLEAN_START=1, clearing Vite cache..."
  fi
  rm -rf "$PORTAL_DIR/node_modules/.vite" "$PORTAL_DIR/dist"
  if [[ -n "$CURRENT_FINGERPRINT" ]]; then
    mkdir -p "$PORTAL_DIR/node_modules/.vite"
    printf '%s' "$CURRENT_FINGERPRINT" > "$DEPS_FINGERPRINT_FILE"
  fi
  echo "[start] Starting portal on :$PORT with forced dependency re-optimization..."
  echo "[start] strictPort enabled; if :$PORT is occupied, startup will fail instead of switching ports."
  run_portal_dev --force
else
  if [[ -n "$CURRENT_FINGERPRINT" ]]; then
    mkdir -p "$PORTAL_DIR/node_modules/.vite"
    printf '%s' "$CURRENT_FINGERPRINT" > "$DEPS_FINGERPRINT_FILE"
  fi
  echo "[start] Starting portal on :$PORT ..."
  echo "[start] strictPort enabled; if :$PORT is occupied, startup will fail instead of switching ports."
  echo "[start] Using normal Vite startup to avoid mixed optimized-deps hashes on first load."
  run_portal_dev
fi
