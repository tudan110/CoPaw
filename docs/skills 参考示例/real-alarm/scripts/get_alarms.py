#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实时告警查询脚本

使用方式:
    uv run get_alarms.py [--token <token>] [--page_num 1] [--page_size 10]

说明:
    - 配置优先取环境变量/共享 secrets，回退 skill 目录下的 .env
    - 配置项：INOE_API_BASE_URL（API 基础地址）、INOE_API_TOKEN（认证令牌）
    - 接口为 GET /resource/alarm/statistics/hisAlarmList，强制要求 begin/end
      时间窗；未传时按 REAL_ALARM_QUERY_WINDOW_HOURS（默认 24 小时）自动回溯
    - USE_MOCK_DATA=true 时读取 mock_data.json，不发真实请求，方便无接口权限
      时联调技能行为
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

# dotenv 是可选依赖：装了就用它自动读取 .env 文件，没装也不影响脚本
# 运行（只是没法从 .env 里取配置，只能靠系统环境变量或命令行参数）。
try:
    from dotenv import load_dotenv
    HAS_DOTENV = True
except ImportError:
    HAS_DOTENV = False


def _load_skill_env() -> None:
    """
    加载 skill 目录下的 .env 文件

    优先级（数字越小越优先，override=False 表示"已经有的环境变量不会
    被 .env 里的值覆盖"，所以下面 1 天然优先于 2）:
    1. 已有环境变量（共享 secrets 注入，优先）
    2. skill 目录下的 .env，再到项目根目录 .env（回退，override=False）
    """
    if not HAS_DOTENV:
        return

    # __file__ 是当前脚本自己的路径，script_dir 就是 scripts/ 目录，
    # 它的上一级 skill_dir 才是整个 skill 的根目录（SKILL.md 所在处）。
    script_dir = Path(__file__).parent
    skill_dir = script_dir.parent

    skill_env_file = skill_dir / ".env"
    if skill_env_file.exists():
        load_dotenv(skill_env_file, override=False)
        return

    # 找不到 skill 自己的 .env，就再往上翻两级找项目根目录的 .env
    # 兜底（一般用不上，只是留个后路）。
    project_root = skill_dir.parent.parent
    project_env_file = project_root / ".env"
    if project_env_file.exists():
        load_dotenv(project_env_file, override=False)


# 模块被 import 时就立刻尝试加载 .env，这样后面所有 os.getenv(...) 调用
# 都能拿到值，不需要每个函数自己再去操心"配置从哪来"。
_load_skill_env()


def get_api_base_url() -> str:
    """读取接口基础地址，如 http://<host>:<port>，不含具体路径。"""
    return os.getenv("INOE_API_BASE_URL", "")


def get_token() -> Optional[str]:
    """读取认证 Token；没配置时返回 None，调用方要自己处理"未登录"这种情况。"""
    return os.getenv("INOE_API_TOKEN")


def use_mock_data() -> bool:
    """是否使用本地 mock 数据代替真实接口请求（没有接口权限时用于调试）。"""
    return os.getenv("USE_MOCK_DATA", "false").lower() in ("true", "1", "yes")


