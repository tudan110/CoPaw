#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实时告警查询脚本

使用方式:
    uv run get_alarms.py [--token <token>] [--page_num 1] [--page_size 10]

说明:
    - 配置从 skill 目录下的 .env 文件读取
    - 配置项：INOE_API_BASE_URL（API 基础地址）、INOE_API_TOKEN（认证令牌）
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

# 尝试加载 dotenv
try:
    from dotenv import load_dotenv

    HAS_DOTENV = True
except ImportError:
    HAS_DOTENV = False


def _load_skill_env() -> None:
    """
    加载 skill 目录下的 .env 文件

    优先级:
    1. skill 目录下的 .env 文件
    2. 项目根目录下的 .env 文件
    """
    if not HAS_DOTENV:
        return

    # 获取脚本所在目录，然后找到 skill 目录
    script_dir = Path(__file__).parent
    skill_dir = script_dir.parent  # scripts 的上级目录就是 skill 目录

    # 优先加载 skill 目录下的 .env
    skill_env_file = skill_dir / ".env"
    if skill_env_file.exists():
        load_dotenv(skill_env_file, override=True)
        return

    # 如果 skill 目录没有，尝试项目根目录
    project_root = (
        skill_dir.parent.parent
    )  # .claude/skills/real-alarm -> .claude -> project_root
    project_env_file = project_root / ".env"
    if project_env_file.exists():
        load_dotenv(project_env_file, override=False)


# 在模块加载时加载环境变量
_load_skill_env()


def get_api_base_url() -> str:
    """
    获取 API 基础地址

    Returns:
        API 基础地址字符串
    """
    return os.getenv("INOE_API_BASE_URL", "")


def get_token() -> Optional[str]:
    """
    获取 API Token

    Returns:
        Token 字符串，如果不存在则返回 None
    """
    return os.getenv("INOE_API_TOKEN")


def use_mock_data() -> bool:
    """
    检查是否使用 Mock 数据

    Returns:
        bool: 是否使用 Mock 数据
    """
    return os.getenv("USE_MOCK_DATA", "false").lower() in ("true", "1", "yes")


