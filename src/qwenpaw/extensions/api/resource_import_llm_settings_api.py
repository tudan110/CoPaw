# -*- coding: utf-8 -*-
"""Settings-page store for the resource-import LLM pool.

``resource_import.py`` reads a dynamic pool of OpenAI-compatible models
from ``RESOURCE_IMPORT_LLM_*`` / ``RESOURCE_IMPORT_LLM_2_*`` … env vars
(round-robin per sheet) plus two tuning scalars. This module persists that
pool (variable-length list + scalars) in :mod:`settings_store` as JSON, so
it can be edited on the settings page; :mod:`working_secrets` materialises
it back into ``os.environ`` for the resource-import subprocess.

Stored shape (namespace ``resource_import_llm``)::

    scalars -> {"sheet_parallelism": int, "step_timeout": int}
    models  -> [ {"base_url", "api_key", "model", "vision_model"}, ... ]

Sensitive ``api_key`` is masked on read; an empty/masked value on write
keeps the previously stored key at the same row index.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from qwenpaw.extensions.api import settings_store
from qwenpaw.extensions.api.diagnosis_settings_store import (
    CLEAR_SENTINEL,
    mask_token,
)
from qwenpaw.extensions.runtime_data_paths import (
    SETTINGS_DB_PATH as DEFAULT_DB_PATH,
)

_NAMESPACE = "resource_import_llm"

DEFAULT_SHEET_PARALLELISM = 4
DEFAULT_STEP_TIMEOUT = 45

__all__ = [
    "CLEAR_SENTINEL",
    "build_settings_payload",
    "apply_settings_update",
    "get_resolved_scalars",
    "get_resolved_models",
]


def _load(db_path: Path) -> dict[str, Any]:
    return settings_store.get_namespace(_NAMESPACE, db_path=db_path)


def _resolved_scalars(data: dict[str, Any]) -> dict[str, int]:
    raw = data.get("scalars") or {}
    try:
        par = max(
            1, int(raw.get("sheet_parallelism", DEFAULT_SHEET_PARALLELISM))
        )
    except (TypeError, ValueError):
        par = DEFAULT_SHEET_PARALLELISM
    try:
        timeout = max(1, int(raw.get("step_timeout", DEFAULT_STEP_TIMEOUT)))
    except (TypeError, ValueError):
        timeout = DEFAULT_STEP_TIMEOUT
    return {"sheet_parallelism": par, "step_timeout": timeout}


def _resolved_models(data: dict[str, Any]) -> list[dict[str, str]]:
    models = data.get("models")
    if not isinstance(models, list):
        return []
    out: list[dict[str, str]] = []
    for item in models:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "base_url": str(item.get("base_url") or "").strip(),
                "api_key": str(item.get("api_key") or "").strip(),
                "model": str(item.get("model") or "").strip(),
                "vision_model": str(item.get("vision_model") or "").strip(),
            }
        )
    return out


def get_resolved_scalars(*, db_path: Path = DEFAULT_DB_PATH) -> dict[str, int]:
    return _resolved_scalars(_load(db_path))


def get_resolved_models(
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> list[dict[str, str]]:
    """Plain (unmasked) models, for materialisation into os.environ."""
    return _resolved_models(_load(db_path))


def build_settings_payload(
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """``{scalars, models}`` with each model's api_key masked."""
    data = _load(db_path)
    masked_models = []
    for m in _resolved_models(data):
        masked_models.append(
            {
                "base_url": m["base_url"],
                "model": m["model"],
                "vision_model": m["vision_model"],
                "api_key": {
                    "is_set": bool(m["api_key"]),
                    "masked": mask_token(m["api_key"]),
                },
            }
        )
    return {
        "scalars": _resolved_scalars(data),
        "models": masked_models,
    }


def _coerce_api_key(
    raw: Any,
    *,
    index: int,
    existing: list[dict[str, str]],
) -> str:
    """Resolve a row's api_key: explicit value wins, blank/masked keeps the
    stored one at the same index, ``CLEAR_SENTINEL`` clears it."""
    if raw == CLEAR_SENTINEL:
        return ""
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    # blank, None, or a masked-secret echo -> keep existing at this index
    if index < len(existing):
        return existing[index].get("api_key", "")
    return ""


def apply_settings_update(
    body: dict[str, Any],
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """Replace the whole pool from ``{scalars?, models?}``.

    Raises ``ValueError`` on invalid input (mapped to HTTP 400 by caller).
    """
    if not isinstance(body, dict):
        raise ValueError("Request body must be a JSON object")
    existing_models = _resolved_models(_load(db_path))

    scalars_in = body.get("scalars") or {}
    scalars = _resolved_scalars({"scalars": scalars_in})

    models_in = body.get("models")
    if models_in is None:
        models_in = []
    if not isinstance(models_in, list):
        raise ValueError("models must be a list")

    models: list[dict[str, str]] = []
    for index, item in enumerate(models_in):
        if not isinstance(item, dict):
            raise ValueError("each model must be an object")
        base_url = str(item.get("base_url") or "").strip()
        model = str(item.get("model") or "").strip()
        vision = str(item.get("vision_model") or "").strip()
        api_key = _coerce_api_key(
            item.get("api_key"), index=index, existing=existing_models
        )
        # drop fully-empty rows
        if not base_url and not model and not api_key and not vision:
            continue
        models.append(
            {
                "base_url": base_url,
                "api_key": api_key,
                "model": model,
                "vision_model": vision,
            }
        )

    settings_store.replace_namespace(
        _NAMESPACE,
        {"scalars": scalars, "models": models},
        db_path=db_path,
    )
