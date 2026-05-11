#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资源巡检指标采集脚本。

使用方式:
    python scripts/inspect_resource_metrics.py --res-id 3094 --metric-type mysql --output markdown

说明:
    - 默认读取当前 skill 目录下的 .env
    - 复用 fault/alarm-analyst 的指标接口访问与 HTTP fallback 能力
    - 先查询全部指标定义，再提取全部 metric codes
    - 再以一次批量请求把全部 metric codes 传给 /resource/pm/getMetricData
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import html
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import requests

try:
    from dotenv import load_dotenv

    HAS_DOTENV = True
except ImportError:
    HAS_DOTENV = False


ALLOWED_OUTPUTS = {"json", "markdown"}
DEFAULT_PAGE_SIZE = 100
DEFAULT_MAX_PAGES = 20
DEFAULT_NOTIFY_TIMEOUT_SECONDS = 8
PORTAL_INSPECTION_CARD_MARKER = "# PORTAL INSPECTION CARD MODE"


def _load_skill_env() -> None:
    if not HAS_DOTENV:
        return

    skill_dir = Path(__file__).resolve().parents[1]
    skill_env_file = skill_dir / ".env"
    if skill_env_file.exists():
        load_dotenv(skill_env_file, override=True)


_load_skill_env()


def _skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _workspaces_root() -> Path:
    return _skill_root().parents[2]


def _alarm_metric_script_path() -> Path:
    return (
        _workspaces_root()
        / "fault"
        / "skills"
        / "alarm-analyst"
        / "scripts"
        / "get_metric_definitions.py"
    )


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_ALARM_METRIC_HELPERS = _load_module(
    "inspection_alarm_metric_helpers",
    _alarm_metric_script_path(),
)


def _safe_str(value: Any) -> str:
    return _ALARM_METRIC_HELPERS._safe_str(value)  # noqa: SLF001


def _get_page_size(page_size: int | None) -> int:
    if page_size is not None:
        return page_size
    raw = (os.getenv("INSPECTION_METRIC_PAGE_SIZE") or "").strip()
    if not raw:
        return DEFAULT_PAGE_SIZE
    return int(raw)


def _get_timeout(timeout_seconds: int | None) -> int:
    if timeout_seconds is not None:
        return timeout_seconds
    raw = (os.getenv("INSPECTION_METRIC_TIMEOUT_SECONDS") or "").strip()
    if raw:
        return int(raw)
    return int(getattr(_ALARM_METRIC_HELPERS, "DEFAULT_TIMEOUT_SECONDS", 120))


def _normalize_rule_text(value: Any) -> str:
    return html.unescape(_safe_str(value))


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []

    for key in ("rows", "records", "list", "items", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    for key in ("page", "result", "data"):
        nested = payload.get(key)
        rows = _extract_rows(nested)
        if rows:
            return rows

    return []


def _curl_get_json(
    *,
    url: str,
    headers: dict[str, str],
    timeout_seconds: int,
) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile(delete=False) as body_file:
        body_path = body_file.name

    args = [
        "curl",
        "-sS",
        "--location",
        "-X",
        "GET",
        "--connect-timeout",
        str(int(timeout_seconds)),
        "--max-time",
        str(int(timeout_seconds)),
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
            timeout=max(int(timeout_seconds) + 5, 10),
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or completed.stdout or "curl 请求失败").strip())
        status_code = int((completed.stdout or "").strip() or "0")
        with open(body_path, "r", encoding="utf-8", errors="replace") as handle:
            body_text = handle.read()
        if status_code >= 400:
            raise requests.HTTPError(f"HTTP {status_code}: {body_text[:200]}")
        if not body_text.strip():
            raise ValueError("curl 接口返回空响应")
        return json.loads(body_text)
    finally:
        try:
            os.unlink(body_path)
        except OSError:
            pass


