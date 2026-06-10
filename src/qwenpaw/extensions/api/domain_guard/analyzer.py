# -*- coding: utf-8 -*-
"""技能侧领域守卫：作为一个 ``BaseAnalyzer`` 插进 skill_scanner。

每次导入 / 启用技能时 skill_scanner 都会跑它；不属于网管领域 -> 发一条 HIGH 级
``Finding(rule_id="domain.off_topic")`` -> 触发既有的 ``SkillScanError`` -> 路由返回
422（带结构化 findings）-> Portal 弹窗展示。

注意：分析器**总会运行**，但"是否真的拦截导入"由 ``security.skill_scanner.mode`` 决定：
``block`` -> 拦截；``warn`` -> 只记日志、放行（导入照样成功，只是日志里留痕）；
``off`` -> 整个扫描被跳过，分析器也不会跑。要让领域校验真正生效，请把 skill_scanner
设为 ``block``（config.json 的 ``security.skill_scanner.mode``，或环境变量
``QWENPAW_SKILL_SCAN_MODE=block``）。
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from . import judge_text

if TYPE_CHECKING:  # pragma: no cover
    from qwenpaw.security.skill_scanner.analyzers import BaseAnalyzer as _Base
    from qwenpaw.security.skill_scanner.models import Finding, SkillFile

logger = logging.getLogger(__name__)

_DOMAIN_ANALYZER_NAME = "domain_relevance"


def _parse_frontmatter(content: str) -> tuple[str, str]:
    """Best-effort extraction of ``name`` / ``description`` from SKILL.md."""
    raw = content or ""
    if not raw.lstrip().startswith("---"):
        return "", ""
    stripped = raw.lstrip()
    end = stripped.find("\n---", 3)
    if end == -1:
        end = stripped.find("\n...", 3)
    if end == -1:
        return "", ""
    block = stripped[3:end].strip()
    try:
        import yaml

        data = yaml.safe_load(block) or {}
        if isinstance(data, dict):
            return str(data.get("name") or "").strip(), str(
                data.get("description") or ""
            ).strip()
    except Exception:  # pragma: no cover - defensive
        pass
    return "", ""


def _looks_builtin(skill_name: str) -> bool:
    if not skill_name:
        return False
    try:
        from qwenpaw.agents.skill_system.registry import (  # type: ignore
            list_builtin_import_candidates,
        )

        for item in list_builtin_import_candidates() or []:
            cand = item.get("name") if isinstance(item, dict) else getattr(
                item, "name", None
            )
            if cand and str(cand) == skill_name:
                return True
    except Exception:  # pragma: no cover - defensive
        return False
    return False


def _build_analyzer_class():
    """Build the analyzer class lazily so importing this module never forces
    the security package to load."""
    from qwenpaw.security.skill_scanner.analyzers import BaseAnalyzer
    from qwenpaw.security.skill_scanner.models import (
        Finding,
        Severity,
        ThreatCategory,
    )

    class DomainRelevanceAnalyzer(BaseAnalyzer):
        """Rejects skills that don't belong to the network-management domain."""

        def __init__(self, *, policy=None) -> None:
            super().__init__(_DOMAIN_ANALYZER_NAME, policy=policy)

        # ------------------------------------------------------------------
        def analyze(
            self,
            skill_dir: Path,
            files: "list[SkillFile]",
            *,
            skill_name: Optional[str] = None,
        ) -> "list[Finding]":
            skill_md = None
            for f in files or []:
                if Path(f.relative_path).name.lower() == "skill.md":
                    skill_md = f
                    break
            content = ""
            if skill_md is not None:
                try:
                    content = skill_md.read_content()
                except Exception:  # pragma: no cover - defensive
                    content = ""
            fm_name, fm_desc = _parse_frontmatter(content)
            name = (
                skill_name or fm_name or Path(str(skill_dir)).name or ""
            ).strip()

            try:
                verdict = judge_text(
                    kind="skill",
                    name=name,
                    description=fm_desc,
                    content=content,
                    is_builtin=_looks_builtin(name),
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "domain_relevance analyzer crashed for '%s': %s", name, exc
                )
                return [self._unavailable_finding(str(exc))]

            if verdict.allowed:
                return []
            if verdict.decision == "reject_unavailable":
                return [self._unavailable_finding(verdict.reason)]

            return [
                Finding(
                    id=str(uuid.uuid4()),
                    rule_id="domain.off_topic",
                    category=ThreatCategory.POLICY_VIOLATION,
                    severity=Severity.HIGH,
                    title="该技能不属于网络管理 / 运维领域",
                    description=verdict.reject_message(),
                    file_path="SKILL.md",
                    analyzer=self.name,
                    metadata={
                        "domain_category": verdict.category,
                        "confidence": verdict.confidence,
                        "source": verdict.source,
                    },
                )
            ]

        # ------------------------------------------------------------------
        def _unavailable_finding(self, detail: str) -> "Finding":
            return Finding(
                id=str(uuid.uuid4()),
                rule_id="domain.check_unavailable",
                category=ThreatCategory.POLICY_VIOLATION,
                severity=Severity.HIGH,
                title="技能领域审核未完成",
                description="技能领域审核失败，请稍后重试或联系管理员。",
                file_path="SKILL.md",
                analyzer=self.name,
                metadata={"detail": (detail or "")[:300]},
            )

    return DomainRelevanceAnalyzer


_registered = False
_reg_lock = __import__("threading").Lock()


def register_skill_domain_analyzer() -> bool:
    """Register the domain analyzer onto the global skill-scanner singleton.

    Idempotent; safe to call multiple times. Returns ``True`` on the call that
    actually performed the registration.
    """
    global _registered
    with _reg_lock:
        if _registered:
            return False
        try:
            from qwenpaw.security.skill_scanner import _get_scanner

            scanner = _get_scanner()
            existing = getattr(scanner, "_analyzers", []) or []
            if any(
                getattr(a, "name", "") == _DOMAIN_ANALYZER_NAME
                for a in existing
            ):
                _registered = True
                return False
            scanner.register_analyzer(_build_analyzer_class()())
            _registered = True
            logger.info(
                "domain_guard: registered '%s' analyzer into skill scanner",
                _DOMAIN_ANALYZER_NAME,
            )
            return True
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "domain_guard: failed to register skill analyzer: %s", exc
            )
            return False
