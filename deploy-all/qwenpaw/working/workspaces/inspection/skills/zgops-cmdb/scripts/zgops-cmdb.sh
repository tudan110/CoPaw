#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMMAND="${1:-}"

usage() {
  cat <<'EOF'
用法：
  scripts/zgops-cmdb.sh login
  scripts/zgops-cmdb.sh fetch <api_path>
  scripts/zgops-cmdb.sh find-project [project_name]
  scripts/zgops-cmdb.sh app-topology <project_name> [--output markdown|echarts|json]
  scripts/zgops-cmdb.sh list-models
  scripts/zgops-cmdb.sh model-attributes <type_id>
  scripts/zgops-cmdb.sh model-relations <type_id>
  scripts/zgops-cmdb.sh analyze [--mode <mode>] [--output <output>]
  scripts/zgops-cmdb.sh inoe-stat [count|group|child|child-group|group-attr|types] [--resource_type <type>] [--type_id <id>] [--attr <attr>] [--output json|markdown]
EOF
}

if [[ -z "${COMMAND}" ]]; then
  usage >&2
  exit 1
fi

shift || true

case "${COMMAND}" in
  login)
    exec "${SCRIPT_DIR}/login.sh" "$@"
    ;;
  fetch)
    exec "${SCRIPT_DIR}/fetch-json.sh" "$@"
    ;;
  find-project)
    exec "${SCRIPT_DIR}/find-project.sh" "$@"
    ;;
  app-topology)
    source "${SCRIPT_DIR}/_env.sh"
    exec "${VEOPS_PYTHON_BIN}" "${SCRIPT_DIR}/app_topology.py" "$@"
    ;;
  list-models)
    exec "${SCRIPT_DIR}/list-models.sh" "$@"
    ;;
  model-attributes)
    exec "${SCRIPT_DIR}/model-attributes.sh" "$@"
    ;;
  model-relations)
    exec "${SCRIPT_DIR}/model-relations.sh" "$@"
    ;;
  analyze)
    source "${SCRIPT_DIR}/_env.sh"
    exec "${VEOPS_PYTHON_BIN}" "${SCRIPT_DIR}/analyze_cmdb.py" "$@"
    ;;
  inoe-stat)
    source "${SCRIPT_DIR}/_env.sh"
    exec "${VEOPS_PYTHON_BIN}" "${SCRIPT_DIR}/inoe_cmdb_stats.py" "$@"
    ;;
  *)
    echo "未知命令：${COMMAND}" >&2
    usage >&2
    exit 1
    ;;
esac
