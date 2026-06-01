#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

try:
    from dotenv import load_dotenv

    HAS_DOTENV = True
except ImportError:
    HAS_DOTENV = False


ACTION_ALIASES = {
    "goto": "goto",
    "open": "goto",
    "navigate": "goto",
    "wait": "wait",
    "asserttext": "assertText",
    "checktext": "assertText",
    "assert_text": "assertText",
    "assertelement": "assertElement",
    "checkelement": "assertElement",
    "assert_element": "assertElement",
    "click": "click",
    "input": "input",
    "type": "input",
    "fill": "input",
    "scroll": "scroll",
    "screenshot": "screenshot",
    "capture": "screenshot",
}

FAILURE_ALIASES = {
    "abort": "abort",
    "stop": "abort",
    "fail": "abort",
    "warn": "continue-warning",
    "warning": "continue-warning",
    "continue": "continue-warning",
    "continue-warning": "continue-warning",
}

RUNNING_STATUSES = {"queued", "running", "pending", "in_progress"}


def _load_skill_env() -> None:
    if not HAS_DOTENV:
        return
    skill_dir = Path(__file__).resolve().parents[1]
    env_file = skill_dir / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=False)


_load_skill_env()


@dataclass(slots=True)
class WebMonitorConfig:
    base_url: str
    authorization: str = ""
    cookie: str = ""
    timeout_seconds: int = 20
    verify_ssl: bool = True
    enable_curl_fallback: bool = False
    extra_headers: dict[str, str] | None = None

    @classmethod
    def from_env(cls) -> "WebMonitorConfig":
        raw_extra_headers = os.getenv("WEB_MONITOR_EXTRA_HEADERS", "").strip()
        extra_headers: dict[str, str] | None = None
        if raw_extra_headers:
            parsed = json.loads(raw_extra_headers)
            if isinstance(parsed, dict):
                extra_headers = {
                    str(key): str(value)
                    for key, value in parsed.items()
                    if value is not None
                }

        return cls(
            base_url=(os.getenv("WEB_MONITOR_BASE_URL", "http://192.168.134.96:3101").strip() or "http://192.168.134.96:3101").rstrip("/"),
            authorization=os.getenv("WEB_MONITOR_AUTHORIZATION", "").strip(),
            cookie=os.getenv("WEB_MONITOR_COOKIE", "").strip(),
            timeout_seconds=int(os.getenv("WEB_MONITOR_TIMEOUT_SECONDS", "20").strip() or "20"),
            verify_ssl=os.getenv("WEB_MONITOR_VERIFY_SSL", "true").strip().lower() not in {"0", "false", "no"},
            enable_curl_fallback=os.getenv("WEB_MONITOR_ENABLE_CURL_FALLBACK", "false").strip().lower() in {"1", "true", "yes"},
            extra_headers=extra_headers,
        )


