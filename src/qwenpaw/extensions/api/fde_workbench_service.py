"""Service layer for the Portal FDE delivery workbench.

Resolves the ``fde`` agent's workspace, then drives the meta-skill's
deterministic CLI (``skills/fde-onboarding/scripts/fde_tools.py``) as a
subprocess — same pattern as ``fault-disposal`` runs its chat skill bridge.
No FastAPI imports here so the logic is unit-testable in isolation.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

# FDE-internal files that must NOT be installed into the business skill.
_STAGED_INTERNAL_FILES = {"_fde_meta.json", "GENERATION.md"}
ERKAI_TAG = "二开"

FDE_AGENT_ID = "fde"
FDE_ONBOARDING_SKILL = "fde-onboarding"
FDE_TOOLS_TIMEOUT_SECONDS = int(
    os.environ.get("QWENPAW_FDE_TOOLS_TIMEOUT", "60") or "60"
)
FDE_PROBE_TIMEOUT_SECONDS = int(
    os.environ.get("QWENPAW_FDE_PROBE_TIMEOUT", "60") or "60"
)

_SKILL_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")


class FdeWorkbenchError(RuntimeError):
    """Raised on any FDE workbench failure (config missing, tool error)."""


def _validate_skill_name(name: str) -> str:
    norm = str(name or "").strip()
    if not _SKILL_NAME_RE.match(norm):
        raise FdeWorkbenchError(
            "非法技能名：只能用小写字母、数字、连字符，"
            "且不以连字符开头/结尾"
        )
    return norm


def fde_workspace_dir() -> Path:
    """Resolve the ``fde`` agent workspace dir from config (expanded)."""
    from qwenpaw.config.utils import load_config

    config = load_config()
    profiles = getattr(config.agents, "profiles", {}) or {}
    if FDE_AGENT_ID not in profiles:
        raise FdeWorkbenchError(
            "FDE 交付助手未配置"
            "（config.json 缺少 agents.profiles.fde）"
        )
    ref = profiles[FDE_AGENT_ID]
    if not getattr(ref, "enabled", True):
        raise FdeWorkbenchError("FDE 交付助手已停用")
    return Path(getattr(ref, "workspace_dir", "")).expanduser()


def fde_onboarding_skill_dir() -> Path:
    return fde_workspace_dir() / "skills" / FDE_ONBOARDING_SKILL


def fde_tools_script() -> Path:
    return fde_onboarding_skill_dir() / "scripts" / "fde_tools.py"


def fde_staged_dir() -> Path:
    override = os.environ.get("QWENPAW_FDE_STAGED_DIR")
    if override:
        return Path(override).expanduser()
    return fde_workspace_dir() / "staged"


def _run_fde_tools(
    args: list[str],
    *,
    timeout: int = FDE_TOOLS_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    script = fde_tools_script()
    if not script.exists():
        raise FdeWorkbenchError(f"找不到 FDE 工具脚本：{script}")
    cmd = [sys.executable, str(script), *args, "--json"]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(fde_onboarding_skill_dir()),
        )
    except subprocess.TimeoutExpired as exc:  # pragma: no cover - timing
        raise FdeWorkbenchError(
            f"FDE 工具执行超时（{timeout}s）：{' '.join(args)}"
        ) from exc
    stdout = (proc.stdout or "").strip()
    if proc.returncode != 0 and not stdout:
        raise FdeWorkbenchError(
            (proc.stderr or "").strip()
            or (
                f"FDE 工具执行失败（rc={proc.returncode}）："
                f"{' '.join(args)}"
            )
        )
    if not stdout:
        raise FdeWorkbenchError(f"FDE 工具无输出：{' '.join(args)}")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise FdeWorkbenchError(
            f"FDE 工具输出不是合法 JSON：{stdout[:400]}"
        ) from exc
    if not isinstance(payload, dict):
        raise FdeWorkbenchError("FDE 工具输出不是 JSON 对象")
    return payload


def workbench_info() -> dict[str, Any]:
    """Lightweight status for the panel header."""
    try:
        ws = fde_workspace_dir()
    except FdeWorkbenchError as exc:
        return {"available": False, "reason": str(exc)}
    return {
        "available": fde_tools_script().exists(),
        "agentId": FDE_AGENT_ID,
        "workspaceDir": str(ws),
        "stagedDir": str(fde_staged_dir()),
        "onboardingSkill": FDE_ONBOARDING_SKILL,
    }


def list_staged_skills() -> dict[str, Any]:
    return _run_fde_tools(["list-staged"])


def show_staged_skill(name: str, *, max_bytes: int = 40_000) -> dict[str, Any]:
    name = _validate_skill_name(name)
    return _run_fde_tools(
        ["show-staged", "--name", name, "--max-bytes", str(int(max_bytes))]
    )


def selfcheck_staged_skill(name: str) -> dict[str, Any]:
    name = _validate_skill_name(name)
    skill_dir = fde_staged_dir() / name
    if not skill_dir.is_dir():
        raise FdeWorkbenchError(f"未找到 staged 技能：{name}")
    return _run_fde_tools(["selfcheck", "--skill-dir", str(skill_dir)])


def probe_staged_skill(
    name: str,
    *,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    name = _validate_skill_name(name)
    skill_dir = fde_staged_dir() / name
    if not skill_dir.is_dir():
        raise FdeWorkbenchError(f"未找到 staged 技能：{name}")
    args = ["probe", "--skill-dir", str(skill_dir)]
    tmp_path: str | None = None
    if context:
        fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix="fde-probe-")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(context, fh, ensure_ascii=False)
        args += ["--context-file", tmp_path]
    try:
        return _run_fde_tools(args, timeout=FDE_PROBE_TIMEOUT_SECONDS)
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def discard_staged_skill(name: str) -> dict[str, Any]:
    name = _validate_skill_name(name)
    skill_dir = fde_staged_dir() / name
    if not skill_dir.is_dir():
        raise FdeWorkbenchError(f"未找到 staged 技能：{name}")
    return _run_fde_tools(["discard", "--name", name, "--yes"])


def generate_skill(
    *,
    name: str,
    target_workspace: str,
    brief: dict[str, Any] | None = None,
) -> dict[str, Any]:
    name = _validate_skill_name(name)
    target_workspace = str(target_workspace or "").strip()
    if not target_workspace:
        raise FdeWorkbenchError(
            "必须指定 target_workspace"
            "（这个技能最终装到哪个业务智能体）"
        )
    staged = fde_staged_dir()
    staged.mkdir(parents=True, exist_ok=True)
    args = [
        "scaffold",
        "--name",
        name,
        "--target-workspace",
        target_workspace,
        "--out-dir",
        str(staged),
    ]
    tmp_path: str | None = None
    if brief:
        fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix="fde-brief-")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(brief, fh, ensure_ascii=False)
        args += ["--brief-file", tmp_path]
    try:
        return _run_fde_tools(args)
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# --- install (human-confirmed) -------------------------------------------
def _resolve_workspace_dir(agent_id: str) -> Path:
    from qwenpaw.config.utils import load_config

    config = load_config()
    profiles = getattr(config.agents, "profiles", {}) or {}
    if agent_id not in profiles:
        raise FdeWorkbenchError(f"目标业务智能体不存在：{agent_id}")
    ref = profiles[agent_id]
    if not getattr(ref, "enabled", True):
        raise FdeWorkbenchError(f"目标业务智能体已停用：{agent_id}")
    return Path(getattr(ref, "workspace_dir", "")).expanduser()


def _tree_insert(tree: dict[str, Any], parts: list[str], content: str) -> None:
    node = tree
    for part in parts[:-1]:
        node = node.setdefault(part, {})
        if not isinstance(node, dict):
            raise FdeWorkbenchError(
                f"staged 目录结构异常：{'/'.join(parts)}"
            )
    node[parts[-1]] = content


def _read_staged_bundle(skill_dir: Path) -> dict[str, Any]:
    """Split a staged skill dir into create_skill() arguments."""
    content: str | None = None
    references: dict[str, Any] = {}
    scripts: dict[str, Any] = {}
    extra_files: dict[str, Any] = {}
    included: list[str] = []
    for path in sorted(skill_dir.rglob("*")):
        if path.is_dir():
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        rel = path.relative_to(skill_dir)
        parts = list(rel.parts)
        if parts[0] in _STAGED_INTERNAL_FILES and len(parts) == 1:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:  # pragma: no cover - defensive
            raise FdeWorkbenchError(
                f"staged 文件不是文本：{rel}"
            ) from exc
        if parts == ["SKILL.md"]:
            content = text
        elif parts[0] == "references":
            _tree_insert(references, parts[1:], text)
        elif parts[0] == "scripts":
            _tree_insert(scripts, parts[1:], text)
        else:
            _tree_insert(extra_files, parts, text)
        included.append(str(rel))
    if content is None:
        raise FdeWorkbenchError("staged 技能缺少 SKILL.md")
    return {
        "content": content,
        "references": references or None,
        "scripts": scripts or None,
        "extra_files": extra_files or None,
        "files": included,
    }


def install_staged_skill(
    name: str,
    *,
    target_override: str | None = None,
) -> dict[str, Any]:
    """Install a staged skill into a business agent's workspace.

    By default it goes to the agent recorded in ``_fde_meta.json``;
    ``target_override`` redirects it to any existing agent (e.g. one the
    operator just created). Runs the real security scan via
    ``SkillService.create_skill`` (a ``SkillScanError`` surfaces as an
    ``FdeWorkbenchError``), tags it ``二开``, leaves it enabled. The caller
    (route handler) schedules the target agent's reload.
    """
    name = _validate_skill_name(name)
    skill_dir = fde_staged_dir() / name
    if not skill_dir.is_dir():
        raise FdeWorkbenchError(f"未找到 staged 技能：{name}")
    meta_path = skill_dir / "_fde_meta.json"
    if not meta_path.exists():
        raise FdeWorkbenchError(f"staged 技能缺少 _fde_meta.json：{name}")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FdeWorkbenchError(
            f"_fde_meta.json 不是合法 JSON：{name}"
        ) from exc
    override = str(target_override or "").strip()
    recorded = str(meta.get("target_workspace") or "").strip()
    target_workspace = override or recorded
    if not target_workspace:
        raise FdeWorkbenchError(
            f"staged 技能没有标注目标业务智能体：{name}"
        )

    bundle = _read_staged_bundle(skill_dir)
    target_dir = _resolve_workspace_dir(target_workspace)

    from qwenpaw.agents.skills_manager import SkillService
    from qwenpaw.security.skill_scanner import SkillScanError

    service = SkillService(target_dir)
    try:
        created = service.create_skill(
            name=name,
            content=bundle["content"],
            references=bundle["references"],
            scripts=bundle["scripts"],
            extra_files=bundle["extra_files"],
            config={},
            enable=True,
        )
    except SkillScanError as exc:
        raise FdeWorkbenchError(
            f"安装时安全扫描未通过：{exc}"
        ) from exc
    except Exception as exc:  # noqa: BLE001 - normalize for the panel
        raise FdeWorkbenchError(f"安装失败：{exc}") from exc
    if not created:
        raise FdeWorkbenchError(
            f"目标工作区已存在同名技能：{name}"
            "（在技能面板里先处理掉）"
        )
    try:
        service.set_skill_tags(created, [ERKAI_TAG])
    except Exception:  # noqa: BLE001 - tag is best-effort
        pass
    return {
        "installed": True,
        "name": created,
        "target_workspace": target_workspace,
        "files": bundle["files"],
        "tag": ERKAI_TAG,
    }
