#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""门户菜单接口客户端:拉取 ``getRouters`` 并做带 TTL 的内存缓存。

配置复用 INOE 接入(``secrets/inoe.env`` 里的 ``INOE_API_BASE_URL`` /
``INOE_API_TOKEN``,与告警/监控同一后端),只在需要时用菜单专属变量
覆盖。技能子进程通常继承 agent 进程已注入的环境;为支持独立运行,
这里也会就地加载技能本地 ``.env`` 与共享 ``secrets/inoe.env``。
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any

import httpx

try:
    from dotenv import load_dotenv

    HAS_DOTENV = True
except ImportError:  # pragma: no cover - dotenv 缺失时退化
    HAS_DOTENV = False


DEFAULT_APP_CODE = "inoe"
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_CACHE_TTL_SECONDS = 600.0


def _load_skill_env() -> None:
    if not HAS_DOTENV:
        return
    env_file = Path(__file__).resolve().parents[1] / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=False)


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


_load_skill_env()
_load_shared_inoe_env()


def _base_url() -> str:
    base = (
        os.getenv("INOE_MENU_BASE_URL")
        or os.getenv("INOE_API_BASE_URL")
        or ""
    )
    return base.strip().rstrip("/")


def _token() -> str:
    return (
        os.getenv("INOE_API_TOKEN")
        or os.getenv("INOE_MENU_TOKEN")
        or ""
    ).strip()


def _app_code() -> str:
    return (os.getenv("INOE_MENU_APP_CODE") or DEFAULT_APP_CODE).strip()


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name) or default)
    except (TypeError, ValueError):
        return default


def _build_headers() -> dict[str, str]:
    headers = {"Accept": "application/json, text/plain, */*"}
    token = _token()
    if token:
        headers["Authorization"] = (
            token
            if token.lower().startswith("bearer ")
            else f"Bearer {token}"
        )
    return headers


_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {"ts": 0.0, "tree": None}


class MenuClientError(RuntimeError):
    """菜单接口不可用或返回结构异常。"""


def _fetch_raw() -> list[dict]:
    base = _base_url()
    if not base:
        raise MenuClientError(
            "未配置菜单接口地址(INOE_MENU_BASE_URL / INOE_API_BASE_URL)"
        )
    url = f"{base}/admin/menu/getRouters/{_app_code()}"
    timeout = _float_env("INOE_MENU_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
    with httpx.Client(timeout=timeout) as client:
        resp = client.get(url, headers=_build_headers())
        resp.raise_for_status()
        body = resp.json()
    data = body.get("data") if isinstance(body, dict) else body
    if not isinstance(data, list):
        raise MenuClientError(f"菜单接口返回结构异常: {type(data)!r}")
    return data


def get_menu_tree(*, force_refresh: bool = False) -> list[dict]:
    """返回菜单树(``getRouters`` 的 ``data``),命中 TTL 缓存则直接返回。

    拉取失败但有历史缓存时回退到上次成功结果,尽量保证可用性。
    """
    ttl = _float_env("INOE_MENU_CACHE_TTL_SECONDS", DEFAULT_CACHE_TTL_SECONDS)
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get("tree")
        is_fresh = cached is not None and (now - _CACHE["ts"]) < ttl
        if cached is not None and is_fresh and not force_refresh:
            return cached
    try:
        tree = _fetch_raw()
    except Exception as exc:  # noqa: BLE001 - 优先回退陈旧缓存
        with _CACHE_LOCK:
            if _CACHE.get("tree") is not None:
                return _CACHE["tree"]
        raise MenuClientError(f"拉取菜单失败: {exc}") from exc
    with _CACHE_LOCK:
        _CACHE["tree"] = tree
        _CACHE["ts"] = time.monotonic()
    return tree
