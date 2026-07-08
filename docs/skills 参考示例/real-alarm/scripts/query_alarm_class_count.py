#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
告警类别统计查询脚本。

适用接口:
    POST /resource/alarmQuery/queryAlarmClassCount

该接口是通用统计接口。脚本只传用户明确给出的筛选条件；未指定
neAlias、alarmstatus、alarmClass 或时间范围时，请求体保持不带对应
字段，用于查询全量。
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, Iterable, List, Optional

import requests

from get_alarms import (
    _curl_post_json,
    _is_valid_datetime,
    _make_error,
    _normalize_base_url,
    _normalize_ne_alias,
    get_token,
)

ALLOWED_OUTPUTS = {"json", "markdown"}
COUNT_FIELD_CANDIDATES = ("count", "num", "value", "total", "alarmCount")
NAME_FIELD_CANDIDATES = (
    "name",
    "label",
    "alarmClass",
    "alarmclass",
    "alarmSeverity",
    "alarmseverity",
    "alarmseverityName",
    "type",
)


def _clean_text(value: Any) -> str:
    """把任意类型的值统一转成去掉首尾空格的字符串，None 转成空字符串。"""
    if value is None:
        return ""
    return str(value).strip()


def _put_if_present(payload: Dict[str, Any], key: str, value: Any) -> None:
    """只在值非空时写入 payload，避免把空字符串传给接口。"""
    text = _clean_text(value)
    if text:
        payload[key] = text


def _validate_time(name: str, value: Optional[str]) -> Optional[Dict[str, Any]]:
    """校验单个时间字段；空值直接放行（该接口不强制要求时间范围）。"""
    text = _clean_text(value)
    if text and not _is_valid_datetime(text):
        return _make_error(400, f"{name} 格式无效，应为 YYYY-MM-DD HH:MM:SS")
    return None


def build_payload(
    *,
    start_time: str = "",
    end_time: str = "",
    alarm_class: str = "",
    alarm_status: str = "",
    ne_alias: str = "",
    resource_type: str = "",
) -> Dict[str, Any]:
    """按页面字段构建请求体，只传调用方明确给出的过滤条件。"""
    payload: Dict[str, Any] = {}
    _put_if_present(payload, "startTime", start_time)
    _put_if_present(payload, "endTime", end_time)
    _put_if_present(payload, "alarmClass", alarm_class)
    _put_if_present(payload, "alarmstatus", alarm_status)

    normalized_ne_alias = _normalize_ne_alias(ne_alias, resource_type)
    if normalized_ne_alias:
        payload["neAlias"] = normalized_ne_alias

    return payload


def execute(
    *,
    token: str = None,
    api_base_url: str = None,
    start_time: str = "",
    end_time: str = "",
    alarm_class: str = "",
    alarm_status: str = "",
    ne_alias: str = "",
    resource_type: str = "",
) -> Dict[str, Any]:
    """执行告警类别统计查询。

    这个脚本对应的是一个纯统计接口（不返回告警列表，只返回"某类别下
    有多少条"这样的计数），所以逻辑比 get_alarms.py 简单很多：校验参数
    → 拼请求体 → POST 请求 → 兼容几种可能的返回格式。网络失败时同样会
    退到 curl 重试一次（见 get_alarms.py 里 _curl_get_json 的说明，这里
    用的是 POST 版本 _curl_post_json，逻辑是一样的）。
    """
    start_time_error = _validate_time("start_time", start_time)
    if start_time_error:
        return start_time_error
    end_time_error = _validate_time("end_time", end_time)
    if end_time_error:
        return end_time_error

    normalized_token = (token or "").strip()
    if not normalized_token:
        return _make_error(401, "未设置 API Token，请检查 .env 或 --token 参数")

    base_url = _normalize_base_url(api_base_url)
    if not base_url:
        return _make_error(400, "未设置 INOE_API_BASE_URL，请检查 .env 或 --api_base_url 参数")

    url = f"{base_url}/resource/alarmQuery/queryAlarmClassCount"
    headers = {
        "Authorization": f"Bearer {normalized_token}",
        "Content-Type": "application/json;charset=UTF-8",
    }
    payload = build_payload(
        start_time=start_time,
        end_time=end_time,
        alarm_class=alarm_class,
        alarm_status=alarm_status,
        ne_alias=ne_alias,
        resource_type=resource_type,
    )

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()
        return normalize_response(result)
    except requests.exceptions.Timeout:
        return _make_error(408, "请求超时，请检查网络连接或稍后重试")
    except requests.exceptions.ConnectionError:
        return _curl_post_json(
            url=url, headers=headers, data=payload, timeout_seconds=30, allow_array=True
        )
    except requests.exceptions.HTTPError as error:
        status_code = error.response.status_code
        error_text = error.response.text if error.response.text else str(error)
        return _make_error(status_code, f"HTTP错误: {error_text}")
    except ValueError as error:
        return _make_error(500, f"响应解析失败: {str(error)}")
    except requests.exceptions.RequestException as error:
        return _make_error(500, f"请求异常: {str(error)}")
    except Exception as error:  # noqa: BLE001
        return _make_error(500, f"未知错误: {str(error)}")


def normalize_response(result: Any) -> Dict[str, Any]:
    """兼容接口直接返回数组（而不是 {"code":..,"data":[...]} 这种标准
    包裹格式）的情况，统一包装成字典，方便后续代码不用到处判断类型。
    """
    if isinstance(result, dict):
        return result
    if isinstance(result, list):
        return {"code": 200, "msg": "操作成功", "data": result}
    return _make_error(500, "接口返回格式异常：预期为 JSON 对象或数组")


