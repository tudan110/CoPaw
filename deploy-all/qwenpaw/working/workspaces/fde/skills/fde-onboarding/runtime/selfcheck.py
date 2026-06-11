"""对一个 staged 技能跑自检：安全扫描 dry-run + 领域审查 + 语法 + 待确认项。

不依赖 FastAPI，可被 CLI、后端、单测直接调用。返回纯 dict。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _parse_frontmatter(skill_md: str) -> dict[str, str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", skill_md, re.S)
    out: dict[str, str] = {}
    if not m:
        return out
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, val = line.partition(":")
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


def _scan(skill_dir: Path, name: str) -> dict[str, Any]:
    try:
        from qwenpaw.security.skill_scanner import scan_skill_directory
    except Exception as exc:  # pragma: no cover - package not importable
        return {"status": "unavailable", "reason": f"scanner 不可用: {exc}"}
    try:
        result = scan_skill_directory(skill_dir, skill_name=name, block=False)
    except Exception as exc:  # noqa: BLE001 - report, don't crash selfcheck
        return {"status": "error", "reason": str(exc)}
    if result is None:
        return {"status": "skipped", "reason": "扫描已禁用 / 在白名单 / 超时"}
    findings = []
    for f in getattr(result, "findings", []) or []:
        findings.append(
            {
                "severity": getattr(getattr(f, "severity", None), "value", str(getattr(f, "severity", ""))),
                "title": getattr(f, "title", ""),
                "file": getattr(f, "file_path", ""),
                "line": getattr(f, "line_number", None),
                "snippet": getattr(f, "snippet", None),
                "remediation": getattr(f, "remediation", None),
                "category": getattr(getattr(f, "category", None), "value", str(getattr(f, "category", "") or "")),
                "rule_id": getattr(f, "rule_id", ""),
                "description": getattr(f, "description", ""),
            }
        )
    return {
        "status": "ok" if getattr(result, "is_safe", True) else "blocked",
        "is_safe": bool(getattr(result, "is_safe", True)),
        "max_severity": getattr(getattr(result, "max_severity", None), "value", None),
        "findings": findings,
    }


def _domain(name: str, description: str, skill_md: str) -> dict[str, Any]:
    try:
        from qwenpaw.extensions.api.domain_guard import judge_text
    except Exception as exc:  # pragma: no cover
        return {"status": "unavailable", "reason": f"domain_guard 不可用: {exc}"}
    try:
        verdict = judge_text(
            kind="skill",
            name=name,
            description=description or name,
            content=skill_md[:4000],
        )
    except Exception as exc:  # noqa: BLE001
        return {"status": "unavailable", "reason": str(exc)}
    decision = getattr(verdict, "decision", "")
    return {
        "status": "ok" if decision == "allow" else ("blocked" if decision == "reject" else "unavailable"),
        "decision": decision,
        "allowed": bool(getattr(verdict, "allowed", False)),
        "category": getattr(verdict, "category", ""),
        "confidence": getattr(verdict, "confidence", 0.0),
        "reason": getattr(verdict, "reason", ""),
        "source": getattr(verdict, "source", ""),
    }


def _syntax(skill_dir: Path) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    for py in sorted(skill_dir.rglob("*.py")):
        rel = str(py.relative_to(skill_dir))
        try:
            source = py.read_bytes()
        except OSError as exc:
            errors.append({"file": rel, "error": f"读取失败: {exc}"})
            continue
        try:
            # 纯语法校验，跨平台无副作用：内建 compile 不写任何文件
            # （旧实现用 py_compile 往临时 .pyc 落盘，Windows 上 rename
            # 覆盖打开的句柄会 WinError 5，只读/受限 TMPDIR 下也可能失败）。
            # 传 bytes 让 compile 按 PEP 263 自行探测编码（默认 utf-8，
            # 兼容 BOM 与 `# -*- coding: -*-` 声明），不强制 utf-8 误报。
            compile(source, str(py), "exec", dont_inherit=True)
        except (SyntaxError, ValueError) as exc:
            errors.append({"file": rel, "error": str(exc)})
    return {"status": "ok" if not errors else "error", "errors": errors}


def _todo(skill_dir: Path) -> list[str]:
    items: list[str] = []
    meta_path = skill_dir / "_fde_meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            items += [str(x) for x in (meta.get("open_questions") or []) if str(x).strip()]
        except Exception:  # noqa: BLE001
            pass
    env_example = skill_dir / ".env.example"
    if env_example.exists():
        for line in env_example.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and line.endswith("="):
                items.append(f"需要填写凭证：{line[:-1]}（复制 .env.example 为 .env 后填）")
    adapters = skill_dir / "runtime" / "tool_adapters.py"
    if adapters.exists() and "mock-or-real" in adapters.read_text(encoding="utf-8"):
        items.append("runtime/tool_adapters.py 仍是占位实现，需要接上真实接口")
    return items


def run_selfcheck(
    skill_dir: str | Path, *, with_domain: bool = True
) -> dict[str, Any]:
    skill_dir = Path(skill_dir).resolve()
    if not skill_dir.is_dir():
        return {"ok": False, "error": f"目录不存在：{skill_dir}"}
    skill_md_path = skill_dir / "SKILL.md"
    skill_md = skill_md_path.read_text(encoding="utf-8") if skill_md_path.exists() else ""
    fm = _parse_frontmatter(skill_md)
    name = fm.get("name") or skill_dir.name
    description = fm.get("description") or ""

    scan = _scan(skill_dir, name)
    # 领域审查是一次 LLM 调用，可能卡在限流/超时上。加载技能详情时
    # （with_domain=False）跳过它，让呈现文件保持纯本地、秒回；显式
    # 重新自检与安装闸门仍跑完整领域审查（权威，不放水）。
    if with_domain:
        domain = _domain(name, description, skill_md)
    else:
        domain = {
            "status": "skipped",
            "decision": "",
            "reason": "加载详情时不跑领域审查（避免卡限流）；点『重新自检』运行",
        }
    syntax = _syntax(skill_dir)
    todo = _todo(skill_dir)

    blocked_reasons: list[str] = []
    if scan.get("status") == "blocked":
        blocked_reasons.append("安全扫描发现高危项（skill_scanner）")
    if domain.get("status") == "blocked":
        blocked_reasons.append(f"领域审查未通过：{domain.get('reason') or '非网管域'}")
    if syntax.get("status") == "error":
        blocked_reasons.append("runtime 代码有语法错误")
    if not skill_md_path.exists():
        blocked_reasons.append("缺少 SKILL.md")

    warnings: list[str] = []
    if domain.get("status") == "unavailable":
        warnings.append("领域审查未执行（无可用模型/超时）——安装时会再扫一遍")
    if scan.get("status") in {"unavailable", "error"}:
        warnings.append(f"安全扫描未执行：{scan.get('reason') or ''}")

    return {
        "ok": not blocked_reasons,
        "skill_name": name,
        "skill_dir": str(skill_dir),
        "ready_for_review": not blocked_reasons,
        "blocked_reasons": blocked_reasons,
        "warnings": warnings,
        "scan": scan,
        "domain": domain,
        "syntax": syntax,
        "todo": todo,
    }
