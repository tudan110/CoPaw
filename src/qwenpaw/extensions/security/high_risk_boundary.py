# -*- coding: utf-8 -*-
"""高危操作边界一致性校验 (high-risk boundary coverage check).

本系统的高危边界策略：

* **CRITICAL / HIGH** 级守护规则命中 -> 自动拒绝
  （``security.tool_guard.auto_denied_rules`` 枚举 rule ID）；
* **MEDIUM** 级命中 -> 走 ``/approval`` 人工审批
  （agent 配置 ``approval_level: "SMART"``）。

tool_guard 的自动拒绝是 **rule-ID 制**（没有"按严重度拒绝"机制），
auto_denied_rules 清单会随上游新增规则而过时。本模块在启动时核对
CRITICAL/HIGH 规则集与 auto_denied_rules 的差集，缺漏则记 WARNING，
防止新规则悄悄退化为"仅审批"。

只读校验：不注册 guardian、不改核心代码。豁免清单
（:data:`APPROVAL_INSTEAD_OF_DENY`）记录有意走审批而非拒绝的 HIGH
级规则（网管运维常规动作，如服务重启 / 进程管理）。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

__all__ = ["APPROVAL_INSTEAD_OF_DENY", "check_auto_deny_coverage"]

# HIGH-severity rules that are deliberately NOT auto-denied: routine
# NMS-ops actions where a human approval is the right friction level.
APPROVAL_INSTEAD_OF_DENY: frozenset = frozenset(
    {
        "TOOL_CMD_SERVICE_RESTART",
        "TOOL_CMD_PROCESS_KILL",
    },
)


def check_auto_deny_coverage() -> list:
    """Warn about CRITICAL/HIGH guard rules missing from auto-deny.

    Returns the list of uncovered rule IDs (also logged). Never raises.
    """
    try:
        from qwenpaw.security.tool_guard.engine import get_guard_engine
        from qwenpaw.security.tool_guard.guardians.rule_guardian import (
            RuleBasedToolGuardian,
        )
        from qwenpaw.security.tool_guard.models import GuardSeverity

        engine = get_guard_engine()
        auto_denied = set(engine.auto_denied_rules)

        high_risk_ids: set = set()
        for guardian in getattr(engine, "_guardians", []):
            if not isinstance(guardian, RuleBasedToolGuardian):
                continue
            for rule in guardian.rules:
                if rule.severity in (
                    GuardSeverity.CRITICAL,
                    GuardSeverity.HIGH,
                ):
                    high_risk_ids.add(rule.id)

        uncovered = sorted(
            high_risk_ids - auto_denied - APPROVAL_INSTEAD_OF_DENY,
        )
        if uncovered:
            logger.warning(
                "security: %d CRITICAL/HIGH tool-guard rule(s) are NOT in "
                "security.tool_guard.auto_denied_rules and would fall back "
                "to approval-only: %s",
                len(uncovered),
                ", ".join(uncovered),
            )
        else:
            logger.info(
                "security: high-risk boundary OK "
                "(%d CRITICAL/HIGH rules auto-denied or exempted)",
                len(high_risk_ids),
            )
        return uncovered
    except Exception:  # pragma: no cover - defensive
        logger.exception("security: auto-deny coverage check failed")
        return []
