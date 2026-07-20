#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# CMDB 统一复用设置页「平台」的 INOE 网关与访问令牌。所有 CMDB 请求由
# 网关根地址 + /cmdb/api/v0.1/... 组成，并使用 Authorization: Bearer。
: "${INOE_API_BASE_URL:?未配置 INOE_API_BASE_URL（请在设置页「平台」配置）}"
: "${INOE_API_TOKEN:?未配置 INOE_API_TOKEN（请在设置页「平台」配置）}"

INOE_CMDB_API_BASE_URL="${INOE_API_BASE_URL%/}/cmdb"
ZGOPS_PYTHON_BIN="${ZGOPS_PYTHON_BIN:-python3}"
