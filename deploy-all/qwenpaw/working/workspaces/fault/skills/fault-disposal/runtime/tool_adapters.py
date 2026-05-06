from __future__ import annotations

import importlib.util
import json
import math
import os
import ssl
import sys
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib import error, request

from .models import TicketContext, ToolCallRecord


def _candidate_project_roots() -> list[Path]:
    candidates: list[Path] = []

    for env_name in (
        "QWENPAW_FAULT_DISPOSAL_PROJECT_ROOT",
        "QWENPAW_PORTAL_PROJECT_ROOT",
    ):
        raw = str((os.environ.get(env_name) or "")).strip()
        if raw:
            candidates.append(Path(raw).expanduser().resolve())

    current = Path.cwd().resolve()
    candidates.extend([current, *current.parents])

    here = Path(__file__).resolve()
    candidates.extend([*here.parents])

    deduped: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        deduped.append(candidate)
    return deduped


def _default_project_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return here.parents[6]


def _resolve_project_root() -> Path:
    for root in _candidate_project_roots():
        if (
            root
            / "src"
            / "qwenpaw"
            / "extensions"
            / "integrations"
            / "alarm_workorders"
            / "query_alarm_workorders.py"
        ).exists():
            return root
    return _default_project_root()


PROJECT_ROOT = _resolve_project_root()
CLEAR_ALARM_URL = os.getenv(
    "QWENPAW_CLEAR_ALARM_URL",
    "http://192.168.130.51:30080/resource/realalarm/clearAlarm",
).strip()
CLEAR_ALARM_AUTHORIZATION = os.getenv(
    "QWENPAW_CLEAR_ALARM_AUTHORIZATION",
    "Bearer eyJhbGciOiJIUzUxMiJ9.eyJ1c2VyX2lkIjoxLCJ1c2VyX2tleSI6ImU5ZGIyMTljLTRiNmUtNGJkNS1hYmViLWExOWEyOTQ2YzQzYSIsInVzZXJuYW1lIjoieGlhb2sifQ.EpCFu6WKBPmirfqZHkBR-qPy72p9rZ8WgIPXFuDAJzg4KhH8ou88G7NvbfjwF9BN-hnRdCeh9mKJfbeuCVMetA",
).strip()
CLEAR_ALARM_UNIQUE_ID = os.getenv(
    "QWENPAW_CLEAR_ALARM_UNIQUE_ID",
    "HN_IPM_1747382481288_1923287641253916673",
).strip()
CLEAR_ALARM_TIMEOUT_SECONDS = float(
    os.getenv("QWENPAW_CLEAR_ALARM_TIMEOUT_SECONDS", "2").strip() or "2",
)
CLEAR_ALARM_ENABLED = str(
    os.getenv("QWENPAW_CLEAR_ALARM_ENABLED", "false")
).strip().lower() in {"1", "true", "yes", "on"}


