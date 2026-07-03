#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""门户菜单(getRouters)客户端:把操作目录里的 ``component`` 解析为线上
真实路由 ``path``。

操作目录只存组件路径(如 ``workflow/category/index``)和一个兜底 route;
真正注册的路由 path 由门户后端菜单(getRouters)决定。运行期用本模块按
component 反查 path,使目录对"菜单改了路由"更鲁棒。拿不到菜单(未配置/
网络失败)时调用方回退到目录里的兜底 route。

配置优先用 operator 专属变量 ``OPERATOR_MENU_*``(门户「设置 - 操作」分类,
会物化到 os.environ);未设置时回退共享菜单变量 ``INOE_MENU_*``、再回退 INOE
接入 ``INOE_API_BASE_URL`` / ``INOE_API_TOKEN``(与 page-navigator / 告警同一
后端,可来自 ``secrets/inoe.env``)。
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any

try:
    import httpx

    HAS_HTTPX = True
except ImportError:  # pragma: no cover - 离线/未装时退化
    HAS_HTTPX = False


DEFAULT_APP_CODE = "inoe"
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_CACHE_TTL_SECONDS = 600.0

CONTAINER_COMPONENTS = {"Layout", "ParentView", "InnerLink"}


def _load_shared_inoe_env() -> None:
    """向上查找 ``working/secrets/inoe.env`` 并注入(已存在的 env 优先)。"""
    for parent in Path(__file__).resolve().parents:
        secrets = parent / "secrets" / "inoe.env"
        if secrets.is_file() and (parent / "workspaces").is_dir():
            for raw in secrets.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(
                    key.strip(),
                    value.strip().strip('"').strip("'"),
                )
            return


_load_shared_inoe_env()


def _first_env(*names: str) -> str:
    """返回 ``names`` 里第一个非空环境变量(已 strip)。"""
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return ""


def _base_url() -> str:
    # operator 专属(设置页「操作」分类) > 共享菜单变量 > INOE 网关地址。
    base = _first_env(
        "OPERATOR_MENU_BASE_URL",
        "INOE_MENU_BASE_URL",
        "INOE_API_BASE_URL",
    )
    return base.rstrip("/")


def _token() -> str:
    return _first_env(
        "OPERATOR_MENU_TOKEN",
        "INOE_API_TOKEN",
        "INOE_MENU_TOKEN",
    )


def _app_code() -> str:
    return (
        _first_env("OPERATOR_MENU_APP_CODE", "INOE_MENU_APP_CODE")
        or DEFAULT_APP_CODE
    )


def _float_env(default: float, *names: str) -> float:
    raw = _first_env(*names)
    if not raw:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json, text/plain, */*"}
    token = _token()
    if token:
        headers["Authorization"] = (
            token if token.lower().startswith("bearer ") else f"Bearer {token}"
        )
    return headers


class MenuClientError(RuntimeError):
    """菜单接口不可用或返回结构异常。"""


_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {"ts": 0.0, "tree": None}


def _join_path(parent_full: str, child: str) -> str:
    child = child or ""
    if child.startswith("/"):
        return child
    if not parent_full:
        return child
    if parent_full.endswith("/"):
        return parent_full + child
    return parent_full + "/" + child


def flatten_routes(tree: Any) -> list[dict[str, str]]:
    """把 getRouters 的 data 树拍平为 [{path, component, name}]。"""
    out: list[dict[str, str]] = []

    def walk(nodes: Any, parent_full: str) -> None:
        for node in nodes or []:
            if not isinstance(node, dict):
                continue
            full = _join_path(parent_full, node.get("path") or "")
            out.append(
                {
                    "path": full,
                    "component": str(node.get("component") or ""),
                    "name": str(node.get("name") or ""),
                }
            )
            children = node.get("children")
            if children:
                walk(children, full)

    walk(tree, "")
    return out


def resolve_route(
    tree: Any,
    *,
    component: str = "",
    name: str = "",
) -> str | None:
    """在拍平后的路由里按 component(优先)或 name 反查 path。"""
    comp = (component or "").strip()
    nm = (name or "").strip()
    flat = flatten_routes(tree)
    if comp:
        for entry in flat:
            if entry["component"] == comp:
                return entry["path"]
    if nm:
        for entry in flat:
            if entry["name"] == nm:
                return entry["path"]
    return None


def _fetch_raw() -> list[dict]:
    if not HAS_HTTPX:
        raise MenuClientError("httpx 未安装,无法拉取菜单")
    base = _base_url()
    if not base:
        raise MenuClientError(
            "未配置菜单接口地址"
            "(OPERATOR_MENU_BASE_URL / INOE_MENU_BASE_URL / INOE_API_BASE_URL)"
        )
    url = f"{base}/admin/menu/getRouters/{_app_code()}"
    timeout = _float_env(
        DEFAULT_TIMEOUT_SECONDS,
        "OPERATOR_MENU_TIMEOUT_SECONDS",
        "INOE_MENU_TIMEOUT_SECONDS",
    )
    with httpx.Client(timeout=timeout) as client:
        resp = client.get(url, headers=_headers())
        resp.raise_for_status()
        body = resp.json()
    data = body.get("data") if isinstance(body, dict) else body
    if not isinstance(data, list):
        raise MenuClientError(f"菜单接口返回结构异常: {type(data)!r}")
    return data


def get_menu_tree(*, force_refresh: bool = False) -> list[dict]:
    """返回菜单树(带 TTL 缓存);拉取失败但有旧缓存时回退旧缓存。"""
    ttl = _float_env(
        DEFAULT_CACHE_TTL_SECONDS,
        "OPERATOR_MENU_CACHE_TTL_SECONDS",
        "INOE_MENU_CACHE_TTL_SECONDS",
    )
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get("tree")
        fresh = cached is not None and (now - _CACHE["ts"]) < ttl
        if cached is not None and fresh and not force_refresh:
            return cached
    try:
        tree = _fetch_raw()
    except Exception as exc:  # noqa: BLE001 - 优先回退旧缓存
        with _CACHE_LOCK:
            if _CACHE.get("tree") is not None:
                return _CACHE["tree"]
        raise MenuClientError(f"拉取菜单失败: {exc}") from exc
    with _CACHE_LOCK:
        _CACHE["tree"] = tree
        _CACHE["ts"] = time.monotonic()
    return tree


def resolve_live_route(
    *,
    component: str = "",
    name: str = "",
    force_refresh: bool = False,
) -> str | None:
    """拉菜单并反查 path;任何失败都返回 None(调用方回退兜底 route)。"""
    try:
        tree = get_menu_tree(force_refresh=force_refresh)
    except MenuClientError:
        return None
    return resolve_route(tree, component=component, name=name)
