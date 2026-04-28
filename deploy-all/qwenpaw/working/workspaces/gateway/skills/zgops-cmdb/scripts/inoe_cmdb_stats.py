#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""INOE 网关 CMDB 统计接口查询。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests


RESOURCE_TYPE_MAP = {
    "database": {"type_id": "5", "label": "数据库"},
    "db": {"type_id": "5", "label": "数据库"},
    "数据库": {"type_id": "5", "label": "数据库"},
    "middleware": {"type_id": "6", "label": "中间件"},
    "middle": {"type_id": "6", "label": "中间件"},
    "中间件": {"type_id": "6", "label": "中间件"},
    "network": {"type_id": "4", "label": "网络设备"},
    "network_device": {"type_id": "4", "label": "网络设备"},
    "网络设备": {"type_id": "4", "label": "网络设备"},
    "网络": {"type_id": "4", "label": "网络设备"},
    "server": {"type_id": "2", "label": "计算资源"},
    "compute": {"type_id": "2", "label": "计算资源"},
    "计算资源": {"type_id": "2", "label": "计算资源"},
    "服务器": {"type_id": "2", "label": "计算资源"},
    "os": {"type_id": "17", "label": "操作系统"},
    "operating_system": {"type_id": "17", "label": "操作系统"},
    "操作系统": {"type_id": "17", "label": "操作系统"},
}

DEFAULT_STAT_PATHS = {
    "count": "/cmdb/v0.1/ci/count",
    "group": "/cmdb/v0.1/ci/count/group",
    "child": "/cmdb/v0.1/ci/count/child",
    "child-group": "/cmdb/v0.1/ci/count/child/group",
    "group-attr": "/cmdb/v0.1/ci/count/group/attr",
}

STAT_PATH_ENV = {
    "count": "INOE_CMDB_COUNT_PATH",
    "group": "INOE_CMDB_COUNT_GROUP_PATH",
    "child": "INOE_CMDB_COUNT_CHILD_PATH",
    "child-group": "INOE_CMDB_COUNT_CHILD_GROUP_PATH",
    "group-attr": "INOE_CMDB_COUNT_GROUP_ATTR_PATH",
}

ATTR_ALIASES = {
    "vendor": "vendor",
    "manufacturer": "vendor",
    "manufacture": "vendor",
    "factory": "vendor",
    "厂商": "vendor",
    "厂家": "vendor",
    "制造商": "vendor",
    "brand": "vendor",
    "品牌": "vendor",
    "db_type": "db_type",
    "database_type": "db_type",
    "数据库类型": "db_type",
    "os_type": "os_type",
    "系统类型": "os_type",
    "dev_class": "dev_class",
    "设备类型": "dev_class",
}

COUNT_FIELDS = [
    ("total", "总数"),
    ("normalCount", "正常"),
    ("abnormalCount", "异常"),
    ("emergencyCount", "告警"),
    ("severeCount", "严重"),
    ("minorCount", "次要"),
    ("warningCount", "预警"),
    ("unmonitoredCount", "未监控"),
]


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_skill_env() -> None:
    load_env_file(Path(__file__).resolve().parent.parent / ".env")


load_skill_env()


def normalize_resource(resource_type: str | None, type_id: str | None) -> dict[str, str]:
    if type_id:
        return {"type_id": str(type_id), "label": f"type={type_id}", "type_source": "explicit"}
    raw = (resource_type or "database").strip()
    key = raw.lower().replace("-", "_").replace(" ", "_")
    fallback = RESOURCE_TYPE_MAP.get(key)
    if fallback:
        return {**fallback, "type_source": "fallback"}
    return {"type_id": raw, "label": raw, "type_source": "raw"}


def normalize_attr(attr: str | None) -> str | None:
    if not attr:
        return None
    raw = attr.strip()
    key = raw.lower().replace("-", "_").replace(" ", "_")
    return ATTR_ALIASES.get(key, raw)


def make_error(code: int, msg: str) -> dict[str, Any]:
    return {"code": code, "msg": msg, "data": None}


