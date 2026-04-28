#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/_env.sh"

JSON_RESPONSE="$("${SCRIPT_DIR}/fetch-json.sh" "/api/v0.1/ci_types?per_page=200")"

JSON_RESPONSE="${JSON_RESPONSE}" "${VEOPS_PYTHON_BIN}" - <<'PY'
import json
import os

payload = json.loads(os.environ["JSON_RESPONSE"])["响应体"]
print("ID\t模型名\t显示名\t唯一键")
for item in payload["ci_types"]:
    print(f'{item["id"]}\t{item["name"]}\t{item["alias"]}\t{item["unique_key"]}')
PY
