from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .fault_manual_workorder_models import (
    ManualWorkorderCloseNotificationRequest,
    ManualWorkorderDispatchRequest,
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_analysis_dispatch_payload(
    request: ManualWorkorderDispatchRequest,
    *,
    callback_url: str,
) -> dict[str, Any]:
    alarm_payload = request.alarm.model_dump(mode="json")
    analysis_payload = request.analysis.model_dump(mode="json")

    return {
        "alarmId": request.alarm_id,
        "chatId": request.chat_id,
        "resId": request.res_id,
        "metricType": request.metric_type,
        "alarm": alarm_payload,
        "analysis": analysis_payload,
        "context": {
            "source": "portal-fault-disposal",
            "callback_url": callback_url,
        },
    }


def build_analysis_record(
    request: ManualWorkorderDispatchRequest,
    *,
    callback_url: str,
) -> dict[str, Any]:
    now = utc_now_iso()
    dispatch_payload = build_analysis_dispatch_payload(request, callback_url=callback_url)
    return {
        "alarmId": request.alarm_id,
        "chatId": request.chat_id,
        "resId": request.res_id,
        "metricType": request.metric_type,
        "status": "pending_manual",
        "alarm": request.alarm.model_dump(mode="json"),
        "analysis": request.analysis.model_dump(mode="json"),
        "dispatchPayload": dispatch_payload,
        "callbackUrl": callback_url,
        "createdAt": now,
        "updatedAt": now,
    }


def merge_manual_workorder_notification(
    record: dict[str, Any],
    notification: ManualWorkorderCloseNotificationRequest,
    *,
    verification: dict[str, Any],
) -> dict[str, Any]:
    now = utc_now_iso()
    workorder_payload = notification.workorder.model_dump(mode="json")
    processing_payload = notification.processing.model_dump(mode="json")
    verification_status = str(verification.get("status") or "unknown")
    merged = dict(record)
    merged["status"] = f"manual_{verification_status}"
    merged["workorder"] = {
        **(record.get("workorder") or {}),
        **workorder_payload,
    }
    merged["processing"] = processing_payload
    merged["verification"] = verification
    merged["updatedAt"] = now
    return merged


def build_analysis_dispatch_history_message(record: dict[str, Any]) -> dict[str, Any]:
    dispatch_payload = record.get("dispatchPayload") or {}
    alarm = dispatch_payload.get("alarm") or record.get("alarm") or {}
    alarm_id = record.get("alarmId") or alarm.get("alarmId") or alarm.get("alarm_id") or ""
    title = alarm.get("title") or "告警分析报告"
    visible_content = alarm.get("visible_content") or alarm.get("visibleContent") or ""
    summary = dispatch_payload.get("analysis", {}).get("summary") or "AI 已完成根因分析"
    callback_url = dispatch_payload.get("context", {}).get("callback_url") or record.get("callbackUrl") or ""
    content_lines = [
        "## AI 告警分析报告已登记",
        f"- 告警编号：`{alarm_id}`",
        f"- 会话 ID：`{record.get('chatId', '')}`",
        f"- 告警标题：`{title}`",
    ]
    if visible_content:
        content_lines.append(f"- 告警摘要：{visible_content}")
    content_lines.extend(
        [
            f"- 分析结论：{summary}",
            f"- 回调地址：`{callback_url}`",
            "- 当前状态：已推送分析报告，等待处置完成回调",
        ]
    )
    return {
        "type": "agent",
        "content": "\n".join(content_lines),
        "analysisRecord": record,
    }


def build_analysis_close_history_message(
    record: dict[str, Any],
    *,
    verification: dict[str, Any],
) -> dict[str, Any]:
    processing = record.get("processing") or {}
    alarm = record.get("alarm") or {}
    alarm_id = record.get("alarmId") or alarm.get("alarmId") or alarm.get("alarm_id") or ""
    verification_summary = verification.get("summary") or "已完成恢复性检测"
    abnormal_metrics = verification.get("abnormalMetrics") or []
    content_lines = [
        "## 处置完成回调通知",
        f"- 告警编号：`{alarm_id}`",
        f"- 会话 ID：`{record.get('chatId', '')}`",
    ]
    if processing.get("summary"):
        content_lines.append(f"- 处理摘要：{processing['summary']}")
    if processing.get("details"):
        content_lines.append(f"- 处理详情：{processing['details']}")
    content_lines.append(f"- 恢复验证结论：{verification_summary}")
    if abnormal_metrics:
        metric_descriptions = "；".join(
            f"{item.get('metricCode')}={item.get('latestValue') or item.get('avgValue') or '-'}"
            for item in abnormal_metrics
        )
        content_lines.append(f"- 当前仍异常指标：{metric_descriptions}")
    else:
        content_lines.append("- 当前关键指标未见明显异常")

    return {
        "type": "agent",
        "content": "\n".join(content_lines),
        "analysisRecord": record,
        "recoveryVerification": verification,
    }


def evaluate_metric_recovery(metric_result: dict[str, Any]) -> dict[str, Any]:
    definitions = metric_result.get("definitions") or {}
    metric_data_results = metric_result.get("metricDataResults") or []
    selected_metrics = metric_result.get("selectedMetrics") or []

    if not metric_data_results:
        return {
            "status": "unknown",
            "summary": "缺少指标值结果，无法评估是否恢复正常",
            "usedMock": False,
            "checkedMetrics": selected_metrics,
            "abnormalMetrics": [],
            "metricDataResults": metric_data_results,
            "source": definitions.get("source") or "unknown",
        }

    used_mock = any(item.get("source") == "mock" for item in metric_data_results)
    abnormal_metrics: list[dict[str, Any]] = []
    for item in metric_data_results:
        metric_code = str(item.get("metricCode") or "").lower()
        numeric_text = item.get("latestValue") or item.get("avgValue") or ""
        try:
            numeric_value = float(str(numeric_text))
        except (TypeError, ValueError):
            numeric_value = None

        if numeric_value is None:
            continue
        if any(keyword in metric_code for keyword in ("lock", "deadlock", "wait", "slow")) and numeric_value > 0:
            abnormal_metrics.append(item)

    if used_mock:
        status = "unknown"
        summary = "指标查询已回退到 mock 数据，暂时无法据此确认是否恢复正常"
    elif abnormal_metrics:
        status = "unrecovered"
        summary = "最新关键指标仍显示锁等待/慢 SQL 类异常，暂不能判定已经恢复"
    else:
        status = "recovered"
        summary = "最新关键指标未见锁等待/慢 SQL 类异常，可初步判定已恢复"

    return {
        "status": status,
        "summary": summary,
        "usedMock": used_mock,
        "checkedMetrics": selected_metrics,
        "abnormalMetrics": abnormal_metrics,
        "metricDataResults": metric_data_results,
        "source": definitions.get("source") or "unknown",
    }
