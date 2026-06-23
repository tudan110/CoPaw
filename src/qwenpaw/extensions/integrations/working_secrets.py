"""Shared secrets loader for the internal working/secrets directory.

Loads consolidated credential files (e.g. ``secrets/n9e.env``) into
``os.environ`` once at import, so portal backend integrations *and* skill
subprocesses spawned by an agent inherit a single source of truth. Values
already present in the environment (real exports, the qwenpaw env store)
always win, and per-skill ``.env`` files keep working as standalone
overrides.

The INOE connection no longer ships a static ``secrets/inoe.env``: its
token / base URL / timeout / curl-fallback are resolved from the settings
store (see below) and materialised into ``os.environ`` directly.

On top of the static files, the INOE gateway connection (base URL / token
/ timeout) is *materialised* from :mod:`inoe_settings_store` — the
DB-backed, settings-page-editable single source of truth. This is what
makes the image environment-agnostic: skills no longer ship a per-skill
``.env`` with a baked-in gateway address. Instead the value is resolved at
runtime and pushed into ``os.environ`` (which skill subprocesses inherit),
chosen per-environment via the settings page rather than at package time.

Resolution / precedence pushed into ``os.environ``:

    settings-page override (DB)  ->  forced into os.environ
    no override                  ->  setdefault (real exports / secrets
                                     file / docker -e keep winning)
    empty resolved value         ->  skipped (never wipe a live credential)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from qwenpaw.constant import WORKING_DIR

SHARED_SECRET_FILES = ("n9e.env", "zgops-cmdb.env")

# settings-store field key -> resolver attribute on inoe_settings_store.
# The resolved value is written to the field's ``env_var`` (the name skills
# and other consumers read via ``os.getenv``).
_INOE_GETTERS = {
    "inoe_api_base_url": "get_base_url",
    "inoe_api_token": "get_token",
    "inoe_api_timeout_seconds": "get_timeout_seconds",
    "inoe_enable_curl_fallback": "get_enable_curl_fallback",
}

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


def materialize_inoe_to_environ(
    *,
    force: bool = False,
    db_path: Optional[Path] = None,
) -> None:
    """Push the resolved INOE connection into ``os.environ``.

    For each INOE field, resolve the effective value through
    :mod:`inoe_settings_store` (settings-page override -> env -> default)
    and write it under the field's ``env_var`` so skill subprocesses, which
    only read ``os.getenv("INOE_API_BASE_URL")`` / ``INOE_API_TOKEN``,
    inherit it without any per-skill ``.env``.

    Precedence:

    * a settings-page override always wins (written even over an existing
      env value), so changes made in the UI take effect immediately;
    * otherwise ``setdefault`` is used so real exports / the static secrets
      file / ``docker -e`` keep winning;
    * an empty resolved value is skipped, so we never clobber a live
      credential with a blank (e.g. an unset token).

    ``force=True`` rewrites every non-empty value unconditionally — used
    right after a settings-page save/reset so the next skill subprocess
    inherits the change. (A reset to a value with no env/default fallback
    leaves the previous value in ``os.environ`` until the process restarts;
    this is the only residual case and an intentionally narrow one.)
    """
    try:
        from qwenpaw.extensions.api import inoe_settings_store
    except Exception:  # noqa: BLE001 - never break secret loading
        return

    kwargs = {} if db_path is None else {"db_path": db_path}
    for key, spec in inoe_settings_store.INOE_FIELD_SPECS.items():
        getter_name = _INOE_GETTERS.get(key)
        if getter_name is None:
            continue
        try:
            getter = getattr(inoe_settings_store, getter_name)
            raw = getter(**kwargs)
        except Exception:  # noqa: BLE001 - one bad field must not block rest
            continue
        # Skills read bools via ``os.getenv(...).lower() in {"1","true",...}``
        # so a bool must materialise as a lowercase "true"/"false" string.
        if spec.kind == "bool":
            value = "true" if raw else "false"
        else:
            value = str(raw).strip()
        if not value:
            continue
        if force or inoe_settings_store.has_override(key, **kwargs):
            os.environ[spec.env_var] = value
        else:
            os.environ.setdefault(spec.env_var, value)


def refresh_inoe_environ(*, db_path: Optional[Path] = None) -> None:
    """Re-materialise INOE settings after a settings-page save/reset.

    Forces the latest resolved values into ``os.environ`` so subsequently
    spawned skill subprocesses inherit them. Safe to call repeatedly.
    """
    materialize_inoe_to_environ(force=True, db_path=db_path)


def ensure_working_secrets_loaded() -> None:
    """Inject ``WORKING_DIR/secrets/<file>`` into ``os.environ`` once.

    Static secret files are loaded first (``setdefault`` semantics), then
    the INOE connection is materialised from the settings store on top —
    so a settings-page override wins over the static file while real
    exports / ``docker -e`` still win when no override exists.
    """
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    secrets_dir = Path(WORKING_DIR).expanduser() / "secrets"
    for name in SHARED_SECRET_FILES:
        _load_env_file(secrets_dir / name)
    materialize_inoe_to_environ(force=False)
