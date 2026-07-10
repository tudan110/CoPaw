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

# zgops-cmdb.env removed: ZGOPS_* is now materialized from the settings
# store (see materialize_zgops_to_environ) like INOE — no static file.
SHARED_SECRET_FILES = ("n9e.env",)

# settings-store field key -> resolver attribute on inoe_settings_store.
# The resolved value is written to the field's ``env_var`` (the name skills
# and other consumers read via ``os.getenv``).
_INOE_GETTERS = {
    "inoe_api_base_url": "get_base_url",
    "inoe_api_token": "get_token",
    "inoe_api_timeout_seconds": "get_timeout_seconds",
    "inoe_enable_curl_fallback": "get_enable_curl_fallback",
    # Menu / page-navigation API (page-navigator getRouters). Resolved from
    # the same ``inoe`` namespace and written to the INOE_MENU_* env vars the
    # skill subprocess reads.
    "inoe_menu_base_url": "get_menu_base_url",
    "inoe_menu_token": "get_menu_token",
    "inoe_menu_app_code": "get_menu_app_code",
    "inoe_menu_timeout_seconds": "get_menu_timeout_seconds",
    "inoe_menu_cache_ttl_seconds": "get_menu_cache_ttl_seconds",
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


# diagnosis-namespace fields that a skill subprocess consumes via env and
# therefore must be materialised into ``os.environ`` (same as INOE). Most
# diagnosis fields are read by the portal main process and don't need this.
# Covers the analyst skills' metric-fetch knobs (alarm-analyst +
# inspection-analyst).
_ALARM_ANALYST_KEYS = (
    "alarm_analyst_metric_timeout_seconds",
    "alarm_analyst_metric_page_size",
    "alarm_analyst_disposal_detail_mode",
    "inspection_metric_timeout_seconds",
    "inspection_metric_page_size",
)


def materialize_alarm_analyst_to_environ(
    *,
    force: bool = False,
    db_path: Optional[Path] = None,
) -> None:
    """Push analyst-skill metric settings into ``os.environ``.

    alarm-analyst / inspection-analyst read ``*_METRIC_*`` via ``os.getenv``
    in a subprocess, so the settings-page (diagnosis store) values only
    reach them once materialised here. Same precedence as
    :func:`materialize_inoe_to_environ`: override forced, otherwise
    ``setdefault``; empty values skipped.
    """
    try:
        from qwenpaw.extensions.api import diagnosis_settings_store as diag
    except Exception:  # noqa: BLE001 - never break secret loading
        return

    kwargs = {} if db_path is None else {"db_path": db_path}
    for key in _ALARM_ANALYST_KEYS:
        spec = diag.FIELD_SPECS.get(key)
        if spec is None:
            continue
        try:
            value = str(spec.resolve(**kwargs)).strip()
        except Exception:  # noqa: BLE001 - one bad field must not block rest
            continue
        if not value:
            continue
        if force or diag.has_override(key, **kwargs):
            os.environ[spec.env_var] = value
        else:
            os.environ.setdefault(spec.env_var, value)


def refresh_alarm_analyst_environ(*, db_path: Optional[Path] = None) -> None:
    """Re-materialise alarm-analyst metric settings after a save/reset."""
    materialize_alarm_analyst_to_environ(force=True, db_path=db_path)


def materialize_zgops_to_environ(
    *,
    force: bool = False,
    db_path: Optional[Path] = None,
) -> None:
    """Push the zgops CMDB connection into ``os.environ``.

    The zgops-cmdb skills read ``ZGOPS_*`` via ``os.getenv`` (python) or an
    inherited env (shell ``_env.sh``, once the static secrets file is gone).
    Same precedence as :func:`materialize_inoe_to_environ`.
    """
    try:
        from qwenpaw.extensions.api import zgops_settings_store as zg
    except Exception:  # noqa: BLE001 - never break secret loading
        return

    kwargs = {} if db_path is None else {"db_path": db_path}
    for key, spec in zg.ZGOPS_FIELD_SPECS.items():
        try:
            value = zg.resolve_text(spec.env_var, **kwargs).strip()
        except Exception:  # noqa: BLE001 - one bad field must not block rest
            continue
        if not value:
            continue
        if force or zg.has_override(key, **kwargs):
            os.environ[spec.env_var] = value
        else:
            os.environ.setdefault(spec.env_var, value)


def refresh_zgops_environ(*, db_path: Optional[Path] = None) -> None:
    """Re-materialise zgops settings after a save/reset."""
    materialize_zgops_to_environ(force=True, db_path=db_path)


def materialize_operator_to_environ(
    *,
    force: bool = False,
    db_path: Optional[Path] = None,
) -> None:
    """Push the operator (page-operator) menu connection into ``os.environ``.

    The page-operator skill reads ``OPERATOR_MENU_*`` via ``os.getenv`` in a
    subprocess (falling back to ``INOE_MENU_*`` / ``INOE_API_*``), so the
    settings-page values only reach it once materialised here. Same precedence
    as :func:`materialize_inoe_to_environ`: override forced, otherwise
    ``setdefault``; empty values skipped.
    """
    try:
        from qwenpaw.extensions.api import operator_settings_store as op
    except Exception:  # noqa: BLE001 - never break secret loading
        return

    kwargs = {} if db_path is None else {"db_path": db_path}
    for key, spec in op.OPERATOR_FIELD_SPECS.items():
        try:
            value = op.resolve_text(spec.env_var, **kwargs).strip()
        except Exception:  # noqa: BLE001 - one bad field must not block rest
            continue
        if not value:
            continue
        if force or op.has_override(key, **kwargs):
            os.environ[spec.env_var] = value
        else:
            os.environ.setdefault(spec.env_var, value)


def refresh_operator_environ(*, db_path: Optional[Path] = None) -> None:
    """Re-materialise operator settings after a save/reset."""
    materialize_operator_to_environ(force=True, db_path=db_path)


def materialize_order_to_environ(
    *,
    force: bool = False,
    db_path: Optional[Path] = None,
) -> None:
    """Push the work-order (ferry) connection into ``os.environ``.

    The order-workflow skill reads ``ORDER_API_BASE_URL`` / ``ORDER_*`` via
    ``os.getenv`` in a subprocess (falling back to ``INOE_API_BASE_URL`` /
    ``INOE_API_TOKEN`` when unset), so the settings-page values only reach it
    once materialised here. Same precedence as
    :func:`materialize_inoe_to_environ`: override forced, otherwise
    ``setdefault``; empty values skipped so the INOE fallback still applies.
    """
    try:
        from qwenpaw.extensions.api import order_settings_store as order
    except Exception:  # noqa: BLE001 - never break secret loading
        return

    kwargs = {} if db_path is None else {"db_path": db_path}
    for key, spec in order.ORDER_FIELD_SPECS.items():
        try:
            value = order.resolve_text(spec.env_var, **kwargs).strip()
        except Exception:  # noqa: BLE001 - one bad field must not block rest
            continue
        if not value:
            continue
        if force or order.has_override(key, **kwargs):
            os.environ[spec.env_var] = value
        else:
            os.environ.setdefault(spec.env_var, value)


def refresh_order_environ(*, db_path: Optional[Path] = None) -> None:
    """Re-materialise work-order settings after a save/reset."""
    materialize_order_to_environ(force=True, db_path=db_path)


_RIL_SUFFIXES = ("_BASE_URL", "_API_KEY", "_MODEL", "_VISION_MODEL")


def materialize_resource_import_llm_to_environ(
    *,
    force: bool = False,
    db_path: Optional[Path] = None,
) -> None:
    """Expand the resource-import LLM pool into ``os.environ``.

    The pool is a variable-length list; it materialises as
    ``RESOURCE_IMPORT_LLM_BASE_URL`` (#1), ``RESOURCE_IMPORT_LLM_2_*`` (#2)…
    plus the two scalars. On startup with an empty DB pool we leave env
    untouched (static secrets / real exports stand); once the pool exists in
    the DB (or on a forced post-save refresh) the DB is authoritative, so we
    clear any stale ``RESOURCE_IMPORT_LLM_*`` rows first to avoid leftovers
    when a model is removed.
    """
    try:
        from qwenpaw.extensions.api import (
            resource_import_llm_settings_api as llm,
        )
    except Exception:  # noqa: BLE001 - never break secret loading
        return

    kwargs = {} if db_path is None else {"db_path": db_path}
    try:
        models = llm.get_resolved_models(**kwargs)
        scalars = llm.get_resolved_scalars(**kwargs)
    except Exception:  # noqa: BLE001
        return

    if not force and not models:
        return  # nothing in DB; don't disturb static env / secrets file

    for env_key in list(os.environ):
        if env_key.startswith("RESOURCE_IMPORT_LLM_") and env_key.endswith(
            _RIL_SUFFIXES
        ):
            os.environ.pop(env_key, None)

    for index, model in enumerate(models, start=1):
        prefix = (
            "RESOURCE_IMPORT_LLM_"
            if index == 1
            else f"RESOURCE_IMPORT_LLM_{index}_"
        )
        if model.get("base_url"):
            os.environ[prefix + "BASE_URL"] = model["base_url"]
        if model.get("model"):
            os.environ[prefix + "MODEL"] = model["model"]
        if model.get("api_key"):
            os.environ[prefix + "API_KEY"] = model["api_key"]
        if model.get("vision_model"):
            os.environ[prefix + "VISION_MODEL"] = model["vision_model"]

    os.environ["RESOURCE_IMPORT_LLM_SHEET_PARALLELISM"] = str(
        scalars["sheet_parallelism"]
    )
    os.environ["RESOURCE_IMPORT_LLM_STEP_TIMEOUT"] = str(
        scalars["step_timeout"]
    )


def refresh_resource_import_llm_environ(
    *,
    db_path: Optional[Path] = None,
) -> None:
    """Re-materialise the resource-import LLM pool after a save."""
    materialize_resource_import_llm_to_environ(force=True, db_path=db_path)


def materialize_n9e_to_environ(
    *,
    force: bool = False,
    db_path: Optional[Path] = None,
) -> None:
    """Push the Nightingale (N9E) log connection into ``os.environ``.

    The log skills read ``N9E_*`` via ``os.getenv`` (env preferred over the
    ``.env`` fallback). Same precedence as :func:`materialize_inoe_to_environ`.
    """
    try:
        from qwenpaw.extensions.api import n9e_settings_store as n9e
    except Exception:  # noqa: BLE001 - never break secret loading
        return

    kwargs = {} if db_path is None else {"db_path": db_path}
    for key, spec in n9e.N9E_FIELD_SPECS.items():
        try:
            value = n9e.resolve_text(spec.env_var, **kwargs).strip()
        except Exception:  # noqa: BLE001 - one bad field must not block rest
            continue
        if not value:
            continue
        if force or n9e.has_override(key, **kwargs):
            os.environ[spec.env_var] = value
        else:
            os.environ.setdefault(spec.env_var, value)


def refresh_n9e_environ(*, db_path: Optional[Path] = None) -> None:
    """Re-materialise N9E settings after a save/reset."""
    materialize_n9e_to_environ(force=True, db_path=db_path)


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
    materialize_alarm_analyst_to_environ(force=False)
    materialize_zgops_to_environ(force=False)
    materialize_operator_to_environ(force=False)
    materialize_order_to_environ(force=False)
    materialize_resource_import_llm_to_environ(force=False)
    materialize_n9e_to_environ(force=False)
