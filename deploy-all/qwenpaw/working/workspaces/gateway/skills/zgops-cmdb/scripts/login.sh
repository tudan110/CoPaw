#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/_env.sh"

"${ZGOPS_PYTHON_BIN}" "${SCRIPT_DIR}/zgops_http.py" login