def api_base_url() -> str:
    return (os.getenv("INOE_CMDB_API_BASE_URL") or os.getenv("INOE_API_BASE_URL") or "").strip().rstrip("/")


def api_token() -> str:
    return (os.getenv("INOE_API_TOKEN") or "").strip()


def curl_enabled() -> bool:
    return os.getenv("INOE_ENABLE_CURL_FALLBACK", "true").lower() in {"1", "true", "yes", "on"}


def stat_path(stat: str) -> str:
    return (os.getenv(STAT_PATH_ENV.get(stat, "")) or DEFAULT_STAT_PATHS[stat]).strip()


def ci_types_path() -> str:
    return (os.getenv("INOE_CMDB_TYPES_PATH") or "/cmdb/v0.1/ci_types").strip()


def ci_type_groups_path() -> str:
    return (os.getenv("INOE_CMDB_TYPE_GROUPS_PATH") or "/cmdb/v0.1/ci_types/groups").strip()


def parse_json_response(text: str) -> dict[str, Any]:
    if not text.strip():
        return make_error(500, "接口返回空响应")
    data = json.loads(text)
    if isinstance(data, dict):
        return data
    return {"code": 200, "msg": "操作成功", "data": data}


def curl_get(url: str, headers: dict[str, str], timeout_seconds: int) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile(delete=False) as body_file:
        body_path = body_file.name
    args = [
        "curl",
        "-sS",
        "-X",
        "GET",
        "--connect-timeout",
        str(timeout_seconds),
        "--max-time",
        str(timeout_seconds),
        "-o",
        body_path,
        "-w",
        "%{http_code}",
    ]
    for key, value in headers.items():
        args.extend(["-H", f"{key}: {value}"])
    args.append(url)
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=max(timeout_seconds + 5, 10),
            check=False,
        )
        if completed.returncode != 0:
            return make_error(500, (completed.stderr or completed.stdout or "curl 请求失败").strip())
        status_code = int((completed.stdout or "").strip() or "0")
        response_text = Path(body_path).read_text(encoding="utf-8", errors="replace")
        if status_code >= 400:
            return make_error(status_code, response_text[:500])
        return parse_json_response(response_text)
    except json.JSONDecodeError as error:
        return make_error(500, f"curl 响应解析失败: {error}")
    except subprocess.TimeoutExpired:
        return make_error(408, "请求超时")
    finally:
        try:
            os.unlink(body_path)
        except OSError:
            pass


def request_get(path: str, params: dict[str, Any]) -> dict[str, Any]:
    base_url = api_base_url()
    token = api_token()
    if not base_url:
        return make_error(400, "未设置 INOE_API_BASE_URL")
    if not token:
        return make_error(401, "未设置 INOE_API_TOKEN")
    url = f"{base_url}{path}?{urlencode(params)}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json, text/plain, */*"}
    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code >= 400:
            return make_error(response.status_code, response.text[:500])
        return parse_json_response(response.text)
    except (requests.ConnectionError, requests.Timeout, OSError):
        if curl_enabled():
            return curl_get(url, headers, 30)
        return make_error(408, "请求失败且 curl fallback 未启用")
    except json.JSONDecodeError as error:
        return make_error(500, f"响应解析失败: {error}")
    except requests.RequestException as error:
        if curl_enabled():
            return curl_get(url, headers, 30)
        return make_error(500, f"请求异常: {error}")


