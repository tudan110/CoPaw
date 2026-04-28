#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""INOE 资源状态与性能查询脚本。"""

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


RESOURCE_TYPES = {
    "database": {"api_type": "数据库", "label": "数据库", "default_order_code": "diskRate"},
    "data_base": {"api_type": "数据库", "label": "数据库", "default_order_code": "diskRate"},
    "db": {"api_type": "数据库", "label": "数据库", "default_order_code": "diskRate"},
    "数据库": {"api_type": "数据库", "label": "数据库", "default_order_code": "diskRate"},
    "network": {"api_type": "网络设备", "label": "网络设备", "default_order_code": "cpuRate"},
    "network_device": {"api_type": "网络设备", "label": "网络设备", "default_order_code": "cpuRate"},
    "networkdevice": {"api_type": "网络设备", "label": "网络设备", "default_order_code": "cpuRate"},
    "网络": {"api_type": "网络设备", "label": "网络设备", "default_order_code": "cpuRate"},
    "网络设备": {"api_type": "网络设备", "label": "网络设备", "default_order_code": "cpuRate"},
    "os": {"api_type": "操作系统", "label": "操作系统", "default_order_code": "cpuRate"},
    "operating_system": {"api_type": "操作系统", "label": "操作系统", "default_order_code": "cpuRate"},
    "operatingsystem": {"api_type": "操作系统", "label": "操作系统", "default_order_code": "cpuRate"},
    "操作系统": {"api_type": "操作系统", "label": "操作系统", "default_order_code": "cpuRate"},
    "server": {"api_type": "服务器", "label": "服务器", "default_order_code": "cpuRate"},
    "服务器": {"api_type": "服务器", "label": "服务器", "default_order_code": "cpuRate"},
    "compute": {"api_type": "服务器", "label": "服务器", "default_order_code": "cpuRate"},
    "计算资源": {"api_type": "服务器", "label": "服务器", "default_order_code": "cpuRate"},
    "middleware": {"api_type": "中间件", "label": "中间件", "default_order_code": "cpuRate"},
    "middle": {"api_type": "中间件", "label": "中间件", "default_order_code": "cpuRate"},
    "中间件": {"api_type": "中间件", "label": "中间件", "default_order_code": "cpuRate"},
}

ORDER_CODE_LABELS = {
    "cpuRate": "CPU 使用率",
    "memRate": "内存使用率",
    "diskRate": "磁盘使用率",
    "avgDelay": "平均延迟",
    "lossPercent": "丢包率",
    "responseTim": "响应时间",
    "linkCount": "空闲连接数",
}

STATUS_LABELS = {
    -2: "未监控",
    -1: "正常",
    0: "未监控",
    1: "正常",
    2: "警告",
    3: "次要",
    4: "严重",
    5: "紧急",
}


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def load_skill_env() -> None:
    skill_dir = Path(__file__).resolve().parent.parent
    _load_env_file(skill_dir / ".env")


load_skill_env()


def make_error(code: int, message: str) -> dict[str, Any]:
    return {"code": code, "msg": message, "data": None}


def normalize_resource_type(resource_type: str | None) -> dict[str, str]:
    raw = (resource_type or "database").strip()
    key = raw.lower().replace("-", "_").replace(" ", "_")
    return RESOURCE_TYPES.get(key, {"api_type": raw, "label": raw, "default_order_code": "cpuRate"})


def normalize_base_url(api_base_url: str | None = None) -> str:
    return (api_base_url or os.getenv("INOE_API_BASE_URL", "")).strip().rstrip("/")


def get_token(token: str | None = None) -> str:
    return (token or os.getenv("INOE_API_TOKEN", "")).strip()


def curl_enabled() -> bool:
    return os.getenv("INOE_ENABLE_CURL_FALLBACK", "true").lower() in {"1", "true", "yes", "on"}


