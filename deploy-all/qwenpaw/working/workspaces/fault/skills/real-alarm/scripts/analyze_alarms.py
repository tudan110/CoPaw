#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实时告警统一汇总脚本

使用方式:
    uv run analyze_alarms.py --mode summary
    uv run analyze_alarms.py --mode severity
    uv run analyze_alarms.py --mode search --keyword 端口

说明:
    - 统一拉取全部告警后做本地过滤、分组和汇总
    - 默认读取 skill 目录下的 .env 文件
    - 配置项：INOE_API_BASE_URL（API 基础地址）、INOE_API_TOKEN（认证令牌）
"""

import argparse
import json
import sys
from typing import Any, Dict, List, Optional

from get_alarms import get_token
from utils.alarm_analyzer import fetch_all_alarms, apply_filters, analyze_by_mode, make_error
from utils.alarm_normalizer import normalize_alarms
from utils.markdown_renderer import render_markdown, render_error_markdown
from utils.chart_generator import render_chart_only_markdown

ALLOWED_MODES = {
    "summary",
    "severity",
    "title",
    "device",
    "speciality",
    "region",
    "search",
}

ALLOWED_OUTPUTS = {"json", "markdown", "markdown-echarts-only"}


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="统一汇总告警信息，支持总览、分布统计和关键字搜索",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 综合概览
  uv run analyze_alarms.py --mode summary

  # 按告警级别统计
  uv run analyze_alarms.py --mode severity

  # 搜索告警标题包含端口的告警
  uv run analyze_alarms.py --mode search --keyword 端口

  # 查询严重告警
  uv run analyze_alarms.py --mode search --severity 1 --include-alarms

  # 查询指定 CI/网元 ID 的告警
  uv run analyze_alarms.py --mode search --ci_id 18 --include-alarms --output markdown

  # 查询数据库当前活跃告警
  uv run analyze_alarms.py --mode search --ne_alias 数据库 --alarm_status 1 --include-alarms --output markdown

  # 查询指定时间范围的告警
  uv run analyze_alarms.py --mode summary --begin_time "2026-03-15 10:00:00" --end_time "2026-03-16 10:00:00"
        """,
    )
    parser.add_argument("--mode", choices=sorted(ALLOWED_MODES), default="summary", help="分析模式")
    parser.add_argument("--token", type=str, required=False, help="JWT 认证令牌（可选，默认从环境变量 INOE_API_TOKEN 读取）")
    parser.add_argument("--api_base_url", type=str, required=False, help="API 基础地址（可选，默认从环境变量 INOE_API_BASE_URL 读取）")
    parser.add_argument("--keyword", type=str, default="", help="搜索关键字")
    parser.add_argument("--keyword_field", type=str, default="all", help="关键字搜索字段，默认 all")
    parser.add_argument("--severity", type=str, default="", help="按告警级别过滤，例如 1")
    parser.add_argument("--device_name", type=str, default="", help="按设备名称过滤")
    parser.add_argument("--manage_ip", type=str, default="", help="按管理IP过滤")
    parser.add_argument(
        "--ci_id",
        "--ne_id",
        dest="ci_id",
        type=str,
        default="",
        help="按 CI/网元 ID 过滤，对应接口字段 neId",
    )
    parser.add_argument(
        "--ne_alias",
        "--neAlias",
        dest="ne_alias",
        type=str,
        default="",
        help="按资源分类过滤，对应接口字段 neAlias，如 数据库/网络设备/中间件/操作系统/计算资源",
    )
    parser.add_argument(
        "--resource_type",
        "--resource",
        dest="resource_type",
        type=str,
        default="",
        help="资源分类别名，如 database/network/middleware/os/server",
    )
    parser.add_argument("--speciality", type=str, default="", help="按专业过滤")
    parser.add_argument("--region", type=str, default="", help="按区域过滤")
    parser.add_argument("--begin_time", type=str, required=False, help="开始时间，格式：YYYY-MM-DD HH:MM:SS")
    parser.add_argument("--end_time", type=str, required=False, help="结束时间，格式：YYYY-MM-DD HH:MM:SS")
    parser.add_argument("--alarm_severitys", type=str, nargs='+', required=False, help="告警级别列表，如：1 2")
    parser.add_argument("--alarm_status", type=str, required=False, help="告警状态，如：1 表示活跃")
    parser.add_argument("--cities", type=str, nargs='+', required=False, help="城市列表，如：南京 秦淮区")
    parser.add_argument("--fetch_page_size", type=int, default=100, help="抓取全量告警时的分页大小，默认 100")
    parser.add_argument("--top_n", type=int, default=10, help="分组结果或预览告警数量，默认 10")
    parser.add_argument("--include-alarms", action="store_true", help="输出完整告警预览列表")
    parser.add_argument("--output", choices=sorted(ALLOWED_OUTPUTS), default="json", help="输出格式，默认 json")
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> Optional[Dict[str, Any]]:
    """验证命令行参数"""
    if args.fetch_page_size < 1:
        return make_error(400, "fetch_page_size 必须大于等于 1")
    if args.top_n < 1:
        return make_error(400, "top_n 必须大于等于 1")
    if args.output not in ALLOWED_OUTPUTS:
        return make_error(400, f"不支持的 output: {args.output}")
    if args.mode == "search" and not any(
        [
            args.keyword.strip(),
            args.severity.strip(),
            args.device_name.strip(),
            args.manage_ip.strip(),
            args.speciality.strip(),
            args.region.strip(),
            args.ci_id.strip(),
            getattr(args, "ne_alias", "").strip(),
            getattr(args, "resource_type", "").strip(),
        ]
    ):
        return make_error(400, "search 模式至少需要一个过滤条件或关键字")
    return None


