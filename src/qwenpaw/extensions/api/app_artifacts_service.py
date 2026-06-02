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


def _write_html(app_id: str, html_content: str) -> str:
    """将 HTML 内容写入文件，返回相对路径。"""
    app_dir = APP_ARTIFACTS_HTML_DIR / app_id
    app_dir.mkdir(parents=True, exist_ok=True)
    html_file = app_dir / "index.html"
    html_file.write_text(html_content, encoding="utf-8")
    return f"{app_id}/index.html"


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
    html_path = _write_html(app_id, html_content)

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
            html_path = _write_html(app_id, html_content)
            new_version = existing["version"] + 1
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


def get_html_content(app_id: str) -> str | None:
    """读取应用的 HTML 内容。"""
    html_file = APP_ARTIFACTS_HTML_DIR / app_id / "index.html"
    if html_file.exists():
        return html_file.read_text(encoding="utf-8")
    return None
