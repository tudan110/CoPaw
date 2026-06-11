# -*- coding: utf-8 -*-
"""Agent report listing + download endpoints.

Reports are runtime artifacts written by the ``report-export`` skill to
``EXTENSIONS_DATA_DIR/reports/{agent_id}/`` (see ``runtime_data_paths``).
This router exposes them to the portal:

- ``GET  /agents/{agent_id}/reports`` — list one agent's reports
- ``GET  /agents/{agent_id}/reports/{filename}`` — download one report
  (``Content-Disposition: attachment`` so a plain link click downloads)

The router is included by ``portal_backend``'s router, so the full
public paths are ``/api/portal/agents/{agent_id}/reports[/...]``; the
portal frontend reaches them through its ``/portal-api`` reverse proxy.

Security: ``agent_id`` and ``filename`` are validated against strict
patterns, the resolved file must stay inside the agent's report
directory (no traversal, no symlink escape), and only whitelisted
report extensions are served.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from qwenpaw.extensions import runtime_data_paths

router = APIRouter(tags=["agent-reports"])

_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
# Reject path separators and hidden/dot files; the suffix whitelist below
# bounds what can be served regardless of how the file landed there.
_FILENAME_RE = re.compile(r"^[^/\\]+$")

ALLOWED_REPORT_SUFFIXES = {".md", ".pdf", ".docx", ".xlsx", ".pptx"}

_MEDIA_TYPES = {
    ".md": "text/markdown; charset=utf-8",
    ".pdf": "application/pdf",
    ".docx": (
        "application/vnd.openxmlformats-officedocument"
        ".wordprocessingml.document"
    ),
    ".xlsx": (
        "application/vnd.openxmlformats-officedocument" ".spreadsheetml.sheet"
    ),
    ".pptx": (
        "application/vnd.openxmlformats-officedocument"
        ".presentationml.presentation"
    ),
}


@dataclass
class _ResolvedReport:
    path: Path
    suffix: str


def _agent_reports_dir(agent_id: str) -> Path:
    if not _AGENT_ID_RE.match(agent_id or ""):
        raise HTTPException(status_code=400, detail="Invalid agent id")
    return runtime_data_paths.REPORTS_DATA_DIR / agent_id


def _resolve_report(agent_id: str, filename: str) -> _ResolvedReport:
    reports_dir = _agent_reports_dir(agent_id)
    if not _FILENAME_RE.match(filename or "") or filename.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid filename")
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_REPORT_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail="Unsupported report format",
        )
    path = (reports_dir / filename).resolve()
    try:
        path.relative_to(reports_dir.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid path") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Report not found")
    return _ResolvedReport(path=path, suffix=suffix)


@router.get("/agents/{agent_id}/reports")
async def list_agent_reports(agent_id: str) -> dict[str, Any]:
    """List one agent's downloadable reports, newest first."""
    reports_dir = _agent_reports_dir(agent_id)
    items: list[dict[str, Any]] = []
    if reports_dir.is_dir():
        for path in reports_dir.iterdir():
            if (
                not path.is_file()
                or path.name.startswith(".")
                or path.suffix.lower() not in ALLOWED_REPORT_SUFFIXES
            ):
                continue
            stat = path.stat()
            items.append(
                {
                    "name": path.name,
                    "format": path.suffix.lower().lstrip("."),
                    "size": stat.st_size,
                    "modified_at": stat.st_mtime,
                    "download_path": (
                        f"/api/portal/agents/{agent_id}/reports/{path.name}"
                    ),
                },
            )
    items.sort(key=lambda item: item["modified_at"], reverse=True)
    return {"agent_id": agent_id, "reports": items}


@router.get("/agents/{agent_id}/reports/{filename}")
async def download_agent_report(agent_id: str, filename: str) -> FileResponse:
    """Stream one report file as a browser download."""
    resolved = _resolve_report(agent_id, filename)
    return FileResponse(
        resolved.path,
        media_type=_MEDIA_TYPES.get(
            resolved.suffix,
            "application/octet-stream",
        ),
        filename=resolved.path.name,
        content_disposition_type="attachment",
    )