def _load_mock_data() -> Dict[str, Any]:
    """从 skill 目录下的 mock_data.json 读取一份预置的假数据。

    这个函数本身不发任何网络请求，纯粹是读本地文件；即便没有接口
    Token、没有网络，也能靠它跑通"参数解析 → 过滤 → 渲染"这整条链路，
    方便在拿到真实接口权限之前先验证 Skill 逻辑是否正确。
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
    """构造统一错误响应。

    整个脚本约定：不管是参数校验失败、网络超时还是接口返回业务错误，
    最终都统一成 {"code": ..., "msg": ..., "total": 0, "rows": []} 这个
    形状，调用方（analyze_alarms.py 等）只需要判断 code 是不是 200，
    不需要对每种失败场景单独写处理分支。
    """
    return {"code": code, "msg": message, "total": 0, "rows": []}


def _normalize_base_url(api_base_url: Optional[str]) -> str:
    """规范化 API 基础地址：去掉首尾空格和结尾多余的斜杠。

    避免调用方传了 "http://host:port/" 这种带斜杠结尾的地址后，拼出
    "http://host:port//resource/..." 这种带双斜杠的错误 URL。
    """
    base_url = (api_base_url or get_api_base_url()).strip()
    return base_url.rstrip("/")


# 资源分类别名映射：把用户口语化的说法（比如英文 database、中文"数据库"
# 甚至不同大小写/下划线写法）统一映射成接口真正认识的枚举值。这样 Agent
# 不需要严格按接口文档的措辞去问用户"请输入 数据库/网络设备/中间件/
# 操作系统/计算资源 中的一个"，用户随口说个 "db" 也能被正确识别。
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
    """把自然语言资源类型归一到接口的 neAlias 枚举值。

    两个参数任选一个传（ne_alias 优先），先转小写、把 "-" 和空格都换成
    "_"（方便对齐字典的 key 写法），查不到映射就原样返回——这样即使
    用户直接说了接口认识的中文原词（如"数据库"），也能正常透传。
    """
    raw_value = (ne_alias or resource_type or "").strip()
    if not raw_value:
        return None
    normalized_key = raw_value.lower().replace("-", "_").replace(" ", "_")
    return RESOURCE_NE_ALIAS_MAP.get(normalized_key, raw_value)


def _validate_paging(page_num: int, page_size: int) -> Optional[Dict[str, Any]]:
    """校验分页参数是否合法；返回 None 表示校验通过。"""
    if page_num < 1:
        return _make_error(400, "page_num 必须大于等于 1")
    if page_size < 1:
        return _make_error(400, "page_size 必须大于等于 1")
    return None


def _validate_time_range(
    begin_time: Optional[str], end_time: Optional[str]
) -> Optional[Dict[str, Any]]:
    """校验时间字符串格式；只要传了就必须符合 YYYY-MM-DD HH:MM:SS。"""
    if begin_time and not _is_valid_datetime(begin_time):
        return _make_error(400, "begin_time 格式无效，应为 YYYY-MM-DD HH:MM:SS")
    if end_time and not _is_valid_datetime(end_time):
        return _make_error(400, "end_time 格式无效，应为 YYYY-MM-DD HH:MM:SS")
    return None


def _is_valid_datetime(date_string: str) -> bool:
    """用 strptime 尝试解析字符串，能解析成功就是合法时间格式。"""
    try:
        datetime.strptime(date_string, "%Y-%m-%d %H:%M:%S")
        return True
    except ValueError:
        return False


def _handle_http_error(error: requests.exceptions.HTTPError) -> Dict[str, Any]:
    """把 requests 抛出的 HTTPError 转换成统一错误格式。"""
    status_code = error.response.status_code
    error_msg = error.response.text if error.response.text else str(error)
    return _build_http_error(status_code, error_msg)


def _build_http_error(status_code: int, error_msg: str) -> Dict[str, Any]:
    """把常见 HTTP 状态码翻译成人话，其余状态码原样带出错误文本。"""
    message_map = {
        401: "认证失败，请检查 token 是否有效",
        403: "权限不足，无法访问该资源",
        404: "接口不存在，请检查接口地址",
    }
    return _make_error(
        status_code, message_map.get(status_code, f"HTTP错误: {error_msg}")
    )


def _alarm_status_to_is_clear(alarm_status: Optional[str]) -> str:
    """把旧接口的 alarmstatus 语义转换成新接口的 isClear 字段。

    这是这次接口迁移里最容易踩坑的一处：旧接口用 alarmstatus="1"
    表示"告警还活跃、没恢复"；新接口换了个字段名 isClear，而且语义
    是反过来的——"0" 才表示"没清除、活跃中"，"1" 表示"已清除"。
    Agent/用户侧仍然按老习惯传 --alarm_status（1=活跃），这个函数
    负责把它翻译成新接口真正认识的 isClear 取值，调用方完全不需要
    关心这个历史包袱。
    """
    status = str(alarm_status).strip() if alarm_status else "1"
    return "0" if status == "1" else "1"


def _build_his_alarm_params(
    *,
    page_num: int,
    page_size: int,
    begin_time: str,
    end_time: str,
    alarm_severity: Optional[str] = None,
    alarm_severitys: Optional[List[str]] = None,
    alarm_status: Optional[str] = None,
    dev_name: Optional[str] = None,
    manage_ip: Optional[str] = None,
    alarm_title: Optional[str] = None,
    ci_id: Optional[str] = None,
    ne_alias: Optional[str] = None,
) -> Dict[str, Any]:
    """构建 hisAlarmList GET 查询参数。

    几个不直观的转换点，都是为了让"用户/Agent 传的参数" 和 "接口真正
    要的字段" 之间做一层适配：
    - alarm_severitys（列表）优先于 alarm_severity（单值），最终都拼成
      逗号分隔的字符串；两个都没给时默认查全部 4 个级别（1~4）。
    - alarm_status 通过 _alarm_status_to_is_clear() 转成 isClear。
    - 资源过滤优先用精确的网管 IP（neIp，isLike="0" 表示精确匹配，不是
      模糊匹配）；没有 IP 时才退回到关键字模糊搜索 queryKey。
    - 新接口没有"按资源 ID 精确过滤"这个字段（老接口的 neId 已经没了），
      所以如果 ci_id 是纯数字（像是内部资源 ID），直接丢弃它、不传给
      接口，避免用户以为"传了 ID 就会精确过滤"但实际根本不生效；只有
      ci_id 看起来像一段文本（不是纯数字）时，才把它当关键字塞进
      queryKey 做模糊匹配。
    """
    if alarm_severitys:
        severity = ",".join(str(s).strip() for s in alarm_severitys if s)
    elif alarm_severity:
        severity = str(alarm_severity).strip()
    else:
        severity = "1,2,3,4"

    params: Dict[str, Any] = {
        "alarmSeverity": severity or "1,2,3,4",
        "isClear": _alarm_status_to_is_clear(alarm_status),
        "beginTime": begin_time,
        "endTime": end_time,
        "pageNum": page_num,
        "pageSize": page_size,
        "sortType": 1,
    }

    if manage_ip:
        params["neIp"] = str(manage_ip).strip()
        params["isLike"] = "0"

    # queryKey 是模糊搜索关键字，三个来源里挑一个：设备名 > 告警标题 >
    # （当作兜底）非数字的 ci_id。已经用了精确 IP 过滤时就不再叠加
    # queryKey，避免两个过滤条件互相打架、结果反而更少。
    query_key = (dev_name or alarm_title or "").strip()
    if not manage_ip and not query_key and ci_id:
        ci_text = str(ci_id).strip()
        if ci_text and not ci_text.isdigit():
            query_key = ci_text
    if query_key and "neIp" not in params:
        params["queryKey"] = query_key

    if ne_alias:
        params["alarmClassType"] = ne_alias

    return params


def _curl_get_json(
    *,
    url: str,
    headers: Dict[str, str],
    params: Dict[str, Any],
    timeout_seconds: int = 30,
    allow_array: bool = False,
) -> Dict[str, Any]:
    """使用系统 curl 作为 requests 库的网络兼容性回退（GET 请求）。

    背景：某些沙箱/容器环境里 Python 的 requests 库可能因为网络栈限制
    连不上（抛 ConnectionError），但系统自带的 curl 命令行工具反而能连
    通。所以在 execute() 里捕获到 ConnectionError 时，会退而求其次调用
    这个函数，用子进程执行 curl 发同样的请求，尽量保证脚本在各种环境下
    都能跑起来，而不是直接报错退出。
    """
    # 用临时文件接住 curl 返回的响应体，避免直接拼在 stdout 里跟 HTTP
    # 状态码混在一起不好解析。
    with tempfile.NamedTemporaryFile(delete=False) as body_file:
        body_path = body_file.name

    # -o body_path 把响应体写入临时文件；-w "%{http_code}" 让 curl 在
    # stdout 只打印 HTTP 状态码，这样下面读 completed.stdout 就能直接
    # 拿到状态码，不用自己解析 curl 的原始输出格式。
    args = [
        "curl", "-sS", "--get",
        "--connect-timeout", str(int(timeout_seconds)),
        "--max-time", str(int(timeout_seconds)),
        "-o", body_path,
        "-w", "%{http_code}",
    ]
    for key, value in headers.items():
        args.extend(["-H", f"{key}: {value}"])
    for key, value in params.items():
        if value is None:
            continue
        args.extend(["--data-urlencode", f"{key}={value}"])
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
    alarm_title: str = None,
    ci_id: str = None,
    ne_alias: str = None,
    resource_type: str = None,
    cities: List[str] = None,
) -> Dict[str, Any]:
    """
    执行实时告警查询

    Args:
        page_num: 页码，默认为 1
        page_size: 每页数量，默认为 10
        token: JWT 认证令牌
        api_base_url: API 基础地址（可选，默认从环境变量读取）
        begin_time: 开始时间，格式 YYYY-MM-DD HH:MM:SS（缺省时按查询窗口自动计算）
        end_time: 结束时间，格式 YYYY-MM-DD HH:MM:SS（缺省时取当前时间）
        alarm_severitys: 告警级别列表，如 ["1", "2"]
        alarm_status: 告警状态，如 "1" 表示活跃（内部会转换为接口的 isClear）
        dev_name: 设备名称
        manage_ip: 管理IP
        alarm_title: 告警标题
        ci_id: CI/网元 ID（新接口无按 ID 精确过滤字段，纯数字 ID 无法过滤，
            非数字文本会回退到模糊搜索 queryKey）
        ne_alias: 资源分类，对应接口字段 alarmClassType
        resource_type: 资源分类别名，如 database/network/server
        cities: 保留参数，新接口无城市过滤字段，仅为兼容
            analyze_alarms.py 的调用签名，实际不生效

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

    base_url = _normalize_base_url(api_base_url)
    if not base_url:
        return _make_error(400, "未设置 INOE_API_BASE_URL，请检查 .env 或 --api_base_url 参数")

    url = f"{base_url}/resource/alarm/statistics/hisAlarmList"
    headers = {
        "Authorization": f"Bearer {normalized_token}",
        "Content-Type": "application/json;charset=UTF-8",
    }

    # hisAlarmList 是"强制要求"传时间窗的接口——不传 begin/end 会直接
    # 报错，不像旧接口那样默认查全量。为了不让用户每次都手动算时间，
    # 这里做了兜底：只要调用方没传完整的 begin_time/end_time，就自动用
    # "当前时间往前推 N 小时" 当作查询窗口，N 由环境变量
    # REAL_ALARM_QUERY_WINDOW_HOURS 控制，默认 24 小时。
    # 注意：这个窗口如果设置得太小，可能会漏掉更早触发、但还没恢复的
    # 活跃告警（比如告警是 3 天前发生的，窗口只有 24 小时就查不到）。
    if not begin_time or not end_time:
        try:
            window_h = float(
                os.getenv("REAL_ALARM_QUERY_WINDOW_HOURS", "24") or "24"
            )
        except ValueError:
            window_h = 24.0
        now = datetime.now()
        begin_time = (now - timedelta(hours=window_h)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        end_time = now.strftime("%Y-%m-%d %H:%M:%S")

    params = _build_his_alarm_params(
        page_num=page_num,
        page_size=page_size,
        begin_time=begin_time,
        end_time=end_time,
        alarm_severity=alarm_severity,
        alarm_severitys=alarm_severitys,
        alarm_status=alarm_status,
        dev_name=dev_name,
        manage_ip=manage_ip,
        alarm_title=alarm_title,
        ci_id=ci_id,
        ne_alias=_normalize_ne_alias(ne_alias, resource_type),
    )

    # 下面这一串 except 分支按"从具体到笼统"的顺序排列：先处理超时、
    # 连接失败、HTTP 错误这些明确知道原因的情况，给出针对性的中文提示；
    # 最后用 Exception 兜底，保证不管出什么意外，脚本都会返回一个统一
    # 结构的错误字典，而不是直接抛异常把调用方（比如 analyze_alarms.py）
    # 也带崩。
    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            return _make_error(500, "接口返回格式异常：预期为 JSON 对象")
        return result

    except requests.exceptions.Timeout:
        return _make_error(408, "请求超时，请检查网络连接或稍后重试")

    except requests.exceptions.ConnectionError:
        # requests 连不上时，退而用系统 curl 再试一次（见 _curl_get_json
        # 的注释说明为什么需要这个兜底）。
        return _curl_get_json(url=url, headers=headers, params=params, timeout_seconds=30)

    except requests.exceptions.HTTPError as e:
        return _handle_http_error(e)

    except ValueError as e:
        return _make_error(500, f"响应解析失败: {str(e)}")

    except requests.exceptions.RequestException as e:
        return _make_error(500, f"请求异常: {str(e)}")

    except Exception as e:
        return _make_error(500, f"未知错误: {str(e)}")


def main():
    parser = argparse.ArgumentParser(
        description="获取实时告警列表",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 使用配置文件中的配置查询最近告警（未指定时间范围时，按查询窗口回溯，默认 24 小时）
  uv run get_alarms.py --page_num 1 --page_size 10

  # 查询指定时间范围内的告警
  uv run get_alarms.py --begin_time "2026-03-15 10:00:00" --end_time "2026-03-16 10:00:00"

  # 查询严重级别告警
  uv run get_alarms.py --alarm_severitys 1 2

  # 查询指定 CI/网元 ID（文本类关键字）的告警
  uv run get_alarms.py --ci_id 18

  # 查询数据库当前活跃告警
  uv run get_alarms.py --ne_alias 数据库 --alarm_status 1

配置文件:
  技能目录下的 .env（或共享 secrets/ 注入）：
  - INOE_API_BASE_URL              API 基础地址（如：http://<host>:<port>）
  - INOE_API_TOKEN                 API Token（JWT）
  - USE_MOCK_DATA                  可选，true 时读取 mock_data.json 而不发真实请求
  - REAL_ALARM_QUERY_WINDOW_HOURS  可选，未指定时间范围时的默认回溯窗口（小时），默认 24
        """,
    )

    parser.add_argument("--token", type=str, required=False,
                        help="JWT 认证令牌（可选，默认从环境变量 INOE_API_TOKEN 读取）")
    parser.add_argument("--api_base_url", type=str, required=False,
                        help="API 基础地址（可选，默认从环境变量 INOE_API_BASE_URL 读取）")
    parser.add_argument("--page_num", type=int, default=1, help="页码，默认为 1")
    parser.add_argument("--page_size", type=int, default=10, help="每页数量，默认为 10")
    parser.add_argument("--begin_time", type=str, required=False,
                        help="开始时间，格式：YYYY-MM-DD HH:MM:SS")
    parser.add_argument("--end_time", type=str, required=False,
                        help="结束时间，格式：YYYY-MM-DD HH:MM:SS")
    parser.add_argument("--alarm_severity", type=str, required=False,
                        help="告警级别（已废弃，使用 --alarm_severitys）")
    parser.add_argument("--alarm_severitys", type=str, nargs="+", required=False,
                        help="告警级别列表，如：1 2")
    parser.add_argument("--alarm_status", type=str, required=False,
                        help="告警状态，如：1 表示活跃")
    parser.add_argument("--dev_name", type=str, required=False, help="设备名称")
    parser.add_argument("--manage_ip", type=str, required=False, help="管理IP")
    parser.add_argument("--ci_id", "--ne_id", dest="ci_id", type=str, required=False,
                        help="CI/网元 ID；新接口无按 ID 精确过滤字段，纯数字会被忽略，"
                             "文本会回退到模糊搜索 queryKey")
    parser.add_argument("--ne_alias", "--neAlias", dest="ne_alias", type=str, required=False,
                        help="资源分类，对应接口字段 alarmClassType，如 数据库/网络设备/中间件/操作系统/计算资源")
    parser.add_argument("--resource_type", "--resource", dest="resource_type", type=str, required=False,
                        help="资源分类别名，如 database/network/middleware/os/server")
    parser.add_argument("--alarm_title", type=str, required=False, help="告警标题")

    args = parser.parse_args()

    token = args.token or get_token()
    if not token:
        print("错误: 未设置 API Token", file=sys.stderr)
        print("请设置技能目录下的 .env、环境变量 INOE_API_TOKEN，或使用 --token 参数", file=sys.stderr)
        sys.exit(1)

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
        alarm_title=args.alarm_title,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result.get("code") == 200 else 1)


if __name__ == "__main__":
    main()
