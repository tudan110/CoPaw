# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access,unused-argument
"""Tests for the high-risk action boundary (extensions/security).

Covers:
* the new SEC_* custom guard rules (regex behaviour);
* auto-deny vs approval routing through ToolGuardEngine;
* the startup auto-deny coverage check.
"""
from __future__ import annotations

import logging

import pytest

from qwenpaw.extensions.security import high_risk_boundary
from qwenpaw.security.tool_guard.engine import ToolGuardEngine
from qwenpaw.security.tool_guard.guardians import BaseToolGuardian
from qwenpaw.security.tool_guard.guardians.rule_guardian import (
    GuardRule,
    RuleBasedToolGuardian,
)
from qwenpaw.security.tool_guard.models import GuardSeverity


def _make_rule_guardian(rule_dicts):
    """RuleBasedToolGuardian with ONLY the given rules (no disk/config)."""
    guardian = RuleBasedToolGuardian.__new__(RuleBasedToolGuardian)
    BaseToolGuardian.__init__(guardian, name="rule_based_tool_guardian")
    guardian._rules_dir = None
    guardian._extra_rules = []
    guardian._rules = [GuardRule(r) for r in rule_dicts]
    return guardian


# Mirror of the SEC_* rules deployed via security.tool_guard.custom_rules
# (deploy-all/qwenpaw/data/qwenpaw/config.json).
SEC_RULES = [
    {
        "id": "SEC_SQL_DESTRUCTIVE_DDL",
        "category": "command_injection",
        "severity": "CRITICAL",
        "patterns": [
            "(?i)\\bDROP\\s+(TABLE|DATABASE|SCHEMA|INDEX)\\b",
            "(?i)\\bTRUNCATE\\s+(TABLE\\s+)?\\w",
        ],
        "description": "Destructive SQL DDL.",
        "remediation": "Auto-deny.",
    },
    {
        "id": "SEC_SQL_DML_NO_WHERE",
        "category": "command_injection",
        "severity": "HIGH",
        "patterns": [
            "(?i)\\bDELETE\\s+FROM\\s+\\S+(?![^;]*\\bWHERE\\b)",
            "(?i)\\bUPDATE\\s+\\S+\\s+SET\\b(?![^;]*\\bWHERE\\b)",
        ],
        "description": "DELETE/UPDATE without WHERE.",
        "remediation": "Auto-deny.",
    },
    {
        "id": "SEC_SQL_DML_WRITE",
        "category": "command_injection",
        "severity": "MEDIUM",
        "patterns": [
            "(?i)\\b(DELETE\\s+FROM|UPDATE\\s+\\S+\\s+SET"
            "|ALTER\\s+TABLE)\\b",
        ],
        "description": "SQL data modification.",
        "remediation": "Approval.",
    },
    {
        "id": "SEC_WIN_REGISTRY_WRITE",
        "tools": ["execute_shell_command"],
        "params": ["command"],
        "category": "privilege_escalation",
        "severity": "HIGH",
        "patterns": [
            "(?i)\\breg(\\.exe)?\\s+(add|delete|import)\\b",
            "(?i)\\b(Set|Remove|New)-ItemProperty\\b[^\\n]*\\bHK(LM|CU)",
        ],
        "description": "Windows registry modification.",
        "remediation": "Auto-deny.",
    },
    {
        "id": "SEC_WIN_ACL_CHANGE",
        "tools": ["execute_shell_command"],
        "params": ["command"],
        "category": "privilege_escalation",
        "severity": "HIGH",
        "patterns": [
            "(?i)\\b(icacls|cacls|takeown)\\b",
            "(?i)\\bSet-Acl\\b",
            "(?i)\\bnet\\s+(user|localgroup)\\b[^\\n]*\\s/(add|delete)\\b",
            "(?i)\\bchown\\b",
            "(?i)\\bchmod\\s+[0-7]{3,4}\\b",
        ],
        "description": "Permission/ownership change.",
        "remediation": "Auto-deny.",
    },
]

AUTO_DENIED = {
    "SEC_SQL_DESTRUCTIVE_DDL",
    "SEC_SQL_DML_NO_WHERE",
    "SEC_WIN_REGISTRY_WRITE",
    "SEC_WIN_ACL_CHANGE",
}


@pytest.fixture()
def engine(monkeypatch):
    """Engine with only the SEC_* rules and our auto-deny set."""
    eng = ToolGuardEngine(
        guardians=[_make_rule_guardian(SEC_RULES)],
        enabled=True,
    )
    eng._auto_denied_rules = set(AUTO_DENIED)
    return eng


def _guard(engine, command: str):
    return engine.guard("execute_shell_command", {"command": command})


