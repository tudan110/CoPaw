#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
OUTPUT_DIR="${1:-$SCRIPT_DIR}"
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/cnos-inoe-agent.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT

CHART_SOURCE="$REPO_ROOT/deploy-all/helm/cnos-inoe-agent"
CHART_STAGE="$STAGE/cnos-inoe-agent"
mkdir -p "$CHART_STAGE/charts"
cp "$CHART_SOURCE/Chart.yaml" "$CHART_SOURCE/values.yaml" "$CHART_STAGE/"
cp -RL "$REPO_ROOT/deploy-all/portal/helm/digital-workforce-portal" \
  "$CHART_STAGE/charts/digital-workforce-portal"
cp -RL "$REPO_ROOT/deploy-all/qwenpaw/helm/qwenpaw" \
  "$CHART_STAGE/charts/qwenpaw"

if find "$CHART_STAGE" -type l -print -quit | grep -q .; then
  echo "error: staging chart contains a symbolic link" >&2
  exit 1
fi

helm dependency build "$CHART_STAGE" >/dev/null
# 保留已展开的依赖目录，避免父包同时携带重复的子 Chart tgz。
rm -f "$CHART_STAGE"/charts/*.tgz
mkdir -p "$OUTPUT_DIR"
PACKAGE_PATH="$(helm package "$CHART_STAGE" --destination "$OUTPUT_DIR" \
  | awk -F': ' '/Successfully packaged chart and saved it to:/ {print $2}')"

if [[ -z "$PACKAGE_PATH" || ! -f "$PACKAGE_PATH" ]]; then
  echo "error: helm package did not produce an archive" >&2
  exit 1
fi
if tar -tvzf "$PACKAGE_PATH" | grep -qE '^l'; then
  echo "error: packaged chart contains a symbolic link" >&2
  exit 1
fi
for required in \
  cnos-inoe-agent/Chart.yaml \
  cnos-inoe-agent/charts/qwenpaw/Chart.yaml \
  cnos-inoe-agent/charts/digital-workforce-portal/Chart.yaml; do
  if ! tar -tzf "$PACKAGE_PATH" | grep -Fxq "$required"; then
    echo "error: package is missing $required" >&2
    exit 1
  fi
done

printf '%s\n' "$PACKAGE_PATH"
