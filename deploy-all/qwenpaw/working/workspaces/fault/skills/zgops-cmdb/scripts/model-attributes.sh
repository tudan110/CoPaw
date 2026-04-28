#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/_env.sh"
TYPE_ID="${1:-}"

if [[ -z "${TYPE_ID}" ]]; then
  echo "用法：$(basename "$0") <type_id>" >&2
  exit 1
fi

JSON_RESPONSE="$("${SCRIPT_DIR}/fetch-json.sh" "/api/v0.1/ci_types/${TYPE_ID}/attributes")"

JSON_RESPONSE="${JSON_RESPONSE}" "${VEOPS_PYTHON_BIN}" - <<'PY'
import json
import os

payload = json.loads(os.environ["JSON_RESPONSE"])["响应体"]
print("ID\t属性名\t显示名\t值类型\t必填\t唯一\t索引\t列表\t默认展示")
for item in payload["attributes"]:
    print(
        f'{item["id"]}\t{item["name"]}\t{item["alias"]}\t{item["value_type"]}\t'
        f'{item["is_required"]}\t{item["is_unique"]}\t{item["is_index"]}\t'
        f'{item["is_list"]}\t{item["default_show"]}'
    )
PY