def print_result(result: Dict[str, Any], output_format: str) -> None:
    """按输出格式打印结果"""
    if output_format == "markdown-echarts-only":
        if result.get("code") == 200:
            print(render_chart_only_markdown(result))
        else:
            print(render_error_markdown(result))
        return
    if output_format == "markdown":
        if result.get("code") == 200:
            print(render_markdown(result))
        else:
            print(render_error_markdown(result))
        return
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> None:
    """主函数"""
    args = parse_args()
    validation_error = validate_args(args)
    if validation_error:
        print_result(validation_error, args.output)
        sys.exit(1)

    token = args.token or get_token()
    if not token:
        print("错误: 未设置 API Token", file=sys.stderr)
        print("请设置技能目录下的 .env、环境变量 INOE_API_TOKEN，或使用 --token 参数", file=sys.stderr)
        sys.exit(1)

    # 获取告警数据
    fetch_result = fetch_all_alarms(
        token=token,
        api_base_url=args.api_base_url,
        page_size=args.fetch_page_size,
        begin_time=args.begin_time,
        end_time=args.end_time,
        alarm_severitys=args.alarm_severitys,
        alarm_status=args.alarm_status,
        cities=args.cities,
        ci_id=args.ci_id,
        ne_alias=args.ne_alias,
        resource_type=args.resource_type,
    )
    if fetch_result.get("code") != 200:
        print_result(fetch_result, args.output)
        sys.exit(1)

    # 规范化告警数据
    alarms = normalize_alarms(fetch_result.get("rows", []) or [])

    # 应用过滤条件
    filtered_alarms = apply_filters(
        alarms,
        keyword=args.keyword,
        keyword_field=args.keyword_field,
        severity=args.severity,
        device_name=args.device_name,
        manage_ip=args.manage_ip,
        speciality=args.speciality,
        region=args.region,
        ci_id=args.ci_id,
    )

    # 分析告警
    analysis_result = analyze_by_mode(
        mode=args.mode,
        alarms=filtered_alarms,
        top_n=args.top_n,
        include_alarms=args.include_alarms,
    )

    if analysis_result.get("code") and analysis_result.get("code") != 200:
        print_result(analysis_result, args.output)
        sys.exit(1)

    # 构造输出
    output = {
        "code": 200,
        "msg": "查询成功",
        "mode": args.mode,
        "filters": {
            "keyword": args.keyword,
            "keyword_field": args.keyword_field,
            "severity": args.severity,
            "device_name": args.device_name,
            "manage_ip": args.manage_ip,
            "speciality": args.speciality,
            "region": args.region,
            "ci_id": args.ci_id,
            "ne_alias": args.ne_alias,
            "resource_type": args.resource_type,
        },
        "query_params": {
            "begin_time": args.begin_time,
            "end_time": args.end_time,
            "alarm_severitys": args.alarm_severitys,
            "alarm_status": args.alarm_status,
            "cities": args.cities,
            "ci_id": args.ci_id,
            "ne_alias": args.ne_alias,
            "resource_type": args.resource_type,
        },
        "fetched_total": fetch_result.get("total", 0),
        "matched_total": len(filtered_alarms),
        "pages": fetch_result.get("pages", 0),
        **analysis_result,
    }
    print_result(output, args.output)


if __name__ == "__main__":
    main()
