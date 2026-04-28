#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""INOE 监控总览页查询脚本。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests


ALARM_STATUS_LABELS = {
    "0": "正常",
    "1": "告警",
    "2": "异常",
    "3": "严重",
}

ALARM_STATUS_COLORS = {
    "0": "#22c55e",
    "1": "#f97316",
    "2": "#f59e0b",
    "3": "#ef4444",
}

HEALTH_STATUS_LABELS = {
    "green": "健康",
    "yellow": "关注",
    "red": "告警",
}


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_skill_env() -> None:
    skill_dir = Path(__file__).resolve().parent.parent
    _load_env_file(skill_dir / ".env")


load_skill_env()


def make_error(code: int, message: str) -> dict[str, Any]:
    return {"code": code, "msg": message, "data": None}


def normalize_base_url(api_base_url: str | None = None) -> str:
    return (api_base_url or os.getenv("INOE_API_BASE_URL", "")).strip().rstrip("/")


def get_token(token: str | None = None) -> str:
    return (token or os.getenv("INOE_API_TOKEN", "")).strip()


def curl_enabled() -> bool:
    return os.getenv("INOE_ENABLE_CURL_FALLBACK", "true").lower() in {"1", "true", "yes", "on"}


def _parse_json_text(text: str) -> dict[str, Any]:
    if not text.strip():
        return make_error(500, "接口返回空响应")
    payload = json.loads(text)
    if isinstance(payload, dict):
        return payload
    return {"code": 200, "msg": "操作成功", "data": payload}


