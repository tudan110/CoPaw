"""Service layer for the Portal FDE delivery workbench.

Resolves the ``fde`` agent's workspace, then drives the meta-skill's
deterministic CLI (``skills/fde-onboarding/scripts/fde_tools.py``) as a
subprocess — same pattern as ``fault-disposal`` runs its chat skill bridge.
No FastAPI imports here so the logic is unit-testable in isolation.
"""
from __future__ import annotations

import hashlib
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
# Portal "对外入口" agent. Skills mirrored here are reachable from the
# portal main chat box directly. Configurable for deployments that
# rename the entry agent (mirrors the frontend's portalBranding).
GATEWAY_AGENT_ID = os.environ.get(
    "QWENPAW_PORTAL_GATEWAY_AGENT_ID",
    "",
).strip() or "gateway"
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


_INSTALLED_SKILL_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9._-]+$")


def parse_env_example(text: str) -> list[dict[str, str]]:
    """Parse a ``.env.example`` file into a list of fields for a form UI.

    Each entry is ``{key, default, hint}`` where ``hint`` is the concatenation
    of consecutive ``#`` comments immediately preceding the ``KEY=value``
    line. Lines that don't look like ``KEY=...`` are skipped (but their
    comments are still associated with the next real key).
    """
    fields: list[dict[str, str]] = []
    pending: list[str] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            pending = []
            continue
        if stripped.startswith("#"):
            pending.append(stripped.lstrip("#").strip())
            continue
        if "=" not in stripped:
            pending = []
            continue
        key, _, default = stripped.partition("=")
        key = key.strip()
        default = default.strip().strip('"').strip("'")
        if not key:
            pending = []
            continue
        fields.append(
            {
                "key": key,
                "default": default,
                "hint": "\n".join(pending).strip(),
            }
        )
        pending = []
    return fields


def _parse_env_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = val.strip().strip('"').strip("'")
    return values


# KEY as substring + AK/SK only as whole _-bounded segments (so TASK/RISK
# don't false-match). Emptying a non-secret by mistake is harmless (operator
# re-enters at install); leaking a secret into a staged file is not.
_SECRET_ENV_KEY_RE = re.compile(
    r"(TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|KEY|(^|_)(AK|SK)(_|$))",
    re.I,
)


def _is_secret_env_key(key: str) -> bool:
    return bool(_SECRET_ENV_KEY_RE.search(str(key or "")))


def _update_env_example(text: str, updates: dict[str, str]) -> str:
    """Update/append ``KEY=value`` lines, preserving comments + order.
    Secret-looking keys are written with an EMPTY value (D4: credentials
    never land in staged files).
    """
    if not updates:
        return text or ""
    remaining = {
        str(k).strip(): ("" if _is_secret_env_key(k) else str(v))
        for k, v in updates.items()
        if str(k).strip()
    }
    out_lines: list[str] = []
    for raw in (text or "").splitlines():
        stripped = raw.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.partition("=")[0].strip()
            if key in remaining:
                out_lines.append(f"{key}={remaining.pop(key)}")
                continue
        out_lines.append(raw)
    for key, val in remaining.items():
        out_lines.append(f"{key}={val}")
    body = "\n".join(out_lines)
    return body if body.endswith("\n") else body + "\n"


def _installed_skill_dir(target_workspace: str, skill_name: str) -> Path:
    target_workspace = (target_workspace or "").strip()
    if not target_workspace:
        raise FdeWorkbenchError("缺少目标业务智能体")
    name = (skill_name or "").strip()
    if not _INSTALLED_SKILL_SAFE_NAME_RE.match(name):
        raise FdeWorkbenchError(f"非法技能名：{skill_name}")
    workspace_dir = _resolve_workspace_dir(target_workspace)
    skill_dir = workspace_dir / "skills" / name
    if not skill_dir.is_dir():
        raise FdeWorkbenchError(
            f"业务智能体 {target_workspace} 的工作区里找不到技能 {name}"
        )
    return skill_dir


