# -*- coding: utf-8 -*-
"""安全加固扩展 (security hardening extensions).

两项能力，均不入侵 qwenpaw 核心代码（仅在 ``app/_app.py`` 启动时调用
一次 :func:`install_security_hardening`）：

* :mod:`output_guard` —— 出口脱敏：所有渠道的出站消息在发送前打码
  凭证/密钥及业务词库命中内容；
* :mod:`high_risk_boundary` —— 高危操作边界一致性校验：启动时核对
  CRITICAL/HIGH 工具守护规则是否都已配置为自动拒绝
  （``security.tool_guard.auto_denied_rules``），缺漏则告警。

每个子步骤独立 try/except，任何失败只记日志，绝不阻断应用启动。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

__all__ = ["install_security_hardening"]


def install_security_hardening() -> None:
    """Install all security hardening hooks. Never raises."""
    try:
        from .output_guard import install as _install_output_guard

        _install_output_guard()
    except Exception:  # pragma: no cover - defensive
        logger.exception("security: output_guard install failed")

    try:
        from .high_risk_boundary import check_auto_deny_coverage

        check_auto_deny_coverage()
    except Exception:  # pragma: no cover - defensive
        logger.exception("security: high-risk boundary check failed")
