#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/_env.sh"

TYPE_ID="${1:-}"

if [[ -z "${TYPE_ID}" ]]; then
  echo "用法：$(basename "$0") <type_id>" >&2
  exit 1
fi

JSON_RESPONSE="$("${SCRIPT_DIR}/fetch-json.sh" "/api/v0.1/ci_type_relations?ci_type_id=${TYPE_ID}")"

TYPE_ID="${TYPE_ID}" JSON_RESPONSE="${JSON_RESPONSE}" python - <<'PY'
import json
import os

type_id = int(os.environ.get("TYPE_ID", "0"))
payload = json.loads(os.environ["JSON_RESPONSE"])["响应体"]
relations = payload.get("relations", [])
result = []

for item in relations:
    parent = item.get("parent") or {}
    child = item.get("child") or {}
    if parent.get("id") != type_id and child.get("id") != type_id:
        continue
    result.append(
        {
            "来源模型": parent.get("name", ""),
            "来源显示名": parent.get("alias", ""),
            "关系类型": (item.get("relation_type") or {}).get("name", "") or item.get("relation_type_name", ""),
            "目标模型": child.get("name", ""),
            "目标显示名": child.get("alias", ""),
            "约束": item.get("constraint", ""),
            "属性映射": item.get("attr_map") or item.get("attribute_map"),
        }
    )

print(json.dumps(result, ensure_ascii=False, indent=2))
PY
