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
    items = _fetch_relations(client, project.get("_id") or project.get("id"))
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