class WebMonitorClient:
    def __init__(self, config: WebMonitorConfig | None = None) -> None:
        self.config = config or WebMonitorConfig.from_env()

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/api/health")

    def dashboard(self) -> dict[str, Any]:
        return self._request("GET", "/api/dashboard")

    def list_monitors(self) -> dict[str, Any]:
        return self._request("GET", "/api/monitors")

    def get_monitor(self, monitor_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/monitors/{monitor_id}")

    def create_monitor(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/monitors", json_body=self.normalize_monitor_payload(payload))

    def update_monitor(self, monitor_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", f"/api/monitors/{monitor_id}", json_body=self.normalize_monitor_payload(payload))

    def publish_monitor(self, monitor_id: str) -> dict[str, Any]:
        return self._request("POST", f"/api/monitors/{monitor_id}/publish")

    def trigger_monitor(self, monitor_id: str, definition: dict[str, Any] | None = None) -> dict[str, Any]:
        body = self.normalize_definition_payload(definition) if definition is not None else {}
        return self._request("POST", f"/api/monitors/{monitor_id}/trigger", json_body=body)

    def list_runs(self, monitor_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/monitors/{monitor_id}/runs")

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/runs/{run_id}")

    def delete_monitor(self, monitor_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"/api/monitors/{monitor_id}")

    def delete_run(self, run_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"/api/runs/{run_id}")

    def delete_runs(self, run_ids: list[str]) -> dict[str, Any]:
        return self._request("POST", "/api/runs/batch-delete", json_body={"ids": run_ids})

    def selector_helper(self, url: str) -> dict[str, Any]:
        return self._request("POST", "/api/selector-helper", json_body={"url": url})

    def wait_for_run(
        self,
        run_id: str,
        *,
        timeout_seconds: int = 90,
        poll_interval: float = 3.0,
    ) -> dict[str, Any]:
        deadline = time.time() + max(timeout_seconds, 1)
        latest = self.get_run(run_id)
        while time.time() < deadline:
            run = latest.get("run") if isinstance(latest, dict) else None
            status = str((run or {}).get("status") or "").strip().lower()
            if status and status not in RUNNING_STATUSES:
                return latest
            time.sleep(max(poll_interval, 0.5))
            latest = self.get_run(run_id)
        return latest

    def resolve_monitor(self, identifier: str) -> dict[str, Any]:
        needle = str(identifier or "").strip()
        if not needle:
            raise RuntimeError("monitor identifier is required")

        payload = self.list_monitors()
        monitors = payload.get("monitors") if isinstance(payload, dict) else None
        if not isinstance(monitors, list):
            raise RuntimeError("monitor list response is invalid")

        exact_id = next((item for item in monitors if str(item.get("id") or "").strip() == needle), None)
        if exact_id:
            return exact_id

        exact_name = next((item for item in monitors if str(item.get("name") or "").strip() == needle), None)
        if exact_name:
            return exact_name

        lowered = needle.casefold()
        partial = [
            item
            for item in monitors
            if lowered in str(item.get("name") or "").casefold()
            or lowered in str(item.get("targetUrl") or "").casefold()
            or str(item.get("id") or "").startswith(needle)
        ]
        if not partial:
            raise RuntimeError(f"未找到匹配的监测任务：{needle}")
        if len(partial) > 1:
            options = " / ".join(str(item.get("name") or item.get("id") or "") for item in partial[:5])
            raise RuntimeError(f"匹配到多个监测任务，请更具体一些：{options}")
        return partial[0]

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json;charset=UTF-8",
        }
        if self.config.authorization:
            headers["Authorization"] = self.config.authorization
        if self.config.cookie:
            headers["Cookie"] = self.config.cookie
        if self.config.extra_headers:
            headers.update(self.config.extra_headers)
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | list[Any] | None = None,
    ) -> dict[str, Any]:
        if not self.config.base_url:
            raise RuntimeError("WEB_MONITOR_BASE_URL is required")
        url = f"{self.config.base_url}{path}"
        headers = self._build_headers()

        try:
            response = requests.request(
                method=method.upper(),
                url=url,
                headers=headers,
                json=json_body,
                timeout=self.config.timeout_seconds,
                verify=self.config.verify_ssl,
            )
            if response.status_code >= 400:
                detail = response.text[:500].strip() or response.reason
                raise RuntimeError(f"{response.status_code} {detail}")
            if response.status_code == 204 or not response.text.strip():
                return {"ok": True, "status": response.status_code}
            return self._parse_json_text(response.text)
        except (requests.ConnectionError, requests.Timeout, OSError) as error:
            if self.config.enable_curl_fallback:
                return self._curl_request(method=method, url=url, headers=headers, json_body=json_body)
            raise RuntimeError(f"请求失败：{error}") from error
        except requests.RequestException as error:
            if self.config.enable_curl_fallback:
                return self._curl_request(method=method, url=url, headers=headers, json_body=json_body)
            raise RuntimeError(f"请求异常：{error}") from error

    @staticmethod
    def _parse_json_text(text: str) -> dict[str, Any]:
        payload = json.loads(text or "{}")
        if isinstance(payload, dict):
            return payload
        return {"data": payload}

    def _curl_request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        json_body: dict[str, Any] | list[Any] | None,
    ) -> dict[str, Any]:
        with tempfile.NamedTemporaryFile(delete=False) as body_file:
            body_path = body_file.name

        data_path = None
        args = [
            "curl",
            "-sS",
            "-X",
            method.upper(),
            "--connect-timeout",
            str(self.config.timeout_seconds),
            "--max-time",
            str(self.config.timeout_seconds),
            "-o",
            body_path,
            "-w",
            "%{http_code}",
        ]
        if not self.config.verify_ssl:
            args.append("-k")
        for key, value in headers.items():
            args.extend(["-H", f"{key}: {value}"])
        if json_body is not None:
            with tempfile.NamedTemporaryFile(delete=False, mode="w", encoding="utf-8") as payload_file:
                payload_file.write(json.dumps(json_body, ensure_ascii=False))
                data_path = payload_file.name
            args.extend(["--data-binary", f"@{data_path}"])
        args.append(url)

        try:
            completed = subprocess.run(
                args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=max(self.config.timeout_seconds + 5, 10),
                check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError((completed.stderr or completed.stdout or "curl 请求失败").strip())
            status_code = int((completed.stdout or "").strip() or "0")
            response_text = Path(body_path).read_text(encoding="utf-8", errors="replace")
            if status_code >= 400:
                raise RuntimeError(f"{status_code} {response_text[:500].strip()}")
            if status_code == 204 or not response_text.strip():
                return {"ok": True, "status": status_code}
            return self._parse_json_text(response_text)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("请求超时") from error
        finally:
            for path in (body_path, data_path):
                if not path:
                    continue
                try:
                    os.unlink(path)
                except OSError:
                    pass

    @classmethod
    def normalize_monitor_payload(cls, payload: dict[str, Any]) -> dict[str, Any]:
        source = payload.get("monitor") if isinstance(payload.get("monitor"), dict) else payload
        if not isinstance(source, dict):
            raise RuntimeError("monitor payload must be a JSON object")

        schedule = source.get("schedule") if isinstance(source.get("schedule"), dict) else {}
        target_url = str(
            source.get("targetUrl")
            or source.get("target_url")
            or source.get("url")
            or source.get("startUrl")
            or ""
        ).strip()
        name = str(source.get("name") or "").strip()
        if not name:
            raise RuntimeError("monitor payload missing name")
        if not target_url:
            raise RuntimeError("monitor payload missing targetUrl")

        definition = cls.normalize_definition_payload(source)
        schedule_enabled = cls._as_bool(source.get("scheduleEnabled"), default=cls._as_bool(schedule.get("enabled"), default=False))
        schedule_cron = str(source.get("scheduleCron") or schedule.get("cron") or "").strip()
        schedule_timezone = str(
            source.get("scheduleTimezone") or schedule.get("timezone") or "Asia/Shanghai"
        ).strip() or "Asia/Shanghai"
        if schedule_enabled and not schedule_cron:
            raise RuntimeError("scheduleEnabled=true 时必须提供 scheduleCron 或 schedule.cron")

        return {
            "name": name,
            "description": str(source.get("description") or "").strip(),
            "targetUrl": target_url,
            "status": cls._normalize_status(source.get("status")),
            "scheduleEnabled": schedule_enabled,
            "scheduleCron": schedule_cron if schedule_enabled else None,
            "scheduleTimezone": schedule_timezone,
            "definition": definition,
        }

    @classmethod
    def normalize_definition_payload(cls, payload: dict[str, Any]) -> dict[str, Any]:
        source = payload
        for key in ("definition", "draftDefinition", "publishedDefinition"):
            candidate = payload.get(key)
            if isinstance(candidate, dict):
                source = candidate
                break
        if not isinstance(source, dict):
            raise RuntimeError("definition payload must be a JSON object")

        start_url = str(
            source.get("startUrl")
            or payload.get("startUrl")
            or payload.get("targetUrl")
            or payload.get("target_url")
            or payload.get("url")
            or ""
        ).strip()
        steps = source.get("steps") or payload.get("steps") or []
        if not isinstance(steps, list) or not steps:
            raise RuntimeError("monitor definition must include non-empty steps")

        normalized_steps = [
            cls._normalize_step(step, index=index, default_url=start_url)
            for index, step in enumerate(steps, start=1)
        ]
        effective_start_url = start_url or cls._guess_start_url(normalized_steps)
        if not effective_start_url:
            raise RuntimeError("monitor definition missing startUrl or goto step url")

        return {
            "startUrl": effective_start_url,
            "steps": normalized_steps,
        }

    @classmethod
    def _normalize_step(cls, step: dict[str, Any], *, index: int, default_url: str) -> dict[str, Any]:
        if not isinstance(step, dict):
            raise RuntimeError(f"step #{index} must be an object")
        action_raw = str(step.get("actionType") or step.get("action") or step.get("type") or "").strip()
        if not action_raw:
            raise RuntimeError(f"step #{index} missing actionType")
        action_key = action_raw.replace("-", "").replace("_", "").lower()
        action_type = ACTION_ALIASES.get(action_key, action_raw)

        config = step.get("config")
        if not isinstance(config, dict):
            config = {}
        config = dict(config)
        if action_type == "goto" and not str(config.get("url") or "").strip() and default_url:
            config["url"] = default_url
        if action_type == "goto" and not str(config.get("waitUntil") or "").strip():
            config["waitUntil"] = "domcontentloaded"

        normalized = {
            "id": str(step.get("id") or "").strip() or f"step-{index:03d}",
            "name": str(step.get("name") or cls._default_step_name(action_type, index)).strip(),
            "actionType": action_type,
            "enabled": cls._as_bool(step.get("enabled"), default=True),
            "onFailure": cls._normalize_failure_policy(step.get("onFailure") or step.get("failureStrategy")),
            "config": config,
        }
        return normalized

    @staticmethod
    def _guess_start_url(steps: list[dict[str, Any]]) -> str:
        for step in steps:
            if str(step.get("actionType") or "") == "goto":
                config = step.get("config") or {}
                url = str(config.get("url") or "").strip()
                if url:
                    return url
        return ""

    @staticmethod
    def _default_step_name(action_type: str, index: int) -> str:
        names = {
            "goto": "打开页面",
            "wait": "等待条件",
            "assertText": "检查文本",
            "assertElement": "检查元素",
            "click": "点击元素",
            "input": "输入内容",
            "scroll": "滚动页面",
            "screenshot": "截图取证",
        }
        return names.get(action_type, f"步骤 {index}")

    @staticmethod
    def _normalize_status(value: Any) -> str:
        normalized = str(value or "enabled").strip().lower()
        return "disabled" if normalized in {"disabled", "disable", "off", "false", "0"} else "enabled"

    @staticmethod
    def _normalize_failure_policy(value: Any) -> str:
        normalized = str(value or "abort").strip().lower()
        return FAILURE_ALIASES.get(normalized, "abort")

    @staticmethod
    def _as_bool(value: Any, *, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        return default
