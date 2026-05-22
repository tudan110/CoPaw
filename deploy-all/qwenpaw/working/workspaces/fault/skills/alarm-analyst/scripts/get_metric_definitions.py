#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
报警分析指标查询脚本。

使用方式:
    python scripts/get_metric_definitions.py --metric-type mysql --output markdown
    python scripts/get_metric_definitions.py --metric-type mysql --res-id 3094 --output markdown

说明:
    - 优先环境变量/共享 secrets，回退当前 skill 目录下的 .env 文件
    - 先按 ciType 调用 /resource/resource/threshold/getMetricDefinitions
    - 再按 AI 选出的关键指标批量调用 /resource/pm/getMetricData（一次请求传递多个 queryKeys）
    - 接口不可用时直接报错，不再回退到 mock 数据
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import requests

try:
    from dotenv import load_dotenv

    HAS_DOTENV = True
except ImportError:
    HAS_DOTENV = False


DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_PAGE_SIZE = 20
DEFAULT_MAX_METRICS = 5
ALLOWED_OUTPUTS = {"json", "markdown"}

METRIC_NAME_KEYS = (
    "metricName",
    "name",
    "metricCnName",
    "metricEnName",
    "showName",
    "displayName",
    "title",
    "label",
)
METRIC_CODE_KEYS = ("metricCode", "code", "metricId", "id", "uid")
METRIC_DESC_KEYS = ("description", "desc", "remark", "comment", "help")
METRIC_UNIT_KEYS = ("unit", "metricUnit", "unitName", "valUnit")

MYSQL_RELEVANCE_RULES = (
    ("死锁", 130, "疑似存在事务互相竞争"),
    ("deadlock", 130, "疑似存在事务互相竞争"),
    ("锁等待", 120, "锁等待持续增加会直接放大写入阻塞"),
    ("lock wait", 120, "锁等待持续增加会直接放大写入阻塞"),
    ("row lock", 115, "行锁竞争会导致写入事务排队"),
    ("table lock", 110, "表级锁等待会扩大影响范围"),
    ("lock", 100, "锁相关指标与当前告警高度相关"),
    ("长事务", 95, "长事务会拉长锁持有时间"),
    ("事务", 90, "事务堆积可能诱发死锁或阻塞链"),
    ("transaction", 90, "事务堆积可能诱发死锁或阻塞链"),
    ("slow sql", 88, "慢 SQL 可能导致锁无法及时释放"),
    ("慢 sql", 88, "慢 SQL 可能导致锁无法及时释放"),
    ("慢sql", 88, "慢 SQL 可能导致锁无法及时释放"),
    ("innodb", 82, "InnoDB 指标通常能直接反映锁等待与事务竞争"),
    ("rollback", 72, "回滚异常升高通常意味着事务冲突"),
    ("commit", 68, "提交速率变化可辅助判断事务拥塞"),
    ("threads_running", 62, "活跃线程数升高说明数据库并发压力上升"),
    ("线程", 58, "线程压力异常可能与锁等待并发出现"),
    ("连接", 56, "连接堆积会放大故障影响面"),
    ("connection", 56, "连接堆积会放大故障影响面"),
)


def _load_skill_env() -> None:
    if not HAS_DOTENV:
        return

    skill_dir = Path(__file__).resolve().parents[1]
    skill_env_file = skill_dir / ".env"
    if skill_env_file.exists():
        load_dotenv(skill_env_file, override=False)


_load_skill_env()


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _normalize_base_url(api_base_url: str | None) -> str:
    base_url = (api_base_url or os.getenv("INOE_API_BASE_URL") or "").strip()
    if not base_url:
        raise ValueError("未设置 INOE_API_BASE_URL，请检查 skills/alarm-analyst/.env")
    return base_url.rstrip("/")


def _get_token(token: str | None) -> str:
    normalized_token = _safe_str(token or os.getenv("INOE_API_TOKEN"))
    if not normalized_token:
        raise ValueError("未设置 INOE_API_TOKEN，请检查 skills/alarm-analyst/.env")
    return normalized_token