def _curl_request(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile(delete=False) as body_file:
        body_path = body_file.name

    args = [
        "curl",
        "-sS",
        "-X",
        method.upper(),
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
        return _parse_json_text(response_text)
    except subprocess.TimeoutExpired:
        return make_error(408, "请求超时")
    except json.JSONDecodeError as error:
        return make_error(500, f"curl 响应解析失败: {error}")
    except Exception as error:  # noqa: BLE001
        return make_error(500, f"curl 回退失败: {error}")
    finally:
        try:
            os.unlink(body_path)
        except OSError:
            pass


def request_json(
    method: str,
    path: str,
    *,
    query: dict[str, Any] | None = None,
    token: str | None = None,
    api_base_url: str | None = None,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    base_url = normalize_base_url(api_base_url)
    if not base_url:
        return make_error(400, "未设置 INOE_API_BASE_URL")
    auth_token = get_token(token)
    if not auth_token:
        return make_error(401, "未设置 INOE_API_TOKEN")

    url = f"{base_url}{path}"
    if query:
        url = f"{url}?{urlencode(query)}"

    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8",
    }

    try:
        response = requests.request(
            method=method.upper(),
            url=url,
            headers=headers,
            timeout=timeout_seconds,
        )
        if response.status_code >= 400:
            return make_error(response.status_code, response.text[:500])
        return _parse_json_text(response.text)
    except (requests.ConnectionError, requests.Timeout, OSError):
        if curl_enabled():
            return _curl_request(
                method=method,
                url=url,
                headers=headers,
                timeout_seconds=timeout_seconds,
            )
        return make_error(408, "请求失败且 curl fallback 未启用")
    except json.JSONDecodeError as error:
        return make_error(500, f"响应解析失败: {error}")
    except requests.RequestException as error:
        if curl_enabled():
            return _curl_request(
                method=method,
                url=url,
                headers=headers,
                timeout_seconds=timeout_seconds,
            )
        return make_error(500, f"请求异常: {error}")


def query_alarm_top5(
    *,
    alarm_class_type: int = 0,
    resource_type: int = 3,
    alarm_severity: int = 1,
    **kwargs: Any,
) -> dict[str, Any]:
    return request_json(
        "GET",
        "/resource/alarm/statistics/statResTop",
        query={
            "alarmClassType": alarm_class_type,
            "type": resource_type,
            "alarmSeverity": alarm_severity,
        },
        **kwargs,
    )


def query_topology(**kwargs: Any) -> dict[str, Any]:
    return request_json("GET", "/resource/monitor/overview/topology", **kwargs)


def query_asset_overview(**kwargs: Any) -> dict[str, Any]:
    return request_json("GET", "/resource/monitor/overview/asset/overview", **kwargs)


def _as_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _format_table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return "暂无数据"
    output = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        output.append("| " + " | ".join(str(item if item not in {None, ''} else "-") for item in row) + " |")
    return "\n".join(output)


def _alarm_status_label(value: Any) -> str:
    normalized = str(value if value is not None else "").strip()
    return ALARM_STATUS_LABELS.get(normalized, normalized or "未知")


def _alarm_status_color(value: Any) -> str:
    normalized = str(value if value is not None else "").strip()
    return ALARM_STATUS_COLORS.get(normalized, "#94a3b8")


def _resource_display_name(resource: dict[str, Any]) -> str:
    name = str(resource.get("name") or resource.get("resourceName") or resource.get("type") or "未命名").strip()
    manage_ip = str(resource.get("manage_ip") or resource.get("manageIp") or "").strip()
    return f"{name}\\n{manage_ip}" if manage_ip else name


def build_topology_tree_data(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    if not nodes:
        return {"name": "监控总览", "children": []}

    root = nodes[0]
    root_name = str(root.get("type") or "监控总览")
    children: list[dict[str, Any]] = []
    for node in nodes[1:]:
        resources = []
        node_data = node.get("data")
        if isinstance(node_data, dict) and isinstance(node_data.get("resources"), list):
            resources = [item for item in node_data.get("resources", []) if isinstance(item, dict)]
        child_name = f"{node.get('type') or '未命名'} ({node.get('deviceCount') or 0})"
        child_node = {
            "name": child_name,
            "value": int(node.get("deviceCount") or len(resources) or 0),
            "itemStyle": {"color": _alarm_status_color(node.get("alarmStatus"))},
            "label": {"color": "#111827"},
        }
        if resources:
            child_node["children"] = [
                {
                    "name": _resource_display_name(resource),
                    "value": 1,
                    "itemStyle": {"color": _alarm_status_color(resource.get("alarm_status"))},
                    "label": {"color": "#475569"},
                }
                for resource in resources
            ]
        children.append(child_node)

    return {
        "name": root_name,
        "value": int(root.get("deviceCount") or len(children) or 0),
        "itemStyle": {"color": _alarm_status_color(root.get("alarmStatus"))},
        "children": children,
    }


def format_alarm_top5_markdown(payload: dict[str, Any]) -> str:
    if payload.get("code") != 200:
        return f"告警对象 Top5 查询失败：{payload.get('msg') or payload}"
    rows = _as_list(payload)
    table_rows = [[item.get("title") or "未命名", item.get("count") or 0] for item in rows]
    lines = [
        "### 告警对象 Top5",
        "",
        _format_table(["告警对象", "数量"], table_rows),
        "",
        "```echarts",
        json.dumps(
            {
                "tooltip": {"trigger": "axis"},
                "grid": {"left": 96, "right": 32, "top": 24, "bottom": 32},
                "xAxis": {"type": "value"},
                "yAxis": {
                    "type": "category",
                    "data": [item.get("title") or "未命名" for item in rows][::-1],
                },
                "series": [
                    {
                        "type": "bar",
                        "data": [item.get("count") or 0 for item in rows][::-1],
                        "itemStyle": {"color": "#2563eb"},
                        "label": {"show": True, "position": "right"},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        "```",
    ]
    return "\n".join(lines)


def format_topology_markdown(payload: dict[str, Any]) -> str:
    if payload.get("code") != 200:
        return f"监控拓扑查询失败：{payload.get('msg') or payload}"
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    nodes = data.get("nodes") if isinstance(data.get("nodes"), list) else []
    tree = build_topology_tree_data([item for item in nodes if isinstance(item, dict)])
    lines = [
        "### 监控总览拓扑",
        "",
        f"- 根节点：{tree.get('name')}",
        f"- 一级分支数：{len(tree.get('children') or [])}",
        "",
        "```echarts",
        json.dumps(
            {
                "tooltip": {"trigger": "item", "triggerOn": "mousemove"},
                "series": [
                    {
                        "type": "tree",
                        "data": [tree],
                        "top": "6%",
                        "left": "8%",
                        "bottom": "6%",
                        "right": "28%",
                        "symbolSize": 10,
                        "orient": "LR",
                        "expandAndCollapse": True,
                        "initialTreeDepth": 2,
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
                        "animationDuration": 550,
                        "animationDurationUpdate": 750,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        "```",
    ]
    return "\n".join(lines)


def _health_status_label(value: Any) -> str:
    normalized = str(value if value is not None else "").strip().lower()
    return HEALTH_STATUS_LABELS.get(normalized, normalized or "未知")


def format_asset_overview_markdown(payload: dict[str, Any]) -> str:
    if payload.get("code") != 200:
        return f"资产总览查询失败：{payload.get('msg') or payload}"

    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    resource_type_stats = data.get("resourceTypeStats") if isinstance(data.get("resourceTypeStats"), dict) else {}
    resource_rows = []
    for _, stat in resource_type_stats.items():
        if not isinstance(stat, dict):
            continue
        resource_rows.append(
            [
                stat.get("resourceTypeName") or "-",
                stat.get("totalCount") or 0,
                stat.get("normalCount") or 0,
                stat.get("alarmCount") or 0,
            ]
        )

    app_rows = []
    application_health = data.get("applicationHealthList") if isinstance(data.get("applicationHealthList"), list) else []
    for item in application_health:
        if not isinstance(item, dict):
            continue
        app_rows.append(
            [
                item.get("platformName") or "-",
                item.get("healthRate") or 0,
                _health_status_label(item.get("healthStatus")),
                item.get("totalCount") or 0,
                item.get("alarmCount") or 0,
                item.get("responseTime") or "-",
            ]
        )

    host_top = data.get("hostResourceTop") if isinstance(data.get("hostResourceTop"), dict) else {}
    metric_names = [
        item.get("resourceName") or "-"
        for item in (host_top.get("cpuTop5") or [])
        if isinstance(item, dict)
    ]
    if not metric_names:
        metric_names = [
            item.get("resourceName") or "-"
            for item in (host_top.get("memoryTop5") or [])
            if isinstance(item, dict)
        ]
    if not metric_names:
        metric_names = [
            item.get("resourceName") or "-"
            for item in (host_top.get("storageTop5") or [])
            if isinstance(item, dict)
        ]

    def metric_map(key: str) -> dict[str, Any]:
        rows = host_top.get(key) if isinstance(host_top.get(key), list) else []
        return {
            str(item.get("resourceName") or "-"): item.get("usageRate") or 0
            for item in rows
            if isinstance(item, dict)
        }

    cpu_map = metric_map("cpuTop5")
    memory_map = metric_map("memoryTop5")
    storage_map = metric_map("storageTop5")

    lines = [
        "### 监控资产总览",
        "",
        f"- 资源总数：{data.get('totalResources') or 0}",
        f"- 健康率：{data.get('healthRate') or 0}%",
        f"- 健康状态：{_health_status_label(data.get('healthStatus'))}",
        "",
        "#### 资源类型分布",
        "",
        _format_table(["资源类型", "总数", "正常", "告警"], resource_rows),
        "",
        "```echarts",
        json.dumps(
            {
                "tooltip": {"trigger": "axis"},
                "legend": {"bottom": 0},
                "grid": {"left": 56, "right": 24, "top": 24, "bottom": 56},
                "xAxis": {
                    "type": "category",
                    "data": [row[0] for row in resource_rows],
                },
                "yAxis": {"type": "value"},
                "series": [
                    {"name": "总数", "type": "bar", "data": [row[1] for row in resource_rows], "itemStyle": {"color": "#2563eb"}},
                    {"name": "告警", "type": "bar", "data": [row[3] for row in resource_rows], "itemStyle": {"color": "#ef4444"}},
                ],
            },
            ensure_ascii=False,
        ),
        "```",
        "",
        "#### 应用健康概况",
        "",
        _format_table(["应用", "健康率", "状态", "资源数", "告警数", "响应时间"], app_rows),
        "",
        "#### 主机资源 Top",
        "",
        "```echarts",
        json.dumps(
            {
                "tooltip": {"trigger": "axis"},
                "legend": {"bottom": 0},
                "grid": {"left": 64, "right": 24, "top": 24, "bottom": 56},
                "xAxis": {"type": "category", "data": metric_names},
                "yAxis": {"type": "value"},
                "series": [
                    {"name": "CPU", "type": "bar", "data": [cpu_map.get(name, 0) for name in metric_names], "itemStyle": {"color": "#2563eb"}},
                    {"name": "内存", "type": "bar", "data": [memory_map.get(name, 0) for name in metric_names], "itemStyle": {"color": "#14b8a6"}},
                    {"name": "存储", "type": "bar", "data": [storage_map.get(name, 0) for name in metric_names], "itemStyle": {"color": "#f59e0b"}},
                ],
            },
            ensure_ascii=False,
        ),
        "```",
    ]
    return "\n".join(lines)


def print_output(payload: dict[str, Any], output: str, markdown: str | None = None) -> None:
    if output == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(markdown or json.dumps(payload, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="查询 INOE 监控总览页数据")
    parser.add_argument("--token", help="JWT token，默认读取 INOE_API_TOKEN")
    parser.add_argument("--api_base_url", help="API 基础地址，默认读取 INOE_API_BASE_URL")
    subparsers = parser.add_subparsers(dest="command", required=True)

    alarm_top5 = subparsers.add_parser("alarm-top5", help="查询告警对象 Top5")
    alarm_top5.add_argument("--alarm_class_type", type=int, default=0)
    alarm_top5.add_argument("--resource_type", type=int, default=3)
    alarm_top5.add_argument("--alarm_severity", type=int, default=1)
    alarm_top5.add_argument("--output", choices=["json", "markdown"], default="markdown")

    topology = subparsers.add_parser("topology", help="查询监控拓扑")
    topology.add_argument("--output", choices=["json", "markdown"], default="markdown")

    asset_overview = subparsers.add_parser("asset-overview", help="查询资产总览")
    asset_overview.add_argument("--output", choices=["json", "markdown"], default="markdown")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    request_kwargs = {
        "token": args.token,
        "api_base_url": args.api_base_url,
    }

    if args.command == "alarm-top5":
        payload = query_alarm_top5(
            alarm_class_type=args.alarm_class_type,
            resource_type=args.resource_type,
            alarm_severity=args.alarm_severity,
            **request_kwargs,
        )
        markdown = format_alarm_top5_markdown(payload)
        print_output(payload, args.output, markdown)
        return

    if args.command == "topology":
        payload = query_topology(**request_kwargs)
        markdown = format_topology_markdown(payload)
        print_output(payload, args.output, markdown)
        return

    if args.command == "asset-overview":
        payload = query_asset_overview(**request_kwargs)
        markdown = format_asset_overview_markdown(payload)
        print_output(payload, args.output, markdown)
        return

    parser.error(f"未知命令: {args.command}")


if __name__ == "__main__":
    main()
