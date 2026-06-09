# -*- coding: utf-8 -*-
"""应用成果发布服务 — SQLite 存储 + 文件管理。"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from qwenpaw.extensions.runtime_data_paths import (
    APP_ARTIFACTS_DATA_DIR,
    APP_ARTIFACTS_DB_PATH,
    APP_ARTIFACTS_HTML_DIR,
    ensure_extension_data_dir,
)

_DB_INITIALIZED = False


def _get_db() -> sqlite3.Connection:
    """获取 SQLite 连接并确保表已创建。"""
    global _DB_INITIALIZED
    ensure_extension_data_dir(APP_ARTIFACTS_DATA_DIR)
    ensure_extension_data_dir(APP_ARTIFACTS_HTML_DIR)

    conn = sqlite3.connect(str(APP_ARTIFACTS_DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    if not _DB_INITIALIZED:
        _init_tables(conn)
        _DB_INITIALIZED = True

    return conn


def _init_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS apps (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            type TEXT NOT NULL DEFAULT 'app',
            status TEXT NOT NULL DEFAULT 'published',
            author TEXT NOT NULL DEFAULT '',
            session_id TEXT,
            html_path TEXT,
            config TEXT,
            tags TEXT NOT NULL DEFAULT '[]',
            version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS app_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            app_id TEXT NOT NULL REFERENCES apps(id) ON DELETE CASCADE,
            version INTEGER NOT NULL,
            html_path TEXT NOT NULL,
            changelog TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS dashboard_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dashboard_id TEXT NOT NULL REFERENCES apps(id) ON DELETE CASCADE,
            widget_id TEXT NOT NULL,
            position_x INTEGER NOT NULL DEFAULT 0,
            position_y INTEGER NOT NULL DEFAULT 0,
            width INTEGER NOT NULL DEFAULT 1,
            height INTEGER NOT NULL DEFAULT 1,
            config TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_apps_type ON apps(type);
        CREATE INDEX IF NOT EXISTS idx_apps_status ON apps(status);
        CREATE INDEX IF NOT EXISTS idx_app_versions_app_id ON app_versions(app_id);
        CREATE INDEX IF NOT EXISTS idx_dashboard_items_dashboard_id ON dashboard_items(dashboard_id);
    """)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _generate_id() -> str:
    return uuid.uuid4().hex[:12]


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def _parse_tags(tags_str: str) -> list[str]:
    try:
        return json.loads(tags_str) if tags_str else []
    except (json.JSONDecodeError, TypeError):
        return []


def _parse_config(config_str: str | None) -> dict[str, Any] | None:
    if not config_str:
        return None
    try:
        return json.loads(config_str)
    except (json.JSONDecodeError, TypeError):
        return None


def _write_html(app_id: str, html_content: str, version: int) -> str:
    """将某个版本的 HTML 写入独立文件，返回相对路径。

    每个版本落到 ``v{version}.html``，新版本不再覆盖旧版本，
    使 ``app_versions`` 记录的 html_path 始终指向当时的真实内容，
    支持历史版本预览与回滚。
    """
    app_dir = APP_ARTIFACTS_HTML_DIR / app_id
    app_dir.mkdir(parents=True, exist_ok=True)
    filename = f"v{version}.html"
    html_file = app_dir / filename
    html_file.write_text(html_content, encoding="utf-8")
    return f"{app_id}/{filename}"


def _delete_html(app_id: str) -> None:
    """删除应用的 HTML 文件。"""
    app_dir = APP_ARTIFACTS_HTML_DIR / app_id
    if app_dir.exists():
        for f in app_dir.iterdir():
            f.unlink()
        app_dir.rmdir()


# ─── Public API ───────────────────────────────────────────────────────────────


def create_app(
    *,
    title: str,
    description: str = "",
    app_type: str = "app",
    html_content: str,
    config: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    session_id: str | None = None,
    author: str = "",
) -> dict[str, Any]:
    """创建并发布一个应用/卡片。"""
    app_id = _generate_id()
    now = _now_iso()
    html_path = _write_html(app_id, html_content, 1)

    conn = _get_db()
    try:
        conn.execute(
            """INSERT INTO apps (id, title, description, type, status, author,
               session_id, html_path, config, tags, version, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'published', ?, ?, ?, ?, ?, 1, ?, ?)""",
            (
                app_id,
                title,
                description,
                app_type,
                author,
                session_id,
                html_path,
                json.dumps(config) if config else None,
                json.dumps(tags or []),
                now,
                now,
            ),
        )
        conn.execute(
            """INSERT INTO app_versions (app_id, version, html_path, changelog, created_at)
               VALUES (?, 1, ?, '初始发布', ?)""",
            (app_id, html_path, now),
        )
        conn.commit()
    finally:
        conn.close()

    return get_app(app_id)  # type: ignore


