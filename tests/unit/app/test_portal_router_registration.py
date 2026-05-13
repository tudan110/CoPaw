# -*- coding: utf-8 -*-
"""Ensure portal routes are mounted into the main FastAPI app."""

from qwenpaw.app._app import app


def test_main_app_registers_portal_routes() -> None:
    paths = {route.path for route in app.routes}

    assert "/api/portal/employee-status" in paths
    assert "/api/portal/real-alarms" in paths
    assert "/api/portal/qiming-adapter/v1/models" in paths
