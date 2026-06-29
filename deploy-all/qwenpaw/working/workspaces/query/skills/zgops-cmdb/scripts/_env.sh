#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ZGOPS 凭证由设置页「CMDB / 资源导入」统一管理，运行时物化为环境变量
# （子进程继承 os.environ）。脚本只读环境变量，不再回退任何 .env / secrets
# 文件。缺失时给出指向设置页的明确报错。
: "${ZGOPS_BASE_URL:?未配置 ZGOPS_BASE_URL（请在设置页「CMDB / 资源导入」配置）}"

ZGOPS_CMDB_URL="${ZGOPS_BASE_URL%/}/cmdb/"
ZGOPS_API_BASE_URL="${ZGOPS_BASE_URL%/}/api"
ZGOPS_PYTHON_BIN="${ZGOPS_PYTHON_BIN:-python3}"
