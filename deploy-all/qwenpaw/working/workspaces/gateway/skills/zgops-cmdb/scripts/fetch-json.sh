#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/_env.sh"

API_PATH="${1:-}"

if [[ -z "${API_PATH}" ]]; then
  echo "用法：$(basename "$0") /api/v0.1/..." >&2
  exit 1
fi

if [[ "${API_PATH}" != /* ]]; then
  API_PATH="/${API_PATH}"
fi

"${VEOPS_PYTHON_BIN}" "${SCRIPT_DIR}/veops_http.py" fetch "${API_PATH}"
