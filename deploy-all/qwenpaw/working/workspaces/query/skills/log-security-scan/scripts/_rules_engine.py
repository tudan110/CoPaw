#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rules engine for log-security-scan.

Loads YAML rule definitions, compiles regex patterns, and provides a single
`scan_text(text, rules)` entry that returns hits with bounded context windows
and a redacted display string. Each hit carries enough metadata for the
caller to aggregate by rule/host/service.

Rule schema (see ../references/security_rules.yml for examples):

    version: 1
    defaults:
      context_chars: 20      # how many chars to keep on each side of a hit
      redact_keep: 2         # for `tail` redaction, how many chars to keep
    rules:
      - id: secret-aws-ak
        name: "AWS Access Key"
        severity: critical|high|medium
        category: secret|pii|injection|crypto
        pattern: '\bAKIA[0-9A-Z]{16}\b'
        flags: [IGNORECASE, MULTILINE]   # optional, default IGNORECASE
        description: "..."
        redact: full|tail|hash           # default full
        post_filter: luhn                # optional, applied after regex match
        examples:
          hit:    ["foo AKIAIOSFODNN7EXAMPLE bar"]
          miss:   ["AKI not enough chars"]
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    import yaml  # type: ignore[import-untyped]
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


SEVERITY_ORDER = {"critical": 3, "high": 2, "medium": 1, "low": 0}


# ---------------------------------------------------------------------------
# rule model
# ---------------------------------------------------------------------------

@dataclass
class Rule:
    rule_id: str
    name: str
    severity: str
    category: str
    pattern_text: str
    pattern: re.Pattern
    description: str
    redact: str = "full"
    post_filter: Optional[str] = None
    examples_hit: List[str] = field(default_factory=list)
    examples_miss: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.rule_id,
            "name": self.name,
            "severity": self.severity,
            "category": self.category,
            "pattern": self.pattern_text,
            "description": self.description,
            "redact": self.redact,
            "post_filter": self.post_filter,
        }


@dataclass
class LoadedRules:
    rules: List[Rule]
    defaults: Dict[str, Any]
    skipped: List[Dict[str, str]]  # [{id, reason}]


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------

_FLAG_MAP = {
    "IGNORECASE": re.IGNORECASE,
    "MULTILINE": re.MULTILINE,
    "DOTALL": re.DOTALL,
    "VERBOSE": re.VERBOSE,
    "UNICODE": re.UNICODE,
}


