#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Query the static data from the private-line business monitor demo page."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


SKILL_DIR = Path(__file__).resolve().parents[1]
DATA_PATH = SKILL_DIR / "references" / "page_data.json"

STATUS_ALIASES = {
    "normal": "normal",
    "warning": "warning",
    "alarm": "alarm",
    "cutover": "cutover",
    "正常": "normal",
    "预警": "warning",
    "告警": "alarm",
    "报警": "alarm",
    "割接": "cutover",
    "割接中": "cutover",
}

ABNORMAL_STATUSES = ("warning", "alarm", "cutover")
CODE_PATTERN = re.compile(r"ZN-[A-Z]+-\d{6}-\d{4}", re.IGNORECASE)


def load_data() -> dict[str, Any]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


DATA = load_data()
STATUS_MAP = DATA["statusMap"]
CIRCUITS = DATA["circuits"]
NOTICES = DATA["notices"]


def normalize_status(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    normalized = STATUS_ALIASES.get(raw, STATUS_ALIASES.get(raw.lower(), ""))
    if normalized:
        return normalized
    if raw == "abnormal" or raw == "异常":
        return "abnormal"
    return raw.lower()


def status_label(status: str) -> str:
    if status == "abnormal":
        return "异常（预警/告警/割接中）"
    return STATUS_MAP.get(status, {}).get("label", status)


def escape_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def make_table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return ""
    head = "| " + " | ".join(headers) + " |"
    split = "| " + " | ".join(["---"] * len(headers)) + " |"
    body = [
        "| " + " | ".join(escape_cell(item) for item in row) + " |"
        for row in rows
    ]
    return "\n".join([head, split, *body])


def fmt_bandwidth(value: int | float) -> str:
    if value >= 1000:
        return f"{value / 1000:.1f} Gbps"
    return f"{int(value)} Mbps"


def fmt_util(value: float | int | None) -> str:
    if value is None:
        return "-"
    return f"{float(value) * 100:.1f}%"


def latency_ms(circuit: dict[str, Any]) -> float:
    text = str(circuit.get("latency", "")).replace("ms", "").strip()
    try:
        return float(text)
    except ValueError:
        return 0.0


def availability_pct(circuit: dict[str, Any]) -> float:
    text = str(circuit.get("availability", "")).replace("%", "").strip()
    try:
        return float(text)
    except ValueError:
        return 0.0


def find_circuits(
    *,
    keyword: str = "",
    status: str = "",
    circuit_type: str = "",
    customer: str = "",
) -> list[dict[str, Any]]:
    keyword_cf = keyword.strip().casefold()
    status_norm = normalize_status(status)
    type_cf = circuit_type.strip().casefold()
    customer_cf = customer.strip().casefold()

    results: list[dict[str, Any]] = []
    for circuit in CIRCUITS:
        if status_norm:
            if status_norm == "abnormal":
                if circuit["status"] not in ABNORMAL_STATUSES:
                    continue
            elif circuit["status"] != status_norm:
                continue

        if type_cf and type_cf not in str(circuit["type"]).casefold():
            continue

        if customer_cf and customer_cf not in str(circuit["customer"]).casefold():
            continue

        if keyword_cf:
            haystack = " ".join(
                str(circuit.get(field, ""))
                for field in (
                    "code",
                    "type",
                    "customer",
                    "aName",
                    "zName",
                    "aAddress",
                    "zAddress",
                    "latency",
                    "availability",
                )
            ).casefold()
            haystack += " " + status_label(circuit["status"]).casefold()
            if keyword_cf not in haystack:
                continue

        results.append(circuit)
    return results


def find_circuit_by_code(code: str) -> dict[str, Any] | None:
    code_cf = code.strip().casefold()
    for circuit in CIRCUITS:
        if circuit["code"].casefold() == code_cf:
            return circuit
    return None


def guess_matches(keyword: str) -> list[dict[str, Any]]:
    exact = find_circuit_by_code(keyword)
    if exact:
        return [exact]
    return find_circuits(keyword=keyword)


def summary_payload() -> dict[str, Any]:
    status_counts = {
        key: sum(1 for circuit in CIRCUITS if circuit["status"] == key)
        for key in STATUS_MAP
    }
    type_counts: dict[str, int] = {}
    for circuit in CIRCUITS:
        type_counts[circuit["type"]] = type_counts.get(circuit["type"], 0) + 1
    abnormal = [
        {
            "code": circuit["code"],
            "type": circuit["type"],
            "status": circuit["status"],
            "statusLabel": status_label(circuit["status"]),
            "customer": circuit["customer"],
            "latency": circuit["latency"],
            "availability": circuit["availability"],
        }
        for circuit in CIRCUITS
        if circuit["status"] in ABNORMAL_STATUSES
    ]
    return {
        "pageTitle": DATA["pageTitle"],
        "sourceUrl": DATA["sourceUrl"],
        "dataNature": DATA["dataNature"],
        "baseTimeDisplay": DATA["baseTimeDisplay"],
        "total": len(CIRCUITS),
        "statusCounts": status_counts,
        "typeCounts": type_counts,
        "abnormalCircuits": abnormal,
        "cutoverNotices": list(NOTICES.keys()),
    }


def format_summary_markdown(payload: dict[str, Any]) -> str:
    metrics = make_table(
        ["指标", "数值"],
        [
            ["数据性质", "静态演示数据"],
            ["来源页面", payload["sourceUrl"]],
            ["页面基准时间", payload["baseTimeDisplay"]],
            ["专线总数", payload["total"]],
            ["正常", payload["statusCounts"]["normal"]],
            ["预警", payload["statusCounts"]["warning"]],
            ["告警", payload["statusCounts"]["alarm"]],
            ["割接中", payload["statusCounts"]["cutover"]],
        ],
    )
    type_rows = [
        [name, count]
        for name, count in sorted(
            payload["typeCounts"].items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]
    abnormal_table = make_table(
        ["电路编码", "类型", "状态", "客户", "时延", "可用率"],
        [
            [
                item["code"],
                item["type"],
                item["statusLabel"],
                item["customer"],
                item["latency"],
                item["availability"],
            ]
            for item in payload["abnormalCircuits"]
        ],
    )
    parts = [
        "# 专线业务监控概览",
        "",
        "> 当前结果来自“专线业务监控”页面内置的静态演示数据，不代表实时监控。",
        "",
        metrics,
        "",
        "## 专线类型分布",
        "",
        make_table(["专线类型", "数量"], type_rows),
    ]
    if abnormal_table:
        parts.extend(["", "## 当前异常专线", "", abnormal_table])
    return "\n".join(parts).strip()


def list_payload(
    *,
    keyword: str = "",
    status: str = "",
    circuit_type: str = "",
    customer: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    matches = find_circuits(
        keyword=keyword,
        status=status,
        circuit_type=circuit_type,
        customer=customer,
    )
    limited = matches[:limit] if limit > 0 else matches
    return {
        "filters": {
            "keyword": keyword,
            "status": normalize_status(status),
            "type": circuit_type,
            "customer": customer,
            "limit": limit,
        },
        "totalMatched": len(matches),
        "circuits": limited,
    }


def format_list_markdown(payload: dict[str, Any]) -> str:
    circuits = payload["circuits"]
    if not circuits:
        return (
            "# 专线查询结果\n\n"
            "> 当前结果来自静态演示数据。\n\n"
            "未找到符合条件的专线。"
        )
    table = make_table(
        ["电路编码", "状态", "类型", "客户", "A端 -> Z端", "时延", "可用率"],
        [
            [
                circuit["code"],
                status_label(circuit["status"]),
                circuit["type"],
                circuit["customer"],
                f"{circuit['aName']} -> {circuit['zName']}",
                circuit["latency"],
                circuit["availability"],
            ]
            for circuit in circuits
        ],
    )
    filter_bits = []
    if payload["filters"]["keyword"]:
        filter_bits.append(f"关键字={payload['filters']['keyword']}")
    if payload["filters"]["status"]:
        filter_bits.append(f"状态={status_label(payload['filters']['status'])}")
    if payload["filters"]["type"]:
        filter_bits.append(f"类型={payload['filters']['type']}")
    if payload["filters"]["customer"]:
        filter_bits.append(f"客户={payload['filters']['customer']}")
    filter_line = "；".join(filter_bits) if filter_bits else "无筛选条件"
    return (
        "# 专线查询结果\n\n"
        "> 当前结果来自静态演示数据。\n\n"
        f"- 命中数量：{payload['totalMatched']}\n"
        f"- 当前筛选：{filter_line}\n\n"
        f"{table}"
    )


def detail_payload(*, code: str = "", keyword: str = "") -> dict[str, Any]:
    query = code or keyword
    matches = [find_circuit_by_code(code)] if code else guess_matches(keyword)
    matches = [item for item in matches if item]
    if not matches:
        return {"query": query, "matches": []}
    if len(matches) > 1:
        return {"query": query, "matches": matches}
    circuit = matches[0]
    notice = None
    notice_code = circuit.get("noticeCode")
    if notice_code:
        notice = NOTICES.get(notice_code)
    return {
        "query": query,
        "matches": matches,
        "circuit": circuit,
        "notice": notice,
    }


def format_detail_markdown(payload: dict[str, Any]) -> str:
    matches = payload.get("matches") or []
    if not matches:
        return (
            "# 电路详情\n\n"
            "> 当前结果来自静态演示数据。\n\n"
            f"未找到与 `{payload.get('query', '')}` 对应的电路。"
        )
    if len(matches) > 1 and "circuit" not in payload:
        return (
            "# 电路详情\n\n"
            "> 当前结果来自静态演示数据。\n\n"
            "命中多条电路，请根据电路编码继续缩小范围：\n\n"
            + make_table(
                ["电路编码", "状态", "类型", "客户"],
                [
                    [
                        circuit["code"],
                        status_label(circuit["status"]),
                        circuit["type"],
                        circuit["customer"],
                    ]
                    for circuit in matches
                ],
            )
        )

    circuit = payload["circuit"]
    rows = [
        ["数据性质", "静态演示数据"],
        ["电路编码", circuit["code"]],
        ["状态", status_label(circuit["status"])],
        ["客户名称", circuit["customer"]],
        ["专线类型", circuit["type"]],
        [
            "带宽（上行 / 下行）",
            f"{fmt_bandwidth(circuit['bandwidth']['up'])} / {fmt_bandwidth(circuit['bandwidth']['down'])}",
        ],
        ["时延", circuit["latency"]],
        ["可用率", circuit["availability"]],
        ["上行利用率（页面趋势基值）", fmt_util(circuit.get("upUtil"))],
        ["下行利用率（页面趋势基值）", fmt_util(circuit.get("downUtil"))],
        ["A端名称", circuit["aName"]],
        ["A端地址", circuit["aAddress"]],
        ["Z端名称", circuit["zName"]],
        ["Z端地址", circuit["zAddress"]],
    ]
    parts = ["# 电路详情", "", make_table(["字段", "值"], rows)]
    notice = payload.get("notice")
    if notice:
        parts.extend(
            [
                "",
                "## 关联割接通知",
                "",
                make_table(
                    ["字段", "值"],
                    [
                        ["通知单号", circuit.get("noticeCode", "-")],
                        ["标题", notice["title"]],
                        ["类型", notice["type"]],
                        ["系统", notice["system"]],
                        ["区段", notice["section"]],
                        ["开始时间", notice["startTime"]],
                        ["结束时间", notice["endTime"]],
                        ["割接原因", notice["reason"]],
                    ],
                ),
            ]
        )
    return "\n".join(parts).strip()


def cutover_payload(*, code: str = "", notice_code: str = "", keyword: str = "") -> dict[str, Any]:
    current_cutovers = [circuit for circuit in CIRCUITS if circuit["status"] == "cutover"]
    resolved_notice_code = notice_code.strip()
    if code and not resolved_notice_code:
        circuit = find_circuit_by_code(code)
        if circuit:
            resolved_notice_code = str(circuit.get("noticeCode", "")).strip()
    if keyword and not resolved_notice_code:
        for key, notice in NOTICES.items():
            haystack = " ".join([key, *[str(value) for value in notice.values()]])
            if keyword.casefold() in haystack.casefold():
                resolved_notice_code = key
                break

    selected_notice = NOTICES.get(resolved_notice_code) if resolved_notice_code else None
    if selected_notice:
        affected = [find_circuit_by_code(item) for item in selected_notice["affectedCodes"]]
        return {
            "cutoverCircuits": current_cutovers,
            "selectedNoticeCode": resolved_notice_code,
            "selectedNotice": selected_notice,
            "affectedCircuits": [item for item in affected if item],
        }

    return {
        "cutoverCircuits": current_cutovers,
        "notices": [
            {
                "noticeCode": key,
                **value,
            }
            for key, value in NOTICES.items()
        ],
    }


def format_cutover_markdown(payload: dict[str, Any]) -> str:
    if payload.get("selectedNotice"):
        notice = payload["selectedNotice"]
        affected = payload["affectedCircuits"]
        parts = [
            "# 割接通知详情",
            "",
            "> 当前结果来自静态演示数据。",
            "",
            make_table(
                ["字段", "值"],
                [
                    ["通知单号", payload["selectedNoticeCode"]],
                    ["标题", notice["title"]],
                    ["类型", notice["type"]],
                    ["割接对象", notice["name"]],
                    ["所属系统", notice["system"]],
                    ["区段", notice["section"]],
                    ["开始时间", notice["startTime"]],
                    ["结束时间", notice["endTime"]],
                    ["割接原因", notice["reason"]],
                ],
            ),
        ]
        if affected:
            parts.extend(
                [
                    "",
                    "## 影响电路",
                    "",
                    make_table(
                        ["电路编码", "状态", "类型", "客户"],
                        [
                            [
                                circuit["code"],
                                status_label(circuit["status"]),
                                circuit["type"],
                                circuit["customer"],
                            ]
                            for circuit in affected
                        ],
                    ),
                ]
            )
        return "\n".join(parts).strip()

    cutover_circuits = payload.get("cutoverCircuits") or []
    notices = payload.get("notices") or []
    parts = [
        "# 当前割接信息",
        "",
        "> 当前结果来自静态演示数据。",
    ]
    if cutover_circuits:
        parts.extend(
            [
                "",
                "## 割接中的电路",
                "",
                make_table(
                    ["电路编码", "类型", "客户", "通知单号"],
                    [
                        [
                            circuit["code"],
                            circuit["type"],
                            circuit["customer"],
                            circuit.get("noticeCode", "-"),
                        ]
                        for circuit in cutover_circuits
                    ],
                ),
            ]
        )
    if notices:
        parts.extend(
            [
                "",
                "## 割接通知单",
                "",
                make_table(
                    ["通知单号", "标题", "开始时间", "结束时间", "影响电路"],
                    [
                        [
                            notice["noticeCode"],
                            notice["title"],
                            notice["startTime"],
                            notice["endTime"],
                            "、".join(notice["affectedCodes"]),
                        ]
                        for notice in notices
                    ],
                ),
            ]
        )
    if not cutover_circuits and not notices:
        parts.append("\n当前页面数据中没有割接通知。")
    return "\n".join(parts).strip()


METRIC_CHOICES = {
    "latency": {
        "label": "时延",
        "key": latency_ms,
        "reverse": True,
        "display": lambda circuit: circuit["latency"],
    },
    "availability": {
        "label": "可用率",
        "key": availability_pct,
        "reverse": False,
        "display": lambda circuit: circuit["availability"],
    },
    "up-bandwidth": {
        "label": "上行带宽",
        "key": lambda circuit: circuit["bandwidth"]["up"],
        "reverse": True,
        "display": lambda circuit: fmt_bandwidth(circuit["bandwidth"]["up"]),
    },
    "down-bandwidth": {
        "label": "下行带宽",
        "key": lambda circuit: circuit["bandwidth"]["down"],
        "reverse": True,
        "display": lambda circuit: fmt_bandwidth(circuit["bandwidth"]["down"]),
    },
    "up-util": {
        "label": "上行利用率",
        "key": lambda circuit: float(circuit.get("upUtil") or 0),
        "reverse": True,
        "display": lambda circuit: fmt_util(circuit.get("upUtil")),
    },
    "down-util": {
        "label": "下行利用率",
        "key": lambda circuit: float(circuit.get("downUtil") or 0),
        "reverse": True,
        "display": lambda circuit: fmt_util(circuit.get("downUtil")),
    },
}


def rank_payload(metric: str, limit: int) -> dict[str, Any]:
    config = METRIC_CHOICES[metric]
    ranked = sorted(CIRCUITS, key=config["key"], reverse=config["reverse"])
    if limit > 0:
        ranked = ranked[:limit]
    return {
        "metric": metric,
        "metricLabel": config["label"],
        "circuits": ranked,
    }


def format_rank_markdown(payload: dict[str, Any]) -> str:
    metric = payload["metric"]
    config = METRIC_CHOICES[metric]
    return (
        f"# 专线指标排行（{payload['metricLabel']}）\n\n"
        "> 当前结果来自静态演示数据。\n\n"
        + make_table(
            ["排名", "电路编码", "状态", "类型", "客户", payload["metricLabel"]],
            [
                [
                    index,
                    circuit["code"],
                    status_label(circuit["status"]),
                    circuit["type"],
                    circuit["customer"],
                    config["display"](circuit),
                ]
                for index, circuit in enumerate(payload["circuits"], start=1)
            ],
        )
    )


def detect_status_from_text(text: str) -> str:
    if "异常" in text:
        return "abnormal"
    for alias, status in [
        ("割接中", "cutover"),
        ("割接", "cutover"),
        ("告警", "alarm"),
        ("预警", "warning"),
        ("正常", "normal"),
    ]:
        if alias in text:
            return status
    return ""


def detect_type_from_text(text: str) -> str:
    types = sorted({circuit["type"] for circuit in CIRCUITS}, key=len, reverse=True)
    for circuit_type in types:
        if circuit_type in text:
            return circuit_type
    return ""


def detect_customer_from_text(text: str) -> str:
    customers = sorted(
        {circuit["customer"] for circuit in CIRCUITS},
        key=len,
        reverse=True,
    )
    for customer in customers:
        if customer in text:
            return customer
    return ""


def detect_metric_from_text(text: str) -> str:
    if "时延" in text:
        return "latency"
    if "可用率" in text:
        return "availability"
    if "上行利用率" in text:
        return "up-util"
    if "下行利用率" in text:
        return "down-util"
    if "上行带宽" in text:
        return "up-bandwidth"
    if "下行带宽" in text:
        return "down-bandwidth"
    if "带宽" in text:
        return "down-bandwidth"
    return ""


def ask_payload(question: str) -> dict[str, Any]:
    text = question.strip()
    code_match = CODE_PATTERN.search(text)
    code = code_match.group(0).upper() if code_match else ""
    status = detect_status_from_text(text)
    circuit_type = detect_type_from_text(text)
    customer = detect_customer_from_text(text)
    metric = detect_metric_from_text(text)

    if code and ("割接" in text or "通知" in text):
        return {
            "mode": "cutover",
            "payload": cutover_payload(code=code),
        }

    if "割接" in text or "通知单" in text or "割接通知" in text:
        keyword = code or customer or circuit_type
        return {
            "mode": "cutover",
            "payload": cutover_payload(code=code, keyword=keyword),
        }

    if metric and any(word in text for word in ("最高", "最大", "最差", "最低", "排行", "top", "TOP")):
        if metric == "availability" and any(word in text for word in ("最高", "最大", "top", "TOP")):
            payload = rank_payload(metric, limit=5)
            payload["circuits"] = list(reversed(payload["circuits"]))
            return {"mode": "rank", "payload": payload}
        return {
            "mode": "rank",
            "payload": rank_payload(metric, limit=5),
        }

    if code:
        return {"mode": "detail", "payload": detail_payload(code=code)}

    if any(word in text for word in ("概览", "统计", "总数", "总览", "有多少")):
        return {"mode": "summary", "payload": summary_payload()}

    if metric and (customer or circuit_type or status or "哪条" in text or "哪个" in text):
        results = find_circuits(status=status, circuit_type=circuit_type, customer=customer)
        if len(results) == 1:
            return {
                "mode": "detail",
                "payload": {
                    "query": text,
                    "matches": results,
                    "circuit": results[0],
                    "notice": NOTICES.get(results[0].get("noticeCode", "")),
                },
            }

    if status or circuit_type or customer or any(word in text for word in ("哪些", "列表", "全部", "专线", "电路")):
        return {
            "mode": "list",
            "payload": list_payload(
                status=status,
                circuit_type=circuit_type,
                customer=customer,
                keyword="" if (status or circuit_type or customer) else text,
            ),
        }

    matches = guess_matches(text)
    if len(matches) == 1:
        return {
            "mode": "detail",
            "payload": {
                "query": text,
                "matches": matches,
                "circuit": matches[0],
                "notice": NOTICES.get(matches[0].get("noticeCode", "")),
            },
        }
    if matches:
        return {
            "mode": "list",
            "payload": {
                "filters": {"keyword": text, "status": "", "type": "", "customer": "", "limit": 20},
                "totalMatched": len(matches),
                "circuits": matches[:20],
            },
        }
    return {"mode": "summary", "payload": summary_payload()}


def format_by_mode(mode: str, payload: dict[str, Any]) -> str:
    if mode == "summary":
        return format_summary_markdown(payload)
    if mode == "list":
        return format_list_markdown(payload)
    if mode == "detail":
        return format_detail_markdown(payload)
    if mode == "cutover":
        return format_cutover_markdown(payload)
    if mode == "rank":
        return format_rank_markdown(payload)
    raise RuntimeError(f"unsupported mode: {mode}")


def print_output(payload: dict[str, Any], *, output: str, markdown: str) -> None:
    if output == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(markdown)


def main() -> None:
    parser = argparse.ArgumentParser(description="Query static private-line business monitor demo data")
    subparsers = parser.add_subparsers(dest="command", required=True)

    summary_parser = subparsers.add_parser("summary")
    summary_parser.add_argument("--output", choices=["markdown", "json"], default="markdown")

    list_parser = subparsers.add_parser("list-circuits")
    list_parser.add_argument("--keyword", default="")
    list_parser.add_argument("--status", default="")
    list_parser.add_argument("--type", dest="circuit_type", default="")
    list_parser.add_argument("--customer", default="")
    list_parser.add_argument("--limit", type=int, default=20)
    list_parser.add_argument("--output", choices=["markdown", "json"], default="markdown")

    detail_parser = subparsers.add_parser("detail")
    detail_parser.add_argument("--code", default="")
    detail_parser.add_argument("--keyword", default="")
    detail_parser.add_argument("--output", choices=["markdown", "json"], default="markdown")

    cutover_parser = subparsers.add_parser("cutover")
    cutover_parser.add_argument("--code", default="")
    cutover_parser.add_argument("--notice-code", default="")
    cutover_parser.add_argument("--keyword", default="")
    cutover_parser.add_argument("--output", choices=["markdown", "json"], default="markdown")

    rank_parser = subparsers.add_parser("rank")
    rank_parser.add_argument(
        "--metric",
        choices=list(METRIC_CHOICES.keys()),
        required=True,
    )
    rank_parser.add_argument("--limit", type=int, default=5)
    rank_parser.add_argument("--output", choices=["markdown", "json"], default="markdown")

    ask_parser = subparsers.add_parser("ask")
    ask_parser.add_argument("--question", required=True)
    ask_parser.add_argument("--output", choices=["markdown", "json"], default="markdown")

    args = parser.parse_args()

    if args.command == "summary":
        payload = summary_payload()
        print_output(payload, output=args.output, markdown=format_summary_markdown(payload))
        return

    if args.command == "list-circuits":
        payload = list_payload(
            keyword=args.keyword,
            status=args.status,
            circuit_type=args.circuit_type,
            customer=args.customer,
            limit=args.limit,
        )
        print_output(payload, output=args.output, markdown=format_list_markdown(payload))
        return

    if args.command == "detail":
        payload = detail_payload(code=args.code, keyword=args.keyword)
        print_output(payload, output=args.output, markdown=format_detail_markdown(payload))
        return

    if args.command == "cutover":
        payload = cutover_payload(
            code=args.code,
            notice_code=args.notice_code,
            keyword=args.keyword,
        )
        print_output(payload, output=args.output, markdown=format_cutover_markdown(payload))
        return

    if args.command == "rank":
        payload = rank_payload(args.metric, args.limit)
        print_output(payload, output=args.output, markdown=format_rank_markdown(payload))
        return

    if args.command == "ask":
        result = ask_payload(args.question)
        payload = {"question": args.question, "mode": result["mode"], "result": result["payload"]}
        print_output(
            payload,
            output=args.output,
            markdown=format_by_mode(result["mode"], result["payload"]),
        )
        return


if __name__ == "__main__":
    main()