def list_from_payload(payload: dict[str, Any], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    candidates: list[Any] = [payload.get("data"), payload]
    for candidate in candidates:
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
        if isinstance(candidate, dict):
            for key in keys:
                value = candidate.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
    return []


def normalize_match_text(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def match_tokens(*values: Any) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        text = normalize_match_text(value)
        if text:
            tokens.add(text)
            tokens.add(text.replace("_", ""))
    return tokens


def resource_match_tokens(resource_type: str | None) -> set[str]:
    raw = (resource_type or "database").strip()
    tokens = match_tokens(raw)
    fallback = RESOURCE_TYPE_MAP.get(normalize_match_text(raw))
    if fallback:
        tokens.update(match_tokens(fallback.get("label"), fallback.get("type_id")))
    return tokens


def query_type_catalog() -> dict[str, Any]:
    groups_payload = request_get(ci_type_groups_path(), {"need_other": "true"})
    types_payload = request_get(ci_types_path(), {"per_page": 200})
    groups = list_from_payload(groups_payload, ("groups", "ci_type_groups", "ciTypeGroups"))
    ci_types = list_from_payload(types_payload, ("ci_types", "ciTypes", "types"))
    return {
        "groups": groups,
        "ci_types": ci_types,
        "groups_error": groups_payload.get("msg") if groups_payload.get("code") not in {None, 200} else None,
        "types_error": types_payload.get("msg") if types_payload.get("code") not in {None, 200} else None,
    }


def resolve_resource(resource_type: str | None, type_id: str | None, *, dynamic_type: bool = True) -> dict[str, str]:
    if type_id:
        return {"type_id": str(type_id), "label": f"type={type_id}", "type_source": "explicit"}
    fallback = normalize_resource(resource_type, None)
    if not dynamic_type:
        return fallback

    wanted = resource_match_tokens(resource_type)
    catalog = query_type_catalog()

    # 统计接口的 type 优先对应模型分组 id，例如“中间件”组 id=6。
    for group in catalog["groups"]:
        tokens = match_tokens(group.get("id"), group.get("name"), group.get("alias"))
        if wanted & tokens:
            return {
                "type_id": str(group["id"]),
                "label": str(group.get("name") or group.get("alias") or f"type={group['id']}"),
                "type_source": "cmdb_group",
            }

    # 如果用户输入的是具体模型名，例如 mysql/Kafka，则回落到 CI type id。
    for item in catalog["ci_types"]:
        tokens = match_tokens(item.get("id"), item.get("name"), item.get("alias"))
        if wanted & tokens:
            return {
                "type_id": str(item["id"]),
                "label": str(item.get("alias") or item.get("name") or f"type={item['id']}"),
                "type_source": "ci_type",
            }

    return fallback


def query_types() -> dict[str, Any]:
    catalog = query_type_catalog()
    rows: list[dict[str, Any]] = []
    for group in catalog["groups"]:
        children = [
            {
                "id": child.get("id"),
                "name": child.get("name"),
                "alias": child.get("alias"),
            }
            for child in group.get("ci_types", []) or []
            if isinstance(child, dict)
        ]
        rows.append({
            "id": group.get("id"),
            "name": group.get("name") or group.get("alias"),
            "kind": "group",
            "children": children,
        })
    return {
        "code": 200,
        "msg": "操作成功",
        "data": rows,
        "_query": {
            "stat": "types",
            "path": ci_type_groups_path(),
            "types_path": ci_types_path(),
            "groups_error": catalog.get("groups_error"),
            "types_error": catalog.get("types_error"),
        },
    }


def query_stat(stat: str, resource_type: str | None, type_id: str | None, attr: str | None, *, dynamic_type: bool = True) -> dict[str, Any]:
    if stat not in DEFAULT_STAT_PATHS:
        return make_error(400, f"不支持的统计类型: {stat}")
    resource = resolve_resource(resource_type, type_id, dynamic_type=dynamic_type)
    normalized_attr = normalize_attr(attr)
    params: dict[str, Any] = {"type": resource["type_id"]}
    if normalized_attr:
        params["attr"] = normalized_attr
    path = stat_path(stat)
    payload = request_get(path, params)
    payload["_query"] = {
        "stat": stat,
        "resource_type": resource["label"],
        "type": resource["type_id"],
        "type_source": resource.get("type_source"),
        "attr": normalized_attr,
        "path": path,
    }
    return payload


def rows_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def value_text(value: Any) -> str:
    if value is None or value == "":
        return "-"
    return str(value)


def row_name(row: dict[str, Any], index: int) -> str:
    for key in ("resourceType", "resourceClass", "vendor", "name", "alias", "type"):
        if row.get(key):
            return str(row[key])
    return f"分组{index}"


def markdown_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "暂无数据。"
    headers = ["分组", *[label for _, label in COUNT_FIELDS]]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for index, row in enumerate(rows, start=1):
        values = [row_name(row, index), *[value_text(row.get(field)) for field, _ in COUNT_FIELDS]]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def build_chart(title: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    names = [row_name(row, index) for index, row in enumerate(rows, start=1)]
    totals = [row.get("total") or 0 for row in rows]
    return {
        "title": {"text": title, "left": "center"},
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "grid": {"left": 48, "right": 24, "bottom": 72, "top": 56},
        "xAxis": {"type": "category", "data": names, "axisLabel": {"rotate": 25}},
        "yAxis": {"type": "value", "name": "数量"},
        "series": [{"name": "总数", "type": "bar", "barMaxWidth": 42, "data": totals}],
    }


def render_markdown(payload: dict[str, Any]) -> str:
    query = payload.get("_query") or {}
    if query.get("stat") == "types":
        return render_types_markdown(payload)

    title = f"{query.get('resource_type', '资源')}统计"
    if query.get("attr") == "vendor":
        title = f"{query.get('resource_type', '资源')}制造商分布统计"
    elif query.get("attr"):
        title = f"{query.get('resource_type', '资源')}按 {query.get('attr')} 分布统计"

    if payload.get("code") not in {None, 200}:
        return f"# {title}\n\n查询失败：{payload.get('msg') or payload}"

    rows = rows_from_payload(payload)
    lines = [
        f"# {title}",
        "",
        f"- 接口：`{query.get('path')}?type={query.get('type')}" + (f"&attr={query.get('attr')}`" if query.get("attr") else "`"),
        f"- 类型来源：`{query.get('type_source') or '-'}`",
        f"- 返回分组：{len(rows)} 个",
        "",
        markdown_table(rows),
    ]
    if rows:
        lines.extend(["", "```echarts", json.dumps(build_chart(title, rows), ensure_ascii=False, indent=2), "```"])
    return "\n".join(lines)


def render_types_markdown(payload: dict[str, Any]) -> str:
    rows = rows_from_payload(payload)
    lines = [
        "# CMDB 资源类型目录",
        "",
        f"- 分组接口：`{(payload.get('_query') or {}).get('path')}`",
        f"- 分组数量：{len(rows)}",
        "",
        "| 分组ID | 分组名称 | 子模型 |",
        "| --- | --- | --- |",
    ]
    for row in rows:
        children = row.get("children") or []
        child_text = "、".join(
            f"{child.get('alias') or child.get('name')}({child.get('id')})"
            for child in children
            if isinstance(child, dict)
        )
        lines.append(f"| {value_text(row.get('id'))} | {value_text(row.get('name'))} | {child_text or '-'} |")
    query = payload.get("_query") or {}
    errors = [query.get("groups_error"), query.get("types_error")]
    errors = [str(error) for error in errors if error]
    if errors:
        lines.extend(["", "元数据查询提示：" + "；".join(errors)])
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="查询 INOE 网关 CMDB 统计接口")
    parser.add_argument("stat", nargs="?", default="group", choices=sorted([*DEFAULT_STAT_PATHS, "types"]), help="统计接口类型")
    parser.add_argument("--resource_type", default="database", help="database/middleware/network/server/os 或中文名称")
    parser.add_argument("--type_id", help="直接指定 CMDB type id，优先级高于 resource_type")
    parser.add_argument("--attr", help="分组字段，例如 vendor/制造商/厂商/db_type/os_type/dev_class")
    parser.add_argument("--no_dynamic_type", action="store_true", help="禁用 CMDB 元数据查询，只使用内置兜底映射")
    parser.add_argument("--output", choices=["json", "markdown"], default="markdown")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.stat == "types":
        payload = query_types()
    else:
        payload = query_stat(
            args.stat,
            args.resource_type,
            args.type_id,
            args.attr,
            dynamic_type=not args.no_dynamic_type,
        )
    if args.output == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(payload))
    return 0 if payload.get("code") in {None, 200} else 1


if __name__ == "__main__":
    sys.exit(main())
