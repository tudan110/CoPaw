# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from qwenpaw.extensions.api.agent_reports import router

app = FastAPI()
app.include_router(router, prefix="/api/portal")


async def _request(method: str, path: str, **kwargs):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        return await client.request(method, path, **kwargs)


@pytest.fixture(autouse=True)
def reports_root(tmp_path: Path):
    root = tmp_path / "extensions" / "reports"
    with patch(
        "qwenpaw.extensions.runtime_data_paths.REPORTS_DATA_DIR",
        root,
    ):
        yield root


def _write_report(
    root: Path,
    agent_id: str,
    name: str,
    content: bytes = b"# report\n",
) -> Path:
    path = root / agent_id / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


class TestListReports:
    async def test_empty_when_dir_missing(self):
        response = await _request("GET", "/api/portal/agents/gateway/reports")
        assert response.status_code == 200
        assert response.json() == {"agent_id": "gateway", "reports": []}

    async def test_lists_newest_first_with_download_path(
        self,
        reports_root: Path,
    ):
        old = _write_report(reports_root, "gateway", "20260101-0900-a.md")
        new = _write_report(reports_root, "gateway", "20260201-0900-b.pdf")
        import os

        os.utime(old, (1, 1))
        os.utime(new, (2, 2))

        response = await _request("GET", "/api/portal/agents/gateway/reports")
        assert response.status_code == 200
        reports = response.json()["reports"]
        assert [r["name"] for r in reports] == [
            "20260201-0900-b.pdf",
            "20260101-0900-a.md",
        ]
        assert reports[0]["format"] == "pdf"
        assert reports[0]["download_path"] == (
            "/api/portal/agents/gateway/reports/20260201-0900-b.pdf"
        )

    async def test_skips_unsupported_and_hidden_files(
        self,
        reports_root: Path,
    ):
        _write_report(reports_root, "gateway", "report.md")
        _write_report(reports_root, "gateway", "evil.sh")
        _write_report(reports_root, "gateway", ".hidden.md")

        response = await _request("GET", "/api/portal/agents/gateway/reports")
        names = [r["name"] for r in response.json()["reports"]]
        assert names == ["report.md"]

    async def test_rejects_invalid_agent_id(self):
        response = await _request(
            "GET",
            "/api/portal/agents/%2e%2e/reports",
        )
        assert response.status_code == 400


class TestDownloadReport:
    async def test_downloads_as_attachment(self, reports_root: Path):
        _write_report(
            reports_root,
            "gateway",
            "巡检报告.md",
            b"# inspection\n",
        )
        response = await _request(
            "GET",
            "/api/portal/agents/gateway/reports/巡检报告.md",
        )
        assert response.status_code == 200
        assert response.content == b"# inspection\n"
        disposition = response.headers["content-disposition"]
        assert disposition.startswith("attachment")
        assert "text/markdown" in response.headers["content-type"]

    async def test_404_for_missing_file(self):
        response = await _request(
            "GET",
            "/api/portal/agents/gateway/reports/nope.md",
        )
        assert response.status_code == 404

    async def test_rejects_unsupported_extension(self, reports_root: Path):
        _write_report(reports_root, "gateway", "evil.sh")
        response = await _request(
            "GET",
            "/api/portal/agents/gateway/reports/evil.sh",
        )
        assert response.status_code == 400

    async def test_rejects_traversal_filename(self, reports_root: Path):
        secret = reports_root.parent / "secret.md"
        secret.parent.mkdir(parents=True, exist_ok=True)
        secret.write_text("secret")
        response = await _request(
            "GET",
            "/api/portal/agents/gateway/reports/%2e%2e%2fsecret.md",
        )
        assert response.status_code in (400, 404)

    async def test_rejects_symlink_escape(self, reports_root: Path):
        outside = reports_root.parent / "outside.md"
        outside.parent.mkdir(parents=True, exist_ok=True)
        outside.write_text("outside")
        link = reports_root / "gateway" / "link.md"
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(outside)
        response = await _request(
            "GET",
            "/api/portal/agents/gateway/reports/link.md",
        )
        assert response.status_code == 400

    async def test_rejects_dotfile(self, reports_root: Path):
        _write_report(reports_root, "gateway", ".hidden.md")
        response = await _request(
            "GET",
            "/api/portal/agents/gateway/reports/.hidden.md",
        )
        assert response.status_code == 400
