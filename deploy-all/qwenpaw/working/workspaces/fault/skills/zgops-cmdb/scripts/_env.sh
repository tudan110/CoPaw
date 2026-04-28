#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${SKILL_ROOT}/.env"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "缺少环境变量文件：${ENV_FILE}" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

: "${VEOPS_BASE_URL:?必须配置 VEOPS_BASE_URL}"

VEOPS_CMDB_URL="${VEOPS_BASE_URL%/}/cmdb/"
VEOPS_API_BASE_URL="${VEOPS_BASE_URL%/}/api"
VEOPS_PYTHON_BIN="${VEOPS_PYTHON_BIN:-python3}"
