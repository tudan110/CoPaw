"""Shared secrets loader for the internal working/secrets directory.

Loads consolidated credential files (e.g. ``secrets/inoe.env``) into
``os.environ`` once at import, so portal backend integrations *and* skill
subprocesses spawned by an agent inherit a single source of truth. Values
already present in the environment (real exports, the qwenpaw env store)
always win, and per-skill ``.env`` files keep working as standalone
overrides.
"""

from __future__ import annotations

import os
from pathlib import Path

from qwenpaw.constant import WORKING_DIR

SHARED_SECRET_FILES = ("inoe.env",)

_LOADED = False


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(
            key.strip(),
            value.strip().strip('"').strip("'"),
        )


def ensure_working_secrets_loaded() -> None:
    """Inject ``WORKING_DIR/secrets/<file>`` into ``os.environ`` once."""
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    secrets_dir = Path(WORKING_DIR).expanduser() / "secrets"
    for name in SHARED_SECRET_FILES:
        _load_env_file(secrets_dir / name)
