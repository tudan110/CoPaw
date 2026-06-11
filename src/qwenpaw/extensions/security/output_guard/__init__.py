# -*- coding: utf-8 -*-
"""出口脱敏 (output guard) —— 聊天回复敏感信息打码.

所有渠道（钉钉/飞书/QQ/Console/...）的出站文本在发送前经过脱敏：

* 内置凭证类 pattern：API key / token / 密码 / 私钥 / JWT / DB 连接串等；
* 业务词库 ``lexicon.yaml``：运维可直接编辑，按 mtime 热加载。

命中片段**就地打码**（如 ``sk-tes***``、``138****5678``），不拦截整条
消息；日志只记录 pattern id，绝不记录原始敏感值。

配置：基准值放在 ``config.json`` 的 ``security.output_guard`` 段；下列
环境变量在设置时**覆盖**对应字段::

    QWENPAW_OUTPUT_GUARD_ENABLED            true(默认) | false
    QWENPAW_OUTPUT_GUARD_MODE               mask(默认) | off
    QWENPAW_OUTPUT_GUARD_LEXICON_PATH       自定义词库路径
    QWENPAW_OUTPUT_GUARD_DISABLED_PATTERNS  逗号分隔的内置 pattern id

接入方式：应用启动时调用一次 :func:`install`（由
``extensions.security.install_security_hardening`` 触发），对所有已注册
channel 类的出站方法做幂等包装；不修改 qwenpaw 渠道核心代码。
"""
from __future__ import annotations

import logging
import re

from .redactor import OutputGuardSettings, mask_value, redact

logger = logging.getLogger(__name__)

__all__ = [
    "OutputGuardSettings",
    "install",
    "load_config",
    "mask_value",
    "redact",
]


def _split_csv(raw: str) -> tuple:
    return tuple(
        x.strip() for x in re.split(r"[,\n;]+", raw or "") if x.strip()
    )


def load_config() -> OutputGuardSettings:
    """Resolve output-guard settings.

    Base values come from ``config.json`` -> ``security.output_guard``;
    the ``QWENPAW_OUTPUT_GUARD_*`` env vars override individual fields
    when set.
    """
    enabled = True
    mode = "mask"
    lexicon_path = ""
    disabled: tuple = ()
    mask_streaming = True

    # 1. base: config.json (security.output_guard)
    try:
        from qwenpaw.config import load_config as _load_app_config

        ogc = _load_app_config().security.output_guard
        enabled = bool(getattr(ogc, "enabled", True))
        cfg_mode = str(getattr(ogc, "mode", "mask") or "mask").strip().lower()
        if cfg_mode in ("mask", "off"):
            mode = cfg_mode
        lexicon_path = str(getattr(ogc, "lexicon_path", "") or "").strip()
        disabled = tuple(
            str(x).strip()
            for x in (getattr(ogc, "disabled_patterns", None) or [])
            if str(x).strip()
        )
        mask_streaming = bool(getattr(ogc, "mask_streaming", True))
    except Exception as exc:  # pragma: no cover - config not ready
        logger.debug(
            "output_guard: no config.json section, using defaults: %s",
            exc,
        )

    # 2. env overrides (highest priority)
    try:
        from qwenpaw.constant import EnvVarLoader

        env_enabled = (
            (EnvVarLoader.get_str("QWENPAW_OUTPUT_GUARD_ENABLED", "") or "")
            .strip()
            .lower()
        )
        if env_enabled in ("true", "1", "yes", "on"):
            enabled = True
        elif env_enabled in ("false", "0", "no", "off"):
            enabled = False
        env_mode = (
            (EnvVarLoader.get_str("QWENPAW_OUTPUT_GUARD_MODE", "") or "")
            .strip()
            .lower()
        )
        if env_mode in ("mask", "off"):
            mode = env_mode
        env_lex = (
            EnvVarLoader.get_str("QWENPAW_OUTPUT_GUARD_LEXICON_PATH", "") or ""
        ).strip()
        if env_lex:
            lexicon_path = env_lex
        env_disabled = (
            EnvVarLoader.get_str(
                "QWENPAW_OUTPUT_GUARD_DISABLED_PATTERNS",
                "",
            )
            or ""
        )
        if env_disabled.strip():
            disabled = _split_csv(env_disabled)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("output_guard: env override read failed: %s", exc)

    return OutputGuardSettings(
        enabled=enabled,
        mode=mode,
        lexicon_path=lexicon_path,
        disabled_patterns=disabled,
        mask_streaming=mask_streaming,
    )


def install() -> None:
    """Wrap all channel classes' outbound methods with the redactor.

    Idempotent; never raises (logs and continues on failure).
    """
    try:
        from . import channel_patch

        channel_patch.install(load_config)
    except Exception:  # pragma: no cover - defensive
        logger.exception("output_guard: install failed")
