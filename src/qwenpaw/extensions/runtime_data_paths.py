# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from qwenpaw.constant import WORKING_DIR

EXTENSIONS_DATA_DIR = WORKING_DIR / "extensions"

# Shared home for all user-facing settings, persisted in one SQLite DB
# with one table namespaced per concern (diagnosis, notification, ...).
SETTINGS_DATA_DIR = EXTENSIONS_DATA_DIR / "settings"
SETTINGS_DB_FILE = "settings.db"
SETTINGS_DB_PATH = SETTINGS_DATA_DIR / SETTINGS_DB_FILE

NOTIFICATIONS_DATA_DIR = EXTENSIONS_DATA_DIR / "notifications"
NOTIFICATIONS_SETTINGS_FILE = "settings.json"
NOTIFICATIONS_SETTINGS_PATH = (
    NOTIFICATIONS_DATA_DIR / NOTIFICATIONS_SETTINGS_FILE
)

PORTAL_REAL_ALARM_DATA_DIR = EXTENSIONS_DATA_DIR / "portal_real_alarm"
PORTAL_REAL_ALARM_REGISTRY_FILE = "portal_real_alarm_registry.json"
PORTAL_REAL_ALARM_REGISTRY_PATH = (
    PORTAL_REAL_ALARM_DATA_DIR / PORTAL_REAL_ALARM_REGISTRY_FILE
)
PORTAL_REAL_ALARM_REGISTRY_DB_FILE = "portal_real_alarm_registry.db"
PORTAL_REAL_ALARM_REGISTRY_DB_PATH = (
    PORTAL_REAL_ALARM_DATA_DIR / PORTAL_REAL_ALARM_REGISTRY_DB_FILE
)
PORTAL_ALARM_ANALYST_CARDS_DB_FILE = "alarm_analyst_cards.db"
PORTAL_ALARM_ANALYST_CARDS_DB_PATH = (
    PORTAL_REAL_ALARM_DATA_DIR / PORTAL_ALARM_ANALYST_CARDS_DB_FILE
)

# Agent-generated report files (inspection reports, exported sheets, ...)
# land here, one subdirectory per agent id; written by the report-export
# skill and served back to the portal by extensions.api.agent_reports.
REPORTS_DATA_DIR = EXTENSIONS_DATA_DIR / "reports"

NL_CUSTOMIZATION_DATA_DIR = EXTENSIONS_DATA_DIR / "nl_customization"
NL_CUSTOMIZATION_REGISTRY_FILE = "registry.json"
NL_CUSTOMIZATION_BUNDLE_DIRNAME = "bundles"
NL_CUSTOMIZATION_ACTIVE_FILE = "active.json"
NL_CUSTOMIZATION_REGISTRY_PATH = (
    NL_CUSTOMIZATION_DATA_DIR / NL_CUSTOMIZATION_REGISTRY_FILE
)
NL_CUSTOMIZATION_BUNDLE_DIR = (
    NL_CUSTOMIZATION_DATA_DIR / NL_CUSTOMIZATION_BUNDLE_DIRNAME
)
NL_CUSTOMIZATION_ACTIVE_PATH = (
    NL_CUSTOMIZATION_DATA_DIR / NL_CUSTOMIZATION_ACTIVE_FILE
)

APP_ARTIFACTS_DATA_DIR = EXTENSIONS_DATA_DIR / "app_artifacts"
APP_ARTIFACTS_DB_FILE = "artifacts.db"
APP_ARTIFACTS_DB_PATH = APP_ARTIFACTS_DATA_DIR / APP_ARTIFACTS_DB_FILE
APP_ARTIFACTS_HTML_DIR = APP_ARTIFACTS_DATA_DIR / "html"
APP_ARTIFACTS_THUMBNAILS_DIR = APP_ARTIFACTS_DATA_DIR / "thumbnails"

AI_BIG_SCREEN_DATA_DIR = EXTENSIONS_DATA_DIR / "ai_big_screen"
AI_BIG_SCREEN_REGISTRY_FILE = "registry.json"
AI_BIG_SCREEN_REGISTRY_PATH = (
    AI_BIG_SCREEN_DATA_DIR / AI_BIG_SCREEN_REGISTRY_FILE
)
# SQLite home (M1): screens + versions + draft tasks. The legacy
# registry.json is kept as a one-time migration source.
AI_BIG_SCREEN_DB_FILE = "ai_big_screen.sqlite3"
AI_BIG_SCREEN_DB_PATH = AI_BIG_SCREEN_DATA_DIR / AI_BIG_SCREEN_DB_FILE

PROXY_DATASOURCES_DATA_DIR = EXTENSIONS_DATA_DIR / "proxy_datasources"
PROXY_DATASOURCES_CONFIG_FILE = "config.json"
PROXY_DATASOURCES_CONFIG_PATH = (
    PROXY_DATASOURCES_DATA_DIR / PROXY_DATASOURCES_CONFIG_FILE
)


def ensure_extension_data_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