def _load_alarm_workorder_module():
    configured = str(
        os.environ.get("QWENPAW_PORTAL_ALARM_WORKORDERS_SCRIPT", "")
    ).strip()
    if configured:
        script_path = Path(configured).expanduser().resolve()
    else:
        script_path = (
            PROJECT_ROOT
            / "src"
            / "qwenpaw"
            / "extensions"
            / "integrations"
            / "alarm_workorders"
            / "query_alarm_workorders.py"
        )
    spec = importlib.util.spec_from_file_location(
        "copaw_alarm_workorders_bridge",
        script_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load alarm workorder bridge from {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def _alarm_workorder_module():
    return _load_alarm_workorder_module()


def _find_workorder(
    workorders: list[dict[str, Any]],
    *,
    title_contains: str | list[str] | tuple[str, ...],
    exclude_id: str = "",
) -> dict[str, Any] | None:
    patterns = (
        [title_contains]
        if isinstance(title_contains, str)
        else [item for item in title_contains if isinstance(item, str) and item.strip()]
    )
    for item in workorders:
        if exclude_id and str(item.get("id")) == exclude_id:
            continue
        haystacks = [
            str(item.get("title", "")),
            str(item.get("description", "")),
            str(item.get("alarmText", "")),
        ]
        if any(pattern in haystack for pattern in patterns for haystack in haystacks):
            return item
    return None


def _build_ssl_context() -> ssl.SSLContext:
    verify_ssl = os.getenv("QWENPAW_CLEAR_ALARM_VERIFY_SSL", "false").strip().lower()
    if verify_ssl in {"1", "true", "yes", "on"}:
        return ssl.create_default_context()
    return ssl._create_unverified_context()


def _normalize_authorization_header_value(value: str) -> str:
    token = str(value or "").strip()
    if not token:
        return token
    if token.lower().startswith("bearer "):
        return token
    return f"Bearer {token}"


def _is_clear_alarm_debug_enabled() -> bool:
    value = str(
        os.getenv("QWENPAW_CLEAR_ALARM_DEBUG")
        or os.getenv("QWENPAW_FAULT_DISPOSAL_DEBUG")
        or ""
    ).strip().lower()
    return value in {"1", "true", "yes", "on", "debug"}


def _mask_secret(value: str, *, prefix: int = 16, suffix: int = 8) -> str:
    secret = str(value or "").strip()
    if not secret:
        return ""
    if suffix <= 0:
        return secret[:prefix] + ("***" if len(secret) > prefix else "")
    if len(secret) <= prefix + suffix:
        return secret[:4] + "***"
    return f"{secret[:prefix]}***{secret[-suffix:]}"


def _debug_log_clear_alarm(event: str, **fields: Any) -> None:
    if not _is_clear_alarm_debug_enabled():
        return
    payload = {
        "scope": "fault_disposal.clear_alarm",
        "event": event,
        **fields,
    }
    print(
        json.dumps(payload, ensure_ascii=False, default=str),
        file=sys.stderr,
        flush=True,
    )


def _is_clear_alarm_success(status_code: int, payload: Any) -> bool:
    if status_code < 200 or status_code >= 300:
        return False
    if isinstance(payload, dict):
        code = payload.get("code")
        success = payload.get("success")
        if success is True:
            return True
        if str(code) in {"0", "200"}:
            return True
    if isinstance(payload, list):
        return True
    if isinstance(payload, str) and payload.strip():
        lowered = payload.lower()
        if "success" in lowered or "成功" in payload:
            return True
    return False


def _extract_clear_alarm_message(payload: Any, fallback: str) -> str:
    if isinstance(payload, dict):
        for key in ("msg", "message", "detail", "error"):
            value = str(payload.get(key, "")).strip()
            if value:
                return value
    if isinstance(payload, str) and payload.strip():
        return payload.strip()
    return fallback


def _to_percent_number(value: Any, fallback: float = 0.0) -> float:
    if value is None:
        return fallback
    text = str(value).strip()
    if not text:
        return fallback
    if text.endswith("%"):
        text = text[:-1]
    try:
        return round(float(text), 2)
    except (TypeError, ValueError):
        return fallback


def _to_float(value: Any, fallback: float = 0.0) -> float:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return fallback


def _timeline_value(start: float, end: float, position: int, total: int) -> float:
    if total <= 1:
        return round(end, 2)
    progress = max(0.0, min(1.0, position / (total - 1)))
    eased = 1 - pow(1 - progress, 2)
    return round(start + (end - start) * eased, 2)


def _round_metric(value: float, digits: int = 2) -> float:
    return round(float(value), digits)


class FaultDisposalToolbox:
    """Stable business tool facade for playbooks."""

    def load_related_workorders(
        self,
        context: TicketContext,
    ) -> tuple[list[dict[str, Any]], ToolCallRecord]:
        cached = context.workorders or []
        if cached:
            return cached, ToolCallRecord(
                name="get_related_workorders",
                stage="ticket-correlation",
                summary="从当前工单上下文读取同时间窗关联工单",
                request={
                    "sourceWorkorderNo": context.entry_workorder.get("workorderNo", ""),
                    "mode": "context-cache",
                },
                response={"count": len(cached), "items": cached},
            )

        result = _alarm_workorder_module().query_alarm_workorders(5)
        items = result.get("items") or []
        return items, ToolCallRecord(
            name="get_related_workorders",
            stage="ticket-correlation",
            summary="查询同时间窗待处置工单列表",
            request={
                "sourceWorkorderNo": context.entry_workorder.get("workorderNo", ""),
                "limit": 5,
            },
            response={"count": len(items), "items": items},
        )

    def get_root_cause_candidate(
        self,
        source_workorder: dict[str, Any],
        related_workorders: list[dict[str, Any]],
    ) -> tuple[dict[str, Any] | None, ToolCallRecord]:
        source_id = str(source_workorder.get("id", ""))
        title_patterns = [
            "数据库存在慢SQL",
            "数据库慢SQL",
            "慢 SQL",
            "慢SQL",
            "连接池阻塞",
            "连接池等待",
        ]
        candidate = _find_workorder(
            related_workorders,
            title_contains=title_patterns,
            exclude_id=source_id,
        )
        if not candidate:
            for item in related_workorders:
                if source_id and str(item.get("id")) == source_id:
                    continue
                if str(item.get("speciality", "")) != str(source_workorder.get("speciality", "")):
                    continue
                candidate = item
                break
        return candidate, ToolCallRecord(
            name="match_root_cause_ticket",
            stage="root-cause-correlation",
            summary="按标题和时间窗匹配根因候选工单",
            request={
                "sourceWorkorderNo": source_workorder.get("workorderNo", ""),
                "candidateCount": len(related_workorders),
                "titlePatterns": title_patterns,
            },
            response={"matched": bool(candidate), "workorder": candidate},
        )

    def get_application_timeout_snapshot(
        self,
        source_workorder: dict[str, Any],
    ) -> tuple[dict[str, Any], ToolCallRecord]:
        payload = {
            "timeWindow": {
                "start": source_workorder.get("eventTime", ""),
                "durationMinutes": 5,
            },
            "instance": source_workorder.get("locateName", ""),
            "deviceName": source_workorder.get("deviceName", ""),
            "manageIp": source_workorder.get("manageIp", ""),
            "gatewayRttMs": {"min": 4, "max": 8},
            "apiLatency": {"p50": 180, "p95": 8600, "p99": 11800},
            "timeoutRate": "18.7%",
            "jvmCpuUsage": "52%",
            "fullGcCount": 0,
            "tomcatThreads": {"active": 182, "max": 200},
            "dbConnectionPool": {
                "usage": "96%",
                "waitP95Ms": 6900,
                "waitQueueSize": 37,
            },
        }
        return payload, ToolCallRecord(
            name="get_app_timeout_metrics",
            stage="application-analysis",
            summary="查询接口时延、JVM、线程池和连接池指标",
            request={
                "instance": source_workorder.get("locateName", ""),
                "manageIp": source_workorder.get("manageIp", ""),
                "windowMinutes": 5,
            },
            response=payload,
        )

    def get_related_slow_sql_snapshot(
        self,
        root_cause_workorder: dict[str, Any],
    ) -> tuple[dict[str, Any], ToolCallRecord]:
        numeric_suffix = "".join(filter(str.isdigit, root_cause_workorder.get("workorderNo", "")))
        payload = {
            "deviceName": root_cause_workorder.get("deviceName", ""),
            "manageIp": root_cause_workorder.get("manageIp", ""),
            "locateName": root_cause_workorder.get("locateName", ""),
            "sqlId": f"SQL-{numeric_suffix[-6:] or '301441'}",
            "sessionId": f"SID-{numeric_suffix[-4:] or '1441'}",
            "targetSummary": "数据库核心业务查询慢 SQL 会话",
            "executionTimeSeconds": 12.4,
            "lockWaitSeconds": 8.1,
            "activeSessions": 143,
            "occupiedConnections": 37,
            "dbLatencyP95Ms": 4300,
        }
        return payload, ToolCallRecord(
            name="get_slow_sql_candidates",
            stage="database-analysis",
            summary="查询慢SQL、锁等待和会话占用情况",
            request={
                "workorderNo": root_cause_workorder.get("workorderNo", ""),
                "instance": root_cause_workorder.get("locateName", ""),
            },
            response=payload,
        )

    def execute_kill_slow_sql(
        self,
        operation_params: dict[str, Any],
    ) -> tuple[dict[str, Any], ToolCallRecord]:
        payload = {
            "success": True,
            "simulated": True,
            "action": "kill-slow-sql",
            "sqlId": operation_params.get("sqlId", ""),
            "sessionId": operation_params.get("sessionId", ""),
            "message": "当前为模拟处置：已按演示流程生成慢SQL终止后的恢复结果，尚未接入真实终止接口。",
            "recovery": {
                "apiP95Ms": 620,
                "dbP95Ms": 43,
                "connectionPoolUsage": "58%",
                "timeoutRate": "0.4%",
            },
        }
        return payload, ToolCallRecord(
            name="kill_slow_sql_session",
            stage="action-execution",
            summary="执行慢SQL终止动作并返回恢复指标",
            request=operation_params,
            response=payload,
        )

    def clear_related_alarms(
        self,
        operation_params: dict[str, Any],
    ) -> tuple[dict[str, Any], ToolCallRecord]:
        alarm_unique_id = CLEAR_ALARM_UNIQUE_ID
        authorization_value = _normalize_authorization_header_value(
            CLEAR_ALARM_AUTHORIZATION,
        )
        request_payload = (
            [{"alarmuniqueid": alarm_unique_id}] if alarm_unique_id else []
        )

        if not request_payload:
            _debug_log_clear_alarm(
                "skip-no-alarm-id",
                envVar="QWENPAW_CLEAR_ALARM_AUTHORIZATION",
                alarmUniqueId=alarm_unique_id,
                clearAlarmUrl=CLEAR_ALARM_URL,
            )
            payload = {
                "attempted": False,
                "success": False,
                "alarmUniqueId": "",
                "message": "未找到可清除的告警标识，已跳过告警闭环调用。",
                "statusCode": None,
                "response": None,
            }
            return payload, ToolCallRecord(
                name="clear_alarm",
                stage="alarm-clearance",
                summary="调用清除告警接口关闭已恢复告警",
                request={"url": CLEAR_ALARM_URL, "payload": request_payload},
                response=payload,
            )

        if not CLEAR_ALARM_ENABLED:
            payload = {
                "attempted": False,
                "success": False,
                "alarmUniqueId": alarm_unique_id,
                "message": "当前为模拟处置，未调用外部告警清除接口。",
                "statusCode": None,
                "response": None,
            }
            return payload, ToolCallRecord(
                name="clear_alarm",
                stage="alarm-clearance",
                summary="调用清除告警接口关闭已恢复告警",
                request={
                    "url": CLEAR_ALARM_URL,
                    "payload": request_payload,
                    "enabled": CLEAR_ALARM_ENABLED,
                },
                response=payload,
            )

        raw_response: Any = None
        status_code: int | None = None
        try:
            body = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
            _debug_log_clear_alarm(
                "request",
                envVar="QWENPAW_CLEAR_ALARM_AUTHORIZATION",
                clearAlarmUrl=CLEAR_ALARM_URL,
                alarmUniqueId=alarm_unique_id,
                authorizationPresent=bool(CLEAR_ALARM_AUTHORIZATION.strip()),
                authorizationMasked=_mask_secret(authorization_value),
                authorizationHasBearer=authorization_value.lower().startswith("bearer "),
                headerNames=[
                    "Content-Type",
                    "Accept",
                    "Authorization",
                ],
                requestPayload=request_payload,
            )
            req = request.Request(
                CLEAR_ALARM_URL,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Authorization": authorization_value,
                },
                method="POST",
            )
            with request.urlopen(
                req,
                timeout=CLEAR_ALARM_TIMEOUT_SECONDS,
                context=_build_ssl_context(),
            ) as response:
                status_code = getattr(response, "status", response.getcode())
                response_text = response.read().decode("utf-8", errors="replace")
                try:
                    raw_response = json.loads(response_text) if response_text.strip() else {}
                except json.JSONDecodeError:
                    raw_response = response_text
                _debug_log_clear_alarm(
                    "response",
                    statusCode=status_code,
                    success=_is_clear_alarm_success(int(status_code or 0), raw_response),
                    responsePreview=_mask_secret(str(raw_response), prefix=240, suffix=0),
                )
        except error.HTTPError as exc:
            status_code = exc.code
            response_text = exc.read().decode("utf-8", errors="replace")
            try:
                raw_response = json.loads(response_text) if response_text.strip() else {}
            except json.JSONDecodeError:
                raw_response = response_text or str(exc)
            _debug_log_clear_alarm(
                "http-error",
                statusCode=status_code,
                reason=str(exc),
                responsePreview=_mask_secret(str(raw_response), prefix=240, suffix=0),
            )
        except Exception as exc:  # pragma: no cover - environment/network dependent
            raw_response = str(exc)
            _debug_log_clear_alarm(
                "exception",
                reason=str(exc),
            )

        success = _is_clear_alarm_success(int(status_code or 0), raw_response)
        payload = {
            "attempted": True,
            "success": success,
            "alarmUniqueId": alarm_unique_id,
            "statusCode": status_code,
            "response": raw_response,
            "message": _extract_clear_alarm_message(
                raw_response,
                "告警清除请求执行完成。" if success else "告警清除请求未返回成功结果。",
            ),
        }
        return payload, ToolCallRecord(
            name="clear_alarm",
            stage="alarm-clearance",
            summary="调用清除告警接口关闭已恢复告警",
            request={"url": CLEAR_ALARM_URL, "payload": request_payload},
            response=payload,
        )

    def collect_recovery_verification(
        self,
        operation_params: dict[str, Any],
        recovery: dict[str, Any],
    ) -> tuple[dict[str, Any], ToolCallRecord]:
        baseline = operation_params.get("preRecoverySnapshot") or {}
        before_snapshot = {
            "capturedAt": str(
                baseline.get("capturedAt")
                or datetime.now().replace(second=0, microsecond=0).isoformat(timespec="seconds")
            ),
            "windowSeconds": int(baseline.get("windowSeconds") or 30),
            "apiP95Ms": _to_float(baseline.get("apiP95Ms"), 8600),
            "dbP95Ms": _to_float(baseline.get("dbP95Ms"), 4300),
            "connectionPoolUsagePct": _to_percent_number(
                baseline.get("connectionPoolUsagePct"),
                _to_percent_number(baseline.get("connectionPoolUsage"), 96),
            ),
            "timeoutRatePct": _to_percent_number(
                baseline.get("timeoutRatePct"),
                _to_percent_number(baseline.get("timeoutRate"), 18.7),
            ),
        }

        after_snapshot = {
            "capturedAt": datetime.now().replace(microsecond=0).isoformat(timespec="seconds"),
            "windowSeconds": 30,
            "apiP95Ms": max(280.0, _to_float(recovery.get("apiP95Ms"), 620) - 110.0),
            "dbP95Ms": max(18.0, _to_float(recovery.get("dbP95Ms"), 43) - 7.0),
            "connectionPoolUsagePct": max(
                28.0,
                _to_percent_number(recovery.get("connectionPoolUsage"), 58) - 4.0,
            ),
            "timeoutRatePct": max(
                0.08,
                _to_percent_number(recovery.get("timeoutRate"), 0.4) - 0.12,
            ),
        }

        now = datetime.now().replace(microsecond=0)
        action_time = now
        before_offsets = [-6, -5, -4, -3, -2, -1, 0]
        after_offsets = list(range(1, 21))
        timeline: list[dict[str, Any]] = []
        fault_marker_time = str(before_snapshot.get("capturedAt") or "").strip()
        action_marker_time = action_time.strftime("%H:%M:%S")
        fault_marker_label = (
            f"故障发生 {fault_marker_time[-8:]}"
            if fault_marker_time and len(fault_marker_time) >= 8
            else "故障发生"
        )
        action_marker_label = f"执行处置 {action_marker_time}"

        for index, offset in enumerate(before_offsets):
            sample_time = action_time + timedelta(seconds=offset)
            axis_label = (
                action_time.strftime("%H:%M:%S")
                if offset == 0
                else ("\u200b" * (index + 1))
            )
            timeline.append(
                {
                    "timestamp": sample_time.isoformat(timespec="seconds"),
                    "label": axis_label,
                    "phase": "fault" if index == 0 else "before" if offset < 0 else "action",
                    "apiP95Ms": _round_metric(_timeline_value(
                        before_snapshot["apiP95Ms"] * 1.06,
                        before_snapshot["apiP95Ms"],
                        index,
                        len(before_offsets),
                    ), 1),
                    "dbP95Ms": _round_metric(_timeline_value(
                        before_snapshot["dbP95Ms"] * 1.08,
                        before_snapshot["dbP95Ms"],
                        index,
                        len(before_offsets),
                    ), 1),
                    "connectionPoolUsagePct": _round_metric(_timeline_value(
                        min(99.0, before_snapshot["connectionPoolUsagePct"] + 2.0),
                        before_snapshot["connectionPoolUsagePct"],
                        index,
                        len(before_offsets),
                    ), 2),
                    "timeoutRatePct": _round_metric(_timeline_value(
                        before_snapshot["timeoutRatePct"] + 1.1,
                        before_snapshot["timeoutRatePct"],
                        index,
                        len(before_offsets),
                    ), 2),
                }
            )

        for index, offset in enumerate(after_offsets, start=1):
            sample_time = action_time + timedelta(seconds=offset)
            progress = index / max(1, len(after_offsets))
            decay = max(0.12, 1 - progress)
            api_wave = math.sin(index * 0.72) * 34 * decay
            db_wave = math.cos(index * 0.64) * 5.2 * decay
            pool_wave = math.sin(index * 0.58) * 2.6 * decay
            timeout_wave = math.cos(index * 0.49) * 0.22 * decay
            timeline.append(
                {
                    "timestamp": sample_time.isoformat(timespec="seconds"),
                    "label": sample_time.strftime("%H:%M:%S"),
                    "phase": "after",
                    "apiP95Ms": _round_metric(max(260.0, _timeline_value(
                        _to_float(recovery.get("apiP95Ms"), 620),
                        after_snapshot["apiP95Ms"],
                        index,
                        len(after_offsets),
                    ) + api_wave), 1),
                    "dbP95Ms": _round_metric(max(18.0, _timeline_value(
                        _to_float(recovery.get("dbP95Ms"), 43),
                        after_snapshot["dbP95Ms"],
                        index,
                        len(after_offsets),
                    ) + db_wave), 1),
                    "connectionPoolUsagePct": _round_metric(max(24.0, _timeline_value(
                        _to_percent_number(recovery.get("connectionPoolUsage"), 58),
                        after_snapshot["connectionPoolUsagePct"],
                        index,
                        len(after_offsets),
                    ) + pool_wave), 2),
                    "timeoutRatePct": _round_metric(max(0.05, _timeline_value(
                        _to_percent_number(recovery.get("timeoutRate"), 0.4),
                        after_snapshot["timeoutRatePct"],
                        index,
                        len(after_offsets),
                    ) + timeout_wave), 2),
                }
            )

        payload = {
            "mode": "mock-stream",
            "transport": "sse",
            "provider": "mock-recovery-metrics-collector",
            "collector": "application-recovery-verification",
            "phaseMarkerLabel": action_marker_label,
            "faultMarkerLabel": fault_marker_label,
            "samplingIntervalSeconds": 1,
            "streamWindowSeconds": 26,
            "streamMode": "append-window",
            "mockPlaybackIntervalMs": 900,
            "mockPlaybackBatchSize": 1,
            "initialVisiblePoints": min(len(timeline), len(before_offsets) + 2),
            "description": (
                "当前返回的是按实时采集协议预留的 mock 趋势数据。"
                "后续接入真实长连接指标流时，只需替换采集实现，无需改动前端渲染协议。"
            ),
            "beforeSnapshot": before_snapshot,
            "afterSnapshot": after_snapshot,
            "timeline": timeline,
        }
        return payload, ToolCallRecord(
            name="collect_recovery_verification",
            stage="recovery-verification",
            summary="采集慢SQL处置前后应用与数据库恢复趋势",
            request={
                "sessionId": operation_params.get("sessionId", ""),
                "sqlId": operation_params.get("sqlId", ""),
                "streamMode": payload["mode"],
                "transport": payload["transport"],
                "windowSeconds": after_snapshot["windowSeconds"],
            },
            response=payload,
        )
