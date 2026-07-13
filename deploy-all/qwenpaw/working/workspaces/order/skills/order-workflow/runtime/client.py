#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime
import base64
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlencode
import urllib.error
import urllib.request
import ssl


def _load_env_file(path: Path) -> None:
    """把 .env 风格文件的 KEY=VALUE 注入 os.environ（不覆盖已有值）。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def _load_skill_env() -> None:
    """加载配置，优先级：进程环境变量 > 共享 secrets/inoe.env > 技能 .env。

    纯标准库实现（不依赖 python-dotenv）。脚本会自己向上找到工作根的
    `secrets/inoe.env` 加载，所以直接 `python scripts/order_workflow.py ...`
    就能读到 ORDER_* 配置，无需手动传环境变量、也无需技能目录下的 .env。
    """
    here = Path(__file__).resolve()
    # 1) 共享 secrets/inoe.env（与后端注入的是同一份）
    for parent in here.parents:
        shared = parent / "secrets" / "inoe.env"
        if shared.exists():
            _load_env_file(shared)
            break
        if (parent / "workspaces").is_dir() and (parent / "secrets").is_dir():
            break  # 到工作根仍没有就停，别一路找到文件系统根
    # 2) 技能目录自身 .env（可选覆盖，最低优先级）
    env_file = here.parents[1] / ".env"
    if env_file.exists():
        _load_env_file(env_file)


_load_skill_env()


def _load_notification_setting_helpers():
    current_path = Path(__file__).resolve()
    for parent in current_path.parents:
        helper_dir = parent / "extensions" / "notifications"
        if helper_dir.is_dir() and (parent / "workspaces").is_dir():
            if str(helper_dir) not in sys.path:
                sys.path.insert(0, str(helper_dir))
            from notification_settings import (
                resolve_notification_bool,
                resolve_notification_int,
                resolve_notification_text,
            )

            return (
                resolve_notification_bool,
                resolve_notification_int,
                resolve_notification_text,
            )
    raise RuntimeError("无法定位 working/extensions/notifications/notification_settings.py")


(
    _RESOLVE_NOTIFICATION_BOOL,
    _RESOLVE_NOTIFICATION_INT,
    _RESOLVE_NOTIFICATION_TEXT,
) = _load_notification_setting_helpers()


@dataclass(slots=True)
class OrderWorkflowConfig:
    base_url: str
    authorization: str
    cookie: str = ""
    serial_no: str = ""
    timeout_seconds: int = 20
    verify_ssl: bool = True
    enable_curl_fallback: bool = False
    extra_headers: dict[str, str] | None = None
    create_notify_push_url: str = ""
    create_notify_webhook_url: str = ""
    create_notify_dingtalk_webhook_url: str = ""
    create_notify_dingtalk_secret: str = ""
    create_notify_feishu_webhook_url: str = ""
    create_notify_feishu_secret: str = ""
    create_notify_timeout_seconds: int = 8
    create_notify_mention_all: bool = False

    @classmethod
    def from_env(cls) -> "OrderWorkflowConfig":
        start_path = Path(__file__).resolve()
        base_url = (
            os.getenv("ORDER_API_BASE_URL", "").strip()
            or os.getenv("INOE_API_BASE_URL", "").strip()
            or "http://gateway:8080"
        )
        authorization = (
            os.getenv("ORDER_AUTHORIZATION", "").strip()
            or os.getenv("INOE_API_TOKEN", "").strip()
        )
        cookie = os.getenv("ORDER_COOKIE", "").strip()
        serial_no = os.getenv("ORDER_SERIAL_NO", "").strip()
        timeout_seconds = int(float(os.getenv("ORDER_TIMEOUT_SECONDS", "20").strip() or "20"))
        verify_ssl = os.getenv("ORDER_VERIFY_SSL", "true").strip().lower() not in {
            "0",
            "false",
            "no",
        }
        enable_curl_fallback = os.getenv(
            "ORDER_ENABLE_CURL_FALLBACK",
            "false",
        ).strip().lower() in {"1", "true", "yes"}

        extra_headers: dict[str, str] | None = None
        raw_extra_headers = os.getenv("ORDER_EXTRA_HEADERS", "").strip()
        if raw_extra_headers:
            parsed = json.loads(raw_extra_headers)
            if isinstance(parsed, dict):
                extra_headers = {
                    str(key): str(value)
                    for key, value in parsed.items()
                    if value is not None
                }

        create_notify_push_url = _RESOLVE_NOTIFICATION_TEXT(
            "order_workflow",
            "push_url",
            env_keys=["ORDER_CREATE_NOTIFY_PUSH_URL"],
            start_path=start_path,
        )
        create_notify_webhook_url = _RESOLVE_NOTIFICATION_TEXT(
            "order_workflow",
            "push_url",
            env_keys=["ORDER_CREATE_NOTIFY_WEBHOOK_URL"],
            start_path=start_path,
        )
        create_notify_dingtalk_webhook_url = _RESOLVE_NOTIFICATION_TEXT(
            "order_workflow",
            "dingtalk_webhook_url",
            env_keys=["ORDER_CREATE_NOTIFY_DINGTALK_WEBHOOK_URL"],
            start_path=start_path,
        )
        create_notify_dingtalk_secret = _RESOLVE_NOTIFICATION_TEXT(
            "order_workflow",
            "dingtalk_secret",
            env_keys=["ORDER_CREATE_NOTIFY_DINGTALK_SECRET"],
            start_path=start_path,
        )
        create_notify_feishu_webhook_url = _RESOLVE_NOTIFICATION_TEXT(
            "order_workflow",
            "feishu_webhook_url",
            env_keys=["ORDER_CREATE_NOTIFY_FEISHU_WEBHOOK_URL"],
            start_path=start_path,
        )
        create_notify_feishu_secret = _RESOLVE_NOTIFICATION_TEXT(
            "order_workflow",
            "feishu_secret",
            env_keys=["ORDER_CREATE_NOTIFY_FEISHU_SECRET"],
            start_path=start_path,
        )
        create_notify_timeout_seconds = _RESOLVE_NOTIFICATION_INT(
            "order_workflow",
            "timeout_seconds",
            env_keys=["ORDER_CREATE_NOTIFY_TIMEOUT_SECONDS"],
            start_path=start_path,
            default=8,
        )
        create_notify_mention_all = _RESOLVE_NOTIFICATION_BOOL(
            "order_workflow",
            "mention_all",
            env_keys=["ORDER_CREATE_NOTIFY_MENTION_ALL"],
            start_path=start_path,
            default=False,
        )

        return cls(
            base_url=base_url.rstrip("/"),
            authorization=authorization,
            cookie=cookie,
            serial_no=serial_no,
            timeout_seconds=timeout_seconds,
            verify_ssl=verify_ssl,
            enable_curl_fallback=enable_curl_fallback,
            extra_headers=extra_headers,
            create_notify_push_url=create_notify_push_url,
            create_notify_webhook_url=create_notify_webhook_url,
            create_notify_dingtalk_webhook_url=create_notify_dingtalk_webhook_url,
            create_notify_dingtalk_secret=create_notify_dingtalk_secret,
            create_notify_feishu_webhook_url=create_notify_feishu_webhook_url,
            create_notify_feishu_secret=create_notify_feishu_secret,
            create_notify_timeout_seconds=create_notify_timeout_seconds,
            create_notify_mention_all=create_notify_mention_all,
        )


class OrderWorkflowClient:
    DEFAULT_BATCH_SIZE = 100

    # inoe-ferry 工单模块统一前缀；base url 仍由配置决定，这里只固定路径。
    BASE_PATH = "/api/v1/work-order"
    STATS_PATH = f"{BASE_PATH}/getWorkOrder"
    CREATE_FAULT_PATH = f"{BASE_PATH}/faultManualWorkorders"
    LIST_PATH = f"{BASE_PATH}/list"
    DETAIL_PATH = f"{BASE_PATH}/process-structure"

    # 列表 classify 口径：1=待办 / 5=已办理（见接口文档）。
    CLASSIFY_TODO = 1
    CLASSIFY_FINISHED = 5

    def __init__(self, config: OrderWorkflowConfig | None = None) -> None:
        self.config = config or OrderWorkflowConfig.from_env()

    def get_workorder_stats(
        self,
        *,
        start_time: str = "",
        end_time: str = "",
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
        payload = self._request("GET", self.STATS_PATH, params=params or None)
        self._require_ok(payload, self.config.base_url)
        return payload

    def create_disposal_workorder(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized_payload = self._normalize_create_payload(payload)
        response_payload = self._request(
            "POST",
            self.CREATE_FAULT_PATH,
            json_body=normalized_payload,
        )
        self._require_ok(response_payload, self.config.base_url)
        response_payload["notification"] = self._notify_create_success(
            response_payload=response_payload,
            request_payload=normalized_payload,
        )
        return response_payload

    def list_todo_workorders(
        self,
        *,
        page_num: int = 1,
        page_size: int = 10,
        begin_time: str = "",
        end_time: str = "",
        title: str = "",
        fetch_all: bool = False,
    ) -> dict[str, Any]:
        return self._list_workorders(
            classify=self.CLASSIFY_TODO,
            page_num=page_num,
            page_size=page_size,
            begin_time=begin_time,
            end_time=end_time,
            title=title,
            fetch_all=fetch_all,
        )

    def list_finished_workorders(
        self,
        *,
        page_num: int = 1,
        page_size: int = 10,
        begin_time: str = "",
        end_time: str = "",
        title: str = "",
        fetch_all: bool = False,
    ) -> dict[str, Any]:
        return self._list_workorders(
            classify=self.CLASSIFY_FINISHED,
            page_num=page_num,
            page_size=page_size,
            begin_time=begin_time,
            end_time=end_time,
            title=title,
            fetch_all=fetch_all,
        )

    def get_workorder_detail(
        self,
        *,
        process_id: str,
        work_order_id: str,
    ) -> dict[str, Any]:
        payload = self._request(
            "GET",
            self.DETAIL_PATH,
            params={
                "processId": process_id,
                "workOrderId": work_order_id or "0",
            },
        )
        self._require_ok(payload, self.config.base_url)
        return payload

    @staticmethod
    def _build_list_params(
        *,
        classify: int,
        page: int,
        per_page: int,
        begin_time: str = "",
        end_time: str = "",
        title: str = "",
        is_end: str = "",
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "classify": classify,
            "page": page,
            "per_page": per_page,
        }
        if title:
            params["title"] = title
        if begin_time:
            params["startTime"] = begin_time
        if end_time:
            params["endTime"] = end_time
        if is_end != "":
            params["isEnd"] = is_end
        return params

    @staticmethod
    def _require_ok(payload: dict[str, Any], base_url: str = "") -> None:
        """ferry HTTP 恒 200，业务结果看 code；非 200 抛出 msg。

        附带请求的网关地址，方便区分“地址/服务未就绪”与“本地缺配置”。
        """
        if not isinstance(payload, dict):
            return
        code = payload.get("code")
        if code is None:
            # ferry 的每个业务响应都带 code；一个没有 code 的 JSON 体
            # （例如配错网关时上游应答 200 {"msg":""}）不是 ferry 的响应。
            # 以前这里静默放行，随后被归一化成"0 条数据"——把配置错误
            # 伪装成了"暂无数据"。诚实报错，别装作查到了空结果。
            message = "工单接口未返回业务码，疑似网关未代理 ferry 服务"
            if base_url:
                message = (
                    f"{message}（工单接口地址 {base_url}，"
                    f"请确认该地址是 ferry 服务的正确入口）"
                )
            raise RuntimeError(message)
        try:
            code_int = int(code)
        except (TypeError, ValueError):
            return
        if code_int != 200:
            message = (
                str(payload.get("msg") or "").strip()
                or f"接口返回业务失败 (code={code_int})"
            )
            if base_url:
                message = (
                    f"{message}（工单接口地址 {base_url}，"
                    f"请确认网关/ferry 服务地址是否正确；本地无需 .env）"
                )
            raise RuntimeError(message)

    @staticmethod
    def _normalize_list_payload(payload: dict[str, Any]) -> dict[str, Any]:
        """把 ferry PaginatorResult 归一化成 formatter 现有契约。"""
        data = payload.get("data")
        if not isinstance(data, dict):
            data = {}
        rows = data.get("data")
        if not isinstance(rows, list):
            rows = []
        total = data.get("total_count")
        if total is None:
            total = len(rows)
        return {
            "total": int(total or 0),
            "rows": rows,
            "pageNum": int(data.get("page") or 1),
            "pageSize": int(data.get("per_page") or (len(rows) or 10)),
            "totalPage": int(data.get("total_page") or 0),
            "fetchedAll": False,
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.config.base_url:
            raise RuntimeError("ORDER_API_BASE_URL is required")
        if not self.config.authorization:
            raise RuntimeError("ORDER_AUTHORIZATION is required")

        url = f"{self.config.base_url}{path}"
        if params:
            url = f"{url}?{urlencode(params, doseq=True)}"
        headers = self._build_headers()
        data: bytes | None = None
        if json_body is not None:
            data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            headers = {**headers, "Content-Type": "application/json;charset=utf-8"}

        try:
            return self._urlopen_json(method.upper(), url, headers, data)
        except urllib.error.HTTPError as exc:
            body = self._read_error_body(exc)
            if self.config.enable_curl_fallback:
                return self._curl_request(
                    method=method, url=url, headers=headers,
                    params=None, json_body=json_body,
                )
            try:
                return json.loads(body)
            except (ValueError, TypeError):
                raise RuntimeError(
                    f"HTTP {exc.code}: {body[:300] or exc.reason}"
                ) from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            if self.config.enable_curl_fallback:
                return self._curl_request(
                    method=method, url=url, headers=headers,
                    params=None, json_body=json_body,
                )
            raise RuntimeError(self._format_request_error(exc)) from exc
        except ValueError as exc:
            raise RuntimeError(f"Invalid JSON response from {url}") from exc

    def _ssl_context(self) -> "ssl.SSLContext | None":
        if self.config.verify_ssl:
            return None
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    def _urlopen_json(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        data: bytes | None,
    ) -> dict[str, Any]:
        req = urllib.request.Request(
            url, data=data, headers=headers, method=method
        )
        with urllib.request.urlopen(
            req,
            timeout=self.config.timeout_seconds,
            context=self._ssl_context(),
        ) as resp:
            body = resp.read().decode("utf-8", "replace")
        return json.loads(body or "{}")

    @staticmethod
    def _read_error_body(exc: "urllib.error.HTTPError") -> str:
        try:
            return exc.read().decode("utf-8", "replace")
        except Exception:
            return ""

    def _post_json(
        self, url: str, payload: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(
            req, timeout=timeout, context=self._ssl_context()
        ) as resp:
            body = resp.read().decode("utf-8", "replace")
        try:
            return json.loads(body or "{}")
        except ValueError:
            return {}

    def _list_workorders(
        self,
        *,
        classify: int,
        page_num: int,
        page_size: int,
        begin_time: str = "",
        end_time: str = "",
        title: str = "",
        is_end: str = "",
        fetch_all: bool = False,
    ) -> dict[str, Any]:
        effective_page_size = page_size if page_size > 0 else self.DEFAULT_BATCH_SIZE
        first_payload = self._request(
            "GET",
            self.LIST_PATH,
            params=self._build_list_params(
                classify=classify,
                page=page_num,
                per_page=effective_page_size,
                begin_time=begin_time,
                end_time=end_time,
                title=title,
                is_end=is_end,
            ),
        )
        self._require_ok(first_payload, self.config.base_url)
        normalized = self._normalize_list_payload(first_payload)
        if not fetch_all:
            return normalized

        rows = list(normalized.get("rows") or [])
        total = int(normalized.get("total") or len(rows))
        if total <= len(rows):
            normalized["rows"] = rows
            normalized["fetchedAll"] = True
            return normalized

        next_page = page_num + 1
        while len(rows) < total:
            payload = self._request(
                "GET",
                self.LIST_PATH,
                params=self._build_list_params(
                    classify=classify,
                    page=next_page,
                    per_page=effective_page_size,
                    begin_time=begin_time,
                    end_time=end_time,
                    title=title,
                    is_end=is_end,
                ),
            )
            self._require_ok(payload, self.config.base_url)
            batch = list(self._normalize_list_payload(payload).get("rows") or [])
            if not batch:
                break
            rows.extend(batch)
            next_page += 1

        normalized["rows"] = rows[:total]
        normalized["pageNum"] = page_num
        normalized["pageSize"] = effective_page_size
        normalized["fetchedAll"] = len(normalized["rows"]) >= total
        return normalized

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "Authorization": self.config.authorization,
            "SerialNo": self.config.serial_no or self._generate_serial_no(),
        }
        if self.config.cookie:
            headers["Cookie"] = self.config.cookie
        if self.config.extra_headers:
            headers.update(self.config.extra_headers)
        return headers

    @staticmethod
    def _generate_serial_no() -> str:
        return uuid.uuid4().hex

    @classmethod
    def _normalize_create_payload(cls, payload: dict[str, Any]) -> dict[str, Any]:
        """归一化为「故障处置」流程模板字段。

        form_data 的 key 必须与模板字段 model 对齐，前端才能正常回显：
        alarmSeq/alarmTitle/neTime/sendTim/alarmSeverity(中文)/isClear(中文)/
        neName/neAlias/neIp/vendor/clearuser/clearanceCollectTime/
        additionalText/alarmLocation/suggestions。
        """
        if not isinstance(payload, dict):
            raise RuntimeError("create payload must be a JSON object")

        chat_id = cls._pick_text(
            payload, "chatId", "sessionId", "conversationId"
        ) or str(uuid.uuid4())
        analysis_payload = (
            payload.get("analysis")
            if isinstance(payload.get("analysis"), dict)
            else {}
        )
        ticket_payload = (
            payload.get("ticket")
            if isinstance(payload.get("ticket"), dict)
            else {}
        )

        ne_name = cls._pick_text(
            payload, "neName", "deviceName", "设备名称", "name", "hostname",
            nested=("alarm", "neName"), nested_alt=("alarm", "deviceName"),
        )
        ne_ip = cls._pick_text(
            payload, "neIp", "manageIp", "ip", "deviceIp", "设备IP", "hostIp",
            nested=("alarm", "neIp"), nested_alt=("alarm", "manageIp"),
        )
        alarm_title = cls._pick_text(
            payload, "alarmTitle", "title", "告警标题", "标题",
            nested=("alarm", "alarmTitle"), nested_alt=("alarm", "title"),
        ) or cls._pick_text(payload, nested=("ticket", "title"))
        suggestions_text = cls._pick_text(
            payload, "suggestions", "处置建议", "处置意见", "advice", "comment",
            nested=("analysis", "summary"),
        ) or cls._join_suggestions(analysis_payload.get("suggestions"))

        ne_ip = ne_ip or cls._extract_ip(alarm_title) or cls._extract_ip(
            suggestions_text
        )
        if not alarm_title:
            alarm_title = (suggestions_text or ne_name or ne_ip or "").strip()
        if not alarm_title:
            raise RuntimeError(
                "创建工单至少需要提供告警标题（或处置意见），"
                "以及设备名称、设备IP 中的至少一个。"
            )
        if not (ne_name or ne_ip):
            raise RuntimeError("创建工单至少需要设备名称、设备IP 中的至少一个。")

        severity_cn = cls._to_alarm_severity(
            cls._pick_text(
                payload, "alarmSeverity", "level", "priority", "severity",
                "告警级别", "级别", "优先级",
                nested=("alarm", "alarmSeverity"),
                nested_alt=("ticket", "priority"),
            )
        )
        is_clear = cls._to_is_clear(
            cls._pick_text(
                payload, "isClear", "status", "告警状态",
                nested=("alarm", "isClear"), nested_alt=("alarm", "status"),
            )
        )
        ne_time = cls._resolve_event_time(
            cls._pick_text(
                payload, "neTime", "eventTime", "发生时间", "alarmTime",
                "occurTime", nested=("alarm", "neTime"),
            )
        )
        send_tim = cls._resolve_event_time(
            cls._pick_text(payload, "sendTim", "sendTime", "发现时间"),
            default=ne_time,
        )
        metric_type = cls._pick_text(
            payload, "metricType", "resourceType", "ciType"
        ) or cls._infer_metric_type(
            " ".join([alarm_title, suggestions_text, ne_name]).strip()
        )
        alarm_id = cls._pick_text(
            payload, "alarmId", nested=("alarm", "alarmId")
        ) or cls._generate_alarm_id()
        res_id = cls._pick_text(
            payload, "resId", "resourceId", "assetId"
        ) or ne_name or ne_ip or alarm_id
        priority = ticket_payload.get("priority") or cls._severity_to_priority(
            severity_cn
        )

        def field(*keys: str, alarm_key: str = "") -> str:
            nested = ("alarm", alarm_key) if alarm_key else None
            return cls._pick_text(payload, *keys, nested=nested)

        return {
            "chatId": chat_id,
            "resId": res_id,
            "metricType": metric_type,
            "alarm": {
                "alarmId": alarm_id,
                "alarmSeq": field("alarmSeq", "告警流水", "seq", "流水",
                                  alarm_key="alarmSeq"),
                "alarmTitle": alarm_title,
                "neTime": ne_time,
                "sendTim": send_tim,
                "alarmSeverity": severity_cn,
                "isClear": is_clear,
                "neName": ne_name,
                "neAlias": field("neAlias", "设备别名", "alias",
                                 alarm_key="neAlias"),
                "neIp": ne_ip,
                "vendor": field("vendor", "厂家", "设备类型", "厂商",
                                "manufacturer", alarm_key="vendor"),
                "clearuser": field("clearuser", "告警清除人",
                                   alarm_key="clearuser"),
                "clearanceCollectTime": field(
                    "clearanceCollectTime", "告警清除时间",
                    alarm_key="clearanceCollectTime"),
                "additionalText": field(
                    "additionalText", "告警原始报文", "原始报文", "rawMessage",
                    alarm_key="additionalText"),
                "alarmLocation": field("alarmLocation", "定位信息", "location",
                                       alarm_key="alarmLocation"),
            },
            "analysis": {
                "summary": analysis_payload.get("summary") or "",
                "rootCause": analysis_payload.get("rootCause") or "",
                "suggestions": cls._split_suggestions(
                    analysis_payload.get("suggestions") or suggestions_text
                ),
            },
            "ticket": {
                "title": ticket_payload.get("title") or alarm_title,
                "priority": priority,
                "category": ticket_payload.get("category")
                or cls._infer_category(metric_type),
                "source": ticket_payload.get("source") or "portal-order-agent",
                "externalSystem": ticket_payload.get("externalSystem")
                or "manual-workorder",
            },
        }

    _SEVERITY_CN: dict[str, str] = {
        "严重": "严重", "critical": "严重", "p1": "严重", "紧急": "严重",
        "高危": "严重", "一级": "严重",
        "主要": "主要", "major": "主要", "p2": "主要", "重要": "主要",
        "二级": "主要",
        "普通": "普通", "minor": "普通", "p3": "普通", "一般": "普通",
        "三级": "普通",
        "预警": "预警", "warning": "预警", "p4": "预警", "四级": "预警",
    }

    @classmethod
    def _to_alarm_severity(cls, raw: str) -> str:
        """输入级别/优先级 → 模板下拉中文（严重/主要/普通/预警）。"""
        text = (raw or "").strip().lower()
        if not text:
            return "主要"
        for token, label in cls._SEVERITY_CN.items():
            if token in text:
                return label
        for digit, label in (("1", "严重"), ("2", "主要"), ("3", "普通"),
                             ("4", "预警")):
            if text == digit:
                return label
        return "主要"

    @staticmethod
    def _severity_to_priority(severity_cn: str) -> str:
        return {"严重": "P1", "主要": "P2", "普通": "P3", "预警": "P3"}.get(
            severity_cn, "P2"
        )

    @staticmethod
    def _to_is_clear(raw: str) -> str:
        """告警状态 → 模板下拉中文（活跃告警/清除告警）。"""
        text = (raw or "").strip().lower()
        if any(t in text for t in ["clear", "清除", "恢复", "closed",
                                   "resolved"]):
            return "清除告警"
        return "活跃告警"

    @staticmethod
    def _resolve_event_time(raw: str, *, default: str = "") -> str:
        text = (raw or "").strip()
        if not text or text in {"现在", "now", "当前", "此刻", "刚刚", "目前"}:
            return default or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return text

    @staticmethod
    def _pick_text(
        payload: dict[str, Any],
        *keys: str,
        nested: tuple[str, str] | None = None,
        nested_alt: tuple[str, str] | None = None,
    ) -> str:
        candidates: list[Any] = []
        for key in keys:
            candidates.append(payload.get(key))
        for path in [nested, nested_alt]:
            if not path:
                continue
            parent = payload.get(path[0])
            if isinstance(parent, dict):
                candidates.append(parent.get(path[1]))
        for item in candidates:
            if isinstance(item, list):
                item = OrderWorkflowClient._join_suggestions(item)
            if item is None:
                continue
            text = str(item).strip()
            if text:
                return text
        return ""

    @staticmethod
    def _join_suggestions(value: Any) -> str:
        if isinstance(value, list):
            parts = [str(item).strip() for item in value if str(item).strip()]
            return "；".join(parts)
        if value is None:
            return ""
        return str(value).strip()

    @staticmethod
    def _split_suggestions(value: Any) -> list[str]:
        text = OrderWorkflowClient._join_suggestions(value)
        if not text:
            return []
        parts = [item.strip() for item in re.split(r"[；;。\n]+", text) if item.strip()]
        return parts or [text]

    @staticmethod
    def _extract_ip(text: str) -> str:
        if not text:
            return ""
        matched = re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text)
        return matched.group(0) if matched else ""

    @staticmethod
    def _derive_title(
        *,
        title: str,
        visible_content: str,
        suggestions: str,
        device_name: str,
        manage_ip: str,
        asset_id: str,
    ) -> str:
        if title:
            return title
        base = visible_content or suggestions
        if not base:
            base = device_name or asset_id or manage_ip or "人工处置"
        compact = re.sub(r"\s+", " ", base).strip("，,；;。 ")
        if len(compact) > 24:
            compact = compact[:24].rstrip()
        return compact or "人工处置"

    @staticmethod
    def _derive_ticket_title(title: str) -> str:
        if title.endswith("工单"):
            return title
        if title.endswith("人工处置"):
            return title
        return f"{title}人工处置"

    @staticmethod
    def _derive_visible_content(
        *,
        title: str,
        device_name: str,
        manage_ip: str,
        asset_id: str,
        suggestions: str,
    ) -> str:
        device_part = device_name or asset_id
        if device_part and manage_ip:
            return f"{title}（{device_part} {manage_ip}）"
        if device_part:
            return f"{title}（{device_part}）"
        if manage_ip:
            return f"{title}（{manage_ip}）"
        if suggestions:
            return suggestions
        return title

    @staticmethod
    def _infer_metric_type(text: str) -> str:
        lowered = text.lower()
        if "mysql" in lowered:
            return "mysql"
        if "oracle" in lowered:
            return "oracle"
        if "redis" in lowered:
            return "redis"
        if "nginx" in lowered:
            return "nginx"
        if "k8s" in lowered or "kubernetes" in lowered or "pod" in lowered:
            return "kubernetes"
        if "数据库" in text or "db" in lowered:
            return "database"
        if "交换机" in text or "路由器" in text or "网络" in text:
            return "network"
        if "服务器" in text or "主机" in text or "host" in lowered:
            return "server"
        return "generic"

    @staticmethod
    def _normalize_level(raw_value: str, *, fallback_text: str) -> str:
        text = (raw_value or fallback_text or "").strip().lower()
        if any(token in text for token in ["critical", "严重", "高危", "紧急", "p1", "sev1", "一级"]):
            return "critical"
        if any(token in text for token in ["major", "重要", "较高", "高", "p2", "sev2", "二级"]):
            return "major"
        if any(token in text for token in ["minor", "一般", "中", "p3", "sev3", "三级"]):
            return "minor"
        if any(token in text for token in ["异常", "告警", "故障", "error", "alert", "incident"]):
            return "major"
        return "major"

    @staticmethod
    def _normalize_status(raw_value: str) -> str:
        text = (raw_value or "").strip().lower()
        if text in {"clear", "closed", "resolved", "1"}:
            return "clear"
        return "active"

    @staticmethod
    def _level_to_priority(level: str) -> str:
        return {
            "critical": "P1",
            "major": "P2",
            "minor": "P3",
            "warning": "P4",
        }.get(level, "P2")

    @staticmethod
    def _infer_category(metric_type: str) -> str:
        normalized = (metric_type or "generic").strip().lower().replace(" ", "-")
        return f"{normalized}-manual"

    @staticmethod
    def _generate_alarm_id() -> str:
        return f"alarm-{uuid.uuid4().hex[:12]}"

    def _notify_create_success(
        self,
        *,
        response_payload: dict[str, Any],
        request_payload: dict[str, Any],
    ) -> dict[str, Any]:
        app_push_url = self.config.create_notify_push_url.strip() or self.config.create_notify_webhook_url.strip()
        dingtalk_webhook_url = self.config.create_notify_dingtalk_webhook_url.strip()
        feishu_webhook_url = self.config.create_notify_feishu_webhook_url.strip()
        if not app_push_url and not dingtalk_webhook_url and not feishu_webhook_url:
            return {
                "enabled": False,
                "status": "skipped",
                "reason": "webhook_not_configured",
                "channels": [],
            }

        data = response_payload.get("data") or {}
        work_order_id = str(data.get("workOrderId") or "").strip()
        process_id = str(data.get("processId") or "").strip()
        if not work_order_id and not process_id:
            return {
                "enabled": True,
                "status": "skipped",
                "reason": "missing_workorder_identifiers",
                "channels": [],
            }

        context = self._build_create_notify_context(
            response_payload=response_payload,
            request_payload=request_payload,
        )
        channels: list[dict[str, Any]] = []
        if app_push_url:
            channels.append(
                self._send_app_push(
                    channel_name="app",
                    push_url=app_push_url,
                    payload=self._build_create_notify_payload(context),
                )
            )
        if dingtalk_webhook_url:
            channels.append(
                self._send_json_webhook(
                    channel_name="dingtalk",
                    webhook_url=self._build_dingtalk_signed_webhook_url(dingtalk_webhook_url),
                    payload=self._build_dingtalk_create_notify_payload(context),
                    success_predicate=lambda data: str(data.get("errcode", "")) == "0",
                )
            )
        if feishu_webhook_url:
            channels.append(
                self._send_json_webhook(
                    channel_name="feishu",
                    webhook_url=feishu_webhook_url,
                    payload=self._build_feishu_create_notify_payload(context),
                    success_predicate=lambda data: str(data.get("StatusCode", "")) == "0"
                    or str(data.get("code", "")) == "0",
                )
            )

        sent_count = sum(1 for item in channels if item.get("status") == "sent")
        if sent_count == len(channels) and channels:
            status = "sent"
            reason = ""
        elif sent_count > 0:
            status = "partial"
            reason = "partial_failure"
        else:
            status = "failed"
            reason = "; ".join(
                f"{item.get('channel')}:{item.get('reason') or 'unknown'}"
                for item in channels
            )

        return {
            "enabled": True,
            "status": status,
            "reason": reason,
            "channels": channels,
        }

    def _build_create_notify_context(
        self,
        *,
        response_payload: dict[str, Any],
        request_payload: dict[str, Any],
    ) -> dict[str, str]:
        data = response_payload.get("data") or {}
        alarm_payload = request_payload.get("alarm") or {}
        analysis_payload = request_payload.get("analysis") or {}
        ticket_payload = request_payload.get("ticket") or {}

        title = str(
            ticket_payload.get("title")
            or alarm_payload.get("alarmTitle")
            or "处置工单"
        ).strip()
        device_name = str(alarm_payload.get("neName") or "-").strip()
        manage_ip = str(alarm_payload.get("neIp") or "-").strip()
        level = str(alarm_payload.get("alarmSeverity") or "-").strip()
        visible_content = str(alarm_payload.get("alarmTitle") or "-").strip()
        suggestions = self._join_suggestions(analysis_payload.get("suggestions")) or str(
            analysis_payload.get("summary") or "-"
        ).strip()
        work_order_id = str(data.get("workOrderId") or "-").strip()
        process_id = str(data.get("processId") or "-").strip()
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        summary = self._build_create_summary(
            title=title,
            visible_content=visible_content,
            suggestions=suggestions,
        )

        return {
            "title": title,
            "summary": summary,
            "device_name": device_name,
            "manage_ip": manage_ip,
            "level": level,
            "work_order_id": work_order_id,
            "process_id": process_id,
            "created_at": created_at,
        }

    def _build_create_notify_payload(self, context: dict[str, str]) -> dict[str, Any]:
        content_lines = [
            "【工单创建通知】",
            f"标题：{context['title']}",
            f"摘要：{context['summary']}",
            f"设备：{context['device_name']} / {context['manage_ip']}",
            f"等级：{context['level']}",
            f"工单号：{context['work_order_id']}",
            f"流程：{context['process_id']}",
            f"创建时间：{context['created_at']}",
            "请相关同事关注并尽快处理。",
        ]
        return {
            "title": "工单创建通知",
            "content": "\n".join(content_lines),
            "type": "text",
        }

    def _build_dingtalk_create_notify_payload(self, context: dict[str, str]) -> dict[str, Any]:
        content_lines = [
            "【工单创建通知】",
            f"标题：{context['title']}",
            f"摘要：{context['summary']}",
            f"设备：{context['device_name']} / {context['manage_ip']}",
            f"等级：{context['level']}",
            f"工单号：{context['work_order_id']}",
            f"流程：{context['process_id']}",
            f"创建时间：{context['created_at']}",
            "请相关同事关注并尽快处理。",
        ]
        payload: dict[str, Any] = {
            "msgtype": "text",
            "text": {
                "content": "\n".join(content_lines),
            },
        }
        if self.config.create_notify_mention_all:
            payload["at"] = {"isAtAll": True}
        return payload

    def _build_feishu_create_notify_payload(self, context: dict[str, str]) -> dict[str, Any]:
        content_lines = [
            "【工单创建通知】",
            f"标题：{context['title']}",
            f"摘要：{context['summary']}",
            f"设备：{context['device_name']} / {context['manage_ip']}",
            f"等级：{context['level']}",
            f"工单号：{context['work_order_id']}",
            f"流程：{context['process_id']}",
            f"创建时间：{context['created_at']}",
            "请相关同事关注并尽快处理。",
        ]
        if self.config.create_notify_mention_all:
            content_lines.insert(0, '<at user_id="all">所有人</at>')
        payload: dict[str, Any] = {
            "msg_type": "text",
            "content": {
                "text": "\n".join(content_lines),
            },
        }
        secret = self.config.create_notify_feishu_secret.strip()
        if secret:
            timestamp = str(int(time.time()))
            string_to_sign = f"{timestamp}\n{secret}"
            sign = base64.b64encode(
                hmac.new(
                    string_to_sign.encode("utf-8"),
                    b"",
                    digestmod=hashlib.sha256,
                ).digest()
            ).decode("utf-8")
            payload["timestamp"] = timestamp
            payload["sign"] = sign
        return payload

    def _build_dingtalk_signed_webhook_url(self, webhook_url: str) -> str:
        secret = self.config.create_notify_dingtalk_secret.strip()
        if not secret:
            return webhook_url
        timestamp = str(int(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{secret}"
        sign = hmac.new(
            secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        encoded_sign = quote_plus(base64.b64encode(sign))
        separator = "&" if "?" in webhook_url else "?"
        return f"{webhook_url}{separator}timestamp={timestamp}&sign={encoded_sign}"

    @staticmethod
    def _is_successful_push_response(response_json: Any) -> bool:
        if not isinstance(response_json, dict) or not response_json:
            return True
        if "success" in response_json:
            return bool(response_json.get("success"))
        if "ok" in response_json:
            return bool(response_json.get("ok"))
        if "code" in response_json:
            return str(response_json.get("code") or "") in {"0", "200"}
        if "status" in response_json:
            return str(response_json.get("status") or "").lower() in {"ok", "success", "sent"}
        if "errcode" in response_json:
            return str(response_json.get("errcode") or "") == "0"
        return True

    def _send_app_push(
        self,
        *,
        channel_name: str,
        push_url: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            response_json = self._post_json(
                push_url,
                payload,
                self.config.create_notify_timeout_seconds,
            )
        except Exception as exc:
            return {
                "channel": channel_name,
                "status": "failed",
                "reason": str(exc),
            }

        if self._is_successful_push_response(response_json):
            return {
                "channel": channel_name,
                "status": "sent",
                "reason": "",
            }

        return {
            "channel": channel_name,
            "status": "failed",
            "reason": response_json.get("errmsg")
            or response_json.get("message")
            or response_json.get("reason")
            or "push_rejected",
        }

    def _send_json_webhook(
        self,
        *,
        channel_name: str,
        webhook_url: str,
        payload: dict[str, Any],
        success_predicate: Any,
    ) -> dict[str, Any]:
        try:
            response_json = self._post_json(
                webhook_url,
                payload,
                self.config.create_notify_timeout_seconds,
            )
            if success_predicate(response_json):
                return {
                    "channel": channel_name,
                    "status": "sent",
                    "reason": "",
                }
            return {
                "channel": channel_name,
                "status": "failed",
                "reason": response_json.get("errmsg")
                or response_json.get("message")
                or "webhook_rejected",
            }
        except Exception as exc:
            return {
                "channel": channel_name,
                "status": "failed",
                "reason": str(exc),
            }

    @staticmethod
    def _build_create_summary(*, title: str, visible_content: str, suggestions: str) -> str:
        parts: list[str] = []
        for text in [visible_content, suggestions]:
            compact = re.sub(r"\s+", " ", str(text or "")).strip("，,；;。 ")
            if not compact:
                continue
            if compact not in parts:
                parts.append(compact)
        if not parts and title:
            parts.append(title)
        summary = "；".join(parts)
        if len(summary) > 80:
            summary = f"{summary[:80].rstrip()}..."
        return summary or "人工处置工单已创建"

    @staticmethod
    def _format_request_error(exc: Exception) -> str:
        reason = getattr(exc, "reason", None)
        return f"{type(exc).__name__}: {reason if reason is not None else exc}"

    def _curl_request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        params: dict[str, Any] | None,
        json_body: dict[str, Any] | None,
    ) -> dict[str, Any]:
        query_url = url
        if params:
            query_url = f"{url}?{urlencode(params, doseq=True)}"

        args = [
            "curl",
            "-sS",
            "-X",
            method.upper(),
            "--connect-timeout",
            str(int(self.config.timeout_seconds)),
            "--max-time",
            str(int(self.config.timeout_seconds)),
            query_url,
        ]
        for key, value in headers.items():
            args.extend(["-H", f"{key}: {value}"])

        tmp_path = ""
        if json_body is not None:
            tmp = tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                delete=False,
            )
            json.dump(json_body, tmp, ensure_ascii=False)
            tmp.flush()
            tmp.close()
            tmp_path = tmp.name
            args.extend(
                [
                    "-H",
                    "Content-Type: application/json;charset=utf-8",
                    "--data-binary",
                    f"@{tmp_path}",
                ]
            )

        try:
            completed = subprocess.run(
                args,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            if completed.returncode != 0:
                raise RuntimeError(completed.stderr.strip() or "curl request failed")
            return json.loads(completed.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid JSON response from {query_url}") from exc
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
