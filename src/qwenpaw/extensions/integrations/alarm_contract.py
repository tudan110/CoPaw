# -*- coding: utf-8 -*-
"""Authoritative display maps for the alarm capability contract (v0).

Single source of truth for the alarm domain's severity / status / class
→ human-readable names. The portal integration layer
(:mod:`portal_real_alarms`) and, through it, the AI big-screen consume
these. The ``real-alarm`` skill keeps a byte-identical copy in its
``scripts/utils/alarm_normalizer.py`` because that skill runs as an
offline subprocess which cannot import this package;
``test_alarm_contract_parity`` guards the two against drift until M1
folds the skill onto the shared connector and this module becomes the
sole definition.

Part of the north/south capability-standardization effort — see
``docs/solution-design/南北向接口标准化-方案与风险评估.md`` and
``docs/solution-design/capability-contracts/alarm.v0.md``.

This module holds data only (no imports, no logic) so any consumer —
including a future subprocess/connector — can depend on it cheaply.
"""

from __future__ import annotations

# Severity code → human-readable Chinese name (displayed as ``levelName``).
SEVERITY_TO_NAME = {
    "1": "紧急",
    "2": "严重",
    "3": "普通",
    "4": "预警",
}

# Alarm status code → human-readable Chinese name (displayed as ``statusName``).
STATUS_TO_NAME = {
    "0": "自动清除",
    "1": "活跃",
    "2": "同步清除",
    "3": "手工清除",
}

# Alarm class code → human-readable Chinese name (displayed as ``className``).
CLASS_TO_NAME = {
    "sys_log": "设备告警",
    "threshold": "性能告警",
    "derivative": "衍生告警",
}

# Severity code → internal English tone token feeding the ``level`` field
# (NOT the display name ``levelName``). Integration-only: the skill has no
# equivalent, so this map is intentionally excluded from the parity test.
SEVERITY_TO_LEVEL = {
    "1": "critical",
    "2": "urgent",
    "3": "warning",
}