def load_rules(path: Path) -> LoadedRules:
    if not HAS_YAML:
        raise RuntimeError(
            "PyYAML 未安装。请用 `uv run` 跑脚本（PEP 723 内联依赖会自动装），"
            "或 `pip install pyyaml`。"
        )
    if not path.exists():
        raise FileNotFoundError(f"rules 文件不存在: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    defaults = raw.get("defaults") or {}
    rule_defs = raw.get("rules") or []
    rules: List[Rule] = []
    skipped: List[Dict[str, str]] = []
    seen_ids: set = set()
    for rd in rule_defs:
        rule_id = (rd.get("id") or "").strip()
        if not rule_id:
            skipped.append({"id": "(missing)", "reason": "id 字段为空"})
            continue
        if rule_id in seen_ids:
            skipped.append({"id": rule_id, "reason": "重复 id"})
            continue
        pattern_text = rd.get("pattern") or ""
        if not pattern_text:
            skipped.append({"id": rule_id, "reason": "pattern 字段为空"})
            continue
        flags_val = 0
        for f in rd.get("flags") or ["IGNORECASE"]:
            flags_val |= _FLAG_MAP.get(str(f).strip().upper(), 0)
        try:
            compiled = re.compile(pattern_text, flags_val)
        except re.error as exc:
            skipped.append({"id": rule_id, "reason": f"regex 编译失败: {exc}"})
            continue
        severity = str(rd.get("severity") or "medium").lower()
        if severity not in SEVERITY_ORDER:
            skipped.append({"id": rule_id, "reason": f"未知 severity: {severity}"})
            continue
        examples = rd.get("examples") or {}
        rules.append(
            Rule(
                rule_id=rule_id,
                name=str(rd.get("name") or rule_id),
                severity=severity,
                category=str(rd.get("category") or "other"),
                pattern_text=pattern_text,
                pattern=compiled,
                description=str(rd.get("description") or ""),
                redact=str(rd.get("redact") or "full"),
                post_filter=rd.get("post_filter"),
                examples_hit=list(examples.get("hit") or []),
                examples_miss=list(examples.get("miss") or []),
            )
        )
        seen_ids.add(rule_id)
    rules.sort(key=lambda r: (-SEVERITY_ORDER[r.severity], r.rule_id))
    return LoadedRules(rules=rules, defaults=defaults, skipped=skipped)


def filter_by_severity(rules: List[Rule], min_severity: str) -> List[Rule]:
    threshold = SEVERITY_ORDER.get(min_severity.lower(), 1)
    return [r for r in rules if SEVERITY_ORDER[r.severity] >= threshold]


# ---------------------------------------------------------------------------
# scanning
# ---------------------------------------------------------------------------

def scan_text(
    text: str,
    rules: Sequence[Rule],
    *,
    context_chars: int = 20,
    redact_keep: int = 2,
    max_hits_per_rule: int = 5,
) -> List[Dict[str, Any]]:
    """Run all rules over `text` and return hits.

    Returns a list of dicts, one per (rule, match), capped at
    `max_hits_per_rule` per rule. Each dict has redacted match text,
    bounded context, and the original span position.
    """
    hits: List[Dict[str, Any]] = []
    if not text:
        return hits
    for rule in rules:
        per_rule = 0
        for m in rule.pattern.finditer(text):
            if per_rule >= max_hits_per_rule:
                break
            value = m.group(0)
            if rule.post_filter and not _post_filter_passes(rule.post_filter, value):
                continue
            redacted = _redact(value, rule.redact, redact_keep)
            ctx = _bounded_context(text, m.start(), m.end(), context_chars)
            hits.append(
                {
                    "rule_id": rule.rule_id,
                    "rule_name": rule.name,
                    "severity": rule.severity,
                    "category": rule.category,
                    "match_redacted": redacted,
                    "match_len": len(value),
                    "context": ctx.replace(value, redacted),
                    "span": [m.start(), m.end()],
                }
            )
            per_rule += 1
    return hits


def _bounded_context(text: str, start: int, end: int, ctx: int) -> str:
    s = max(0, start - ctx)
    e = min(len(text), end + ctx)
    out = text[s:e].replace("\n", " ").replace("\r", " ")
    if s > 0:
        out = "…" + out
    if e < len(text):
        out = out + "…"
    return out


def _redact(value: str, mode: str, keep: int) -> str:
    if not value:
        return ""
    if mode == "hash":
        return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()[:8]}"
    if mode == "tail":
        if len(value) <= keep * 2:
            return "*" * len(value)
        return f"{value[:keep]}***{value[-keep:]}"
    # default: full redaction
    return f"***len{len(value)}***"


def _post_filter_passes(name: str, value: str) -> bool:
    name = (name or "").lower()
    if name == "luhn":
        return _luhn_check(value)
    if name == "no_digits_only":
        return any(c.isalpha() for c in value)
    return True


def _luhn_check(value: str) -> bool:
    digits = [int(c) for c in value if c.isdigit()]
    if len(digits) < 13:
        return False
    checksum = 0
    parity = len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


# ---------------------------------------------------------------------------
# rule self-test (used by n9e_log_secrules.py --mode test)
# ---------------------------------------------------------------------------

def selftest_rule(rule: Rule, *, context_chars: int = 20, redact_keep: int = 2) -> Dict[str, Any]:
    """Run all rule.examples_hit and examples_miss through the rule, returning
    a structured pass/fail summary."""
    hit_results: List[Tuple[str, bool]] = []
    for s in rule.examples_hit:
        hit_results.append((s, bool(rule.pattern.search(s) and (
            not rule.post_filter or _post_filter_passes(rule.post_filter, rule.pattern.search(s).group(0))
        ))))
    miss_results: List[Tuple[str, bool]] = []
    for s in rule.examples_miss:
        m = rule.pattern.search(s)
        miss_ok = (m is None) or (
            rule.post_filter and not _post_filter_passes(rule.post_filter, m.group(0))
        )
        miss_results.append((s, bool(miss_ok)))
    return {
        "rule_id": rule.rule_id,
        "hit_results": [{"input": s, "passed": ok} for s, ok in hit_results],
        "miss_results": [{"input": s, "passed": ok} for s, ok in miss_results],
        "all_passed": all(ok for _, ok in hit_results) and all(ok for _, ok in miss_results),
    }