# ---------------------------------------------------------------------------
# auto-deny routing
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "command,rule_id",
    [
        ("mysql -e 'DROP TABLE users'", "SEC_SQL_DESTRUCTIVE_DDL"),
        ("psql -c 'TRUNCATE TABLE logs'", "SEC_SQL_DESTRUCTIVE_DDL"),
        ("mysql -e 'DELETE FROM users'", "SEC_SQL_DML_NO_WHERE"),
        ("mysql -e 'UPDATE users SET role=1'", "SEC_SQL_DML_NO_WHERE"),
        ("reg add HKLM\\Software\\X /v Y /d Z", "SEC_WIN_REGISTRY_WRITE"),
        ("icacls C:\\data /grant Users:F", "SEC_WIN_ACL_CHANGE"),
        ("net user hacker P@ss /add", "SEC_WIN_ACL_CHANGE"),
        ("chmod 777 /etc/passwd", "SEC_WIN_ACL_CHANGE"),
    ],
)
def test_high_risk_commands_auto_denied(engine, command, rule_id):
    result = _guard(engine, command)
    assert any(f.rule_id == rule_id for f in result.findings)
    assert engine.should_auto_deny_result(result) is True


def test_scoped_delete_routes_to_approval_not_deny(engine):
    """DELETE with WHERE: only the MEDIUM rule fires -> approval path."""
    result = _guard(engine, "mysql -e 'DELETE FROM users WHERE id=1'")
    fired = {f.rule_id for f in result.findings}
    assert fired == {"SEC_SQL_DML_WRITE"}
    assert engine.should_auto_deny_result(result) is False
    assert result.max_severity == GuardSeverity.MEDIUM


def test_scoped_update_routes_to_approval_not_deny(engine):
    result = _guard(
        engine,
        "mysql -e 'UPDATE users SET role=2 WHERE id=1'",
    )
    fired = {f.rule_id for f in result.findings}
    assert fired == {"SEC_SQL_DML_WRITE"}
    assert engine.should_auto_deny_result(result) is False


def test_read_only_sql_untouched(engine):
    result = _guard(engine, "mysql -e 'SELECT * FROM users WHERE id=1'")
    assert not result.findings
    assert engine.should_auto_deny_result(result) is False


def test_sql_rules_apply_to_any_tool(engine):
    """tools: [] means the SQL rules also cover future MCP/DB tools."""
    result = engine.guard("db_query", {"sql": "DROP TABLE users"})
    assert any(f.rule_id == "SEC_SQL_DESTRUCTIVE_DDL" for f in result.findings)


def test_registry_rule_scoped_to_shell_tool(engine):
    result = engine.guard("db_query", {"sql": "reg add HKLM\\X"})
    assert not any(
        f.rule_id == "SEC_WIN_REGISTRY_WRITE" for f in result.findings
    )


# ---------------------------------------------------------------------------
# coverage check
# ---------------------------------------------------------------------------
@pytest.fixture()
def _propagate_logs(monkeypatch):
    """qwenpaw's logger disables propagation; re-enable for caplog."""
    monkeypatch.setattr(logging.getLogger("qwenpaw"), "propagate", True)


def test_coverage_check_warns_on_uncovered_critical(
    monkeypatch,
    caplog,
    _propagate_logs,
):
    guardian = _make_rule_guardian(
        [
            {
                "id": "NEW_CRITICAL_RULE",
                "category": "command_injection",
                "severity": "CRITICAL",
                "patterns": ["x"],
                "description": "d",
            },
        ],
    )
    eng = ToolGuardEngine(guardians=[guardian], enabled=True)
    eng._auto_denied_rules = set()
    monkeypatch.setattr(
        "qwenpaw.security.tool_guard.engine.get_guard_engine",
        lambda: eng,
    )

    with caplog.at_level(logging.WARNING):
        uncovered = high_risk_boundary.check_auto_deny_coverage()
    assert uncovered == ["NEW_CRITICAL_RULE"]
    assert "NEW_CRITICAL_RULE" in caplog.text


def test_coverage_check_ok_with_exemptions(
    monkeypatch,
    caplog,
    _propagate_logs,
):
    guardian = _make_rule_guardian(
        [
            {
                "id": "TOOL_CMD_SERVICE_RESTART",
                "category": "command_injection",
                "severity": "HIGH",
                "patterns": ["x"],
                "description": "d",
            },
            {
                "id": "COVERED_RULE",
                "category": "command_injection",
                "severity": "CRITICAL",
                "patterns": ["y"],
                "description": "d",
            },
        ],
    )
    eng = ToolGuardEngine(guardians=[guardian], enabled=True)
    eng._auto_denied_rules = {"COVERED_RULE"}
    monkeypatch.setattr(
        "qwenpaw.security.tool_guard.engine.get_guard_engine",
        lambda: eng,
    )

    with caplog.at_level(logging.WARNING):
        uncovered = high_risk_boundary.check_auto_deny_coverage()
    assert not uncovered
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_coverage_check_never_raises(monkeypatch):
    def _boom():
        raise RuntimeError("engine exploded")

    monkeypatch.setattr(
        "qwenpaw.security.tool_guard.engine.get_guard_engine",
        _boom,
    )
    assert not high_risk_boundary.check_auto_deny_coverage()