def _get_timeout(timeout_seconds: int | None) -> int:
    if timeout_seconds is not None:
        return timeout_seconds
    raw = (os.getenv("ALARM_ANALYST_METRIC_TIMEOUT_SECONDS") or "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    return int(raw)


def _get_page_size(page_size: int | None) -> int:
    if page_size is not None:
        return page_size
    raw = (os.getenv("ALARM_ANALYST_METRIC_PAGE_SIZE") or "").strip()
    if not raw:
        return DEFAULT_PAGE_SIZE
    return int(raw)


def _should_fallback_to_curl(error: Exception) -> bool:
    if isinstance(error, requests.RequestException):
        return True
    if isinstance(error, OSError):
        return True
    return "No route to host" in str(error)


def _curl_post_json(
    *,
    url: str,
    headers: dict[str, str],
    json_payload: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile(delete=False) as body_file:
        body_path = body_file.name

    args = [
        "curl",
        "-sS",
        "--location",
        "-X",
        "POST",
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
    args.extend(["--data-binary", json.dumps(json_payload, ensure_ascii=False)])
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


def _post_json_with_fallback(
    *,
    url: str,
    headers: dict[str, str],
    json_payload: dict[str, Any],
    timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
    try:
        response = requests.post(
            url,
            headers=headers,
            json=json_payload,
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        response_text = response.text.strip()
        if not response_text:
            raise ValueError("接口返回空响应")
        return response.json(), "requests"
    except (requests.exceptions.RequestException, ValueError, json.JSONDecodeError) as error:
        if not _should_fallback_to_curl(error):
            raise
        return _curl_post_json(
            url=url,
            headers=headers,
            json_payload=json_payload,
            timeout_seconds=timeout_seconds,
        ), "curl"


def _pick_first(item: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = _safe_str(item.get(key))
        if value:
            return value
    return ""


def _extract_metric_rows(payload: Any) -> list[dict[str, Any]]:
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
        rows = _extract_metric_rows(nested)
        if rows:
            return rows

    return []


def _normalize_metric(item: dict[str, Any]) -> dict[str, Any]:
    name = _pick_first(item, METRIC_NAME_KEYS)
    code = _pick_first(item, METRIC_CODE_KEYS)
    description = _pick_first(item, METRIC_DESC_KEYS)
    unit = _pick_first(item, METRIC_UNIT_KEYS)
    searchable = " | ".join(
        part for part in (name, code, description, unit, json.dumps(item, ensure_ascii=False)) if part
    ).lower()
    return {
        "name": name or code or "未命名指标",
        "code": code,
        "description": description,
        "unit": unit,
        "raw": item,
        "_searchable": searchable,
    }


def _score_mysql_metric(metric: dict[str, Any]) -> tuple[int, list[str]]:
    searchable = metric["_searchable"]
    score = 0
    reasons: list[str] = []
    for keyword, weight, reason in MYSQL_RELEVANCE_RULES:
        if keyword in searchable:
            score += weight
            if reason not in reasons:
                reasons.append(reason)
    return score, reasons


def _select_relevant_metrics(
    metric_type: str,
    metrics: list[dict[str, Any]],
    *,
    limit: int = DEFAULT_MAX_METRICS,
) -> list[dict[str, Any]]:
    normalized_metric_type = metric_type.strip().lower()
    if limit < 1:
        return []

    if normalized_metric_type != "mysql":
        return metrics[:limit]

    scored: list[tuple[int, dict[str, Any]]] = []
    for metric in metrics:
        score, reasons = _score_mysql_metric(metric)
        enriched_metric = {
            **metric,
            "selectionScore": score,
            "selectionReasons": reasons,
        }
        scored.append((score, enriched_metric))

    prioritized = [
        metric
        for score, metric in sorted(scored, key=lambda item: item[0], reverse=True)
        if score > 0
    ]
    if prioritized:
        return prioritized[:limit]
    return [{**metric, "selectionScore": 0, "selectionReasons": []} for metric in metrics[:limit]]


def _build_metric_definitions_result(
    response_payload: dict[str, Any],
    *,
    metric_type: str,
    url: str,
    request_payload: dict[str, Any],
    source: str,
    fallback_reason: str | None = None,
    limit: int = DEFAULT_MAX_METRICS,
) -> dict[str, Any]:
    raw_rows = _extract_metric_rows(response_payload)
    metrics = [_normalize_metric(item) for item in raw_rows]
    relevant_metrics = _select_relevant_metrics(metric_type, metrics, limit=limit)
    msg = _safe_str(response_payload.get("msg")) or "查询成功"

    return {
        "code": 200,
        "msg": msg,
        "url": url,
        "request": request_payload,
        "source": source,
        "fallbackReason": fallback_reason,
        "metricsTotal": len(metrics),
        "relevantMetrics": relevant_metrics,
        "metrics": metrics,
        "raw": response_payload,
    }


def fetch_metric_definitions(
    *,
    metric_type: str,
    page_num: int = 1,
    page_size: int | None = None,
    api_base_url: str | None = None,
    token: str | None = None,
    timeout_seconds: int | None = None,
    limit: int = DEFAULT_MAX_METRICS,
) -> dict[str, Any]:
    normalized_metric_type = metric_type.strip()
    if not normalized_metric_type:
        raise ValueError("metric_type 不能为空")
    if page_num < 1:
        raise ValueError("page_num 必须大于等于 1")

    resolved_page_size = _get_page_size(page_size)
    if resolved_page_size < 1:
        raise ValueError("page_size 必须大于等于 1")

    url = f"{_normalize_base_url(api_base_url)}/resource/resource/threshold/getMetricDefinitions"
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "Accept": "application/json",
        "Authorization": f"Bearer {_get_token(token)}",
    }
    request_payload = {
        "metricType": normalized_metric_type,
        "pageSize": resolved_page_size,
        "pageNum": page_num,
    }
    resolved_timeout = _get_timeout(timeout_seconds)

    response_payload, _transport = _post_json_with_fallback(
        url=url,
        headers=headers,
        json_payload=request_payload,
        timeout_seconds=resolved_timeout,
    )
    raw_rows = _extract_metric_rows(response_payload)
    if not raw_rows:
        raise ValueError("指标定义接口未返回可用指标列表")
    return _build_metric_definitions_result(
        response_payload,
        metric_type=normalized_metric_type,
        url=url,
        request_payload=request_payload,
        source="live",
        limit=limit,
    )


def _build_metric_data_request(
    *,
    res_id: str | int,
    metric_codes: list[str],
    query_type: str,
    start_time: str | None = None,
    end_time: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "mulRes": [{"resId": res_id}],
        "queryKeys": metric_codes,
        "queryType": str(query_type),
    }
    if str(query_type) != "0":
        if not _safe_str(start_time) or not _safe_str(end_time):
            raise ValueError("当 queryType 不等于 0 时，必须同时提供 startTime 和 endTime")
        payload["startTime"] = _safe_str(start_time)
        payload["endTime"] = _safe_str(end_time)
    return payload


def _infer_unit(metric_code: str) -> str:
    normalized = metric_code.lower()
    if "time" in normalized:
        return "ms"
    if "ratio" in normalized or "usage" in normalized:
        return "%"
    return ""


_infer_mock_unit = _infer_unit


def _extract_latest_metric_value(payload: dict[str, Any], metric_code: str) -> dict[str, str]:
    data_rows = payload.get("data") or []
    if not data_rows or not isinstance(data_rows[0], dict):
        return {
            "latestValue": "",
            "sampleTime": "",
            "minValue": "",
            "avgValue": "",
            "maxValue": "",
            "unit": "",
        }

    row = data_rows[0]
    process_data = row.get("processData") or {}
    original_datas = row.get("originalDatas") or []
    latest_point = original_datas[-1] if original_datas and isinstance(original_datas[-1], dict) else {}

    return {
        "latestValue": _safe_str(latest_point.get(metric_code)),
        "sampleTime": _safe_str(latest_point.get("formatTime")),
        "minValue": _safe_str(process_data.get(f"{metric_code}Min")),
        "avgValue": _safe_str(process_data.get(f"{metric_code}Avg")),
        "maxValue": _safe_str(process_data.get(f"{metric_code}Max")),
        "unit": _safe_str(process_data.get("unit")),
    }


def fetch_metric_data(
    *,
    res_id: str | int,
    metric_code: str,
    query_type: str = "0",
    start_time: str | None = None,
    end_time: str | None = None,
    api_base_url: str | None = None,
    token: str | None = None,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    normalized_metric_code = _safe_str(metric_code)
    if not normalized_metric_code:
        raise ValueError("metric_code 不能为空")
    if not _safe_str(res_id):
        raise ValueError("res_id 不能为空，它应来自 CMDB 返回的 CI ID")

    url = f"{_normalize_base_url(api_base_url)}/resource/pm/getMetricData"
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "Accept": "application/json",
        "Authorization": f"Bearer {_get_token(token)}",
    }
    request_payload = _build_metric_data_request(
        res_id=res_id,
        metric_codes=[normalized_metric_code],
        query_type=query_type,
        start_time=start_time,
        end_time=end_time,
    )
    resolved_timeout = _get_timeout(timeout_seconds)

    response_payload, _transport = _post_json_with_fallback(
        url=url,
        headers=headers,
        json_payload=request_payload,
        timeout_seconds=resolved_timeout,
    )
    data_rows = response_payload.get("data") or []
    if not data_rows:
        raise ValueError("指标数据接口未返回有效 data")

    values = _extract_latest_metric_value(response_payload, normalized_metric_code)
    return {
        "code": 200,
        "msg": "查询成功",
        "source": "live",
        "fallbackReason": None,
        "url": url,
        "request": request_payload,
        "metricCode": normalized_metric_code,
        "resId": str(res_id),
        **values,
        "raw": response_payload,
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
            or _infer_unit(metric_code)
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
        raise ValueError("res_id 不能为空，它应来自 CMDB 返回的 CI ID")

    metric_codes = [
        _safe_str(metric.get("code"))
        for metric in metric_definitions
        if _safe_str(metric.get("code"))
    ]
    if not metric_codes:
        raise ValueError("metric_definitions 不能为空，且必须包含至少一个指标编码")

    url = f"{_normalize_base_url(api_base_url)}/resource/pm/getMetricData"
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "Accept": "application/json",
        "Authorization": f"Bearer {_get_token(token)}",
    }
    request_payload = _build_metric_data_request(
        res_id=normalized_res_id,
        metric_codes=metric_codes,
        query_type=query_type,
        start_time=start_time,
        end_time=end_time,
    )
    resolved_timeout = _get_timeout(timeout_seconds)

    response_payload, _transport = _post_json_with_fallback(
        url=url,
        headers=headers,
        json_payload=request_payload,
        timeout_seconds=resolved_timeout,
    )
    data_rows = response_payload.get("data") or []
    if not data_rows:
        raise ValueError("指标数据接口未返回有效 data")

    return {
        "code": 200,
        "msg": "查询成功",
        "source": "live",
        "fallbackReason": None,
        "url": url,
        "request": request_payload,
        "resId": normalized_res_id,
        "metricResults": _extract_metric_data_results(
            response_payload,
            metric_definitions=metric_definitions,
            source="live",
        ),
        "raw": response_payload,
    }


def analyze_metrics(
    *,
    metric_type: str,
    res_id: str | int | None = None,
    page_num: int = 1,
    page_size: int | None = None,
    api_base_url: str | None = None,
    token: str | None = None,
    timeout_seconds: int | None = None,
    max_metrics: int = DEFAULT_MAX_METRICS,
    query_type: str = "0",
    start_time: str | None = None,
    end_time: str | None = None,
) -> dict[str, Any]:
    definitions = fetch_metric_definitions(
        metric_type=metric_type,
        page_num=page_num,
        page_size=page_size,
        api_base_url=api_base_url,
        token=token,
        timeout_seconds=timeout_seconds,
        limit=max_metrics,
    )

    selected_metrics = definitions.get("relevantMetrics", [])
    metric_data_results: list[dict[str, Any]] = []
    metric_data_request: dict[str, Any] = {}
    if res_id is not None and selected_metrics:
        batch_result = fetch_metric_data_batch(
            res_id=res_id,
            metric_definitions=selected_metrics,
            query_type=query_type,
            start_time=start_time,
            end_time=end_time,
            api_base_url=api_base_url,
            token=token,
            timeout_seconds=timeout_seconds,
        )
        metric_data_results = batch_result.get("metricResults", [])
        metric_data_request = batch_result.get("request", {})

    return {
        "code": 200,
        "msg": "查询成功",
        "metricType": metric_type,
        "resId": None if res_id is None else str(res_id),
        "definitions": definitions,
        "selectedMetrics": selected_metrics,
        "metricDataResults": metric_data_results,
        "metricDataRequest": metric_data_request,
    }


def _render_metrics_table(metrics: list[dict[str, Any]]) -> str:
    if not metrics:
        return "- 未筛选到候选指标"

    lines = [
        "| 指标名 | 指标编码 | 可能影响 |",
        "|---|---|---|",
    ]
    for metric in metrics:
        reasons = "；".join(metric.get("selectionReasons") or []) or "-"
        lines.append(
            "| {name} | {code} | {reasons} |".format(
                name=metric["name"].replace("|", "\\|"),
                code=(metric["code"] or "-").replace("|", "\\|"),
                reasons=reasons.replace("|", "\\|"),
            )
        )
    return "\n".join(lines)


def _render_metric_data_table(metric_data_results: list[dict[str, Any]], selected_metrics: list[dict[str, Any]]) -> str:
    if not metric_data_results:
        return "- 未执行指标值查询"

    name_map = {metric.get("code"): metric.get("name") for metric in selected_metrics}
    lines = [
        "| 指标名 | 指标编码 | 最近值 | 采样时间 | Min/Avg/Max | 数据来源 |",
        "|---|---|---|---|---|---|",
    ]
    for item in metric_data_results:
        metric_code = item.get("metricCode") or "-"
        min_avg_max = "/".join(
            [
                item.get("minValue") or "-",
                item.get("avgValue") or "-",
                item.get("maxValue") or "-",
            ]
        )
        value = item.get("latestValue") or item.get("avgValue") or "-"
        unit = item.get("unit") or ""
        if unit:
            value = f"{value} {unit}".strip()
        lines.append(
            "| {name} | {code} | {value} | {sample_time} | {mam} | {source} |".format(
                name=_safe_str(name_map.get(metric_code) or metric_code).replace("|", "\\|"),
                code=_safe_str(metric_code).replace("|", "\\|"),
                value=_safe_str(value).replace("|", "\\|"),
                sample_time=_safe_str(item.get("sampleTime") or "-").replace("|", "\\|"),
                mam=_safe_str(min_avg_max).replace("|", "\\|"),
                source=_safe_str(item.get("source") or "-").replace("|", "\\|"),
            )
        )
    return "\n".join(lines)


def render_markdown(result: dict[str, Any]) -> str:
    definitions = result.get("definitions") or {}
    lines = [
        "## 指标定义查询结果",
        f"- 请求地址：`{definitions.get('url', '-')}`",
        f"- 请求参数：`{json.dumps(definitions.get('request', {}), ensure_ascii=False)}`",
        f"- 数据来源：`{definitions.get('source', '-')}`",
        f"- 候选指标数：`{definitions.get('metricsTotal', 0)}`",
        "",
        "### AI 优先筛选的指标",
        _render_metrics_table(result.get("selectedMetrics") or []),
    ]

    if definitions.get("fallbackReason"):
        lines.append(f"- 指标定义接口回退原因：{definitions['fallbackReason']}")

    if result.get("resId") is not None:
        metric_data_results = result.get("metricDataResults") or []
        metric_data_request = result.get("metricDataRequest") or {}
        lines.extend(
            [
                "",
                "## 指标值查询结果",
                f"- 资源 ID（CMDB CI ID）：`{result['resId']}`",
                f"- 查询方式：`queryType={metric_data_request.get('queryType', '0')}`",
                f"- 批量查询指标数：`{len(metric_data_request.get('queryKeys', []))}`",
                "",
                _render_metric_data_table(metric_data_results, result.get("selectedMetrics") or []),
            ]
        )

    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="查询资源指标定义，并按关键指标逐个查询指标值")
    parser.add_argument("--metric-type", required=True, help="资源类型，对应 ciType，例如 mysql")
    parser.add_argument("--res-id", help="CMDB 返回的 CI ID，对应 getMetricData 的 mulRes[].resId")
    parser.add_argument("--page-num", type=int, default=1, help="页码，默认 1")
    parser.add_argument("--page-size", type=int, default=None, help="每页条数，默认从 .env 读取")
    parser.add_argument("--api-base-url", help="API 基础地址，默认从 .env 读取")
    parser.add_argument("--token", help="可选，Bearer Token，默认从环境变量 INOE_API_TOKEN 读取")
    parser.add_argument("--timeout-seconds", type=int, default=None, help="超时时间，默认从 .env 读取")
    parser.add_argument("--max-metrics", type=int, default=DEFAULT_MAX_METRICS, help="最多查询多少个相关指标")
    parser.add_argument("--query-type", default="0", help="指标查询类型，0 表示查询最近一次")
    parser.add_argument("--start-time", help="开始时间，queryType != 0 时必填")
    parser.add_argument("--end-time", help="结束时间，queryType != 0 时必填")
    parser.add_argument("--output", choices=sorted(ALLOWED_OUTPUTS), default="json", help="输出格式")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        result = analyze_metrics(
            metric_type=args.metric_type,
            res_id=args.res_id,
            page_num=args.page_num,
            page_size=args.page_size,
            api_base_url=args.api_base_url,
            token=args.token,
            timeout_seconds=args.timeout_seconds,
            max_metrics=args.max_metrics,
            query_type=args.query_type,
            start_time=args.start_time,
            end_time=args.end_time,
        )
    except (ValueError, requests.exceptions.RequestException, json.JSONDecodeError) as error:
        print(f"错误: {error}", file=sys.stderr)
        sys.exit(1)
    except Exception as error:
        print(f"未预期的错误: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(2)

    if args.output == "markdown":
        print(render_markdown(result))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