def get_app(app_id: str) -> dict[str, Any] | None:
    """获取应用详情。"""
    conn = _get_db()
    try:
        row = conn.execute("SELECT * FROM apps WHERE id = ?", (app_id,)).fetchone()
        if row is None:
            return None
        d = _row_to_dict(row)
        d["tags"] = _parse_tags(d.get("tags", "[]"))
        d["config"] = _parse_config(d.get("config"))
        d["url"] = f"/artifacts/{app_id}/"
        return d
    finally:
        conn.close()


def list_apps(
    *,
    app_type: str | None = None,
    status: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """查询应用列表，支持过滤和分页。"""
    conn = _get_db()
    try:
        conditions = []
        params: list[Any] = []

        if app_type:
            conditions.append("type = ?")
            params.append(app_type)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if search:
            conditions.append("(title LIKE ? OR description LIKE ? OR tags LIKE ?)")
            like_val = f"%{search}%"
            params.extend([like_val, like_val, like_val])

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        total_row = conn.execute(
            f"SELECT COUNT(*) as cnt FROM apps {where_clause}", params
        ).fetchone()
        total = total_row["cnt"] if total_row else 0

        offset = (page - 1) * page_size
        rows = conn.execute(
            f"SELECT * FROM apps {where_clause} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()

        items = []
        for row in rows:
            d = _row_to_dict(row)
            d["tags"] = _parse_tags(d.get("tags", "[]"))
            d["config"] = _parse_config(d.get("config"))
            d["url"] = f"/artifacts/{d['id']}/"
            items.append(d)

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    finally:
        conn.close()


def update_app(
    app_id: str,
    *,
    title: str | None = None,
    description: str | None = None,
    html_content: str | None = None,
    config: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    status: str | None = None,
) -> dict[str, Any] | None:
    """更新应用，如果有新 HTML 则创建新版本。"""
    conn = _get_db()
    try:
        existing = conn.execute("SELECT * FROM apps WHERE id = ?", (app_id,)).fetchone()
        if existing is None:
            return None

        now = _now_iso()
        updates = []
        params: list[Any] = []

        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if description is not None:
            updates.append("description = ?")
            params.append(description)
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if tags is not None:
            updates.append("tags = ?")
            params.append(json.dumps(tags))
        if config is not None:
            updates.append("config = ?")
            params.append(json.dumps(config))

        if html_content is not None:
            new_version = existing["version"] + 1
            html_path = _write_html(app_id, html_content, new_version)
            updates.append("html_path = ?")
            params.append(html_path)
            updates.append("version = ?")
            params.append(new_version)
            conn.execute(
                """INSERT INTO app_versions (app_id, version, html_path, changelog, created_at)
                   VALUES (?, ?, ?, '更新发布', ?)""",
                (app_id, new_version, html_path, now),
            )

        if updates:
            updates.append("updated_at = ?")
            params.append(now)
            params.append(app_id)
            conn.execute(
                f"UPDATE apps SET {', '.join(updates)} WHERE id = ?", params
            )
            conn.commit()

        return get_app(app_id)
    finally:
        conn.close()


def delete_app(app_id: str) -> bool:
    """删除应用及其 HTML 文件。"""
    conn = _get_db()
    try:
        existing = conn.execute("SELECT id FROM apps WHERE id = ?", (app_id,)).fetchone()
        if existing is None:
            return False
        conn.execute("DELETE FROM dashboard_items WHERE dashboard_id = ?", (app_id,))
        conn.execute("DELETE FROM app_versions WHERE app_id = ?", (app_id,))
        conn.execute("DELETE FROM apps WHERE id = ?", (app_id,))
        conn.commit()
        _delete_html(app_id)
        return True
    finally:
        conn.close()


def get_app_versions(app_id: str) -> list[dict[str, Any]]:
    """获取应用的版本历史。"""
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM app_versions WHERE app_id = ? ORDER BY version DESC",
            (app_id,),
        ).fetchall()
        return [_row_to_dict(row) for row in rows]
    finally:
        conn.close()


def get_html_content(app_id: str, version: int | None = None) -> str | None:
    """读取应用的 HTML 内容。

    version 为 None 时返回当前版本（apps.html_path）；指定 version
    时返回该历史版本（app_versions.html_path）。按 DB 记录的相对路径
    读取，兼容老数据中指向 ``index.html`` 的记录。
    """
    conn = _get_db()
    try:
        if version is None:
            row = conn.execute(
                "SELECT html_path FROM apps WHERE id = ?", (app_id,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT html_path FROM app_versions WHERE app_id = ? AND version = ?",
                (app_id, version),
            ).fetchone()
    finally:
        conn.close()

    if row is None or not row["html_path"]:
        return None
    html_file = APP_ARTIFACTS_HTML_DIR / row["html_path"]
    if html_file.exists():
        return html_file.read_text(encoding="utf-8")
    return None


def rollback_to_version(app_id: str, version: int) -> dict[str, Any] | None:
    """将应用回滚到指定版本。

    读取目标版本的 HTML 内容,通过 update_app 写回,自动产生新版本号。
    原版本的 HTML 文件不受影响(按 v{n}.html 存储,互不覆盖)。
    """
    html = get_html_content(app_id, version=version)
    if html is None:
        return None
    changelog = f"回滚到 v{version}"
    return update_app(app_id, html_content=html, status="published")


# ─── Dashboard API ────────────────────────────────────────────────────────────


def create_dashboard(
    *,
    title: str,
    description: str = "",
    items: list[dict[str, Any]] | None = None,
    tags: list[str] | None = None,
    session_id: str | None = None,
    author: str = "",
) -> dict[str, Any]:
    """创建仪表盘，关联多个 widget 卡片。"""
    dashboard_id = _generate_id()
    now = _now_iso()

    # Generate an empty HTML page as placeholder (actual rendering is client-side)
    html_content = _build_dashboard_html(title, items or [])
    html_path = _write_html(dashboard_id, html_content, 1)

    conn = _get_db()
    try:
        conn.execute(
            """INSERT INTO apps (id, title, description, type, status, author,
               session_id, html_path, config, tags, version, created_at, updated_at)
               VALUES (?, ?, ?, 'dashboard', 'published', ?, ?, ?, ?, ?, 1, ?, ?)""",
            (
                dashboard_id,
                title,
                description,
                author,
                session_id,
                html_path,
                json.dumps({"layout": "grid"}),
                json.dumps(tags or []),
                now,
                now,
            ),
        )
        conn.execute(
            """INSERT INTO app_versions (app_id, version, html_path, changelog, created_at)
               VALUES (?, 1, ?, '初始创建', ?)""",
            (dashboard_id, html_path, now),
        )

        # Insert widget items
        for item in (items or []):
            conn.execute(
                """INSERT INTO dashboard_items
                   (dashboard_id, widget_id, position_x, position_y, width, height, config)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    dashboard_id,
                    item["widget_id"],
                    item.get("position_x", 0),
                    item.get("position_y", 0),
                    item.get("width", 1),
                    item.get("height", 1),
                    json.dumps(item.get("config")) if item.get("config") else None,
                ),
            )

        conn.commit()
    finally:
        conn.close()

    return get_dashboard(dashboard_id)  # type: ignore


def get_dashboard(dashboard_id: str) -> dict[str, Any] | None:
    """获取仪表盘详情（含关联的 widget 列表）。"""
    conn = _get_db()
    try:
        row = conn.execute("SELECT * FROM apps WHERE id = ? AND type = 'dashboard'", (dashboard_id,)).fetchone()
        if row is None:
            return None
        d = _row_to_dict(row)
        d["tags"] = _parse_tags(d.get("tags", "[]"))
        d["config"] = _parse_config(d.get("config"))
        d["url"] = f"/artifacts/{dashboard_id}/"

        # Fetch widget items
        items_rows = conn.execute(
            "SELECT * FROM dashboard_items WHERE dashboard_id = ? ORDER BY position_y, position_x",
            (dashboard_id,),
        ).fetchall()
        d["items"] = []
        for item_row in items_rows:
            item_d = _row_to_dict(item_row)
            item_d["config"] = _parse_config(item_d.get("config"))
            # Attach widget title
            widget = conn.execute("SELECT title, type FROM apps WHERE id = ?", (item_d["widget_id"],)).fetchone()
            item_d["widget_title"] = widget["title"] if widget else "未知卡片"
            item_d["widget_type"] = widget["type"] if widget else "widget"
            d["items"].append(item_d)

        return d
    finally:
        conn.close()


def update_dashboard_items(
    dashboard_id: str,
    items: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """更新仪表盘的 widget 布局（替换所有 items）。"""
    conn = _get_db()
    try:
        existing = conn.execute(
            "SELECT * FROM apps WHERE id = ? AND type = 'dashboard'", (dashboard_id,)
        ).fetchone()
        if existing is None:
            return None

        now = _now_iso()

        # Delete old items and insert new ones
        conn.execute("DELETE FROM dashboard_items WHERE dashboard_id = ?", (dashboard_id,))
        for item in items:
            conn.execute(
                """INSERT INTO dashboard_items
                   (dashboard_id, widget_id, position_x, position_y, width, height, config)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    dashboard_id,
                    item["widget_id"],
                    item.get("position_x", 0),
                    item.get("position_y", 0),
                    item.get("width", 1),
                    item.get("height", 1),
                    json.dumps(item.get("config")) if item.get("config") else None,
                ),
            )

        # Regenerate dashboard HTML
        new_version = existing["version"] + 1
        html_content = _build_dashboard_html(existing["title"], items)
        html_path = _write_html(dashboard_id, html_content, new_version)

        conn.execute(
            """UPDATE apps SET html_path = ?, version = ?, updated_at = ? WHERE id = ?""",
            (html_path, new_version, now, dashboard_id),
        )
        conn.execute(
            """INSERT INTO app_versions (app_id, version, html_path, changelog, created_at)
               VALUES (?, ?, ?, '布局更新', ?)""",
            (dashboard_id, new_version, html_path, now),
        )

        conn.commit()
    finally:
        conn.close()

    return get_dashboard(dashboard_id)


def list_widgets() -> list[dict[str, Any]]:
    """列出所有可用的 widget 卡片（type = widget 或 app 且 status = published）。"""
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT id, title, description, type, tags, updated_at FROM apps WHERE status = 'published' AND type IN ('widget', 'app') ORDER BY updated_at DESC",
        ).fetchall()
        result = []
        for row in rows:
            d = _row_to_dict(row)
            d["tags"] = _parse_tags(d.get("tags", "[]"))
            result.append(d)
        return result
    finally:
        conn.close()