def _get_json_with_fallback(
    *,
    url: str,
    headers: dict[str, str],
    timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        response_text = response.text.strip()
        if not response_text:
            raise ValueError("接口返回空响应")
        return response.json(), "requests"
    except (requests.exceptions.RequestException, ValueError, json.JSONDecodeError) as error:
        if not _ALARM_METRIC_HELPERS._should_fallback_to_curl(error):  # noqa: SLF001
            raise
        return _curl_get_json(
            url=url,
            headers=headers,
            timeout_seconds=timeout_seconds,
        ), "curl"


def _get_notify_env(name: str) -> str:
    return _safe_str(
        os.getenv(f"INSPECTION_NOTIFY_{name}")
        or os.getenv(f"ORDER_CREATE_NOTIFY_{name}")
    )


def _get_notify_timeout() -> int:
    raw = _get_notify_env("TIMEOUT_SECONDS")
    return int(raw) if raw else DEFAULT_NOTIFY_TIMEOUT_SECONDS


def _get_notify_mention_all() -> bool:
    return (_get_notify_env("MENTION_ALL") or "false").lower() in {"1", "true", "yes"}


def _build_metric_data_batch_request(
    *,
    res_id: str | int,
    metric_codes: list[str],
    query_type: str,
    start_time: str | None = None,
    end_time: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "mulRes": [{"resId": str(res_id)}],
        "queryKeys": metric_codes,
        "queryType": str(query_type),
    }
    if str(query_type) != "0":
        if not _safe_str(start_time) or not _safe_str(end_time):
            raise ValueError("当 queryType 不等于 0 时，必须同时提供 startTime 和 endTime")
        payload["startTime"] = _safe_str(start_time)
        payload["endTime"] = _safe_str(end_time)
    return payload


def fetch_all_metric_definitions(
    *,
    metric_type: str,
    page_size: int | None = None,
    api_base_url: str | None = None,
    token: str | None = None,
    timeout_seconds: int | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> dict[str, Any]:
    normalized_metric_type = _safe_str(metric_type)
    if not normalized_metric_type:
        raise ValueError("metric_type 不能为空")

    resolved_page_size = _get_page_size(page_size)
    if resolved_page_size < 1:
        raise ValueError("page_size 必须大于等于 1")
    if max_pages < 1:
        raise ValueError("max_pages 必须大于等于 1")

    all_metrics: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    page_sources: list[str] = []
    fallback_reasons: list[str] = []
    first_url = ""
    first_request: dict[str, Any] = {}
    pages_fetched = 0

    for page_num in range(1, max_pages + 1):
        page_result = _ALARM_METRIC_HELPERS.fetch_metric_definitions(
            metric_type=normalized_metric_type,
            page_num=page_num,
            page_size=resolved_page_size,
            api_base_url=api_base_url,
            token=token,
            timeout_seconds=timeout_seconds,
            limit=resolved_page_size,
        )
        pages_fetched += 1
        if not first_url:
            first_url = _safe_str(page_result.get("url"))
        if not first_request:
            first_request = page_result.get("request") or {}

        page_source = _safe_str(page_result.get("source")) or "unknown"
        page_sources.append(page_source)
        fallback_reason = _safe_str(page_result.get("fallbackReason"))
        if fallback_reason:
            fallback_reasons.append(fallback_reason)

        page_metrics = page_result.get("metrics") or []
        if not page_metrics:
            break

        for metric in page_metrics:
            code = _safe_str(metric.get("code"))
            dedupe_key = code or json.dumps(metric, ensure_ascii=False, sort_keys=True)
            if dedupe_key in seen_codes:
                continue
            seen_codes.add(dedupe_key)
            all_metrics.append(metric)

        if page_source != "live" or len(page_metrics) < resolved_page_size:
            break

    combined_source = "live" if page_sources and all(source == "live" for source in page_sources) else "mock"
    return {
        "code": 200,
        "msg": "查询成功" if combined_source == "live" else "指标定义查询已部分或全部回退到 mock 数据",
        "metricType": normalized_metric_type,
        "source": combined_source,
        "fallbackReason": "；".join(dict.fromkeys(fallback_reasons)) if fallback_reasons else None,
        "url": first_url,
        "request": first_request,
        "pageSize": resolved_page_size,
        "pagesFetched": pages_fetched,
        "metricsTotal": len(all_metrics),
        "metrics": all_metrics,
    }


def _normalize_inspection_rule_config(item: dict[str, Any]) -> dict[str, Any]:
    params = [
        {
            "operator": _safe_str(param.get("operator")),
            "staticValues": _normalize_rule_text(param.get("staticValues")),
        }
        for param in (item.get("opInspectionRuleConfigParaList") or [])
        if isinstance(param, dict)
    ]
    return {
        "ruleName": _safe_str(item.get("ruleName")),
        "expression": _safe_str(item.get("expression")),
        "ciType": _safe_str(item.get("ciType")),
        "modelId": _safe_str(item.get("modelId")),
        "status": _safe_str(item.get("status")),
        "conditions": [param for param in params if param.get("operator")],
        "raw": item,
    }


def _is_enabled_rule_config(item: dict[str, Any]) -> bool:
    status = _safe_str(item.get("status"))
    return not status or status in {"1", "true", "TRUE", "enabled", "active", "启用"}


def fetch_inspection_rule_configs(
    *,
    api_base_url: str | None = None,
    token: str | None = None,
    timeout_seconds: int | None = None,
    page_size: int | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> dict[str, Any]:
    resolved_page_size = _get_page_size(page_size)
    if resolved_page_size < 1:
        raise ValueError("page_size 必须大于等于 1")
    if max_pages < 1:
        raise ValueError("max_pages 必须大于等于 1")

    base_url = _ALARM_METRIC_HELPERS._normalize_base_url(api_base_url)  # noqa: SLF001
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {_ALARM_METRIC_HELPERS._get_token(token)}",  # noqa: SLF001
    }
    resolved_timeout = _get_timeout(timeout_seconds)
    all_rules: list[dict[str, Any]] = []
    first_url = ""

    try:
        for page_num in range(1, max_pages + 1):
            url = (
                f"{base_url}/resource/inspection/config/list"
                f"?pageSize={resolved_page_size}&pageNum={page_num}"
            )
            if not first_url:
                first_url = url
            response_payload, _transport = _get_json_with_fallback(
                url=url,
                headers=headers,
                timeout_seconds=resolved_timeout,
            )
            page_rules = [_normalize_inspection_rule_config(item) for item in _extract_rows(response_payload)]
            enabled_rules = [
                item
                for item in page_rules
                if _is_enabled_rule_config(item) and item.get("expression") and item.get("conditions")
            ]
            all_rules.extend(enabled_rules)
            total = int(response_payload.get("total") or 0)
            if not page_rules or len(page_rules) < resolved_page_size or (total and page_num * resolved_page_size >= total):
                break
    except (requests.exceptions.RequestException, ValueError, RuntimeError, json.JSONDecodeError) as error:
        return {
            "code": 200,
            "msg": "巡检阈值规则查询失败，将回退到经验规则",
            "source": "unavailable",
            "fallbackReason": str(error),
            "url": first_url,
            "rulesTotal": 0,
            "ruleConfigs": [],
        }

    return {
        "code": 200,
        "msg": "查询成功",
        "source": "live",
        "fallbackReason": None,
        "url": first_url,
        "rulesTotal": len(all_rules),
        "ruleConfigs": all_rules,
    }


def fetch_verification_rule_dict(
    *,
    api_base_url: str | None = None,
    token: str | None = None,
    timeout_seconds: int | None = None,
    page_size: int | None = None,
) -> dict[str, Any]:
    resolved_page_size = _get_page_size(page_size)
    if resolved_page_size < 1:
        raise ValueError("page_size 必须大于等于 1")

    base_url = _ALARM_METRIC_HELPERS._normalize_base_url(api_base_url)  # noqa: SLF001
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {_ALARM_METRIC_HELPERS._get_token(token)}",  # noqa: SLF001
    }
    resolved_timeout = _get_timeout(timeout_seconds)
    url = (
        f"{base_url}/admin/dict/data/list"
        f"?pageNum=1&pageSize={resolved_page_size}&dictType=verification_rules_new"
    )

    try:
        response_payload, _transport = _get_json_with_fallback(
            url=url,
            headers=headers,
            timeout_seconds=resolved_timeout,
        )
        operator_map: dict[str, str] = {}
        for item in _extract_rows(response_payload):
            code = _safe_str(item.get("dictValue") or item.get("value") or item.get("dictCode"))
            label = _normalize_rule_text(item.get("dictLabel") or item.get("label") or item.get("dictName"))
            if code and label:
                operator_map[code] = label
        if not operator_map:
            raise ValueError("verification_rules_new 字典未返回可用映射")
    except (requests.exceptions.RequestException, ValueError, RuntimeError, json.JSONDecodeError) as error:
        return {
            "code": 200,
            "msg": "规则操作符字典查询失败，将回退到经验规则",
            "source": "unavailable",
            "fallbackReason": str(error),
            "url": url,
            "operatorMap": {},
        }

    return {
        "code": 200,
        "msg": "查询成功",
        "source": "live",
        "fallbackReason": None,
        "url": url,
        "operatorMap": operator_map,
    }


def fetch_inspection_verification_rules(
    *,
    api_base_url: str | None = None,
    token: str | None = None,
    timeout_seconds: int | None = None,
    page_size: int | None = None,
) -> dict[str, Any]:
    rule_configs = fetch_inspection_rule_configs(
        api_base_url=api_base_url,
        token=token,
        timeout_seconds=timeout_seconds,
        page_size=page_size,
    )
    operator_dict = fetch_verification_rule_dict(
        api_base_url=api_base_url,
        token=token,
        timeout_seconds=timeout_seconds,
        page_size=page_size,
    )
    sources = {_safe_str(rule_configs.get("source")), _safe_str(operator_dict.get("source"))}
    if sources == {"live"}:
        source = "live"
    elif "live" in sources:
        source = "partial"
    else:
        source = "unavailable"

    fallback_reasons = [
        _safe_str(rule_configs.get("fallbackReason")),
        _safe_str(operator_dict.get("fallbackReason")),
    ]
    return {
        "code": 200,
        "msg": "查询成功" if source == "live" else "阈值规则查询未完全成功，将按规则/经验混合判断",
        "source": source,
        "fallbackReason": "；".join(reason for reason in fallback_reasons if reason) or None,
        "ruleConfigsSource": _safe_str(rule_configs.get("source")) or "unknown",
        "operatorDictSource": _safe_str(operator_dict.get("source")) or "unknown",
        "ruleConfigsTotal": int(rule_configs.get("rulesTotal") or 0),
        "ruleConfigs": rule_configs.get("ruleConfigs") or [],
        "operatorMap": operator_dict.get("operatorMap") or {},
        "ruleConfigsFallbackReason": rule_configs.get("fallbackReason"),
        "operatorDictFallbackReason": operator_dict.get("fallbackReason"),
    }


def _build_mock_metric_data_batch_payload(
    *,
    res_id: str | int,
    metric_codes: list[str],
) -> dict[str, Any]:
    original_point = {"formatTime": "2026-04-24 10:00:00", "gatherTime": 1777005600}
    process_data: dict[str, str] = {}
    for index, metric_code in enumerate(metric_codes, start=1):
        sample_value = str(index)
        process_data[f"{metric_code}Min"] = sample_value
        process_data[f"{metric_code}Avg"] = sample_value
        process_data[f"{metric_code}Max"] = sample_value
        original_point[metric_code] = sample_value

    return {
        "code": 200,
        "msg": "mock",
        "data": [
            {
                "resId": str(res_id),
                "subResName": "",
                "processData": process_data,
                "originalDatas": [original_point],
            }
        ],
    }


def _extract_metric_data_results(
    payload: dict[str, Any],
    *,
    metric_definitions: list[dict[str, Any]],
    source: str,
) -> list[dict[str, Any]]:
    definitions_by_code = {
        _safe_str(metric.get("code")): metric
        for metric in metric_definitions
        if _safe_str(metric.get("code"))
    }
    data_rows = payload.get("data") or []
    row = data_rows[0] if data_rows and isinstance(data_rows[0], dict) else {}
    process_data = row.get("processData") or {}
    original_datas = row.get("originalDatas") or []
    latest_point = original_datas[-1] if original_datas and isinstance(original_datas[-1], dict) else {}

    results: list[dict[str, Any]] = []
    for metric_code, metric in definitions_by_code.items():
        unit = (
            _safe_str(process_data.get("unit"))
            or _safe_str(metric.get("unit"))
            or _safe_str(_ALARM_METRIC_HELPERS._infer_mock_unit(metric_code))  # noqa: SLF001
        )
        results.append(
            {
                "metricCode": metric_code,
                "metricName": _safe_str(metric.get("name")) or metric_code,
                "latestValue": _safe_str(latest_point.get(metric_code)),
                "sampleTime": _safe_str(latest_point.get("formatTime")),
                "minValue": _safe_str(process_data.get(f"{metric_code}Min")),
                "avgValue": _safe_str(process_data.get(f"{metric_code}Avg")),
                "maxValue": _safe_str(process_data.get(f"{metric_code}Max")),
                "unit": unit,
                "source": source,
            }
        )
    return results


def _build_rule_config_index(rule_configs: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for config in rule_configs:
        expression = _safe_str(config.get("expression")).lower()
        if not expression:
            continue
        index.setdefault(expression, []).append(config)
    return index


def _notification_metric_preview(metric_results: list[dict[str, Any]], limit: int = 5) -> str:
    previews: list[str] = []
    for item in metric_results[:limit]:
        name = _safe_str(item.get("metricName") or item.get("metricCode")) or "指标"
        value = _format_notification_metric_value(item)
        previews.append(f"{name}={value}")
    return "；".join(previews) or "-"


def _format_notification_metric_value(item: dict[str, Any]) -> str:
    return _safe_str(item.get("latestValue") or item.get("avgValue")) or "-"


def _collect_inspection_findings(metric_results: list[dict[str, Any]]) -> list[str]:
    findings: list[str] = []
    for item in metric_results:
        status = _metric_status(item)
        if status not in {"异常", "需关注", "需大模型判断"}:
            continue
        value = _format_notification_metric_value(item)
        label = _safe_str(item.get("metricName") or item.get("metricCode"))
        findings.append(f"{label}={value}（{_metric_reason(item)}）")
    return findings


def _build_inspection_conclusion(metric_results: list[dict[str, Any]]) -> str:
    if not metric_results:
        return "未获取到有效指标数据，请检查指标采集链路与权限配置。"

    status = _derive_inspection_status(metric_results)
    findings = _collect_inspection_findings(metric_results)
    finding_text = "；".join(findings[:3])

    if status == "异常":
        if finding_text:
            return f"发现异常指标：{finding_text}，建议优先按阈值规则排查对应资源状态。"
        return "存在异常指标，建议立即排查资源连接与服务状态。"
    if status == "需关注":
        if finding_text:
            return f"发现需关注指标：{finding_text}，其中未命中规则配置的指标需结合上下文由大模型进一步判断。"
        return "存在需关注指标，建议持续观察并进一步核查。"
    return "各项指标均在正常范围，资源运行健康。"


def _build_notification_metric_lines(metric_results: list[dict[str, Any]]) -> list[str]:
    if not metric_results:
        return ["- 未获取到指标值"]

    lines: list[str] = []
    for item in metric_results:
        metric_name = _safe_str(item.get("metricName") or item.get("metricCode")) or "指标"
        metric_code = _safe_str(item.get("metricCode")) or "-"
        metric_value = _format_notification_metric_value(item)
        lines.append(f"- {metric_name}（{metric_code}）：{metric_value}")
    return lines


def _build_notification_context(result: dict[str, Any]) -> dict[str, Any]:
    definitions = result.get("definitions") or {}
    metric_batch = result.get("metricDataBatch") or {}
    metric_results = metric_batch.get("metricResults") or []
    inspection_time = _extract_inspection_time(metric_results)
    return {
        "inspection_object": _safe_str(result.get("inspectionObject")) or "-",
        "resource_name": _safe_str(result.get("resourceName")) or "-",
        "res_id": _safe_str(result.get("resId")) or "-",
        "metric_type": _safe_str(result.get("metricType")) or "-",
        "metrics_total": str(int(definitions.get("metricsTotal") or 0)),
        "definition_source": _safe_str(definitions.get("source")) or "-",
        "data_source": _safe_str(metric_batch.get("source")) or "-",
        "metric_preview": _notification_metric_preview(metric_results),
        "metric_results": metric_results,
        "inspection_status": _derive_inspection_status(metric_results),
        "inspection_time": inspection_time,
        "inspection_conclusion": _build_inspection_conclusion(metric_results),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def _build_notification_markdown_lines(context: dict[str, Any]) -> list[str]:
    return [
        "**AI巡检结果**",
        "",
        f"- **巡检对象**：{context['inspection_object']}",
        f"- **资源**：{context['resource_name']} / CI ID: {context['res_id']}",
        f"- **资源类型**：{context['metric_type']}",
        f"- **整体状态**：{context['inspection_status']}",
        f"- **指标总数**：{context['metrics_total']}",
        f"- **指标定义来源**：{context['definition_source']}",
        f"- **指标数据来源**：{context['data_source']}",
        f"- **巡检时间**：{context['inspection_time']}",
        "",
        "**全量指标值**",
        *_build_notification_metric_lines(context["metric_results"]),
        "",
        "**巡检结论**",
        f"- {context['inspection_conclusion']}",
        "",
        "> 此结果由 AI 自动巡检生成，请及时关注。",
    ]


def _build_notification_plain_text_lines(context: dict[str, Any]) -> list[str]:
    return [
        "AI巡检结果",
        "",
        f"- 巡检对象：{context['inspection_object']}",
        f"- 资源：{context['resource_name']} / CI ID: {context['res_id']}",
        f"- 资源类型：{context['metric_type']}",
        f"- 整体状态：{context['inspection_status']}",
        f"- 指标总数：{context['metrics_total']}",
        f"- 指标定义来源：{context['definition_source']}",
        f"- 指标数据来源：{context['data_source']}",
        f"- 巡检时间：{context['inspection_time']}",
        "",
        "全量指标值",
        *_build_notification_metric_lines(context["metric_results"]),
        "",
        "巡检结论",
        f"- {context['inspection_conclusion']}",
        "",
        "此结果由 AI 自动巡检生成，请及时关注。",
    ]


def _build_notification_markdown_text(context: dict[str, Any]) -> str:
    return "\n".join(_build_notification_markdown_lines(context))


def _build_app_notify_payload(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": "AI巡检结果",
        "content": "\n".join(_build_notification_plain_text_lines(context)),
        "type": "text",
    }


def _build_dingtalk_notify_payload(context: dict[str, Any]) -> dict[str, Any]:
    markdown_lines: list[str] = []
    keyword = _get_notify_env("DINGTALK_KEYWORD")
    if keyword:
        markdown_lines.extend([keyword, ""])
    markdown_lines.extend(_build_notification_markdown_lines(context))
    payload: dict[str, Any] = {
        "msgtype": "markdown",
        "markdown": {
            "title": _safe_str(context.get("inspection_object")) or "AI巡检结果",
            "text": "\n".join(markdown_lines),
        },
    }
    if _get_notify_mention_all():
        payload["at"] = {"isAtAll": True}
    return payload


def _build_feishu_status_text(status: str) -> str:
    if status == "正常":
        return "🟢 正常"
    if status == "需关注":
        return "🟠 需关注"
    if status == "异常":
        return "🔴 异常"
    return "⚪ 未知"


def _build_feishu_header_template(status: str) -> str:
    if status == "正常":
        return "green"
    if status == "需关注":
        return "orange"
    if status == "异常":
        return "red"
    return "grey"


def _build_feishu_metric_table(metric_results: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    for item in metric_results:
        metric_name = _safe_str(item.get("metricName") or item.get("metricCode")) or "-"
        rows.append(
            {
                "metric_name": metric_name,
                "metric_code": _safe_str(item.get("metricCode")) or "-",
                "latest_value": _format_notification_metric_value(item),
            }
        )
    return {
        "tag": "table",
        "page_size": min(max(len(rows), 10), 50),
        "columns": [
            {
                "name": "metric_name",
                "display_name": "指标名",
                "width": "auto",
                "horizontal_align": "left",
            },
            {
                "name": "metric_code",
                "display_name": "指标编码",
                "width": "auto",
                "horizontal_align": "left",
            },
            {
                "name": "latest_value",
                "display_name": "最近值",
                "width": "auto",
                "horizontal_align": "left",
            },
        ],
        "rows": rows or [{"metric_name": "未获取到指标值", "metric_code": "-", "latest_value": "-"}],
    }


def _build_feishu_notify_payload(context: dict[str, Any]) -> dict[str, Any]:
    elements: list[dict[str, Any]] = []
    if _get_notify_mention_all():
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "<at id=all></at>",
                },
            }
        )
    elements.extend(
        [
            {
                "tag": "div",
                "fields": [
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**巡检对象**\n{context['inspection_object']}",
                        },
                    },
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**资源 ID (CI ID)**\n{context['res_id']}",
                        },
                    },
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**资源名称**\n{context['resource_name']}",
                        },
                    },
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**资源类型**\n{context['metric_type']}",
                        },
                    },
                ],
            },
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**整体状态**\n{_build_feishu_status_text(context['inspection_status'])}"
                    ),
                },
            },
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        "**巡检摘要**\n"
                        f"- 整体状态：{context['inspection_status']}\n"
                        f"- 指标总数：{context['metrics_total']}\n"
                        f"- 指标定义来源：{context['definition_source']}\n"
                        f"- 指标数据来源：{context['data_source']}\n"
                        f"- 巡检时间：{context['inspection_time']}"
                    ),
                },
            },
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "**指标值明细**",
                },
            },
            _build_feishu_metric_table(context["metric_results"]),
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**巡检结论**\n- {context['inspection_conclusion']}",
                },
            },
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": f"巡检时间：{context['inspection_time']}",
                    },
                    {
                        "tag": "plain_text",
                        "content": "此结果由 AI 自动巡检生成，请及时关注。",
                    },
                ],
            },
        ]
    )
    payload: dict[str, Any] = {
        "msg_type": "interactive",
        "card": {
            "config": {
                "wide_screen_mode": True,
                "enable_forward": True,
            },
            "header": {
                "template": _build_feishu_header_template(context["inspection_status"]),
                "title": {
                    "tag": "plain_text",
                    "content": f"AI巡检报告 — {context['resource_name'] or context['inspection_object']}",
                },
            },
            "elements": elements,
        },
    }
    secret = _get_notify_env("FEISHU_SECRET")
    if secret:
        timestamp = str(int(time.time()))
        string_to_sign = f"{timestamp}\n{secret}"
        sign = base64.b64encode(
            hmac.new(
                string_to_sign.encode("utf-8"),
                b"",
                digestmod=hashlib.sha256,
            ).digest()
        ).decode("utf-8")
        payload["timestamp"] = timestamp
        payload["sign"] = sign
    return payload