def build_top_metric_payload(resource_type: str, top_num: int, order_code: str | None = None) -> dict[str, Any]:
    resource = normalize_resource_type(resource_type)
    return {
        "topNum": top_num,
        "type": resource["api_type"],
        "orderCode": order_code or resource["default_order_code"],
    }


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
    json_payload: dict[str, Any] | None = None,
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
    if json_payload is not None:
        args.extend(["--data-binary", json.dumps(json_payload, ensure_ascii=False)])
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
    json_payload: dict[str, Any] | None = None,
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
            json=json_payload,
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
                json_payload=json_payload,
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
                json_payload=json_payload,
                timeout_seconds=timeout_seconds,
            )
        return make_error(500, f"请求异常: {error}")


def query_database_status_overview(**kwargs: Any) -> dict[str, Any]:
    return request_json("GET", "/resource/database/resource/status/overview", **kwargs)


def query_top_metric(
    resource_type: str = "database",
    top_num: int = 5,
    order_code: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    payload = build_top_metric_payload(resource_type, top_num, order_code)
    return request_json("POST", "/resource/pm/TopMetricDataNew", json_payload=payload, **kwargs)


def query_top_resource_metric(
    top_num: int = 10,
    order_key: str = "diskRate",
    **kwargs: Any,
) -> dict[str, Any]:
    payload = {"topNum": top_num, "orderKey": order_key}
    return request_json("POST", "/resource/resource/performance/topResMetricData", json_payload=payload, **kwargs)


def query_database_metric_page(
    page_num: int = 1,
    page_size: int = 10,
    keyword: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    body: dict[str, Any] = {"pageNum": page_num, "pageSize": page_size}
    if keyword:
        body["keyWord"] = keyword
    return request_json(
        "POST",
        "/resource/database/performance/metric/page",
        query={"pageNum": page_num, "pageSize": page_size},
        json_payload=body,
        **kwargs,
    )


def _as_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    rows = payload.get("rows")
    if isinstance(rows, list):
        return [item for item in rows if isinstance(item, dict)]
    return []


def _display_status(value: Any) -> str:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return str(value) if value not in {None, ""} else "-"
    return STATUS_LABELS.get(normalized, str(value))


def _metric_value(row: dict[str, Any], key: str) -> Any:
    metric_data = row.get("metricData")
    if isinstance(metric_data, dict) and key in metric_data:
        return metric_data.get(key)
    return row.get(key)


def _format_table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return "暂无数据"
    output = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        output.append("| " + " | ".join(str(item if item not in {None, ''} else "-") for item in row) + " |")
    return "\n".join(output)


def format_status_overview_markdown(payload: dict[str, Any]) -> str:
    if payload.get("code") != 200:
        return f"数据库状态总览查询失败：{payload.get('msg') or payload}"
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    total = data.get("total", 0)
    normal = data.get("normalCount", 0)
    abnormal = data.get("abnormalCount", 0)
    alarm = data.get("alarmCount", 0)
    unknown = data.get("unknownCount", 0)
    lines = [
        "### 数据库状态总览",
        "",
        f"- 总数：{total}",
        f"- 正常：{normal}",
        f"- 异常：{abnormal}",
        f"- 告警：{alarm}",
        f"- 未知：{unknown}",
        "",
        "```echarts",
        json.dumps(
            {
                "tooltip": {"trigger": "item"},
                "legend": {"bottom": 0},
                "series": [
                    {
                        "type": "pie",
                        "radius": ["45%", "70%"],
                        "data": [
                            {"name": "正常", "value": normal},
                            {"name": "异常", "value": abnormal},
                            {"name": "告警", "value": alarm},
                            {"name": "未知", "value": unknown},
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        "```",
    ]
    return "\n".join(lines)


def format_top_metric_markdown(payload: dict[str, Any], resource_type: str, order_code: str | None) -> str:
    resource = normalize_resource_type(resource_type)
    order_label = ORDER_CODE_LABELS.get(order_code or resource["default_order_code"], order_code or resource["default_order_code"])
    if payload.get("code") != 200:
        return f"{resource['label']}性能 Top 查询失败：{payload.get('msg') or payload}"
    rows = _as_list(payload)
    table_rows: list[list[Any]] = []
    if resource["api_type"] == "数据库":
        headers = ["名称", "IP", "类型", "状态", "告警数", "磁盘使用率", "响应时间", "空闲连接数"]
        for item in rows:
            table_rows.append(
                [
                    item.get("devName") or item.get("resourceName") or "-",
                    item.get("manageIp") or item.get("resourceIp") or "-",
                    item.get("dataBaseType") or item.get("resourceType") or "-",
                    _display_status(item.get("devStatus")),
                    item.get("alarmCount", 0),
                    _metric_value(item, "diskRate"),
                    _metric_value(item, "responseTim"),
                    _metric_value(item, "linkCount"),
                ]
            )
    else:
        headers = ["名称", "IP", "厂商", "型号", "状态", "告警数", "CPU", "内存", "延迟", "丢包率"]
        for item in rows:
            table_rows.append(
                [
                    item.get("devName") or item.get("resourceName") or "-",
                    item.get("manageIp") or item.get("resourceIp") or "-",
                    item.get("vendorId") or "-",
                    item.get("modelId") or "-",
                    _display_status(item.get("devStatus")),
                    item.get("alarmCount", 0),
                    _metric_value(item, "cpuRate"),
                    _metric_value(item, "memRate"),
                    _metric_value(item, "avgDelay"),
                    _metric_value(item, "lossPercent"),
                ]
            )
    lines = [
        f"### {resource['label']}性能 Top（按 {order_label}）",
        "",
        f"共返回 {len(rows)} 条数据。",
        "",
        _format_table(headers, table_rows),
    ]
    return "\n".join(lines)


def format_top_resource_metric_markdown(payload: dict[str, Any], order_key: str) -> str:
    if payload.get("code") != 200:
        return f"资源性能 Top 查询失败：{payload.get('msg') or payload}"
    rows = _as_list(payload)
    headers = ["资源名称", "IP", "类型", "状态", "CPU", "内存", "磁盘", "响应时间", "空闲连接数"]
    table_rows = []
    for item in rows:
        table_rows.append(
            [
                item.get("resourceName") or item.get("devName") or item.get("nameId") or "-",
                item.get("resourceIp") or item.get("manageIp") or "-",
                item.get("ciTypeAlias") or item.get("resourceType") or "-",
                _display_status(item.get("resourceStatus") or item.get("devStatus")),
                _metric_value(item, "cpuRate"),
                _metric_value(item, "memRate"),
                _metric_value(item, "diskRate"),
                _metric_value(item, "responseTime"),
                _metric_value(item, "freeConnection"),
            ]
        )
    return "\n".join(
        [
            f"### 资源性能 Top（orderKey={order_key}）",
            "",
            f"共返回 {len(rows)} 条数据。",
            "",
            _format_table(headers, table_rows),
        ]
    )


def format_metric_page_markdown(payload: dict[str, Any]) -> str:
    if payload.get("code") != 200:
        return f"数据库性能指标清单查询失败：{payload.get('msg') or payload}"
    rows = _as_list(payload)
    headers = ["指标名称", "指标编码", "数据库类型", "采集周期", "单位", "值类型"]
    table_rows = [
        [
            item.get("metricName"),
            item.get("metricCode"),
            item.get("dbType"),
            item.get("collectCycle"),
            item.get("unit"),
            item.get("valueType"),
        ]
        for item in rows
    ]
    return "\n".join(
        [
            "### 数据库性能指标清单",
            "",
            f"总数：{payload.get('total', len(rows))}；当前返回 {len(rows)} 条。",
            "",
            _format_table(headers, table_rows),
        ]
    )


def format_summary_markdown(resource_type: str, overview: dict[str, Any], top_metric: dict[str, Any]) -> str:
    return "\n\n".join(
        [
            format_status_overview_markdown(overview) if normalize_resource_type(resource_type)["api_type"] == "数据库" else "",
            format_top_metric_markdown(top_metric, resource_type, None),
        ]
    ).strip()


def print_output(payload: dict[str, Any], output: str, markdown: str | None = None) -> None:
    if output == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(markdown or json.dumps(payload, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="查询 INOE 资源状态与性能数据")
    parser.add_argument("--token", help="JWT token，默认读取 INOE_API_TOKEN")
    parser.add_argument("--api_base_url", help="API 基础地址，默认读取 INOE_API_BASE_URL")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status-overview", help="查询资源状态总览")
    status.add_argument("--resource_type", default="database", help="当前支持 database")
    status.add_argument("--output", choices=["json", "markdown"], default="markdown")

    top = subparsers.add_parser("top-metric", help="查询页面性能 Top")
    top.add_argument("--resource_type", default="database", help="database/network/os/server/middleware")
    top.add_argument("--top_num", type=int, default=5)
    top.add_argument("--order_code", help="cpuRate/memRate/diskRate/avgDelay/lossPercent/responseTim/linkCount")
    top.add_argument("--output", choices=["json", "markdown"], default="markdown")

    top_resource = subparsers.add_parser("top-resource-metric", help="查询资源性能 Top")
    top_resource.add_argument("--top_num", type=int, default=10)
    top_resource.add_argument("--order_key", default="diskRate")
    top_resource.add_argument("--output", choices=["json", "markdown"], default="markdown")

    metric_page = subparsers.add_parser("metric-page", help="查询数据库性能指标清单")
    metric_page.add_argument("--page_num", type=int, default=1)
    metric_page.add_argument("--page_size", type=int, default=10)
    metric_page.add_argument("--keyword")
    metric_page.add_argument("--output", choices=["json", "markdown"], default="markdown")

    summary = subparsers.add_parser("summary", help="查询资源概览汇总")
    summary.add_argument("--resource_type", default="database")
    summary.add_argument("--top_num", type=int, default=5)
    summary.add_argument("--output", choices=["json", "markdown"], default="markdown")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    common = {"token": args.token, "api_base_url": args.api_base_url}

    if args.command == "status-overview":
        resource = normalize_resource_type(args.resource_type)
        if resource["api_type"] != "数据库":
            payload = make_error(400, "当前状态 overview 仅发现并封装了数据库接口；其他资源状态统计请使用 zgops-cmdb 的 CMDB count 类查询")
            print_output(payload, args.output, payload["msg"])
            return 1
        payload = query_database_status_overview(**common)
        print_output(payload, args.output, format_status_overview_markdown(payload))
        return 0 if payload.get("code") == 200 else 1

    if args.command == "top-metric":
        payload = query_top_metric(
            resource_type=args.resource_type,
            top_num=args.top_num,
            order_code=args.order_code,
            **common,
        )
        print_output(payload, args.output, format_top_metric_markdown(payload, args.resource_type, args.order_code))
        return 0 if payload.get("code") == 200 else 1

    if args.command == "top-resource-metric":
        payload = query_top_resource_metric(top_num=args.top_num, order_key=args.order_key, **common)
        print_output(payload, args.output, format_top_resource_metric_markdown(payload, args.order_key))
        return 0 if payload.get("code") == 200 else 1

    if args.command == "metric-page":
        payload = query_database_metric_page(
            page_num=args.page_num,
            page_size=args.page_size,
            keyword=args.keyword,
            **common,
        )
        print_output(payload, args.output, format_metric_page_markdown(payload))
        return 0 if payload.get("code") == 200 else 1

    if args.command == "summary":
        resource = normalize_resource_type(args.resource_type)
        overview = query_database_status_overview(**common) if resource["api_type"] == "数据库" else {}
        top_metric = query_top_metric(resource_type=args.resource_type, top_num=args.top_num, **common)
        if args.output == "json":
            print(
                json.dumps(
                    {"code": 200, "data": {"overview": overview, "topMetric": top_metric}},
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(format_summary_markdown(args.resource_type, overview, top_metric))
        return 0 if top_metric.get("code") == 200 else 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
