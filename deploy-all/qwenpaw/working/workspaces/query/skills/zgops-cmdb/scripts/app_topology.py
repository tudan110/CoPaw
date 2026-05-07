#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
from collections import defaultdict
from pathlib import Path
from typing import Any

from find_project import (
    CmdbHttpClient,
    _clean_text,
    _load_env_file,
    _match_projects,
    _normalize_token,
    _project_name,
)


TYPE_BUCKET_PRIORITY = {
    "product": 10,
    "PhysicalMachine": 20,
    "vserver": 30,
    "docker": 40,
    "database": 50,
    "mysql": 51,
    "PostgreSQL": 52,
    "redis": 53,
    "Kafka": 54,
    "elasticsearch": 55,
    "nginx": 56,
    "apache": 57,
    "networkdevice": 60,
}

SOFTWARE_TYPES = {
    "database",
    "mysql",
    "PostgreSQL",
    "redis",
    "Kafka",
    "elasticsearch",
    "nginx",
    "apache",
}


# Some VEOPS deployments encode a project's relationships as **inline attributes** on
# the project CI itself instead of (or in addition to) `ci_relations` rows — e.g. the
# project document carries `Kafka`, `mysql`, `redis`, `operatingsystem` fields whose
# values are the names of related CIs. The map below is the fallback catalog used
# when the live `/api/v0.1/ci_types` lookup is unavailable; keys are normalized
# (lower-case, punctuation-stripped via `_normalize_token`), values are the
# canonical `ci_type` to search.
INLINE_RELATION_TYPES = {
    "kafka": "Kafka",
    "redis": "redis",
    "elasticsearch": "elasticsearch",
    "nginx": "nginx",
    "apache": "apache",
    "mysql": "mysql",
    "postgresql": "PostgreSQL",
    "database": "database",
    "operatingsystem": "operatingsystem",
    "physicalmachine": "PhysicalMachine",
    "vserver": "vserver",
    "docker": "docker",
    "networkdevice": "networkdevice",
    "product": "product",
}


# Per-ci_type list of attributes that may carry a CI's display name. Used to
# match the values of inline relation attributes (which are typically display
# names like "kafka-web01") against actual CIs returned by `/api/v0.1/ci/s`.
_CI_TYPE_NAME_FIELDS: dict[str, list[str]] = {
    "vserver": ["vserver_name", "name", "private_ip", "manage_ip"],
    "docker": ["middleware_name", "name", "manage_ip", "private_ip"],
    "database": ["db_instance", "name", "manage_ip", "db_ip"],
    "mysql": ["db_instance", "name", "manage_ip", "db_ip"],
    "PostgreSQL": ["db_instance", "name", "manage_ip", "db_ip"],
    "redis": ["middleware_name", "name", "middleware_ip", "manage_ip"],
    "Kafka": ["middleware_name", "name", "middleware_ip", "manage_ip"],
    "elasticsearch": ["middleware_name", "name", "middleware_ip", "manage_ip"],
    "nginx": ["middleware_name", "name", "middleware_ip", "manage_ip"],
    "apache": ["middleware_name", "name", "middleware_ip", "manage_ip"],
    "networkdevice": ["dev_name", "name", "manage_ip"],
    "PhysicalMachine": ["host_name", "name", "private_ip", "manage_ip"],
    "operatingsystem": ["name", "os_name", "host_name"],
    "product": ["product_name", "name"],
    "project": ["project_name", "name"],
}


def _default_env_file() -> Path:
    return Path(__file__).resolve().parents[1] / ".env"


def _split_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            text = _clean_text(item)
            if text:
                result.append(text)
        return result
    text = _clean_text(value)
    if not text:
        return []
    separators = [",", "，", ";", "；", "|", "\n", "\t"]
    values = [text]
    for separator in separators:
        expanded: list[str] = []
        for item in values:
            expanded.extend(item.split(separator))
        values = expanded
    return [item.strip() for item in values if item.strip()]


def _fetch_relations(client: CmdbHttpClient, root_id: Any) -> list[dict[str, Any]]:
    payload = client._request_json(  # noqa: SLF001 - skill local helper reuse
        f"/api/v0.1/ci_relations/s?root_id={urllib.parse.quote(str(root_id))}&level=1,2,3&count=10000"
    )
    if isinstance(payload, dict):
        result = payload.get("result")
        if isinstance(result, list):
            return result
    return []


