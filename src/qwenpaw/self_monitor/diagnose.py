# -*- coding: utf-8 -*-
"""AIOps root-cause diagnosis (design P2) — the dogfood diagnostician.

``diagnose()`` gathers a cross-layer snapshot (KPIs, deltas, active
alerts, top events, datasource/worker state, cost) and asks the
configured LLM for a structured verdict via the battle-tested
``structured_call`` repair loop from the big screen.  When no model is
configured/reachable the deterministic rule-based analyser answers
instead — the endpoint always returns, ``degraded`` says which brain
produced it.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from .costs import cost_summary
from .store import SelfMonitorStore

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "你是「智观AI 自监控」的根因诊断专家。输入是系统四层监控"
    "(L1体验/L2应用/L3依赖/L4资源)的窗口快照 JSON。"
    "请只输出一个 JSON 对象,不要输出其他文本,字段:"
    '{"summary": "一句话结论", "rootCause": "最可能根因",'
    ' "confidence": "high|medium|low",'
    ' "evidence": ["证据1", "证据2"],'
    ' "recommendations": ["建议1", "建议2"]}。'
    "推理规则:降级+429 同窗出现时根因通常是上游限流而非代码;"
    "worker 掉线看 L4;数据源断连只影响对应能力;"
    "无异常时如实说明系统健康,不要编造问题。"
)


def gather_snapshot(
    store: SelfMonitorStore, *, window_s: float = 3600.0
) -> dict[str, Any]:
    now = time.time()
    since = now - window_s
    latest = store.latest_samples()

    def _gauge_map(name: str, label: str) -> dict[str, float]:
        return {
            str(row["labels"].get(label) or row["worker_id"]): row["value"]
            for row in latest
            if row["name"] == name
        }

    return {
        "windowS": window_s,
        "generatedAt": int(now),
        "deltas": {
            "degradeEvents": store.counter_delta(
                "qwenpaw_degrade_events_total", since=since
            ),
            "llm429": store.counter_delta(
                "qwenpaw_llm_requests_total",
                since=since,
                label_filter={"status": "429"},
            ),
            "llmErrors": store.counter_delta(
                "qwenpaw_llm_requests_total",
                since=since,
                label_filter={"status": "error"},
            ),
            "llmRequests": store.counter_delta(
                "qwenpaw_llm_requests_total", since=since
            ),
            "chatErrors": store.counter_delta(
                "qwenpaw_chat_turns_total",
                since=since,
                label_filter={"status": "error"},
            ),
            "governanceTimeouts": store.counter_delta(
                "qwenpaw_governance_decisions_total",
                since=since,
                label_filter={"decision": "timeout"},
            ),
            "logErrors": store.counter_delta("qwenpaw_log_errors_total", since=since),
        },
        "gauges": {
            "workersUp": sorted(
                row["worker_id"]
                for row in latest
                if row["name"] == "qwenpaw_worker_up" and row["value"] >= 1.0
            ),
            "datasources": {
                key: value >= 1.0
                for key, value in _gauge_map("qwenpaw_datasource_up", "source").items()
            },
            "probes": {
                key: value >= 1.0
                for key, value in _gauge_map("qwenpaw_probe_up", "target").items()
            },
            "diskUsagePercent": max(
                (
                    row["value"]
                    for row in latest
                    if row["name"] == "qwenpaw_disk_usage_percent"
                ),
                default=None,
            ),
        },
        "activeAlerts": store.active_alerts(),
        "recentEvents": store.query_events(since=since, limit=20),
        "cost": cost_summary(store, since=since),
    }


def rule_based_diagnosis(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Deterministic fallback: pick the dominant incident signature."""
    deltas = snapshot.get("deltas") or {}
    gauges = snapshot.get("gauges") or {}
    evidence: list[str] = []

    degrade = float(deltas.get("degradeEvents") or 0)
    storm = float(deltas.get("llm429") or 0)
    workers = gauges.get("workersUp") or []
    probes_down = [key for key, up in (gauges.get("probes") or {}).items() if not up]
    ds_down = [key for key, up in (gauges.get("datasources") or {}).items() if not up]
    gov_timeout = float(deltas.get("governanceTimeouts") or 0)
    disk = gauges.get("diskUsagePercent")
    log_errors = float(deltas.get("logErrors") or 0)

    if not workers:
        return _verdict(
            "所有 worker 心跳缺失",
            "worker 进程全部掉线或自监控采集中断(单 worker 部署无法自证全灭,需外部抓取佐证)",
            "high",
            ["qwenpaw_worker_up 窗口内无新鲜心跳"],
            ["检查 supervisor/进程状态", "核对外部 /metrics 抓取是否同样中断"],
        )
    if degrade > 0 and storm > 0:
        evidence = [
            f"窗口内降级 {degrade:.0f} 起与 429 {storm:.0f} 次同现",
            "历史同款事故(上游 TPM 限流 → LLM 路径失败 → 退回模版)",
        ]
        return _verdict(
            "上游 LLM 限流引发组件降级",
            "上游模型服务 429 限流,重试耗尽后组件退回降级/模版路径",
            "high",
            evidence,
            [
                "确认限流窗口(检查 limiter pause 指标)",
                "必要时下调并发/QPM 或切换备用模型",
            ],
        )
    if degrade > 0:
        return _verdict(
            "组件降级(非限流)",
            "LLM 路径失败但无 429 佐证,疑似代码/配置问题(参考历史 llm.py 事故)",
            "medium",
            [f"降级 {degrade:.0f} 起而 429 为 0"],
            ["查看 component.degraded 事件的 lastError", "深链 trace 复现失败请求"],
        )
    if storm > 0:
        return _verdict(
            "LLM 限流风暴(未致降级)",
            "上游 429 频发,重试链路暂能扛住",
            "medium",
            [f"429 计 {storm:.0f} 次"],
            ["关注降级率是否跟涨", "评估调低 QPM"],
        )
    if probes_down:
        return _verdict(
            "端到端拨测失败",
            f"探测目标不可达: {', '.join(probes_down)}",
            "high",
            [f"probe_up=0: {probes_down}"],
            ["检查对应端点进程/路由"],
        )
    if ds_down:
        return _verdict(
            "外部数据源断连",
            f"数据源不可用: {', '.join(ds_down)},相关能力将降级",
            "medium",
            [f"datasource_up=0: {ds_down}"],
            ["核对 secrets 配置与网络连通性(改配置需重启后端)"],
        )
    if gov_timeout > 0:
        return _verdict(
            "治理审批超时",
            "工具审批等待超时后默认 DENY(No-rule-hit→ASK→超时链)",
            "medium",
            [f"治理超时 {gov_timeout:.0f} 次"],
            ["为高频路径补 policy.yaml 放行规则", "调大审批超时环境变量"],
        )
    if disk is not None and float(disk) >= 90:
        return _verdict(
            "磁盘水位过高",
            f"working 卷已用 {float(disk):.0f}%",
            "high",
            [f"disk_usage_percent={float(disk):.0f}"],
            ["清理日志/DB 或扩容"],
        )
    if log_errors > 50:
        return _verdict(
            "日志 ERROR 激增",
            "指标未见明确故障但错误日志异常增多",
            "low",
            [f"ERROR 日志 {log_errors:.0f} 条"],
            ["抽样最近 ERROR 日志定位来源"],
        )
    return _verdict(
        "系统健康",
        "窗口内未发现异常信号",
        "high",
        ["四层关键指标均在正常范围"],
        ["无需处置"],
    )


