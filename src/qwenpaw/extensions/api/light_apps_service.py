# -*- coding: utf-8 -*-
"""统一轻应用货架服务 — 聚合任务应用与页面应用两个来源。

任务应用来自自然语言定制（轻应用工坊上架的固化任务），
页面应用来自应用成果库（我的应用中手动上架的 HTML 应用）。
"""
from __future__ import annotations

from typing import Any

from qwenpaw.extensions import natural_language_customization_registry
from qwenpaw.extensions.api import app_artifacts_service


def _task_app_to_record(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "task",
        "id": str(item.get("versionId") or ""),
        "appId": str(item.get("appId") or ""),
        "title": str(item.get("title") or ""),
        "description": str(item.get("description") or ""),
        "scenarioType": str(item.get("scenarioType") or ""),
        "artifactType": "",
        "tags": [],
        "listedAt": str(item.get("listedAt") or ""),
        "updatedAt": str(item.get("publishedAt") or ""),
        "launch": {
            "type": "chat-dispatch",
            "employeeId": str(item.get("launchEmployeeId") or ""),
            "prompt": str(item.get("launchPrompt") or ""),
            "url": "",
        },
    }


def _page_app_to_record(item: dict[str, Any]) -> dict[str, Any]:
    app_id = str(item.get("id") or "")
    tags = item.get("tags")
    return {
        "kind": "page",
        "id": app_id,
        "appId": "",
        "title": str(item.get("title") or ""),
        "description": str(item.get("description") or ""),
        "scenarioType": "",
        "artifactType": str(item.get("type") or ""),
        "tags": list(tags) if isinstance(tags, list) else [],
        "listedAt": str(item.get("listed_at") or ""),
        "updatedAt": str(item.get("updated_at") or ""),
        "launch": {
            "type": "open-url",
            "employeeId": "",
            "prompt": "",
            "url": f"/portal-api/app-artifacts/{app_id}/preview",
        },
    }


def list_light_apps(*, limit: int = 100) -> list[dict[str, Any]]:
    """列出应用中心货架上的全部轻应用，按上架时间倒序。"""
    records: list[dict[str, Any]] = []

    registry = natural_language_customization_registry
    task_items = registry.list_installed_customization_apps(limit=limit)
    records.extend(_task_app_to_record(item) for item in task_items)

    page_result = app_artifacts_service.list_apps(
        status="published",
        listed=True,
        page=1,
        page_size=limit,
    )
    records.extend(
        _page_app_to_record(item) for item in page_result.get("items", [])
    )

    records.sort(key=lambda record: record["listedAt"], reverse=True)
    if limit > 0:
        return records[:limit]
    return records
