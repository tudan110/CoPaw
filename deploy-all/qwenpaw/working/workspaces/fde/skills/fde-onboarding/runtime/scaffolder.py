"""从 skill 骨架生成一个新技能的 staged 产物。

骨架的权威概念在 `src/qwenpaw/extensions/templates/skill_scaffold/`；这里
用的是一份"已填好、可直接 import / 运行"的镜像副本，随本技能一起部署：
`fde-onboarding/references/skeleton/`。生成的产物落在 fde 工作区的
`staged/<skill_name>/`，**不会**写进任何业务智能体的工作区——真正安装由
人工在 Portal『skill 构建助手』确认后走现有 `/api/skills` 接口。
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SKILL_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")


def skeleton_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "references" / "skeleton"


def normalize_skill_name(name: str) -> str:
    norm = re.sub(r"[^a-z0-9-]+", "-", str(name or "").strip().lower()).strip("-")
    norm = re.sub(r"-{2,}", "-", norm)
    if not norm or not _SKILL_NAME_RE.match(norm):
        raise ValueError(
            f"非法技能名 {name!r}：只能用小写字母、数字、连字符，且不以连字符开头/结尾"
        )
    return norm


def _placeholders(skill_name: str, brief: dict[str, Any]) -> dict[str, str]:
    brief = brief or {}
    tags = brief.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    triggers = brief.get("triggers") or []
    if isinstance(triggers, str):
        triggers = [t.strip() for t in triggers.split(",") if t.strip()]
    scene_tag = (tags[0] if tags else skill_name).strip()
    upper = re.sub(r"[^A-Z0-9]+", "_", skill_name.upper()).strip("_") or "SKILL"
    return {
        "skill-name": skill_name,
        "skill-title": str(brief.get("title") or brief.get("display_name") or skill_name),
        "business-category": str(brief.get("category") or "ops"),
        "tags": ", ".join(str(t) for t in tags) or skill_name,
        "triggers": ", ".join(str(t) for t in triggers) or skill_name,
        "description": str(
            brief.get("description")
            or f"由 skill 构建助手生成的 {skill_name} 技能（待补全真实接口）。"
        ),
        "summary": str(brief.get("summary") or "面向具体业务场景的数字员工技能。"),
        "when-to-use": str(brief.get("when_to_use") or "继续推进业务闭环，而不是只做一般查询"),
        "scene-tag": scene_tag,
        "playbook-id": f"{skill_name}-default",
        "Playbook Display Name": str(brief.get("playbook_name") or f"{skill_name} 默认流程"),
        "env-base-url-key": f"{upper}_BASE_URL",
        "env-token-key": f"{upper}_TOKEN",
    }


def _render(text: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


_TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".yaml", ".yml", ".example", ".cfg", ".ini"}


def _is_text_file(path: Path) -> bool:
    if path.suffix in _TEXT_SUFFIXES:
        return True
    return path.name in {".gitkeep"}


def scaffold_skill(
    *,
    skill_name: str,
    target_workspace: str,
    out_dir: Path,
    brief: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把骨架渲染并写入 `out_dir/<skill_name>/`，返回 manifest。"""
    norm_name = normalize_skill_name(skill_name)
    target_workspace = str(target_workspace or "").strip()
    if not target_workspace:
        raise ValueError("必须指定 target_workspace（这个技能最终要装到哪个业务智能体）")
    src = skeleton_dir()
    if not src.is_dir():
        raise FileNotFoundError(f"找不到骨架目录：{src}")

    dest = Path(out_dir) / norm_name
    if dest.exists():
        raise FileExistsError(
            f"staged 目录已存在：{dest}（先 discard 旧产物，或换个技能名）"
        )

    brief = dict(brief or {})
    values = _placeholders(norm_name, brief)
    written: list[str] = []
    dest.mkdir(parents=True)
    for path in sorted(src.rglob("*")):
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        rel = path.relative_to(src)
        out_path = dest / rel
        if path.is_dir():
            out_path.mkdir(parents=True, exist_ok=True)
            continue
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if _is_text_file(path):
            out_path.write_text(_render(path.read_text(encoding="utf-8"), values), encoding="utf-8")
        else:
            out_path.write_bytes(path.read_bytes())
        written.append(str(rel))

    todo = list(brief.get("open_questions") or brief.get("todo") or [])
    todo = [str(t) for t in todo if str(t).strip()]
    meta = {
        "schema": "fde-staged-skill.v1",
        "skill_name": norm_name,
        "target_workspace": target_workspace,
        "source": "fde-onboarding",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "brief": brief,
        "open_questions": todo,
        "files": written,
    }
    (dest / "_fde_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    written.append("_fde_meta.json")

    generation_md = [
        f"# 生成说明：{norm_name}",
        "",
        f"- 目标工作区：`{target_workspace}`",
        f"- 生成时间：{meta['created_at']}",
        "",
        "## 待人工补全/确认",
        "",
    ]
    if todo:
        generation_md += [f"- [ ] {item}" for item in todo]
    else:
        generation_md.append("- [ ] 把 `runtime/tool_adapters.py` 的 `mock-or-real` 占位换成真实接口")
        generation_md.append("- [ ] 确认连接：复用平台 settings 已配的连接，或为新外部系统新建 settings store 字段并在设置页配置（不要塞 .env）")
    generation_md += [
        "",
        "## 安装",
        "",
        "在 Portal『skill 构建助手』面板上查看代码、（可选）沙箱试跑，然后点"
        f"「确认安装到 {target_workspace}」——安装会再走一遍安全扫描。",
    ]
    (dest / "GENERATION.md").write_text("\n".join(generation_md) + "\n", encoding="utf-8")
    written.append("GENERATION.md")
    meta["files"] = written

    return {
        "skill_name": norm_name,
        "target_workspace": target_workspace,
        "staged_dir": str(dest),
        "files": written,
        "meta": meta,
    }
