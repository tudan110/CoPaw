# -*- coding: utf-8 -*-
"""Synthetic probes (design P1 拨测) — L1 experience layer.

A background loop performs black-box HTTP checks against this very
instance (portal index, key APIs) and records ``qwenpaw_probe_up`` /
``qwenpaw_probe_duration_seconds``.  Failures emit dedup-merged
``probe.failed`` events and drive the built-in ``probe-down`` alert.

Operators extend the target list (e.g. a chat smoke-test endpoint that
costs tokens, hence never probed by default) via
``<working-dir>/self_monitor_probes.json``:

    {"probes": [{"id": "chat-smoke", "name": "对话冒烟",
                 "url": "http://127.0.0.1:8088/api/...",
                 "method": "POST", "body": {...}, "timeoutS": 30}],
     "disable": ["portal-index"]}
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from ..constant import WORKING_DIR, EnvVarLoader
from .events import emit_event
from .registry import get_registry

logger = logging.getLogger(__name__)

PROBES_FILENAME = "self_monitor_probes.json"

PROBES_ENABLED = EnvVarLoader.get_bool("QWENPAW_SELF_MONITOR_PROBES_ENABLED", True)
PROBE_INTERVAL_SECONDS = EnvVarLoader.get_float(
    "QWENPAW_SELF_MONITOR_PROBE_INTERVAL", 60.0, min_value=5.0
)


def _default_base_url() -> str:
    explicit = EnvVarLoader.get_str("QWENPAW_SELF_MONITOR_PROBE_BASE", "")
    if explicit:
        return explicit.rstrip("/")
    port = EnvVarLoader.get_int("QWENPAW_PORT", 8088)
    return f"http://127.0.0.1:{port}"


@dataclass(frozen=True)
class Probe:
    id: str
    name: str
    url: str
    method: str = "GET"
    body: Any = None
    timeout_s: float = 5.0
    expect_status: int = 200


def default_probes(base_url: str) -> list[Probe]:
    return [
        Probe(id="portal-index", name="门户首屏", url=f"{base_url}/"),
        Probe(id="api-version", name="API 版本", url=f"{base_url}/api/version"),
        Probe(
            id="self-monitor",
            name="自监控健康",
            url=f"{base_url}/api/portal/self-monitor/health",
        ),
    ]


def load_probes(base_url: str | None = None, path=None) -> list[Probe]:
    base = base_url or _default_base_url()
    probes = {probe.id: probe for probe in default_probes(base)}
    config_path = path or (WORKING_DIR / PROBES_FILENAME)
    try:
        if config_path.exists():
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            for probe_id in raw.get("disable") or []:
                probes.pop(str(probe_id), None)
            for spec in raw.get("probes") or []:
                try:
                    url = str(spec.get("url") or "")
                    if not url and spec.get("path"):
                        url = f"{base}{spec['path']}"
                    probe = Probe(
                        id=str(spec["id"]),
                        name=str(spec.get("name") or spec["id"]),
                        url=url,
                        method=str(spec.get("method") or "GET").upper(),
                        body=spec.get("body"),
                        timeout_s=float(spec.get("timeoutS") or 5.0),
                        expect_status=int(spec.get("expectStatus") or 200),
                    )
                    if probe.url:
                        probes[probe.id] = probe
                except Exception:
                    logger.warning("self_monitor: bad probe spec skipped: %r", spec)
    except Exception:
        logger.warning("self_monitor: probes config unreadable", exc_info=True)
    return list(probes.values())


class ProbeRunner:
    """Executes the probe list once per call; owned by the sampler."""

    def __init__(self, probes: list[Probe] | None = None) -> None:
        self.probes = probes if probes is not None else load_probes()

    async def run_once(self) -> None:
        """Probe every target. Never raises."""
        try:
            import httpx

            registry = get_registry()
            up_gauge = registry.gauge("qwenpaw_probe_up")
            duration = registry.histogram("qwenpaw_probe_duration_seconds")
            async with httpx.AsyncClient(follow_redirects=True) as client:
                for probe in self.probes:
                    labels = {"target": probe.id}
                    started = time.monotonic()
                    ok, reason = False, ""
                    try:
                        response = await client.request(
                            probe.method,
                            probe.url,
                            json=probe.body if probe.body is not None else None,
                            timeout=probe.timeout_s,
                        )
                        ok = response.status_code == probe.expect_status
                        if not ok:
                            reason = f"HTTP {response.status_code}"
                    except Exception as exc:
                        reason = type(exc).__name__
                    duration.observe(time.monotonic() - started, labels)
                    up_gauge.set(labels, 1.0 if ok else 0.0)
                    if not ok:
                        emit_event(
                            "probe.failed",
                            severity="warn",
                            layer="l1",
                            source=probe.id,
                            message=f"{probe.name} 探测失败: {reason}",
                            dedup_key=f"probe.failed|{probe.id}",
                        )
        except Exception:  # pragma: no cover - probes are fail-open
            logger.warning("self_monitor probe pass failed", exc_info=True)


__all__ = [
    "PROBES_ENABLED",
    "PROBE_INTERVAL_SECONDS",
    "PROBES_FILENAME",
    "Probe",
    "ProbeRunner",
    "default_probes",
    "load_probes",
]
