#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CMDB 汇总与图表脚本

使用方式：
    python3 scripts/analyze_cmdb.py --mode summary --output markdown
    python3 scripts/analyze_cmdb.py --mode model-groups --output markdown
    python3 scripts/analyze_cmdb.py --mode app-relations --output markdown-echarts-only

说明：
    - 默认读取技能目录下的 .env
    - 通过后台 HTTP 会话登录并读取接口，不打开浏览器
    - 分布类输出支持 ECharts 代码块，适合页面直接渲染
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from veops_http import build_url, create_session, request_with_fallback, try_login  # noqa: E402

ALLOWED_MODES = {"summary", "model-groups", "relation-types", "app-relations"}
ALLOWED_OUTPUTS = {"json", "markdown", "markdown-echarts-only"}

GROUP_MAP = {
    "product": "业务",
    "project": "业务",
    "Department": "部门组织",
    "users": "部门组织",
    "operatingsystem": "操作系统",
    "PhysicalMachine": "计算资源",
    "vserver": "计算资源",
    "RAM": "计算资源",
    "harddisk": "计算资源",
    "NIC": "计算资源",
    "Host": "计算资源",
    "Hypervisor": "计算资源",
    "Storage": "数据存储",
    "database": "数据存储",
    "mysql": "数据存储",
    "PostgreSQL": "数据存储",
    "ipam_subnet": "IP地址管理",
    "ipam_address": "IP地址管理",
    "ipam_scope": "IP地址管理",
    "networkdevice": "网络设备",
    "port": "网络设备",
    "link": "网络设备",
    "redis": "中间件",
    "Kafka": "中间件",
    "elasticsearch": "中间件",
    "nginx": "中间件",
    "apache": "中间件",
    "kubernetes": "容器",
    "docker": "容器",
    "dcim_region": "数据中心",
    "dcim_idc": "数据中心",
    "dcim_server_room": "数据中心",
    "dcim_rack": "数据中心",
    "datacenter": "数据中心",
    "circuit": "数据中心",
    "Contract": "Other",
}


def parse_env(path: Path) -> Dict[str, str]:
    env: Dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        env[key.strip()] = value.strip()
    return env


def run_command(command: List[str], cwd: Path) -> str:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip() or "命令执行失败"
        raise RuntimeError(stderr)
    return result.stdout.strip()


def build_error(message: str, code: int = 500) -> Dict[str, Any]:
    return {
        "code": code,
        "msg": message,
        "mode": "error",
    }


def fetch_json(api_path: str, session: Any, base_url: str) -> Dict[str, Any]:
    response = request_with_fallback(
        session,
        "GET",
        build_url(base_url, api_path),
        timeout=30,
    )
    try:
        body = response.json()
    except json.JSONDecodeError:
        body = response.text
    return {"状态码": response.status_code, "响应体": body}


def summarize_groups(counter: Counter[str], total: int) -> List[Dict[str, Any]]:
    groups: List[Dict[str, Any]] = []
    for name, count in counter.most_common():
        ratio = round((count / total) * 100, 2) if total else 0
        groups.append({"name": name, "count": count, "ratio": ratio})
    return groups


def load_models(session: Any, base_url: str) -> List[Dict[str, Any]]:
    payload = fetch_json("/api/v0.1/ci_types?per_page=200", session, base_url)
    if payload["状态码"] != 200:
        raise RuntimeError(f"获取模型列表失败：HTTP {payload['状态码']}")
    return payload["响应体"]["ci_types"]


def load_all_relations(session: Any, base_url: str) -> List[Dict[str, Any]]:
    payload = fetch_json("/api/v0.1/ci_type_relations?ci_type_id=3", session, base_url)
    if payload["状态码"] != 200:
        raise RuntimeError(f"获取关系配置失败：HTTP {payload['状态码']}")
    return payload["响应体"]["relations"]


def load_relation_types(session: Any, base_url: str) -> List[Dict[str, Any]]:
    payload = fetch_json("/api/v0.1/relation_types", session, base_url)
    if payload["状态码"] != 200:
        raise RuntimeError(f"获取关系类型失败：HTTP {payload['状态码']}")
    return payload["响应体"]


