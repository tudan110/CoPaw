# -*- coding: utf-8 -*-
"""Per-connection configuration health for the big-screen config center.

Each big-screen capability declares a backing ``connection`` (inoe /
n9e / zgops / proxy:<id> / skill:<...> / "" for none). This reports
whether that connection is actually configured, so the workshop can
show "已配置/未配置" per functional domain and point the operator at the
right settings tab — instead of the screen silently returning empty
because (e.g.) INOE still points at the in-cluster ``gateway:8080``
default with no token.

Reads the EFFECTIVE values from ``os.environ`` (every settings store
materialises its resolved config there via working_secrets), so this
reflects exactly what the fetchers will use at request time.
"""

from __future__ import annotations

import os
from typing import Any

# In-cluster service-name defaults that mean "not really configured for
# this host" — present out of the box but unreachable outside k8s.
_PLACEHOLDER_HOST_MARKERS = (
    "gateway:",
    "cnos-iomp-",
    "localhost",
    "127.0.0.1",
)

# connection id -> (label, settings tab in the portal settings page)
_CONNECTION_META: dict[str, tuple[str, str]] = {
    "inoe": ("INOE 网关", "inoe"),
    "n9e": ("夜莺日志", "n9e"),
    "zgops": ("ZGOPS CMDB", "cmdb"),
    "order": ("工单 / ferry", "order"),
}


def _env(name: str) -> str:
    return str(os.environ.get(name) or "").strip()


def _looks_placeholder(base_url: str) -> bool:
    return any(marker in base_url for marker in _PLACEHOLDER_HOST_MARKERS)


def _inoe_status() -> tuple[bool, str]:
    base = _env("INOE_API_BASE_URL")
    token = _env("INOE_API_TOKEN")
    if not base or _looks_placeholder(base):
        return False, "网关地址未配置或仍是集群内默认地址"
    if not token:
        return False, "缺少访问 token"
    return True, ""


def _n9e_status() -> tuple[bool, str]:
    base = _env("N9E_API_BASE_URL")
    token = _env("N9E_USER_TOKEN")
    if not base or _looks_placeholder(base):
        return False, "夜莺地址未配置"
    if not token:
        return False, "缺少夜莺 token"
    return True, ""


def _zgops_status() -> tuple[bool, str]:
    base = _env("ZGOPS_BASE_URL")
    has_cred = bool(_env("ZGOPS_USERNAME") or _env("ZGOPS_PASSWORD"))
    if not base or _looks_placeholder(base):
        return False, "CMDB 地址未配置或仍是集群内默认地址"
    if not has_cred:
        return False, "缺少 CMDB 账号/密码"
    return True, ""


def _order_status() -> tuple[bool, str]:
    """Work-order (ferry) health, honouring the client's INOE fallback.

    The order-workflow client uses ``ORDER_API_BASE_URL`` /
    ``ORDER_AUTHORIZATION`` and falls back to the INOE connection when
    they are empty, so 工单 is "configured" if either its own ferry
    endpoint is set or the shared INOE connection is usable.
    """
    base = _env("ORDER_API_BASE_URL")
    auth = _env("ORDER_AUTHORIZATION")
    if base and not _looks_placeholder(base) and auth:
        return True, ""
    inoe_ok, _ = _inoe_status()
    if inoe_ok:
        return True, "工单接口未单独配置，回退平台 INOE 连接"
    return False, "工单接口未配置，且平台 INOE 也未配置"


def _proxy_status(connection: str) -> tuple[bool, str, str, str]:
    datasource_id = connection[len("proxy:") :]
    try:
        from qwenpaw.extensions.api import proxy_datasource_service as svc

        cfg = svc.get_datasource(datasource_id)
    except Exception:
        cfg = None
    if cfg is None:
        return False, "连接器未注册", f"连接器 {datasource_id}", "proxy"
    label = str(cfg.name or datasource_id)
    if not getattr(cfg, "enabled", False):
        return False, "连接器已禁用", label, "proxy"
    url = str(getattr(cfg, "url_template", "") or "")
    if not url or _looks_placeholder(url):
        return False, "连接器地址未配置或仍是集群内默认地址", label, "proxy"
    return True, "", label, "proxy"


def connection_status(connection: str) -> dict[str, Any]:
    """Resolve one connection's health → {connection, configured, label,
    settingsTab, reason}. Never raises."""
    conn = str(connection or "").strip()

    # no backing connection needed (web-live-data, capability-gap)
    if not conn or conn == "web":
        return {
            "connection": conn,
            "configured": True,
            "label": "无需连接" if not conn else "公网检索",
            "settingsTab": "",
            "reason": "",
        }

    if conn.startswith("proxy:"):
        configured, reason, label, tab = _proxy_status(conn)
        return {
            "connection": conn,
            "configured": configured,
            "label": label,
            "settingsTab": tab,
            "reason": reason,
        }

    # skill-backed capabilities run through their underlying connection
    # (the inspection skill, for instance, calls INOE); default to inoe.
    if conn.startswith("skill:"):
        underlying = "inoe"
    else:
        underlying = conn

    checker = {
        "inoe": _inoe_status,
        "n9e": _n9e_status,
        "zgops": _zgops_status,
        "order": _order_status,
    }.get(underlying)
    if checker is None:
        return {
            "connection": conn,
            "configured": False,
            "label": conn,
            "settingsTab": "",
            "reason": "未知连接类型",
        }
    configured, reason = checker()
    label, tab = _CONNECTION_META.get(underlying, (underlying, ""))
    return {
        "connection": conn,
        "configured": configured,
        "label": label,
        "settingsTab": tab,
        "reason": reason,
    }
