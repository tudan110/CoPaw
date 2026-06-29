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

# 找到配置文件就 source；没有文件也可以——配置可由设置页「CMDB / 资源导入」
# 物化到环境变量（子进程继承 os.environ）。最后统一校验 ZGOPS_BASE_URL。
if [[ -n "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

: "${ZGOPS_BASE_URL:?未配置 ZGOPS_BASE_URL（请在设置页「CMDB / 资源导入」配置，或提供 secrets/zgops-cmdb.env）}"

ZGOPS_CMDB_URL="${ZGOPS_BASE_URL%/}/cmdb/"
ZGOPS_API_BASE_URL="${ZGOPS_BASE_URL%/}/api"
ZGOPS_PYTHON_BIN="${ZGOPS_PYTHON_BIN:-python3}"