def read_skill_env_state(
    target_workspace: str,
    skill_name: str,
) -> dict[str, Any]:
    """Return the env schema (from .env.example) + current values (.env)."""
    skill_dir = _installed_skill_dir(target_workspace, skill_name)
    example = skill_dir / ".env.example"
    env_path = skill_dir / ".env"
    schema = []
    if example.is_file():
        try:
            schema = parse_env_example(
                example.read_text(encoding="utf-8"),
            )
        except OSError:
            schema = []
    values: dict[str, str] = {}
    if env_path.is_file():
        try:
            values = _parse_env_values(env_path.read_text(encoding="utf-8"))
        except OSError:
            values = {}
    return {
        "target_workspace": target_workspace,
        "skill_name": skill_name,
        "skill_dir": str(skill_dir),
        "schema": schema,
        "values": values,
        "has_env": env_path.is_file(),
        "has_example": example.is_file(),
    }


def write_skill_env(
    *,
    target_workspace: str,
    skill_name: str,
    values: dict[str, Any] | None,
) -> dict[str, Any]:
    """Write/update ``.env`` in the installed skill dir.

    Existing keys not present in ``values`` are preserved; values present
    are overwritten. Empty-string values delete the key. Sets mode 0600
    so credentials aren't world-readable.
    """
    skill_dir = _installed_skill_dir(target_workspace, skill_name)
    env_path = skill_dir / ".env"
    current: dict[str, str] = {}
    if env_path.is_file():
        try:
            current = _parse_env_values(env_path.read_text(encoding="utf-8"))
        except OSError:
            current = {}
    incoming = dict(values or {})
    for key, val in incoming.items():
        key = str(key).strip()
        if not key:
            continue
        text = "" if val is None else str(val)
        if text == "":
            current.pop(key, None)
        else:
            current[key] = text
    lines = [
        "# 由 Portal 交付工作台写入。包含敏感凭证，请妥善保护。",
        "",
    ] + [f"{k}={v}" for k, v in current.items()]
    body = "\n".join(lines) + "\n"
    env_path.write_text(body, encoding="utf-8")
    try:
        os.chmod(env_path, 0o600)
    except OSError:
        pass
    return {
        "target_workspace": target_workspace,
        "skill_name": skill_name,
        "skill_dir": str(skill_dir),
        "keys": sorted(current.keys()),
        "wrote_count": len(current),
    }


def _parse_skill_frontmatter(text: str) -> tuple[str, str]:
    """Best-effort YAML frontmatter parse → (name, description)."""
    if not text or not text.lstrip().startswith("---"):
        return "", ""
    stripped = text.lstrip()
    end = stripped.find("\n---", 3)
    if end == -1:
        return "", ""
    block = stripped[3:end].strip()
    try:
        import yaml

        data = yaml.safe_load(block) or {}
    except Exception:  # noqa: BLE001 - defensive
        return "", ""
    if not isinstance(data, dict):
        return "", ""
    return (
        str(data.get("name") or "").strip(),
        str(data.get("description") or "").strip(),
    )


def prefill_domain_allow_for_staged(
    skill_dir: Path,
    *,
    source: str = "fde-manual-override",
    reason: str = "FDE 交付工作台手动确认（领域审核服务暂不可用）",
) -> bool:
    """Pre-warm ``domain_guard``'s in-memory verdict cache with an
    ``allow`` for the staged skill's content digest.

    Used when the install path's ``skill_scanner`` would otherwise refuse
    to import the skill because the domain LLM is unreachable: the
    operator has reviewed the code in the panel, so we let them override
    that one check (and only that one — ``skill_scanner`` still runs and
    can block on real security findings). Returns ``True`` when a
    verdict was inserted into the cache.
    """
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return False
    try:
        content = skill_md.read_text(encoding="utf-8")
    except OSError:
        return False
    fm_name, fm_desc = _parse_skill_frontmatter(content)
    skill_name = fm_name or skill_dir.name
    try:
        from qwenpaw.extensions.api.domain_guard import (
            DomainVerdict,
            _cache_put,
            _content_digest,
        )
    except Exception:  # noqa: BLE001 - defensive
        return False
    digest = _content_digest("skill", skill_name, fm_desc, content, {})
    verdict = DomainVerdict(
        relevant=True,
        confidence=1.0,
        category="人工确认",
        reason=reason,
        decision="allow",
        source=source,
    )
    try:
        _cache_put(digest, verdict)
    except Exception:  # noqa: BLE001 - defensive
        return False
    return True