def _fetch_ci_detail(client: CmdbHttpClient, ci_id: Any) -> dict[str, Any]:
    """Fetch the full CI document so inline relation attributes are visible."""
    try:
        payload = client._request_json(  # noqa: SLF001
            f"/api/v0.1/ci/{urllib.parse.quote(str(ci_id))}"
        )
    except Exception:
        return {}
    if isinstance(payload, dict):
        result = payload.get("result")
        if isinstance(result, dict):
            return result
        return payload
    return {}


def _fetch_ci_type_catalog(client: CmdbHttpClient) -> dict[str, str]:
    """Return a catalog mapping normalized type names/aliases → canonical ci_type.

    Pulls from `/api/v0.1/ci_types?per_page=200`; falls back to the hard-coded
    `INLINE_RELATION_TYPES` map when the metadata endpoint is unreachable.
    """
    catalog: dict[str, str] = {}
    try:
        payload = client._request_json("/api/v0.1/ci_types?per_page=200")  # noqa: SLF001
    except Exception:
        payload = None

    type_items: list[Any] = []
    if isinstance(payload, dict):
        for key in ("result", "ci_types", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                type_items = value
                break
    elif isinstance(payload, list):
        type_items = payload

    for entry in type_items:
        if not isinstance(entry, dict):
            continue
        canonical = _clean_text(entry.get("name"))
        if not canonical:
            continue
        for key in ("name", "alias", "show_name"):
            token = _normalize_token(_clean_text(entry.get(key)))
            if token:
                catalog.setdefault(token, canonical)

    for normalized_key, canonical in INLINE_RELATION_TYPES.items():
        catalog.setdefault(normalized_key, canonical)
    return catalog


def _fetch_cis_by_type(client: CmdbHttpClient, ci_type: str) -> list[dict[str, Any]]:
    query = urllib.parse.quote(f"_type:{ci_type}", safe=":_")
    try:
        payload = client._request_json(  # noqa: SLF001
            f"/api/v0.1/ci/s?q={query}&count=10000&page=1"
        )
    except Exception:
        return []
    if isinstance(payload, dict):
        result = payload.get("result")
        if isinstance(result, list):
            return result
    if isinstance(payload, list):
        return payload
    return []


def _candidate_name_fields(ci_type: str) -> list[str]:
    return _CI_TYPE_NAME_FIELDS.get(ci_type, ["name"])


def _item_matches_token(item: dict[str, Any], ci_type: str, token_set: set[str]) -> bool:
    for field_name in _candidate_name_fields(ci_type):
        for value in _split_values(item.get(field_name)):
            if _normalize_token(value) in token_set:
                return True
    return False


def _resolve_inline_resources(
    client: CmdbHttpClient,
    project_detail: dict[str, Any],
) -> list[dict[str, Any]]:
    """Walk a project's attributes and resolve inline ci-type fields into CIs.

    Some VEOPS environments record a project's related middleware/database/host
    set as inline string fields (e.g. `Kafka: "kafka-web01, kafka-web02"`). The
    `ci_relations` endpoint does not return those, so this is queried as a
    complement to `_fetch_relations`. Returns CI items that can be merged into
    the same items list `_build_tree` consumes.
    """
    if not isinstance(project_detail, dict) or not project_detail:
        return []

    catalog = _fetch_ci_type_catalog(client)

    candidates_by_type: dict[str, set[str]] = defaultdict(set)
    for key, value in project_detail.items():
        if not isinstance(key, str):
            continue
        canonical = catalog.get(_normalize_token(key))
        if not canonical or canonical == "project":
            continue
        for token in _split_values(value):
            normalized = _normalize_token(token)
            if normalized:
                candidates_by_type[canonical].add(normalized)

    resolved: list[dict[str, Any]] = []
    for ci_type, token_set in candidates_by_type.items():
        if not token_set:
            continue
        type_items = _fetch_cis_by_type(client, ci_type)
        if not type_items:
            continue
        for item in type_items:
            if _item_matches_token(item, ci_type, token_set):
                if not _clean_text(item.get("ci_type")):
                    item["ci_type"] = ci_type
                resolved.append(item)
    return resolved


def _merge_items(
    primary: list[dict[str, Any]],
    extra: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Concatenate two CI lists, deduplicated by `_id` / `id`."""
    seen: set[Any] = set()
    merged: list[dict[str, Any]] = []
    for item in list(primary) + list(extra):
        if not isinstance(item, dict):
            continue
        ci_id = item.get("_id") or item.get("id")
        key = ci_id if ci_id is not None else id(item)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def _resource_label(item: dict[str, Any]) -> str:
    ci_type = _clean_text(item.get("ci_type"))
    candidates: list[Any] = []
    if ci_type == "project":
        candidates.extend([item.get("project_name"), item.get("name")])
    elif ci_type == "product":
        candidates.extend([item.get("product_name"), item.get("name")])
    elif ci_type == "vserver":
        candidates.extend([item.get("vserver_name"), item.get("name"), item.get("private_ip")])
    elif ci_type == "docker":
        candidates.extend([item.get("middleware_name"), item.get("manage_ip"), item.get("name")])
    elif ci_type in {"database", "mysql", "PostgreSQL"}:
        candidates.extend([item.get("db_instance"), item.get("name"), item.get("manage_ip"), item.get("db_ip")])
    elif ci_type in {"redis", "Kafka", "elasticsearch", "nginx", "apache"}:
        candidates.extend([item.get("middleware_name"), item.get("name"), item.get("middleware_ip")])
    elif ci_type == "networkdevice":
        candidates.extend([item.get("dev_name"), item.get("name"), item.get("manage_ip")])
    elif ci_type == "PhysicalMachine":
        candidates.extend([item.get("host_name"), item.get("name"), item.get("private_ip")])
    else:
        candidates.extend(
            [
                item.get("name"),
                item.get("project_name"),
                item.get("product_name"),
                item.get("middleware_name"),
                item.get("db_instance"),
                item.get("dev_name"),
                item.get("vserver_name"),
                item.get("manage_ip"),
                item.get("private_ip"),
            ]
        )

    for value in candidates:
        values = _split_values(value)
        if values:
            return values[0]

    ci_id = item.get("_id") or item.get("id") or "unknown"
    return f"{ci_type or 'resource'}-{ci_id}"


def _resource_ips(item: dict[str, Any]) -> set[str]:
    fields = [
        "private_ip",
        "manage_ip",
        "middleware_ip",
        "db_ip",
        "host_ip",
        "manager_ip",
        "AssociatedVM",
        "AssociatedPhyMachine",
        "deploy_target",
    ]
    values: set[str] = set()
    for field_name in fields:
        for token in _split_values(item.get(field_name)):
            values.add(token)
    return values


def _resource_node(item: dict[str, Any]) -> dict[str, Any]:
    label = _resource_label(item)
    ci_type = _clean_text(item.get("ci_type"))
    alias = _clean_text(item.get("ci_type_alias")) or ci_type or "资源"
    return {
        "name": label,
        "value": {
            "id": item.get("_id") or item.get("id"),
            "ciType": ci_type,
            "ciTypeAlias": alias,
        },
        "children": [],
    }


def _bucket_sort_key(item: dict[str, Any]) -> tuple[int, str]:
    ci_type = _clean_text(item.get("ci_type"))
    return TYPE_BUCKET_PRIORITY.get(ci_type, 999), _resource_label(item)


def _build_tree(project: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    root_name = _project_name(project) or "应用"
    nodes_by_id: dict[Any, dict[str, Any]] = {}
    docker_by_ip: dict[str, list[dict[str, Any]]] = defaultdict(list)
    vserver_by_ip: dict[str, list[dict[str, Any]]] = defaultdict(list)
    vserver_nodes: list[dict[str, Any]] = []
    software_pending: list[dict[str, Any]] = []
    direct_children: list[dict[str, Any]] = []

    filtered_items = [item for item in items if _clean_text(item.get("ci_type")) != "project"]
    filtered_items.sort(key=_bucket_sort_key)

    for item in filtered_items:
        node = _resource_node(item)
        item_id = item.get("_id") or item.get("id")
        nodes_by_id[item_id] = node
        ci_type = _clean_text(item.get("ci_type"))
        if ci_type == "vserver":
            direct_children.append(node)
            vserver_nodes.append(node)
            for ip_value in _resource_ips(item):
                vserver_by_ip[ip_value].append(node)
        elif ci_type == "docker":
            attached = False
            for parent_ip in _split_values(item.get("AssociatedVM")) + _split_values(item.get("deploy_target")):
                for parent_node in vserver_by_ip.get(parent_ip, []):
                    parent_node["children"].append(node)
                    attached = True
            if not attached and len(vserver_nodes) == 1:
                vserver_nodes[0]["children"].append(node)
                attached = True
            if not attached:
                direct_children.append(node)
            for ip_value in _resource_ips(item):
                docker_by_ip[ip_value].append(node)
        elif ci_type in SOFTWARE_TYPES:
            software_pending.append(item)
        else:
            direct_children.append(node)

    for item in software_pending:
        item_id = item.get("_id") or item.get("id")
        node = nodes_by_id[item_id]
        attached = False
        for parent_ip in _resource_ips(item):
            if parent_ip in docker_by_ip:
                for parent_node in docker_by_ip[parent_ip]:
                    parent_node["children"].append(node)
                    attached = True
                break
        if not attached:
            for parent_ip in _resource_ips(item):
                if parent_ip in vserver_by_ip:
                    for parent_node in vserver_by_ip[parent_ip]:
                        parent_node["children"].append(node)
                        attached = True
                    break
        if not attached:
            direct_children.append(node)

    root = {
        "name": root_name,
        "value": {
            "id": project.get("_id") or project.get("id"),
            "ciType": "project",
            "ciTypeAlias": _clean_text(project.get("ci_type_alias")) or "应用",
        },
        "children": sorted(direct_children, key=lambda node: node["name"]),
    }
    return root


def _build_option(tree: dict[str, Any], title: str) -> dict[str, Any]:
    return {
        "series": [
            {
                "type": "tree",
                "data": [tree],
                "orient": "LR",
                "initialTreeDepth": -1,
                "expandAndCollapse": True,
                "animationDuration": 550,
                "animationDurationUpdate": 750,
                "label": {
                    "position": "left",
                    "verticalAlign": "middle",
                    "align": "right",
                    "fontSize": 12,
                },
                "leaves": {
                    "label": {
                        "position": "right",
                        "verticalAlign": "middle",
                        "align": "left",
                    }
                },
            }
        ],
    }


def _render_markdown(project_name: str, items: list[dict[str, Any]], option: dict[str, Any]) -> str:
    type_counter: dict[str, int] = defaultdict(int)
    for item in items:
        type_counter[_clean_text(item.get("ci_type_alias")) or _clean_text(item.get("ci_type")) or "资源"] += 1

    summary = "、".join(
        f"{name} {count} 个" for name, count in sorted(type_counter.items(), key=lambda item: item[0])
    )
    lines = [
        f"`{project_name}` 当前共发现 {len(items)} 个关联资源。",
        f"资源分布：{summary}。",
        "",
        "```echarts",
        json.dumps(option, ensure_ascii=False, indent=2),
        "```",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="输出指定应用的标准 ECharts 拓扑")
    parser.add_argument("keyword", help="应用名")
    parser.add_argument(
        "--output",
        choices=["markdown", "echarts", "json"],
        default="markdown",
        help="输出格式",
    )
    args = parser.parse_args()

    env_file = _default_env_file()
    env = _load_env_file(env_file)
    client = CmdbHttpClient(
        base_url=env["VEOPS_BASE_URL"],
        username=env.get("VEOPS_USERNAME", ""),
        password=env.get("VEOPS_PASSWORD", ""),
    )
    client.try_login()

    projects = client.list_projects()
    matched_projects, _mode = _match_projects(projects, args.keyword)
    if not matched_projects:
        print(f"未找到应用：{args.keyword}", file=sys.stderr)
        return 1
    if len(matched_projects) > 1:
        print(f"存在多个与 {args.keyword} 匹配的应用，请使用精确名称。", file=sys.stderr)
        return 1

    project = matched_projects[0]
    project_name = _project_name(project) or _clean_text(args.keyword)
    project_id = project.get("_id") or project.get("id")
    items = _fetch_relations(client, project_id)

    # Some VEOPS deployments express a project's relationships as inline
    # attributes on the project CI itself (e.g. `Kafka`, `mysql`, `redis`,
    # `operatingsystem` fields whose values are CI names). Always merge those
    # in — `ci_relations` alone is not authoritative.
    project_detail = _fetch_ci_detail(client, project_id) or project
    inline_items = _resolve_inline_resources(client, project_detail)
    items = _merge_items(items, inline_items)

    tree = _build_tree(project, items)
    option = _build_option(tree, f"{project_name} 应用关系拓扑")

    if args.output == "json":
        print(
            json.dumps(
                {
                    "project": project_name,
                    "root_id": project.get("_id") or project.get("id"),
                    "resource_count": len(items),
                    "option": option,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.output == "echarts":
        print(json.dumps(option, ensure_ascii=False, indent=2))
        return 0

    print(_render_markdown(project_name, items, option))
    return 0


if __name__ == "__main__":
    sys.exit(main())