def _iter_candidate_records(result: Dict[str, Any]) -> Iterable[Any]:
    """从返回结果里"猜"出真正的统计记录列表在哪。

    不同接口/不同版本，统计数据可能包在 data / rows / list 里，甚至
    还可能嵌套一层（data 里面又是个带 data/rows/list 的字典）。这个
    函数按 data → rows → list 的顺序依次尝试，找到第一个是列表的字段
    就直接用；找不到列表但找到字典，就把这个字典本身当唯一一条记录
    产出。这样写是为了让脚本对接口返回格式的细微差异更宽容，不用为了
    某个字段名不对就直接报错。
    """
    for key in ("data", "rows", "list"):
        value = result.get(key)
        if isinstance(value, list):
            yield from value
            return
        if isinstance(value, dict):
            for nested_key in ("data", "rows", "list"):
                nested_value = value.get(nested_key)
                if isinstance(nested_value, list):
                    yield from nested_value
                    return
            yield value
            return


def _first_present(record: Dict[str, Any], candidates: Iterable[str]) -> Any:
    """按候选字段名列表依次查找，返回第一个"存在且非空"的值。

    用途和上面的"猜格式"是同一个道理：不同接口版本里，"类别名称"这个
    含义可能叫 name，也可能叫 alarmClass、type 等，这个函数负责按
    优先级把它们都试一遍。
    """
    for key in candidates:
        if key in record and record[key] not in (None, ""):
            return record[key]
    return ""


def _format_record_name(record: Dict[str, Any]) -> str:
    """取出一条统计记录的"类别名称"，取不到就显示"未命名"。"""
    name = _first_present(record, NAME_FIELD_CANDIDATES)
    return _clean_text(name) or "未命名"


def _format_record_count(record: Dict[str, Any]) -> str:
    """取出一条统计记录的"数量"，取不到就显示 0。"""
    count = _first_present(record, COUNT_FIELD_CANDIDATES)
    return _clean_text(count) or "0"


def render_markdown(result: Dict[str, Any]) -> str:
    if str(result.get("code")) != "200":
        return f"告警类别统计查询失败：{result.get('msg') or '未知错误'}"

    records = [item for item in _iter_candidate_records(result) if isinstance(item, dict)]
    if not records:
        data = result.get("data")
        if isinstance(data, dict) and data:
            records = [
                {"name": key, "count": value}
                for key, value in data.items()
                if isinstance(value, (int, float, str))
            ]

    if not records:
        return "未查询到告警类别统计数据。"

    lines = ["## 告警类别统计", "", "| 类别 | 数量 |", "|---|---:|"]
    for record in records:
        lines.append(f"| {_format_record_name(record)} | {_format_record_count(record)} |")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="查询告警类别统计",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 不带任何筛选条件，查询全量类别统计
  uv run scripts/query_alarm_class_count.py --output markdown

  # 查询数据库当前应用类告警统计
  uv run scripts/query_alarm_class_count.py --ne_alias 数据库 --alarm_status 1 --alarm_class application --output markdown

  # 使用资源类型别名
  uv run scripts/query_alarm_class_count.py --resource_type database --alarm_status 1
        """,
    )
    parser.add_argument("--token", type=str, required=False,
                        help="JWT 认证令牌（默认读取 INOE_API_TOKEN）")
    parser.add_argument("--api_base_url", type=str, required=False,
                        help="API 基础地址（默认读取 INOE_API_BASE_URL）")
    parser.add_argument("--start_time", "--startTime", dest="start_time", type=str, default="",
                        help="开始时间，格式 YYYY-MM-DD HH:MM:SS")
    parser.add_argument("--end_time", "--endTime", dest="end_time", type=str, default="",
                        help="结束时间，格式 YYYY-MM-DD HH:MM:SS")
    parser.add_argument("--alarm_class", "--alarmClass", dest="alarm_class", type=str, default="",
                        help="告警类别，如 application")
    parser.add_argument("--alarm_status", "--alarmstatus", dest="alarm_status", type=str, default="",
                        help="告警状态，如 1 表示活跃")
    parser.add_argument("--ne_alias", "--neAlias", dest="ne_alias", type=str, default="",
                        help="资源分类，如 数据库/网络设备/中间件/操作系统/计算资源")
    parser.add_argument("--resource_type", "--resource", dest="resource_type", type=str, default="",
                        help="资源分类别名，如 database/network/middleware/os/server")
    parser.add_argument("--output", choices=sorted(ALLOWED_OUTPUTS), default="json",
                        help="输出格式")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    token = args.token or get_token()
    if not token:
        print("错误: 未设置 API Token", file=sys.stderr)
        print("请设置技能目录下的 .env、环境变量 INOE_API_TOKEN，或使用 --token 参数", file=sys.stderr)
        sys.exit(1)

    result = execute(
        token=token,
        api_base_url=args.api_base_url,
        start_time=args.start_time,
        end_time=args.end_time,
        alarm_class=args.alarm_class,
        alarm_status=args.alarm_status,
        ne_alias=args.ne_alias,
        resource_type=args.resource_type,
    )
    if args.output == "markdown":
        print(render_markdown(result))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))

    sys.exit(0 if str(result.get("code")) == "200" else 1)


if __name__ == "__main__":
    main()