def build_model_group_summary(models: List[Dict[str, Any]]) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    counter: Counter[str] = Counter()
    for item in models:
        group_name = GROUP_MAP.get(item["name"], "未分组")
        counter[group_name] += 1
        rows.append(
            {
                "模型名": item["name"],
                "显示名": item["alias"],
                "分组": group_name,
                "唯一键": item["unique_key"],
            }
        )
    return {
        "total_models": len(models),
        "groups": summarize_groups(counter, len(models)),
        "rows": rows,
    }


def simplify_relations(relations: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for item in relations:
        result.append(
            {
                "来源模型": (item.get("parent") or {}).get("name", ""),
                "来源显示名": (item.get("parent") or {}).get("alias", ""),
                "关系类型": ((item.get("relation_type") or {}).get("name")) or item.get("relation_type_name") or "",
                "目标模型": (item.get("child") or {}).get("name", ""),
                "目标显示名": (item.get("child") or {}).get("alias", ""),
                "约束": item.get("constraint", ""),
            }
        )
    return result


def build_relation_type_summary(relations: List[Dict[str, Any]], relation_types: List[Dict[str, Any]]) -> Dict[str, Any]:
    simplified = simplify_relations(relations)
    counter = Counter(item["关系类型"] for item in simplified if item["关系类型"])
    groups = summarize_groups(counter, len(simplified))
    all_type_names = [item["name"] for item in relation_types]
    return {
        "configured_relation_count": len(simplified),
        "available_relation_types": all_type_names,
        "groups": groups,
        "rows": simplified,
    }


def build_app_relation_summary(relations: List[Dict[str, Any]]) -> Dict[str, Any]:
    simplified = simplify_relations(relations)
    app_outgoing = [item for item in simplified if item["来源模型"] == "project"]
    incoming = [item for item in simplified if item["目标模型"] == "project"]
    target_counter = Counter(item["目标显示名"] or item["目标模型"] for item in app_outgoing)
    type_counter = Counter(item["关系类型"] for item in app_outgoing)
    return {
        "outgoing_count": len(app_outgoing),
        "incoming_count": len(incoming),
        "target_groups": summarize_groups(target_counter, len(app_outgoing)),
        "relation_type_groups": summarize_groups(type_counter, len(app_outgoing)),
        "incoming_rows": incoming,
        "outgoing_rows": app_outgoing,
    }


def build_summary(models: List[Dict[str, Any]], relations: List[Dict[str, Any]], relation_types: List[Dict[str, Any]]) -> Dict[str, Any]:
    model_summary = build_model_group_summary(models)
    relation_summary = build_relation_type_summary(relations, relation_types)
    app_summary = build_app_relation_summary(relations)
    return {
        "model_summary": model_summary,
        "relation_summary": relation_summary,
        "app_summary": app_summary,
    }


def _format_percent(value: float) -> str:
    return f"{value:.2f}%".rstrip("0").rstrip(".") + "%" if isinstance(value, float) and False else f"{value:.2f}%"


def _build_markdown_table(rows: List[Dict[str, Any]], columns: List[Tuple[str, str]]) -> str:
    if not rows:
        return "暂无数据。"
    header = "| " + " | ".join(label for _, label in columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = []
    for row in rows:
        body.append("| " + " | ".join(str(row.get(key, "")) for key, _ in columns) + " |")
    return "\n".join([header, sep, *body])


def _render_group_section(title: str, groups: List[Dict[str, Any]]) -> str:
    if not groups:
        return f"## {title}\n\n暂无数据。"
    lines = [f"## {title}", ""]
    for index, group in enumerate(groups, start=1):
        lines.append(f"{index}. {group['name']}：{group['count']} 个（{group['ratio']:.2f}%）")
    return "\n".join(lines)


def _build_pie_chart_option(title: str, groups: List[Dict[str, Any]], donut: bool = False) -> Dict[str, Any]:
    return {
        "title": {"text": title, "left": "center"},
        "tooltip": {"trigger": "item", "formatter": "{b}: {c} 个 ({d}%)"},
        "legend": {"right": "5%", "top": "center", "orient": "vertical"},
        "series": [
            {
                "name": title,
                "type": "pie",
                "radius": ["40%", "68%"] if donut else "56%",
                "data": [{"name": group["name"], "value": group["count"]} for group in groups],
            }
        ],
    }


def _build_bar_chart_option(title: str, groups: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "title": {"text": title, "left": "center"},
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "grid": {"left": 48, "right": 24, "bottom": 72, "top": 56},
        "xAxis": {
            "type": "category",
            "data": [group["name"] for group in groups],
            "axisLabel": {"rotate": 30},
        },
        "yAxis": {"type": "value", "name": "数量"},
        "series": [
            {
                "name": title,
                "type": "bar",
                "barMaxWidth": 40,
                "data": [group["count"] for group in groups],
            }
        ],
    }


def _render_chart_section(title: str, groups: List[Dict[str, Any]], chart_type: str = "pie") -> str:
    if not groups:
        return ""
    option = _build_bar_chart_option(title, groups) if chart_type == "bar" else _build_pie_chart_option(title, groups, donut=chart_type == "donut")
    return "\n".join([f"## {title}图表", "", "```echarts", json.dumps(option, ensure_ascii=False, indent=2), "```"])


def render_chart_only_markdown(result: Dict[str, Any]) -> str:
    mode = result["mode"]
    if mode == "summary":
        summary = result["summary"]
        sections = [
            _render_chart_section("模型分组分布", summary["model_summary"]["groups"], "pie"),
            _render_chart_section("关系类型分布", summary["relation_summary"]["groups"], "donut"),
            _render_chart_section("应用关联目标分布", summary["app_summary"]["target_groups"], "bar"),
        ]
    elif mode == "model-groups":
        sections = [_render_chart_section("模型分组分布", result["summary"]["groups"], "pie")]
    elif mode == "relation-types":
        sections = [_render_chart_section("关系类型分布", result["summary"]["groups"], "donut")]
    else:
        sections = [
            _render_chart_section("应用关联目标分布", result["summary"]["target_groups"], "bar"),
            _render_chart_section("应用关系类型分布", result["summary"]["relation_type_groups"], "donut"),
        ]
    sections = [item for item in sections if item]
    return "\n\n".join(sections) if sections else "暂无可渲染图表。"


def render_markdown(result: Dict[str, Any]) -> str:
    mode = result["mode"]
    lines: List[str] = ["# CMDB 分析结果", ""]

    if mode == "summary":
        summary = result["summary"]
        model_summary = summary["model_summary"]
        relation_summary = summary["relation_summary"]
        app_summary = summary["app_summary"]
        lines.extend(
            [
                f"- 当前共识别 **{model_summary['total_models']}** 个模型。",
                f"- 当前共识别 **{len(relation_summary['available_relation_types'])}** 种关系类型：{', '.join(relation_summary['available_relation_types'])}。",
                f"- 当前共解析 **{relation_summary['configured_relation_count']}** 条模型关系配置。",
                f"- 应用模型 `project` 当前有 **{app_summary['outgoing_count']}** 条出向关系、**{app_summary['incoming_count']}** 条入向关系。",
                "",
                _render_group_section("模型分组分布", model_summary["groups"]),
                "",
                _render_chart_section("模型分组分布", model_summary["groups"], "pie"),
                "",
                _render_group_section("关系类型分布", relation_summary["groups"]),
                "",
                _render_chart_section("关系类型分布", relation_summary["groups"], "donut"),
                "",
                _render_group_section("应用关联目标分布", app_summary["target_groups"]),
                "",
                _render_chart_section("应用关联目标分布", app_summary["target_groups"], "bar"),
            ]
        )
        return "\n".join(lines).strip()

    if mode == "model-groups":
        summary = result["summary"]
        preview = summary["rows"][:12]
        lines.extend(
            [
                f"- 当前共识别 **{summary['total_models']}** 个模型。",
                "",
                _render_group_section("模型分组分布", summary["groups"]),
                "",
                _render_chart_section("模型分组分布", summary["groups"], "pie"),
                "",
                "## 模型样例",
                "",
                _build_markdown_table(preview, [("模型名", "模型名"), ("显示名", "显示名"), ("分组", "分组"), ("唯一键", "唯一键")]),
            ]
        )
        return "\n".join(lines).strip()

    if mode == "relation-types":
        summary = result["summary"]
        lines.extend(
            [
                f"- 当前已配置关系共 **{summary['configured_relation_count']}** 条。",
                f"- 系统可用关系类型：**{', '.join(summary['available_relation_types'])}**。",
                "",
                _render_group_section("关系类型分布", summary["groups"]),
                "",
                _render_chart_section("关系类型分布", summary["groups"], "donut"),
            ]
        )
        return "\n".join(lines).strip()

    summary = result["summary"]
    outgoing_preview = summary["outgoing_rows"][:12]
    incoming_preview = summary["incoming_rows"][:6]
    lines.extend(
        [
            f"- 应用模型 `project` 当前有 **{summary['outgoing_count']}** 条出向关系。",
            f"- 应用模型 `project` 当前有 **{summary['incoming_count']}** 条入向关系。",
            "",
            _render_group_section("应用关联目标分布", summary["target_groups"]),
            "",
            _render_chart_section("应用关联目标分布", summary["target_groups"], "bar"),
            "",
            _render_group_section("应用关系类型分布", summary["relation_type_groups"]),
            "",
            _render_chart_section("应用关系类型分布", summary["relation_type_groups"], "donut"),
            "",
            "## 应用出向关系样例",
            "",
            _build_markdown_table(outgoing_preview, [("来源显示名", "来源"), ("关系类型", "关系"), ("目标显示名", "目标"), ("约束", "约束")]),
        ]
    )
    if incoming_preview:
        lines.extend(
            [
                "",
                "## 应用入向关系样例",
                "",
                _build_markdown_table(incoming_preview, [("来源显示名", "来源"), ("关系类型", "关系"), ("目标显示名", "目标"), ("约束", "约束")]),
            ]
        )
    return "\n".join(lines).strip()


def analyze(mode: str, skill_root: Path, env: Dict[str, str]) -> Dict[str, Any]:
    session = create_session()
    try_login(
        session,
        env["VEOPS_BASE_URL"],
        env.get("VEOPS_USERNAME", ""),
        env.get("VEOPS_PASSWORD", ""),
    )
    models = load_models(session, env["VEOPS_BASE_URL"])
    relations = load_all_relations(session, env["VEOPS_BASE_URL"])
    relation_types = load_relation_types(session, env["VEOPS_BASE_URL"])

    if mode == "summary":
        return {"code": 200, "mode": mode, "summary": build_summary(models, relations, relation_types)}
    if mode == "model-groups":
        return {"code": 200, "mode": mode, "summary": build_model_group_summary(models)}
    if mode == "relation-types":
        return {"code": 200, "mode": mode, "summary": build_relation_type_summary(relations, relation_types)}
    return {"code": 200, "mode": mode, "summary": build_app_relation_summary(relations)}


def print_result(result: Dict[str, Any], output_format: str) -> None:
    if result.get("code") != 200:
        print(
            "\n".join(
                [
                    "# 分析失败",
                    "",
                    f"- 错误码：{result.get('code', '-')}",
                    f"- 错误信息：{result.get('msg', '未知错误')}",
                ]
            )
        )
        return

    if output_format == "markdown-echarts-only":
        print(render_chart_only_markdown(result))
        return
    if output_format == "markdown":
        print(render_markdown(result))
        return
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="CMDB 汇总与图表输出")
    parser.add_argument("--mode", choices=sorted(ALLOWED_MODES), default="summary")
    parser.add_argument("--output", choices=sorted(ALLOWED_OUTPUTS), default="markdown")
    args = parser.parse_args()

    script_path = Path(__file__).resolve()
    skill_root = script_path.parent.parent
    env_path = skill_root / ".env"
    if not env_path.exists():
        print(
            "\n".join(
                [
                    "# 分析失败",
                    "",
                    f"- 错误信息：缺少环境变量文件 {env_path}",
                ]
            )
        )
        return 1

    env = parse_env(env_path)
    try:
        result = analyze(args.mode, skill_root, env)
    except Exception as exc:  # noqa: BLE001
        result = build_error(str(exc))
    print_result(result, args.output)
    return 0 if result.get("code") == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
