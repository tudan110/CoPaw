#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/_env.sh"

"${VEOPS_PYTHON_BIN}" "${SCRIPT_DIR}/veops_http.py" login