def _verdict(
    summary: str,
    root_cause: str,
    confidence: str,
    evidence: list[str],
    recommendations: list[str],
) -> dict[str, Any]:
    return {
        "summary": summary,
        "rootCause": root_cause,
        "confidence": confidence,
        "evidence": evidence,
        "recommendations": recommendations,
    }


def _parse_verdict(text: str) -> dict[str, Any]:
    payload = json.loads(_strip_fences(text))
    if not isinstance(payload, dict):
        raise ValueError("diagnosis must be a JSON object")
    for key in ("summary", "rootCause"):
        if not str(payload.get(key) or "").strip():
            raise ValueError(f"diagnosis missing '{key}'")
    payload.setdefault("confidence", "medium")
    payload["evidence"] = [str(x) for x in payload.get("evidence") or []]
    payload["recommendations"] = [str(x) for x in payload.get("recommendations") or []]
    return payload


def _strip_fences(text: str) -> str:
    body = str(text or "").strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[-1]
        if body.rstrip().endswith("```"):
            body = body.rstrip()[:-3]
    return body.strip()


async def diagnose(
    *, window_s: float = 3600.0, store: SelfMonitorStore | None = None
) -> dict[str, Any]:
    """Full diagnosis: LLM verdict with rule-based fallback."""
    store = store or SelfMonitorStore()
    snapshot = gather_snapshot(store, window_s=window_s)
    fallback = rule_based_diagnosis(snapshot)
    degraded = True
    attempts = 0
    verdict = fallback
    try:
        from ..extensions.ai_big_screen.llm import (
            create_pipeline_model,
            structured_call,
        )

        model = create_pipeline_model()
        result = await structured_call(
            model,
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(snapshot, ensure_ascii=False, default=str),
                },
            ],
            parser=_parse_verdict,
            max_repair=1,
            timeout=60.0,
            fallback=lambda: fallback,
        )
        verdict = result.value
        degraded = result.degraded
        attempts = result.attempts
    except Exception:
        logger.info(
            "self_monitor diagnose: LLM path unavailable, " "rule-based verdict used",
            exc_info=True,
        )
    return {
        **verdict,
        "engine": "rule-based" if degraded else "llm",
        "degraded": degraded,
        "attempts": attempts,
        "windowS": window_s,
        "generatedAt": snapshot["generatedAt"],
        "snapshot": snapshot,
    }


__all__ = ["diagnose", "gather_snapshot", "rule_based_diagnosis"]