def _build_dingtalk_signed_webhook_url(webhook_url: str) -> str:
    secret = _get_notify_env("DINGTALK_SECRET")
    if not secret:
        return webhook_url
    timestamp = str(int(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{secret}"
    sign = hmac.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    encoded_sign = quote_plus(base64.b64encode(sign))
    separator = "&" if "?" in webhook_url else "?"
    return f"{webhook_url}{separator}timestamp={timestamp}&sign={encoded_sign}"


def _is_successful_push_response(response_json: Any) -> bool:
    if not isinstance(response_json, dict) or not response_json:
        return True
    if "success" in response_json:
        return bool(response_json.get("success"))
    if "ok" in response_json:
        return bool(response_json.get("ok"))
    if "code" in response_json:
        return str(response_json.get("code") or "") in {"0", "200"}
    if "status" in response_json:
        return str(response_json.get("status") or "").lower() in {"ok", "success", "sent"}
    if "errcode" in response_json:
        return str(response_json.get("errcode") or "") == "0"
    return True


def _send_app_push(*, channel_name: str, push_url: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        response = requests.post(
            push_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=_get_notify_timeout(),
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        return {
            "channel": channel_name,
            "status": "failed",
            "reason": str(exc),
        }

    try:
        response_json = response.json()
    except (AttributeError, ValueError):
        response_json = {}

    if _is_successful_push_response(response_json):
        return {
            "channel": channel_name,
            "status": "sent",
            "reason": "",
        }

    return {
        "channel": channel_name,
        "status": "failed",
        "reason": response_json.get("errmsg")
        or response_json.get("message")
        or response_json.get("reason")
        or "push_rejected",
    }


def _send_json_webhook(
    *,
    channel_name: str,
    webhook_url: str,
    payload: dict[str, Any],
    success_predicate: Any,
) -> dict[str, Any]:
    try:
        response = requests.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=_get_notify_timeout(),
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        return {
            "channel": channel_name,
            "status": "failed",
            "reason": str(exc),
        }

    try:
        response_json = response.json()
    except ValueError as exc:
        return {
            "channel": channel_name,
            "status": "failed",
            "reason": f"invalid_json_response: {exc}",
        }

    if success_predicate(response_json):
        return {
            "channel": channel_name,
            "status": "sent",
            "reason": "",
        }
    return {
        "channel": channel_name,
        "status": "failed",
        "reason": response_json.get("errmsg")
        or response_json.get("message")
        or "webhook_rejected",
    }


def _notify_inspection_result(result: dict[str, Any]) -> dict[str, Any]:
    app_push_url = _get_notify_env("PUSH_URL") or _get_notify_env("WEBHOOK_URL")
    dingtalk_webhook_url = _get_notify_env("DINGTALK_WEBHOOK_URL")
    feishu_webhook_url = _get_notify_env("FEISHU_WEBHOOK_URL")
    if not app_push_url and not dingtalk_webhook_url and not feishu_webhook_url:
        return {
            "enabled": False,
            "status": "skipped",
            "reason": "webhook_not_configured",
            "channels": [],
        }

    context = _build_notification_context(result)
    channels: list[dict[str, Any]] = []
    if app_push_url:
        channels.append(
            _send_app_push(
                channel_name="app",
                push_url=app_push_url,
                payload=_build_app_notify_payload(context),
            )
        )
    if dingtalk_webhook_url:
        channels.append(
            _send_json_webhook(
                channel_name="dingtalk",
                webhook_url=_build_dingtalk_signed_webhook_url(dingtalk_webhook_url),
                payload=_build_dingtalk_notify_payload(context),
                success_predicate=lambda data: str(data.get("errcode", "")) == "0",
            )
        )
    if feishu_webhook_url:
        channels.append(
            _send_json_webhook(
                channel_name="feishu",
                webhook_url=feishu_webhook_url,
                payload=_build_feishu_notify_payload(context),
                success_predicate=lambda data: str(data.get("StatusCode", "")) == "0"
                or str(data.get("code", "")) == "0",
            )
        )

    sent_count = sum(1 for item in channels if item.get("status") == "sent")
    if sent_count == len(channels) and channels:
        status = "sent"
        reason = ""
    elif sent_count > 0:
        status = "partial"
        reason = "partial_failure"
    else:
        status = "failed"
        reason = "; ".join(
            f"{item.get('channel')}:{item.get('reason') or 'unknown'}"
            for item in channels
        )
    return {
        "enabled": True,
        "status": status,
        "reason": reason,
        "channels": channels,
    }


def _format_notification_channels(notification: dict[str, Any], *, fallback: str) -> str:
    sent_channels = [
        _safe_str(item.get("channel"))
        for item in notification.get("channels") or []
        if _safe_str(item.get("status")).lower() == "sent"
    ]
    if not sent_channels:
        return fallback
    label_map = {
        "app": "应用",
        "dingtalk": "钉钉",
        "feishu": "飞书",
    }
    labels = [label_map.get(name, name) for name in sent_channels if name]
    return "、".join(labels) + "已发送"


def _format_notification_status(notification: dict[str, Any]) -> str:
    status = _safe_str(notification.get("status")).lower()
    reason = _safe_str(notification.get("reason"))
    if status == "sent":
        return "✅ 已成功推送"
    if status == "partial":
        return "⚠️ 部分推送成功"
    if status == "failed":
        return f"❌ 推送失败：{reason or '未知错误'}"
    if status == "skipped":
        if reason == "webhook_not_configured":
            return "— 未配置"
        return "— 已跳过"
    return "— 未配置"


def fetch_metric_data_batch(
    *,
    res_id: str | int,
    metric_definitions: list[dict[str, Any]],
    query_type: str = "0",
    start_time: str | None = None,
    end_time: str | None = None,
    api_base_url: str | None = None,
    token: str | None = None,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    normalized_res_id = _safe_str(res_id)
    if not normalized_res_id:
        raise ValueError("res_id 不能为空")

    metric_codes = [
        _safe_str(metric.get("code"))
        for metric in metric_definitions
        if _safe_str(metric.get("code"))
    ]
    if not metric_codes:
        raise ValueError("metric_definitions 不能为空，且必须包含至少一个指标编码")

    url = f"{_ALARM_METRIC_HELPERS._normalize_base_url(api_base_url)}/resource/pm/getMetricData"  # noqa: SLF001
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "Accept": "application/json",
        "Authorization": f"Bearer {_ALARM_METRIC_HELPERS._get_token(token)}",  # noqa: SLF001
    }
    request_payload = _build_metric_data_batch_request(
        res_id=normalized_res_id,
        metric_codes=metric_codes,
        query_type=query_type,
        start_time=start_time,
        end_time=end_time,
    )
    resolved_timeout = _get_timeout(timeout_seconds)

    source = "live"
    fallback_reason = None
    try:
        response_payload, _transport = _ALARM_METRIC_HELPERS._post_json_with_fallback(  # noqa: SLF001
            url=url,
            headers=headers,
            json_payload=request_payload,
            timeout_seconds=resolved_timeout,
        )
        data_rows = response_payload.get("data") or []
        if not data_rows:
            raise ValueError("指标数据接口未返回有效 data")
    except (requests.exceptions.RequestException, ValueError, json.JSONDecodeError) as error:
        source = "mock"
        fallback_reason = str(error)
        response_payload = _build_mock_metric_data_batch_payload(
            res_id=normalized_res_id,
            metric_codes=metric_codes,
        )

    return {
        "code": 200,
        "msg": "查询成功" if source == "live" else f"接口失败，已回退到 mock 数据：{fallback_reason}",
        "source": source,
        "fallbackReason": fallback_reason,
        "url": url,
        "request": request_payload,
        "resId": normalized_res_id,
        "metricResults": _extract_metric_data_results(
            response_payload,
            metric_definitions=metric_definitions,
            source=source,
        ),
        "raw": response_payload,
    }


def inspect_resource_metrics(
    *,
    metric_type: str,
    res_id: str | int,
    inspection_object: str = "",
    resource_name: str = "",
    page_size: int | None = None,
    api_base_url: str | None = None,
    token: str | None = None,
    timeout_seconds: int | None = None,
    query_type: str = "0",
    start_time: str | None = None,
    end_time: str | None = None,
    notify: bool = True,
) -> dict[str, Any]:
    definitions = fetch_all_metric_definitions(
        metric_type=metric_type,
        page_size=page_size,
        api_base_url=api_base_url,
        token=token,
        timeout_seconds=timeout_seconds,
    )
    verification_rules = fetch_inspection_verification_rules(
        api_base_url=api_base_url,
        token=token,
        timeout_seconds=timeout_seconds,
        page_size=page_size,
    )
    metric_data_batch = fetch_metric_data_batch(
        res_id=res_id,
        metric_definitions=definitions.get("metrics") or [],
        query_type=query_type,
        start_time=start_time,
        end_time=end_time,
        api_base_url=api_base_url,
        token=token,
        timeout_seconds=timeout_seconds,
    )
    metric_data_batch["metricResults"] = _apply_metric_verification(
        metric_data_batch.get("metricResults") or [],
        verification_rules,
    )
    result = {
        "code": 200,
        "msg": "查询成功",
        "inspectionObject": _safe_str(inspection_object),
        "resourceName": _safe_str(resource_name),
        "metricType": _safe_str(metric_type),
        "resId": _safe_str(res_id),
        "definitions": definitions,
        "verificationRules": verification_rules,
        "metricDataBatch": metric_data_batch,
    }
    result["notification"] = _notify_inspection_result(result) if notify else {
        "enabled": False,
        "status": "skipped",
        "reason": "notify_disabled",
        "channels": [],
    }
    return result


def _render_metric_data_table(metric_results: list[dict[str, Any]]) -> str:
    if not metric_results:
        return "- 未获取到指标值"

    lines = [
        "| 指标名 | 指标编码 | 最近值 | 采样时间 | Min/Avg/Max | 数据来源 | 判定 | 判定依据 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for item in metric_results:
        value = _safe_str(item.get("latestValue") or item.get("avgValue") or "-")
        unit = _safe_str(item.get("unit"))
        if unit and value != "-":
            value = f"{value} {unit}".strip()
        min_avg_max = "/".join(
            [
                _safe_str(item.get("minValue") or "-"),
                _safe_str(item.get("avgValue") or "-"),
                _safe_str(item.get("maxValue") or "-"),
            ]
        )
        lines.append(
            "| {name} | {code} | {value} | {sample_time} | {mam} | {source} | {status} | {reason} |".format(
                name=_safe_str(item.get("metricName") or item.get("metricCode") or "-").replace("|", "\\|"),
                code=_safe_str(item.get("metricCode") or "-").replace("|", "\\|"),
                value=value.replace("|", "\\|"),
                sample_time=_safe_str(item.get("sampleTime") or "-").replace("|", "\\|"),
                mam=min_avg_max.replace("|", "\\|"),
                source=_safe_str(item.get("source") or "-").replace("|", "\\|"),
                status=_metric_status(item).replace("|", "\\|"),
                reason=_metric_reason(item).replace("|", "\\|"),
            )
        )
    return "\n".join(lines)


def _extract_inspection_time(metric_results: list[dict[str, Any]]) -> str:
    for item in metric_results:
        sample_time = _safe_str(item.get("sampleTime"))
        if sample_time:
            return sample_time
    return "-"


def _parse_metric_numeric_value(value: Any) -> float | None:
    text = _safe_str(value)
    if not text:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _split_rule_static_values(value: Any) -> list[str]:
    text = _normalize_rule_text(value)
    if not text:
        return []
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return [_normalize_rule_text(item) for item in parsed if _normalize_rule_text(item)]
    return [item.strip() for item in re.split(r"[;,，；]+", text) if item.strip()]


def _format_rule_condition(operator_label: str, static_values: list[str]) -> str:
    if not static_values:
        return operator_label
    if operator_label in {"介于", "不介于"} and len(static_values) >= 2:
        return f"{operator_label} {static_values[0]} ~ {static_values[1]}"
    return f"{operator_label} {' / '.join(static_values)}"


def _values_equal(left: str, right: str) -> bool:
    left_number = _parse_metric_numeric_value(left)
    right_number = _parse_metric_numeric_value(right)
    if left_number is not None and right_number is not None:
        return left_number == right_number
    return left.strip().lower() == right.strip().lower()


def _evaluate_rule_condition(
    metric_value: str,
    operator_label: str,
    static_values: list[str],
) -> bool | None:
    normalized_operator = operator_label.strip()
    numeric_value = _parse_metric_numeric_value(metric_value)

    if normalized_operator == "=":
        return bool(static_values) and _values_equal(metric_value, static_values[0])
    if normalized_operator == "!=":
        return bool(static_values) and not _values_equal(metric_value, static_values[0])
    if normalized_operator in {">", "<", ">=", "<="}:
        threshold = _parse_metric_numeric_value(static_values[0] if static_values else "")
        if numeric_value is None or threshold is None:
            return None
        if normalized_operator == ">":
            return numeric_value > threshold
        if normalized_operator == "<":
            return numeric_value < threshold
        if normalized_operator == ">=":
            return numeric_value >= threshold
        return numeric_value <= threshold
    if normalized_operator in {"介于", "不介于"}:
        if len(static_values) < 2:
            return None
        lower = _parse_metric_numeric_value(static_values[0])
        upper = _parse_metric_numeric_value(static_values[1])
        if numeric_value is None or lower is None or upper is None:
            return None
        is_between = lower <= numeric_value <= upper
        return is_between if normalized_operator == "介于" else not is_between
    if normalized_operator == "包含":
        return bool(static_values) and static_values[0].lower() in metric_value.lower()
    if normalized_operator == "不包含":
        return bool(static_values) and static_values[0].lower() not in metric_value.lower()
    if normalized_operator in {"开始以", "开始不是以"}:
        if not static_values:
            return None
        starts = metric_value.lower().startswith(static_values[0].lower())
        return starts if normalized_operator == "开始以" else not starts
    if normalized_operator in {"结束以", "结束不是以"}:
        if not static_values:
            return None
        ends = metric_value.lower().endswith(static_values[0].lower())
        return ends if normalized_operator == "结束以" else not ends
    if normalized_operator in {"是空的", "不是空的"}:
        is_empty = not metric_value.strip()
        return is_empty if normalized_operator == "是空的" else not is_empty
    if normalized_operator in {"在列表", "不在列表"}:
        if not static_values:
            return None
        matched = any(_values_equal(metric_value, item) for item in static_values)
        return matched if normalized_operator == "在列表" else not matched
    if normalized_operator == "使用语法匹配值":
        if not static_values:
            return None
        try:
            return re.search(static_values[0], metric_value) is not None
        except re.error:
            return None
    return None


def _derive_heuristic_metric_status(item: dict[str, Any]) -> tuple[str, str]:
    label = _safe_str(item.get("metricName") or item.get("metricCode"))
    numeric = _parse_metric_numeric_value(item.get("latestValue") or item.get("avgValue"))
    if numeric is None:
        return "正常", "经验规则未识别到明显异常"
    if "连接失败" in label and numeric > 0:
        return "异常", "经验规则判定连接失败次数大于 0"
    if ("慢查询" in label or "锁" in label) and numeric > 0:
        return "需关注", "经验规则判定慢查询或锁相关指标大于 0"
    if "使用率" in label and numeric >= 80:
        return "需关注", "经验规则判定使用率达到 80% 及以上"
    return "正常", "经验规则未发现异常"


def _resolve_metric_verification(
    item: dict[str, Any],
    *,
    rule_index: dict[str, list[dict[str, Any]]],
    operator_map: dict[str, str],
    verification_source: str,
) -> dict[str, Any]:
    metric_code = _safe_str(item.get("metricCode"))
    metric_name = _safe_str(item.get("metricName") or metric_code) or "指标"
    metric_value = _safe_str(item.get("latestValue") or item.get("avgValue"))

    if verification_source != "live":
        heuristic_status, heuristic_reason = _derive_heuristic_metric_status(item)
        return {
            **item,
            "verificationStatus": heuristic_status,
            "verificationReason": f"阈值规则不可用，{heuristic_reason}",
            "verificationSource": "heuristic",
            "matchedRuleName": "",
        }

    matched_rules = rule_index.get(metric_code.lower(), [])
    if not matched_rules:
        return {
            **item,
            "verificationStatus": "需大模型判断",
            "verificationReason": "未找到对应阈值规则配置",
            "verificationSource": "llm",
            "matchedRuleName": "",
        }

    config = matched_rules[0]
    rule_name = _safe_str(config.get("ruleName")) or metric_name
    unsupported_conditions: list[str] = []
    failed_conditions: list[str] = []
    passed_conditions: list[str] = []
    for condition in config.get("conditions") or []:
        operator_label = operator_map.get(_safe_str(condition.get("operator"))) or _safe_str(condition.get("operator"))
        static_values = _split_rule_static_values(condition.get("staticValues"))
        condition_text = _format_rule_condition(operator_label, static_values)
        matched = _evaluate_rule_condition(metric_value, operator_label, static_values)
        if matched is True:
            passed_conditions.append(condition_text)
            continue
        if matched is False:
            failed_conditions.append(condition_text)
            continue
        unsupported_conditions.append(condition_text)

    if failed_conditions:
        return {
            **item,
            "verificationStatus": "异常",
            "verificationReason": f"不满足规则“{rule_name}”：{'；'.join(failed_conditions)}，当前值 {metric_value or '-'}",
            "verificationSource": "rule",
            "matchedRuleName": rule_name,
        }
    if unsupported_conditions:
        return {
            **item,
            "verificationStatus": "需大模型判断",
            "verificationReason": f"规则“{rule_name}”包含暂不支持自动判定的条件：{'；'.join(unsupported_conditions)}",
            "verificationSource": "llm",
            "matchedRuleName": rule_name,
        }
    return {
        **item,
        "verificationStatus": "正常",
        "verificationReason": f"满足规则“{rule_name}”：{'；'.join(passed_conditions) or '命中阈值配置'}",
        "verificationSource": "rule",
        "matchedRuleName": rule_name,
    }


def _apply_metric_verification(
    metric_results: list[dict[str, Any]],
    verification_rules: dict[str, Any],
) -> list[dict[str, Any]]:
    rule_index = _build_rule_config_index(verification_rules.get("ruleConfigs") or [])
    operator_map = verification_rules.get("operatorMap") or {}
    verification_source = _safe_str(verification_rules.get("source")) or "unavailable"
    return [
        _resolve_metric_verification(
            item,
            rule_index=rule_index,
            operator_map=operator_map,
            verification_source=verification_source,
        )
        for item in metric_results
    ]


def _metric_status(item: dict[str, Any]) -> str:
    status = _safe_str(item.get("verificationStatus"))
    if status:
        return status
    heuristic_status, _heuristic_reason = _derive_heuristic_metric_status(item)
    return heuristic_status


def _metric_reason(item: dict[str, Any]) -> str:
    reason = _safe_str(item.get("verificationReason"))
    if reason:
        return reason
    _heuristic_status, heuristic_reason = _derive_heuristic_metric_status(item)
    return heuristic_reason


def _derive_inspection_status(metric_results: list[dict[str, Any]]) -> str:
    if not metric_results:
        return "未知"

    has_warning = False
    for item in metric_results:
        status = _metric_status(item)
        if status == "异常":
            return "异常"
        if status in {"需关注", "需大模型判断"}:
            has_warning = True

    return "需关注" if has_warning else "正常"


def render_markdown(result: dict[str, Any]) -> str:
    definitions = result.get("definitions") or {}
    verification_rules = result.get("verificationRules") or {}
    metric_batch = result.get("metricDataBatch") or {}
    metric_results = metric_batch.get("metricResults") or []
    notification = result.get("notification") or {}
    inspection_object = _safe_str(result.get("inspectionObject")) or "-"
    resource_name = _safe_str(result.get("resourceName")) or "-"
    res_id = _safe_str(result.get("resId")) or "-"
    metric_type = _safe_str(result.get("metricType")) or "-"
    metrics_total = str(int(definitions.get("metricsTotal") or 0))
    data_source = _safe_str(metric_batch.get("source")) or "-"
    inspection_time = _extract_inspection_time(metric_results)
    inspection_status = _derive_inspection_status(metric_results)
    title_target = resource_name if resource_name != "-" else inspection_object
    lines = [
        PORTAL_INSPECTION_CARD_MARKER,
        "",
        "---",
        f"## 巡检结果 — {title_target}",
        f"- 巡检对象：`{inspection_object}`",
        f"- 资源名称：`{resource_name}`",
        f"- 资源 ID（CI ID）：`{res_id}`",
        f"- 资源类型：`{metric_type}`",
        f"- 指标总数：`{metrics_total}`",
        f"- 指标定义来源：`{_safe_str(definitions.get('source')) or '-'}`",
        f"- 指标数据来源：`{data_source}`",
        f"- 通知状态：`{_format_notification_status(notification)}`",
        f"- 通知渠道：`{_format_notification_channels(notification, fallback='未发送')}`",
        "",
        "## 基本信息",
        "| 字段 | 值 |",
        "|---|---|",
        f"| 巡检对象 | {inspection_object} |",
        f"| 资源名称 | {resource_name} |",
        f"| 资源 ID（CI ID） | {res_id} |",
        f"| 资源类型 | {metric_type} |",
        "| 管理 IP | - |",
        f"| 状态 | {inspection_status} |",
        f"| 指标总数 | {metrics_total} |",
        f"| 数据来源 | {data_source} |",
        f"| 巡检时间 | {inspection_time} |",
        "",
        "## 指标数据",
        _render_metric_data_table(metric_results),
    ]
    if definitions.get("fallbackReason"):
        lines.append("")
        lines.append(f"- 指标定义回退原因：{definitions['fallbackReason']}")
    if metric_batch.get("fallbackReason"):
        lines.append(f"- 指标数据回退原因：{metric_batch['fallbackReason']}")
    if verification_rules.get("ruleConfigsFallbackReason"):
        lines.append(f"- 阈值规则回退原因：{verification_rules['ruleConfigsFallbackReason']}")
    if verification_rules.get("operatorDictFallbackReason"):
        lines.append(f"- 规则字典回退原因：{verification_rules['operatorDictFallbackReason']}")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="查询巡检对象的全部指标定义与指标数据")
    parser.add_argument("--metric-type", required=True, help="资源类型，对应 ciType，例如 mysql")
    parser.add_argument("--res-id", required=True, help="CMDB 返回的 CI ID")
    parser.add_argument("--inspection-object", default="", help="用户输入的巡检对象")
    parser.add_argument("--resource-name", default="", help="CMDB 确认的资源名称")
    parser.add_argument("--page-size", type=int, default=None, help="每页指标定义数量，默认从 .env 读取")
    parser.add_argument("--api-base-url", help="API 基础地址，默认从 .env 读取")
    parser.add_argument("--token", help="Bearer Token，默认从环境变量 INOE_API_TOKEN 读取")
    parser.add_argument("--timeout-seconds", type=int, default=None, help="超时时间，默认从 .env 读取")
    parser.add_argument("--query-type", default="0", help="指标查询类型，0 表示查询最近一次")
    parser.add_argument("--start-time", help="开始时间，queryType != 0 时必填")
    parser.add_argument("--end-time", help="结束时间，queryType != 0 时必填")
    parser.add_argument("--no-notify", action="store_true", help="仅查询巡检结果，不执行 webhook 推送")
    parser.add_argument("--output", choices=sorted(ALLOWED_OUTPUTS), default="json", help="输出格式")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        result = inspect_resource_metrics(
            metric_type=args.metric_type,
            res_id=args.res_id,
            inspection_object=args.inspection_object,
            resource_name=args.resource_name,
            page_size=args.page_size,
            api_base_url=args.api_base_url,
            token=args.token,
            timeout_seconds=args.timeout_seconds,
            query_type=args.query_type,
            start_time=args.start_time,
            end_time=args.end_time,
            notify=not args.no_notify,
        )
    except ValueError as error:
        print(f"错误: {error}", file=sys.stderr)
        sys.exit(1)

    if args.output == "markdown":
        print(render_markdown(result))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
