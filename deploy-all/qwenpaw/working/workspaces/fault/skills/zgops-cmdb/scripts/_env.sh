#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ZGOPS env resolution order (first existing file wins). Shared secrets
# are preferred; per-skill .env is only a legacy fallback:
#   1. $ZGOPS_ENV_FILE (explicit override)
#   2. $QWENPAW_WORKING_DIR/secrets/zgops-cmdb.env (or COPAW)
#   3. deploy-all/qwenpaw/working/secrets/zgops-cmdb.env (checkout fallback)
#   4. ~/.qwenpaw/secrets/zgops-cmdb.env (shared secrets)
#   5. per-skill .env (legacy fallback)
WORKING_DIR_GUESS="${QWENPAW_WORKING_DIR:-${COPAW_WORKING_DIR:-}}"
CHECKOUT_WORKING_DIR="$(cd "${SKILL_ROOT}/../../../.." && pwd)"
ENV_FILE=""
for _cand in \
  "${ZGOPS_ENV_FILE:-}" \
  "${WORKING_DIR_GUESS:+${WORKING_DIR_GUESS%/}/secrets/zgops-cmdb.env}" \
  "${CHECKOUT_WORKING_DIR%/}/secrets/zgops-cmdb.env" \
  "${HOME}/.qwenpaw/secrets/zgops-cmdb.env" \
  "${SKILL_ROOT}/.env"; do
  if [[ -n "${_cand}" && -f "${_cand}" ]]; then
    ENV_FILE="${_cand}"
    break
  fi
done

if [[ -z "${ENV_FILE}" ]]; then
  echo "未找到 CMDB 环境文件；请优先配置共享 secrets/zgops-cmdb.env，本技能 .env 仅作旧版回退" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

: "${ZGOPS_BASE_URL:?必须配置 ZGOPS_BASE_URL}"

ZGOPS_CMDB_URL="${ZGOPS_BASE_URL%/}/cmdb/"
ZGOPS_API_BASE_URL="${ZGOPS_BASE_URL%/}/api"
ZGOPS_PYTHON_BIN="${ZGOPS_PYTHON_BIN:-python3}"