def _build_dashboard_html(title: str, items: list[dict[str, Any]]) -> str:
    """生成仪表盘 HTML — 使用 iframe 嵌入各 widget。"""
    widget_frames = ""
    for item in items:
        w = item.get("width", 1)
        h = item.get("height", 1)
        widget_id = item.get("widget_id", "")
        widget_frames += f"""
        <div class="dashboard-cell" style="grid-column: span {w}; grid-row: span {h};">
          <iframe src="/portal-api/app-artifacts/{widget_id}/preview"
                  style="width:100%;height:100%;border:none;border-radius:8px;"
                  sandbox="allow-scripts allow-same-origin"
                  loading="lazy"></iframe>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{title}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ background: #0f172a; font-family: system-ui, sans-serif; padding: 20px; min-height: 100vh; }}
.dashboard-header {{ color: #e2e8f0; font-size: 20px; font-weight: 600; margin-bottom: 20px; padding: 8px 0; }}
.dashboard-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; grid-auto-rows: minmax(280px, auto); }}
.dashboard-cell {{ background: rgba(30, 41, 59, 0.6); border-radius: 12px; overflow: hidden; border: 1px solid rgba(148, 163, 184, 0.1); min-height: 280px; }}
@media (max-width: 1200px) {{ .dashboard-grid {{ grid-template-columns: repeat(2, 1fr); }} }}
@media (max-width: 600px) {{ .dashboard-grid {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>
<div class="dashboard-header">{title}</div>
<div class="dashboard-grid">
{widget_frames}
</div>
</body>
</html>"""
