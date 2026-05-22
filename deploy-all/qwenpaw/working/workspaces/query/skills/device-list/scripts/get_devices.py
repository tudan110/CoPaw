#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
设备列表查询脚本

使用方式:
    uv run get_devices.py [--token <token>] [--page_num 1] [--page_size 10]

说明:
    - 配置优先取环境变量/共享 secrets，回退 skill 目录下的 .env
    - 配置项：INOE_API_BASE_URL（API 基础地址）、INOE_API_TOKEN（认证令牌）
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, Any, Optional

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
    1. 已有环境变量（共享 secrets 注入，优先）
    2. skill 目录下的 .env，再到项目根目录 .env（回退，override=False）
    """
    if not HAS_DOTENV:
        return

    # 获取脚本所在目录，然后找到 skill 目录
    script_dir = Path(__file__).parent
    skill_dir = script_dir.parent  # scripts 的上级目录就是 skill 目录

    # skill .env 用 override=False：仅补 os.environ 缺失项（共享 secrets 优先）
    skill_env_file = skill_dir / ".env"
    if skill_env_file.exists():
        load_dotenv(skill_env_file, override=False)
        return

    # 如果 skill 目录没有，尝试项目根目录
    project_root = skill_dir.parent.parent  # .claude/skills/device_list -> .claude -> project_root
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
    return os.getenv("INOE_API_BASE_URL", "http://192.168.130.211:30080")


def get_token() -> Optional[str]:
    """
    获取 API Token

    Returns:
        Token 字符串，如果不存在则返回 None
    """
    return os.getenv("INOE_API_TOKEN")


def _make_error(code: int, message: str) -> Dict[str, Any]:
    """构造统一错误响应。"""
    return {
        "code": code,
        "msg": message,
        "total": 0,
        "rows": []
    }


def _normalize_base_url(api_base_url: Optional[str]) -> str:
    """规范化 API 基础地址。"""
    base_url = (api_base_url or get_api_base_url()).strip()
    return base_url.rstrip("/")


def _validate_paging(page_num: int, page_size: int) -> Optional[Dict[str, Any]]:
    """校验分页参数。"""
    if page_num < 1:
        return _make_error(400, "page_num 必须大于等于 1")
    if page_size < 1:
        return _make_error(400, "page_size 必须大于等于 1")
    return None


def _handle_http_error(error: requests.exceptions.HTTPError) -> Dict[str, Any]:
    """将 HTTPError 转成统一错误响应。"""
    status_code = error.response.status_code
    error_msg = error.response.text if error.response.text else str(error)
    message_map = {
        401: "认证失败，请检查 token 是否有效",
        403: "权限不足，无法访问该资源",
        404: "接口不存在，请检查接口地址",
    }
    return _make_error(status_code, message_map.get(status_code, f"HTTP错误: {error_msg}"))


def execute(page_num: int = 1, page_size: int = 10, token: str = None, api_base_url: str = None) -> Dict[str, Any]:
    """
    执行设备列表查询

    Args:
        page_num: 页码，默认为 1
        page_size: 每页数量，默认为 10
        token: JWT 认证令牌（必填）
        api_base_url: API 基础地址（可选，默认从环境变量读取）

    Returns:
        Dict: 包含查询结果或错误信息的字典
    """
    paging_error = _validate_paging(page_num, page_size)
    if paging_error:
        return paging_error

    normalized_token = (token or "").strip()
    if not normalized_token:
        return _make_error(401, "未设置 API Token，请检查 .env 或 --token 参数")

    # 接口配置
    base_url = _normalize_base_url(api_base_url)
    url = f"{base_url}/resource/device/device/list"
    headers = {
        "Authorization": f"Bearer {normalized_token}",
        "Content-Type": "application/json"
    }
    params = {
        "pageNum": page_num,
        "pageSize": page_size
    }

    try:
        # 发送 GET 请求
        response = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=10
        )

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
        return _make_error(500, "连接失败，请检查服务器地址是否正确")

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
        description='获取能调系统的设备列表',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 使用配置文件中的配置
  uv run get_devices.py --page_num 1 --page_size 35

  # 直接指定 token
  uv run get_devices.py --token "eyJhbGc..." --page_num 1 --page_size 35

    # 临时指定 API 地址
    uv run get_devices.py --api_base_url "http://127.0.0.1:30080" --page_num 1 --page_size 10

配置文件:
  配置优先取环境变量/共享 secrets，回退 skill 目录下的 .env：
  - INOE_API_BASE_URL  API 基础地址（如：http://192.168.130.211:30080）
  - INOE_API_TOKEN     API Token（JWT）
        """
    )

    parser.add_argument(
        '--token',
        type=str,
        required=False,
        help='JWT 认证令牌（可选，默认从环境变量 INOE_API_TOKEN 读取）'
    )

    parser.add_argument(
        '--api_base_url',
        type=str,
        required=False,
        help='API 基础地址（可选，默认从环境变量 INOE_API_BASE_URL 读取）'
    )

    parser.add_argument(
        '--page_num',
        type=int,
        default=1,
        help='页码，默认为 1'
    )

    parser.add_argument(
        '--page_size',
        type=int,
        default=10,
        help='每页数量，默认为 10'
    )

    args = parser.parse_args()

    # 获取 token：优先使用命令行参数，然后使用环境变量
    token = args.token or get_token()
    if not token:
        print("错误: 未设置 API Token", file=sys.stderr)
        print("请设置技能目录下的 .env、环境变量 INOE_API_TOKEN，或使用 --token 参数", file=sys.stderr)
        sys.exit(1)

    # 执行查询
    result = execute(
        page_num=args.page_num,
        page_size=args.page_size,
        token=token,
        api_base_url=args.api_base_url
    )

    # 输出结果（JSON 格式）
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # 根据返回码设置退出状态
    if result.get('code') == 200:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()