def copy_installed_skill(
    *,
    source_agent: str,
    skill_name: str,
    target_workspace: str,
    auto_create_target: bool = True,
    skip_domain_check: bool = False,
    remove_source: bool = False,
    mirror_to_gateway: bool = True,
) -> dict[str, Any]:
    """Copy (or move) an already-installed 二开 skill to another business
    agent. Used to fix "FDE put it in the wrong workspace, so the gateway's
    routing never reaches it" — operator picks the right destination from
    the panel without going back through FDE chat + regenerate.

    Reads the source skill's on-disk files directly (no staged dir needed),
    re-runs the install path against the target (which includes the real
    security scan + 二开 tag). When ``remove_source`` is True, the source
    skill is deleted after a successful install (move semantics; otherwise
    the skill lives in both workspaces).
    """
    source_agent = (source_agent or "").strip()
    if not source_agent:
        raise FdeWorkbenchError("缺少源业务智能体")
    target_workspace = (target_workspace or "").strip()
    if not target_workspace:
        raise FdeWorkbenchError("缺少目标业务智能体")
    if target_workspace == source_agent:
        raise FdeWorkbenchError(
            "目标和来源是同一个业务智能体，不需要复制",
        )
    skill_name = _validate_skill_name(skill_name)

    source_dir = _installed_skill_dir(source_agent, skill_name)
    bundle = _read_staged_bundle(source_dir)

    target_created = False
    if auto_create_target and not _target_agent_exists(target_workspace):
        create_business_agent(
            agent_id=target_workspace,
            name=target_workspace,
            description=(
                f"由 FDE 交付工作台在复制 `{skill_name}` 时自动创建"
            ),
            active_model=_pick_default_active_model(),
        )
        target_created = True
    target_dir = _resolve_workspace_dir(target_workspace)
    if skip_domain_check:
        prefill_domain_allow_for_staged(source_dir)

    from qwenpaw.agents.skill_system import SkillService
    from qwenpaw.security.skill_scanner import SkillScanError

    service = SkillService(target_dir)
    try:
        created = service.create_skill(
            name=skill_name,
            content=bundle["content"],
            references=bundle["references"],
            scripts=bundle["scripts"],
            extra_files=bundle["extra_files"],
            config={},
            enable=True,
        )
    except SkillScanError as exc:
        raise FdeWorkbenchError(
            f"复制时安全扫描未通过：{exc}",
        ) from exc
    except Exception as exc:  # noqa: BLE001 - normalize for the panel
        raise FdeWorkbenchError(f"复制失败：{exc}") from exc
    if not created:
        raise FdeWorkbenchError(
            f"目标工作区已存在同名技能：{skill_name}"
            "（在技能面板里先处理掉）",
        )
    try:
        service.set_skill_tags(created, [ERKAI_TAG])
    except Exception:  # noqa: BLE001 - tag is best-effort
        pass

    removed = False
    remove_error: str | None = None
    if remove_source:
        try:
            from qwenpaw.agents.skill_system import SkillService as _SS

            source_workspace_dir = _resolve_workspace_dir(source_agent)
            source_service = _SS(source_workspace_dir)
            # ``delete_skill`` refuses while the skill is enabled — disable
            # first, then delete. The skill is already live in the target so
            # leaving the source enabled for a moment longer is fine.
            try:
                source_service.disable_skill(skill_name)
            except Exception:  # noqa: BLE001 - delete will surface a real error
                pass
            ok = source_service.delete_skill(skill_name)
            if not ok:
                raise FdeWorkbenchError(
                    "源工作区拒绝删除（可能仍处于启用状态或权限不足）",
                )
            removed = True
        except FdeWorkbenchError as exc:
            remove_error = str(exc)
        except Exception as exc:  # noqa: BLE001 - normalize
            remove_error = str(exc)
    mirror_status: dict[str, Any] = {
        "mirrored": False,
        "gateway_agent": GATEWAY_AGENT_ID,
        "skipped_reason": (
            "目标本身就是 gateway" if target_workspace == GATEWAY_AGENT_ID
            else None
        ),
    }
    if mirror_to_gateway and target_workspace != GATEWAY_AGENT_ID:
        mirror_status = _try_mirror_to_gateway(created, bundle)

    result: dict[str, Any] = {
        "copied": True,
        "name": created,
        "source_agent": source_agent,
        "target_workspace": target_workspace,
        "target_created": target_created,
        "removed_source": removed,
        "tag": ERKAI_TAG,
        "gateway_mirror": mirror_status,
    }
    if remove_error:
        result["remove_error"] = remove_error
    return result