def _load_mock_data() -> Dict[str, Any]:
    """
    加载 Mock 数据文件

    Returns:
        Dict: Mock 数据
    """
    script_dir = Path(__file__).parent
    skill_dir = script_dir.parent
    mock_file = skill_dir / "mock_data.json"

    if not mock_file.exists():
        return _make_error(500, f"Mock 数据文件不存在: {mock_file}")

    try:
        with open(mock_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        return _make_error(500, f"Mock 数据文件解析失败: {str(e)}")
    except Exception as e:
        return _make_error(500, f"读取 Mock 数据文件失败: {str(e)}")


def _make_error(code: int, message: str) -> Dict[str, Any]:
    """构造统一错误响应。"""
    return {"code": code, "msg": message, "total": 0, "rows": []}


def _normalize_base_url(api_base_url: Optional[str]) -> str:
    """规范化 API 基础地址。"""
    base_url = (api_base_url or get_api_base_url()).strip()
    return base_url.rstrip("/")


RESOURCE_NE_ALIAS_MAP = {
    "database": "数据库",
    "data_base": "数据库",
    "db": "数据库",
    "数据库": "数据库",
    "network": "网络设备",
    "network_device": "网络设备",
    "networkdevice": "网络设备",
    "net": "网络设备",
    "网络": "网络设备",
    "网络设备": "网络设备",
    "middleware": "中间件",
    "middle": "中间件",
    "中间件": "中间件",
    "operating_system": "操作系统",
    "operatingsystem": "操作系统",
    "os": "操作系统",
    "操作系统": "操作系统",
    "server": "计算资源",
    "compute": "计算资源",
    "compute_resource": "计算资源",
    "计算": "计算资源",
    "计算资源": "计算资源",
    "服务器": "计算资源",
}


def _normalize_ne_alias(
    ne_alias: Optional[str] = None, resource_type: Optional[str] = None
) -> Optional[str]:
    """把自然语言资源类型归一到实时告警接口的 neAlias 枚举值。"""
    raw_value = (ne_alias or resource_type or "").strip()
    if not raw_value:
        return None

    normalized_key = raw_value.lower().replace("-", "_").replace(" ", "_")
    return RESOURCE_NE_ALIAS_MAP.get(normalized_key, raw_value)


def _validate_paging(page_num: int, page_size: int) -> Optional[Dict[str, Any]]:
    """校验分页参数。"""
    if page_num < 1:
        return _make_error(400, "page_num 必须大于等于 1")
    if page_size < 1:
        return _make_error(400, "page_size 必须大于等于 1")
    return None


def _validate_time_range(
    begin_time: Optional[str], end_time: Optional[str]
) -> Optional[Dict[str, Any]]:
    """校验时间范围参数。"""
    if begin_time and not _is_valid_datetime(begin_time):
        return _make_error(400, "begin_time 格式无效，应为 YYYY-MM-DD HH:MM:SS")
    if end_time and not _is_valid_datetime(end_time):
        return _make_error(400, "end_time 格式无效，应为 YYYY-MM-DD HH:MM:SS")
    return None


def _is_valid_datetime(date_string: str) -> bool:
    """验证日期时间格式。"""
    try:
        datetime.strptime(date_string, "%Y-%m-%d %H:%M:%S")
        return True
    except ValueError:
        return False


def _handle_http_error(error: requests.exceptions.HTTPError) -> Dict[str, Any]:
    """将 HTTPError 转成统一错误响应。"""
    status_code = error.response.status_code
    error_msg = error.response.text if error.response.text else str(error)
    return _build_http_error(status_code, error_msg)


def _build_http_error(status_code: int, error_msg: str) -> Dict[str, Any]:
    """按 HTTP 状态码构造统一错误响应。"""
    message_map = {
        401: "认证失败，请检查 token 是否有效",
        403: "权限不足，无法访问该资源",
        404: "接口不存在，请检查接口地址",
    }
    return _make_error(
        status_code, message_map.get(status_code, f"HTTP错误: {error_msg}")
    )


def _curl_post_json(
    *,
    url: str,
    headers: Dict[str, str],
    data: Dict[str, Any],
    timeout_seconds: int = 30,
    allow_array: bool = False,
) -> Dict[str, Any]:
    """使用系统 curl 作为 requests 的网络兼容性回退。"""
    with tempfile.NamedTemporaryFile(delete=False) as body_file:
        body_path = body_file.name

    args = [
        "curl",
        "-sS",
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
    args.extend(["--data-binary", json.dumps(data, ensure_ascii=False)])
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
            error_text = (completed.stderr or completed.stdout or "curl 请求失败").strip()
            if "timed out" in error_text.lower():
                return _make_error(408, "请求超时，请检查网络连接或稍后重试")
            return _make_error(500, f"curl 请求失败: {error_text}")

        status_code = int((completed.stdout or "").strip() or "0")
        with open(body_path, "r", encoding="utf-8", errors="replace") as handle:
            response_text = handle.read()
        if status_code >= 400:
            return _build_http_error(status_code, response_text)
        if not response_text.strip():
            return _make_error(500, "接口返回空响应")
        result = json.loads(response_text)
        if allow_array and isinstance(result, list):
            return {"code": 200, "msg": "操作成功", "data": result}
        if not isinstance(result, dict):
            return _make_error(500, "接口返回格式异常：预期为 JSON 对象")
        return result
    except json.JSONDecodeError as error:
        return _make_error(500, f"curl 响应解析失败: {str(error)}")
    except subprocess.TimeoutExpired:
        return _make_error(408, "请求超时，请检查网络连接或稍后重试")
    except Exception as error:  # noqa: BLE001
        return _make_error(500, f"curl 回退失败: {str(error)}")
    finally:
        try:
            os.unlink(body_path)
        except OSError:
            pass


def _build_city_list(cities: List[str]) -> List[Dict[str, Any]]:
    """构建城市列表参数。"""
    return [
        {"label": city, "value": city, "remark": None, "raw": {}} for city in cities
    ]


def _normalize_ci_id(ci_id: Optional[str]) -> Optional[Any]:
    """规范化 CI/网元 ID，映射到接口字段 neId。"""
    if ci_id is None:
        return None

    normalized = str(ci_id).strip()
    if not normalized:
        return None
    if normalized.isdigit():
        return int(normalized)
    return normalized


def execute(
    page_num: int = 1,
    page_size: int = 10,
    token: str = None,
    api_base_url: str = None,
    begin_time: str = None,
    end_time: str = None,
    alarm_severity: str = None,
    alarm_severitys: List[str] = None,
    alarm_status: str = None,
    dev_name: str = None,
    manage_ip: str = None,
    cities: List[str] = None,
    alarm_title: str = None,
    ci_id: str = None,
    ne_alias: str = None,
    resource_type: str = None,
) -> Dict[str, Any]:
    """
    执行实时告警查询

    Args:
        page_num: 页码，默认为 1
        page_size: 每页数量，默认为 10
        token: JWT 认证令牌（必填）
        api_base_url: API 基础地址（可选，默认从环境变量读取）
        begin_time: 开始时间，格式 YYYY-MM-DD HH:MM:SS
        end_time: 结束时间，格式 YYYY-MM-DD HH:MM:SS
        alarm_severity: 告警级别（已废弃，使用 alarm_severitys）
        alarm_severitys: 告警级别列表，如 ["1", "2"]
        alarm_status: 告警状态，如 "1" 表示活跃
        dev_name: 设备名称
        manage_ip: 管理IP
        cities: 城市列表
        alarm_title: 告警标题
        ci_id: CI/网元 ID，对应接口字段 neId
        ne_alias: 资源分类，对应接口字段 neAlias，如 数据库/网络设备/中间件/操作系统/计算资源
        resource_type: 资源分类别名，如 database/network/server

    Returns:
        Dict: 包含查询结果或错误信息的字典
    """
    if use_mock_data():
        return _load_mock_data()

    paging_error = _validate_paging(page_num, page_size)
    if paging_error:
        return paging_error

    time_error = _validate_time_range(begin_time, end_time)
    if time_error:
        return time_error

    normalized_token = (token or "").strip()
    if not normalized_token:
        return _make_error(401, "未设置 API Token，请检查 .env 或 --token 参数")

    # 接口配置
    base_url = _normalize_base_url(api_base_url)
    if not base_url:
        return _make_error(400, "未设置 INOE_API_BASE_URL，请检查 .env 或 --api_base_url 参数")
    url = f"{base_url}/resource/realalarm/list"
    headers = {
        "Authorization": f"Bearer {normalized_token}",
        "Content-Type": "application/json;charset=UTF-8",
    }

    normalized_ne_alias = _normalize_ne_alias(ne_alias, resource_type)

    # 构建请求参数
    data = {
        "pageNum": page_num,
        "pageSize": page_size,
        "alarmuniqueid": None,
        "alarmclass": None,
        "devName": dev_name if dev_name else None,
        "manageIp": manage_ip if manage_ip else None,
        "neId": _normalize_ci_id(ci_id),
        "locatenename": None,
        "onuId": None,
        "locatenestatus": None,
        "eventtime": None,
        "daltime": None,
        "eventlasttime": None,
        "canceltime": None,
        "alarmseverity": "",
        "alarmseveritys": alarm_severitys if alarm_severitys else [],
        "vendorserialno": None,
        "alarmstatus": alarm_status if alarm_status else None,
        "speciality": None,
        "addInfo9": None,
        "clearuser": None,
        "ackflag": None,
        "acktime": None,
        "ackuser": None,
        "alarmtitle": alarm_title if alarm_title else None,
        "alarmtext": None,
        "alarmregion": None,
        "alarmcounty": None,
        "cityList": _build_city_list(cities) if cities else [],
        "countyList": [],
        "circName": "",
        "linkName": "",
        "circId": "",
        "linkId": "",
        "params": {"beginEventtime": begin_time, "endEventtime": end_time},
    }
    if normalized_ne_alias:
        data["neAlias"] = normalized_ne_alias

    try:
        # 发送 POST 请求
        response = requests.post(url, headers=headers, json=data, timeout=30)

        # 检查响应状态码
        response.raise_for_status()

        # 解析响应数据 - 直接返回接口原始响应
        result = response.json()
        if not isinstance(result, dict):
            return _make_error(500, "接口返回格式异常：预期为 JSON 对象")
        return result

    except requests.exceptions.Timeout:
        return _make_error(408, "请求超时，请检查网络连接或稍后重试")

    except requests.exceptions.ConnectionError:
        return _curl_post_json(url=url, headers=headers, data=data, timeout_seconds=30)

    except requests.exceptions.HTTPError as e:
        return _handle_http_error(e)

    except ValueError as e:
        return _make_error(500, f"响应解析失败: {str(e)}")

    except requests.exceptions.RequestException as e:
        return _make_error(500, f"请求异常: {str(e)}")

    except Exception as e:
        return _make_error(500, f"未知错误: {str(e)}")


def main():
    """命令行入口函数"""
    parser = argparse.ArgumentParser(
        description="获取实时告警列表",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 使用配置文件中的配置查询最近告警
  uv run get_alarms.py --page_num 1 --page_size 10

  # 查询指定时间范围内的告警
  uv run get_alarms.py --begin_time "2026-03-15 10:00:00" --end_time "2026-03-16 10:00:00"

  # 查询严重级别告警
  uv run get_alarms.py --alarm_severitys 1 2

  # 查询指定城市的告警
  uv run get_alarms.py --cities 南京 秦淮区

  # 查询指定 CI/网元 ID 的告警
  uv run get_alarms.py --ci_id 18

  # 查询数据库当前活跃告警
  uv run get_alarms.py --ne_alias 数据库 --alarm_status 1

  # 直接指定 token
  uv run get_alarms.py --token "eyJhbGc..." --page_num 1 --page_size 10

配置文件:
  配置从 skill 目录下的 .env 文件读取：
  - INOE_API_BASE_URL  API 基础地址（如：http://<host>:<port>/prod-api）
  - INOE_API_TOKEN     API Token（JWT）
        """,
    )

    parser.add_argument(
        "--token",
        type=str,
        required=False,
        help="JWT 认证令牌（可选，默认从环境变量 INOE_API_TOKEN 读取）",
    )

    parser.add_argument(
        "--api_base_url",
        type=str,
        required=False,
        help="API 基础地址（可选，默认从环境变量 INOE_API_BASE_URL 读取）",
    )

    parser.add_argument("--page_num", type=int, default=1, help="页码，默认为 1")

    parser.add_argument("--page_size", type=int, default=10, help="每页数量，默认为 10")

    parser.add_argument(
        "--begin_time",
        type=str,
        required=False,
        help="开始时间，格式：YYYY-MM-DD HH:MM:SS",
    )

    parser.add_argument(
        "--end_time",
        type=str,
        required=False,
        help="结束时间，格式：YYYY-MM-DD HH:MM:SS",
    )

    parser.add_argument(
        "--alarm_severity",
        type=str,
        required=False,
        help="告警级别（已废弃，使用 --alarm_severitys）",
    )

    parser.add_argument(
        "--alarm_severitys",
        type=str,
        nargs="+",
        required=False,
        help="告警级别列表，如：1 2",
    )

    parser.add_argument(
        "--alarm_status", type=str, required=False, help="告警状态，如：1 表示活跃"
    )

    parser.add_argument("--dev_name", type=str, required=False, help="设备名称")

    parser.add_argument("--manage_ip", type=str, required=False, help="管理IP")

    parser.add_argument(
        "--ci_id",
        "--ne_id",
        dest="ci_id",
        type=str,
        required=False,
        help="CI/网元 ID，对应接口字段 neId",
    )

    parser.add_argument(
        "--ne_alias",
        "--neAlias",
        dest="ne_alias",
        type=str,
        required=False,
        help="资源分类，对应接口字段 neAlias，如 数据库/网络设备/中间件/操作系统/计算资源",
    )

    parser.add_argument(
        "--resource_type",
        "--resource",
        dest="resource_type",
        type=str,
        required=False,
        help="资源分类别名，如 database/network/middleware/os/server",
    )

    parser.add_argument(
        "--cities",
        type=str,
        nargs="+",
        required=False,
        help="城市列表，如：南京 秦淮区",
    )

    parser.add_argument("--alarm_title", type=str, required=False, help="告警标题")

    args = parser.parse_args()

    # 获取 token：优先使用命令行参数，然后使用环境变量
    token = args.token or get_token()
    if not token:
        print("错误: 未设置 API Token", file=sys.stderr)
        print(
            "请设置技能目录下的 .env、环境变量 INOE_API_TOKEN，或使用 --token 参数",
            file=sys.stderr,
        )
        sys.exit(1)

    # 执行查询
    result = execute(
        page_num=args.page_num,
        page_size=args.page_size,
        token=token,
        api_base_url=args.api_base_url,
        begin_time=args.begin_time,
        end_time=args.end_time,
        alarm_severity=args.alarm_severity,
        alarm_severitys=args.alarm_severitys,
        alarm_status=args.alarm_status,
        dev_name=args.dev_name,
        manage_ip=args.manage_ip,
        ci_id=args.ci_id,
        ne_alias=args.ne_alias,
        resource_type=args.resource_type,
        cities=args.cities,
        alarm_title=args.alarm_title,
    )

    # 输出结果（JSON 格式）
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # 根据返回码设置退出状态
    if result.get("code") == 200:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