def delete_installed_skill(
    *,
    target_workspace: str,
    skill_name: str,
    also_remove_gateway_mirror: bool = True,
) -> dict[str, Any]:
    """Delete an FDE-installed skill from a business agent's workspace.

    ``delete_skill`` upstream refuses while the skill is enabled, so we
    ``disable_skill`` first then delete. When ``also_remove_gateway_mirror``
    (default) is True and the same-named skill is also present in the
    gateway workspace (the mirror this service writes on every install),
    it gets cleaned up too — otherwise you'd be leaving an orphan copy
    of code behind that the operator can no longer reach from this view.
    """
    target_workspace = (target_workspace or "").strip()
    if not target_workspace:
        raise FdeWorkbenchError("缺少目标业务智能体")
    skill_name = _validate_skill_name(skill_name)

    # Make sure the skill actually exists in the named workspace before we
    # start touching anything (raises FdeWorkbenchError if not).
    _ = _installed_skill_dir(target_workspace, skill_name)

    from qwenpaw.agents.skill_system import SkillService

    workspace_dir = _resolve_workspace_dir(target_workspace)
    service = SkillService(workspace_dir)
    try:
        service.disable_skill(skill_name)
    except Exception:  # noqa: BLE001 - delete will report the real error
        pass
    try:
        ok = service.delete_skill(skill_name)
    except Exception as exc:  # noqa: BLE001
        raise FdeWorkbenchError(f"删除失败：{exc}") from exc
    if not ok:
        raise FdeWorkbenchError(
            "源工作区拒绝删除（可能仍处于启用状态或权限不足）",
        )

    gateway_removed = False
    gateway_skip: str | None = None
    if (
        also_remove_gateway_mirror
        and target_workspace != GATEWAY_AGENT_ID
        and _target_agent_exists(GATEWAY_AGENT_ID)
    ):
        try:
            gateway_dir = _resolve_workspace_dir(GATEWAY_AGENT_ID)
            gw_skill_dir = gateway_dir / "skills" / skill_name
            if gw_skill_dir.is_dir():
                gw_service = SkillService(gateway_dir)
                try:
                    gw_service.disable_skill(skill_name)
                except Exception:  # noqa: BLE001
                    pass
                if gw_service.delete_skill(skill_name):
                    gateway_removed = True
                else:
                    gateway_skip = "gateway 拒绝删除镜像（可能权限不足）"
            else:
                gateway_skip = "gateway 没有同名镜像，无需清理"
        except FdeWorkbenchError as exc:
            gateway_skip = f"gateway 镜像清理失败：{exc}"
        except Exception as exc:  # noqa: BLE001
            gateway_skip = f"gateway 镜像清理失败：{exc}"

    return {
        "deleted": True,
        "target_workspace": target_workspace,
        "skill_name": skill_name,
        "gateway_mirror_removed": gateway_removed,
        "gateway_mirror_skipped_reason": gateway_skip,
    }


def list_installed_erkai_skills() -> dict[str, Any]:
    """List skills tagged ``二开`` across every configured business agent.

    This is what the FDE workbench panel's "已交付技能" view reads: the
    upstream skill pool panel is scoped to the gateway agent only, so
    skills FDE installs into other agents wouldn't show up there. Reads
    each agent's ``skill.json`` manifest directly — no side effects.
    """
    from qwenpaw.config.config import load_agent_config
    from qwenpaw.config.utils import load_config

    config = load_config()
    profiles = getattr(config.agents, "profiles", {}) or {}
    out: list[dict[str, Any]] = []
    for agent_id, ref in profiles.items():
        if agent_id == FDE_AGENT_ID:
            continue  # FDE workspace doesn't host business skills
        workspace_dir = Path(
            getattr(ref, "workspace_dir", ""),
        ).expanduser()
        manifest_path = workspace_dir / "skill.json"
        if not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        agent_name = agent_id
        try:
            agent_cfg = load_agent_config(agent_id)
            agent_name = getattr(agent_cfg, "name", "") or agent_id
        except Exception:  # noqa: BLE001 - best-effort
            pass
        for skill_name, entry in (manifest.get("skills") or {}).items():
            tags = entry.get("tags") or []
            if ERKAI_TAG not in tags:
                continue
            metadata = entry.get("metadata") or {}
            out.append(
                {
                    "agent_id": agent_id,
                    "agent_name": agent_name,
                    "skill_name": skill_name,
                    "enabled": bool(entry.get("enabled", False)),
                    "description": str(metadata.get("description") or "")[
                        :240
                    ],
                    "updated_at": str(
                        entry.get("updated_at")
                        or metadata.get("updated_at")
                        or "",
                    ),
                    "tags": [str(t) for t in tags],
                }
            )
    out.sort(key=lambda s: (s["agent_id"], s["skill_name"]))
    return {"count": len(out), "skills": out}


def _target_agent_exists(agent_id: str) -> bool:
    """Lightweight existence check (no error on missing)."""
    from qwenpaw.config.utils import load_config

    config = load_config()
    profiles = getattr(config.agents, "profiles", {}) or {}
    return agent_id in profiles


def _pick_default_active_model() -> dict[str, Any] | None:
    """Reuse fde's (else the default agent's) active model as a sensible
    default when auto-creating a business agent: matches what's already
    working in the deployment, no manual provider/model setup needed.
    """
    from qwenpaw.config.config import load_agent_config
    from qwenpaw.config.utils import load_config

    config = load_config()
    profiles = getattr(config.agents, "profiles", {}) or {}
    for candidate in (FDE_AGENT_ID, "default"):
        if candidate not in profiles:
            continue
        try:
            agent_cfg = load_agent_config(candidate)
        except Exception:  # noqa: BLE001 - best-effort
            continue
        am = getattr(agent_cfg, "active_model", None)
        provider_id = getattr(am, "provider_id", "") if am else ""
        model = getattr(am, "model", "") if am else ""
        if provider_id and model:
            return {"provider_id": provider_id, "model": model}
    return None


def create_business_agent(
    *,
    agent_id: str,
    name: str | None = None,
    description: str = "",
    active_model: dict[str, Any] | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    """Create a new business agent (workspace + config profile + agent.json).

    Mirrors what ``POST /api/agents`` does but is callable from anywhere
    — the FDE chat agent's ``fde_tools.py create-agent`` shell tool, the
    install endpoint's auto-create branch, and tests. Raises
    ``FdeWorkbenchError`` if the id is invalid or already exists; callers
    that want a no-op on conflict should check ``_target_agent_exists``
    first.
    """
    from qwenpaw.agents.utils import normalize_agent_language
    from qwenpaw.config.config import (
        AgentProfileConfig,
        AgentProfileRef,
        ChannelConfig,
        HeartbeatConfig,
        MCPConfig,
        ModelSlotConfig,
        ToolsConfig,
        save_agent_config,
        validate_agent_id,
    )
    from qwenpaw.config.utils import load_config, save_config
    from qwenpaw.constant import WORKING_DIR
    from qwenpaw.app.routers.agents import (
        _initialize_agent_workspace,
        _normalized_agent_order,
    )

    norm_id = str(agent_id or "").strip()
    if not norm_id:
        raise FdeWorkbenchError("缺少业务智能体 id")

    config = load_config()
    existing_ids = set(config.agents.profiles.keys())
    try:
        validate_agent_id(norm_id, existing_ids)
    except ValueError as exc:
        raise FdeWorkbenchError(str(exc)) from exc

    norm_name = (name or "").strip() or norm_id
    workspace_dir = Path(
        f"{WORKING_DIR}/workspaces/{norm_id}",
    ).expanduser()
    workspace_dir.mkdir(parents=True, exist_ok=True)

    norm_lang = normalize_agent_language(
        language or getattr(config.agents, "language", None) or "zh",
    )

    model_slot = None
    if active_model:
        provider_id = str(active_model.get("provider_id") or "").strip()
        model_name = str(active_model.get("model") or "").strip()
        if provider_id and model_name:
            model_slot = ModelSlotConfig(
                provider_id=provider_id,
                model=model_name,
            )

    agent_config = AgentProfileConfig(
        id=norm_id,
        name=norm_name,
        description=description or "",
        workspace_dir=str(workspace_dir),
        language=norm_lang,
        channels=ChannelConfig(),
        mcp=MCPConfig(),
        heartbeat=HeartbeatConfig(),
        tools=ToolsConfig(),
        active_model=model_slot,
    )

    _initialize_agent_workspace(
        workspace_dir,
        skill_names=[],
        language=norm_lang,
    )

    agent_ref = AgentProfileRef(
        id=norm_id,
        workspace_dir=str(workspace_dir),
        enabled=True,
    )
    config.agents.profiles[norm_id] = agent_ref
    config.agents.agent_order = _normalized_agent_order(config)
    save_config(config)
    save_agent_config(norm_id, agent_config)

    return {
        "id": norm_id,
        "name": norm_name,
        "description": description or "",
        "workspace_dir": str(workspace_dir),
        "language": norm_lang,
        "active_model": (
            {
                "provider_id": model_slot.provider_id,
                "model": model_slot.model,
            }
            if model_slot
            else None
        ),
        "enabled": True,
    }


def _tree_insert(tree: dict[str, Any], parts: list[str], content: str) -> None:
    node = tree
    for part in parts[:-1]:
        node = node.setdefault(part, {})
        if not isinstance(node, dict):
            raise FdeWorkbenchError(
                f"staged 目录结构异常：{'/'.join(parts)}"
            )
    node[parts[-1]] = content


def _staged_content_digest(skill_dir: Path) -> str:
    """SHA-256 over all managed staged files (sorted by relpath),
    excluding FDE-internal meta files. Binds a human-review approval to
    exact content: any edit changes the digest, auto-invalidating the
    approval. Excludes ``_fde_meta.json`` (which stores the digest) to
    avoid self-reference. Mirrors ``_read_staged_bundle``'s file filter.
    """
    h = hashlib.sha256()
    for path in sorted(skill_dir.rglob("*")):
        if path.is_dir():
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        rel = path.relative_to(skill_dir)
        if len(rel.parts) == 1 and rel.parts[0] in _STAGED_INTERNAL_FILES:
            continue
        h.update(rel.as_posix().encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def _load_staged_meta(skill_dir: Path) -> dict[str, Any]:
    meta_path = skill_dir / "_fde_meta.json"
    if not meta_path.exists():
        raise FdeWorkbenchError(
            f"staged 技能缺少 _fde_meta.json：{skill_dir.name}"
        )
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FdeWorkbenchError(
            f"_fde_meta.json 不是合法 JSON：{skill_dir.name}"
        ) from exc
    if not isinstance(data, dict):
        raise FdeWorkbenchError(
            f"_fde_meta.json 不是 JSON 对象：{skill_dir.name}"
        )
    return data


def _save_staged_meta(skill_dir: Path, meta: dict[str, Any]) -> None:
    (skill_dir / "_fde_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8",
    )


def _review_state(
    skill_dir: Path, meta: dict[str, Any],
) -> dict[str, Any]:
    """Derive the human-review verdict. ``effective`` is computed, never
    stored: approved only when status==approved AND the stored digest
    still matches current content (else 'stale'); otherwise 'pending'.
    """
    review = meta.get("review") or {}
    status = str(review.get("status") or "pending")
    stored = review.get("content_digest")
    current = _staged_content_digest(skill_dir)
    digest_matches = bool(stored) and stored == current
    if status == "approved" and digest_matches:
        effective = "approved"
    elif status == "approved":
        effective = "stale"
    else:
        effective = "pending"
    return {
        "status": status,
        "approved_by": review.get("approved_by"),
        "approved_at": review.get("approved_at"),
        "content_digest": stored,
        "current_digest": current,
        "digest_matches": digest_matches,
        "effective": effective,
    }


def _yaml_dq(s: str) -> str:
    """Double-quote a scalar so it's always valid YAML (no quoting guesswork)."""
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _render_fm_line(key: str, value: Any) -> str:
    if isinstance(value, (list, tuple)):
        items = ", ".join(
            _yaml_dq(str(v).strip()) for v in value if str(v).strip()
        )
        return f"{key}: [{items}]"
    return f"{key}: {_yaml_dq(str(value))}"


def _rewrite_frontmatter(skill_md: str, updates: dict[str, Any]) -> str:
    """Surgically update specific frontmatter keys, preserving the body and
    every other key. Edited keys are re-emitted as double-quoted YAML
    scalars / flow lists. Raises on malformed frontmatter so we never write
    a corrupt SKILL.md.
    """
    updates = {k: v for k, v in (updates or {}).items() if v is not None}
    if not updates:
        return skill_md
    m = re.match(r"^(---\s*\n)(.*?)(\n---\s*\n)(.*)$", skill_md, re.S)
    if not m:
        raise FdeWorkbenchError(
            "SKILL.md 缺少合法 YAML frontmatter，无法安全改写"
        )
    head, block, fence, body = m.group(1), m.group(2), m.group(3), m.group(4)
    seen: set[str] = set()
    new_lines: list[str] = []
    for line in block.split("\n"):
        stripped = line.strip()
        key = (
            stripped.partition(":")[0].strip()
            if ":" in stripped and not stripped.startswith("#")
            else ""
        )
        if key in updates:
            new_lines.append(_render_fm_line(key, updates[key]))
            seen.add(key)
        else:
            new_lines.append(line)
    for key, value in updates.items():
        if key not in seen:
            new_lines.append(_render_fm_line(key, value))
    return head + "\n".join(new_lines) + fence + body


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


def _try_mirror_to_gateway(
    skill_name: str,
    bundle: dict[str, Any],
    *,
    env_values: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Best-effort: install ``skill_name`` into the gateway workspace too,
    so portal-entry chats can call it directly without delegating.

    Returns a small status dict instead of raising — mirror failure must
    never block the primary install. Skips silently when gateway isn't
    configured, doesn't exist, or already has the same-named skill.
    """
    status: dict[str, Any] = {
        "mirrored": False,
        "gateway_agent": GATEWAY_AGENT_ID,
        "skipped_reason": None,
    }
    if not _target_agent_exists(GATEWAY_AGENT_ID):
        status["skipped_reason"] = (
            f"gateway 智能体 `{GATEWAY_AGENT_ID}` 未配置，跳过镜像"
        )
        return status
    try:
        gateway_dir = _resolve_workspace_dir(GATEWAY_AGENT_ID)
    except FdeWorkbenchError as exc:
        status["skipped_reason"] = f"gateway 工作区不可用：{exc}"
        return status

    from qwenpaw.agents.skill_system import SkillService
    from qwenpaw.security.skill_scanner import SkillScanError

    service = SkillService(gateway_dir)
    try:
        created = service.create_skill(
            name=skill_name,
            content=bundle["content"],
            references=bundle["references"],
            scripts=bundle["scripts"],
            extra_files=bundle["extra_files"],
            config={},
            enable=True,
        )
    except SkillScanError as exc:
        status["skipped_reason"] = f"gateway 镜像安全扫描未通过：{exc}"
        return status
    except Exception as exc:  # noqa: BLE001 - best-effort
        status["skipped_reason"] = f"gateway 镜像失败：{exc}"
        return status
    if not created:
        status["skipped_reason"] = (
            f"gateway 已经有同名技能 `{skill_name}`，不覆盖"
        )
        return status
    try:
        service.set_skill_tags(created, [ERKAI_TAG])
    except Exception:  # noqa: BLE001
        pass
    if env_values:
        try:
            write_skill_env(
                target_workspace=GATEWAY_AGENT_ID,
                skill_name=created,
                values=env_values,
            )
        except FdeWorkbenchError:
            pass
    status["mirrored"] = True
    return status


def install_staged_skill(
    name: str,
    *,
    target_override: str | None = None,
    auto_create_target: bool = True,
    skip_domain_check: bool = False,
    env_values: dict[str, str] | None = None,
    mirror_to_gateway: bool = True,
) -> dict[str, Any]:
    """Install a staged skill into a business agent's workspace.

    By default it goes to the agent recorded in ``_fde_meta.json``;
    ``target_override`` redirects it to any existing agent (e.g. one the
    operator just created). When ``auto_create_target`` (default), if the
    target business agent doesn't exist yet it is created on the fly with
    sensible defaults — the human "confirm install" click thus atomically
    covers both "建 agent" and "装 skill" instead of forcing a separate
    manual step. Runs the real security scan via ``SkillService.create_skill``
    (a ``SkillScanError`` surfaces as an ``FdeWorkbenchError``), tags it
    ``二开``, leaves it enabled. The caller (route handler) schedules the
    target agent's reload.

    ``skip_domain_check`` is an operator-confirmed override for the
    "领域审核服务不可用" case: it pre-warms ``domain_guard``'s verdict
    cache with an ``allow`` for this exact SKILL.md content so the install
    path's own security scan skips the unreachable-LLM check. Other
    skill-scanner findings (real security issues) still block.

    ``env_values``: keys/values to write into ``.env`` in the installed
    skill dir (operator-supplied credentials from the panel form, so they
    never have to SSH in to edit files). Values containing ``\\n`` /
    quotes are written without escaping — keep them plain.

    ``mirror_to_gateway`` (default ``True``): after the primary install,
    also install a copy into the gateway agent's workspace so portal-entry
    chats can trigger the skill directly without depending on gateway's
    delegation rules knowing about the target agent. Best-effort — if
    gateway isn't configured / scan fails / a same-named skill is already
    there, the primary install still succeeds. Skipped automatically when
    the primary target *is* gateway.
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

    target_created = False
    if auto_create_target and not _target_agent_exists(target_workspace):
        create_business_agent(
            agent_id=target_workspace,
            name=target_workspace,
            description=(
                f"由 FDE 交付工作台在安装 `{name}` 时自动创建"
            ),
            active_model=_pick_default_active_model(),
        )
        target_created = True
    target_dir = _resolve_workspace_dir(target_workspace)

    domain_override_applied = False
    if skip_domain_check:
        domain_override_applied = prefill_domain_allow_for_staged(skill_dir)

    from qwenpaw.agents.skill_system import SkillService
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
    env_written: list[str] = []
    env_error: str | None = None
    if env_values:
        try:
            env_written = write_skill_env(
                target_workspace=target_workspace,
                skill_name=created,
                values=env_values,
            )["keys"]
        except FdeWorkbenchError as exc:
            env_error = str(exc)

    mirror_status: dict[str, Any] = {
        "mirrored": False,
        "gateway_agent": GATEWAY_AGENT_ID,
        "skipped_reason": (
            "目标本身就是 gateway" if target_workspace == GATEWAY_AGENT_ID
            else None
        ),
    }
    if mirror_to_gateway and target_workspace != GATEWAY_AGENT_ID:
        mirror_status = _try_mirror_to_gateway(
            created,
            bundle,
            env_values=env_values,
        )

    result: dict[str, Any] = {
        "installed": True,
        "name": created,
        "target_workspace": target_workspace,
        "target_created": target_created,
        "domain_override_applied": domain_override_applied,
        "env_written": env_written,
        "files": bundle["files"],
        "tag": ERKAI_TAG,
        "gateway_mirror": mirror_status,
    }
    if env_error:
        result["env_error"] = env_error
    return result
