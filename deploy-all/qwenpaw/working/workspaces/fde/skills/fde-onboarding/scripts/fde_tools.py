#!/usr/bin/env python3
"""skill 构建助手的确定性工具。

在 QwenPaw 聊天里由 fde 智能体通过 shell 调用（用 app 自带的 python，不要 uv，
因为要 import qwenpaw 做安全扫描/领域审查）。所有子命令都支持 `--json`。

子命令::

  scaffold     --name N --target-workspace W [--brief-file F] [--out-dir D] [--json]
  selfcheck    --skill-dir D [--json]
  list-staged  [--staged-dir D] [--json]
  show-staged  --name N [--staged-dir D] [--max-bytes 20000] [--json]
  probe        --skill-dir D [--context-file F] [--json]
  discard      --name N [--staged-dir D] [--yes]
  create-agent --id X [--name Y] [--description D] [--provider P --model M] [--json]
  list-agents  [--json]

staged 目录默认是 fde 工作区下的 `staged/`（也可用环境变量
`QWENPAW_FDE_STAGED_DIR` 覆盖）。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_SKILL_ROOT = Path(__file__).resolve().parents[1]
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

from runtime.scaffolder import normalize_skill_name, scaffold_skill  # noqa: E402
from runtime.selfcheck import run_selfcheck  # noqa: E402

_PROBE_TIMEOUT_SECONDS = int(os.environ.get("QWENPAW_FDE_PROBE_TIMEOUT", "45") or "45")
_MAX_TREE_FILE_BYTES = 200_000


def _default_staged_dir() -> Path:
    override = os.environ.get("QWENPAW_FDE_STAGED_DIR")
    if override:
        return Path(override).expanduser()
    # <fde_workspace>/skills/fde-onboarding/scripts/fde_tools.py -> parents[3] == <fde_workspace>
    return _SKILL_ROOT.parents[1] / "staged"


def _emit(payload, *, as_json: bool, human=None) -> None:
    # ensure_ascii=True keeps JSON stdout pure ASCII so it survives any
    # host code page (a Windows zh-CN GBK pipe) byte-for-byte; the
    # parent's json.loads restores the unicode. No stdout reconfigure /
    # no parent-side encoding= needed, and nothing to restart.
    if as_json:
        print(json.dumps(payload, ensure_ascii=True, indent=2))
    elif human is not None:
        print(human)
    else:
        print(json.dumps(payload, ensure_ascii=True, indent=2))


def _read_brief(path: str | None) -> dict:
    if not path:
        return {}
    data = json.loads(Path(path).expanduser().read_text(encoding="utf-8") or "{}")
    if not isinstance(data, dict):
        raise SystemExit("brief 文件必须是一个 JSON 对象")
    return data


def cmd_scaffold(args) -> int:
    out_dir = Path(args.out_dir).expanduser() if args.out_dir else _default_staged_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    result = scaffold_skill(
        skill_name=args.name,
        target_workspace=args.target_workspace,
        out_dir=out_dir,
        brief=_read_brief(args.brief_file),
    )
    # 顺手跑一次自检
    result["selfcheck"] = run_selfcheck(result["staged_dir"])
    human = (
        f"✅ 已生成 staged 技能 `{result['skill_name']}` -> {result['staged_dir']}\n"
        f"   目标工作区：{result['target_workspace']}；文件 {len(result['files'])} 个\n"
        f"   自检：{'通过' if result['selfcheck'].get('ready_for_review') else '未通过 → ' + '; '.join(result['selfcheck'].get('blocked_reasons') or [])}\n"
        f"   待确认项：{len(result['selfcheck'].get('todo') or [])} 条"
    )
    _emit(result, as_json=args.json, human=human)
    return 0


def cmd_selfcheck(args) -> int:
    # 交互式体检：安全扫描 + 语法，不跑领域审查那次 LLM（受限流）。
    # 领域审查在确认安装时由 create_skill 权威校验。
    result = run_selfcheck(
        Path(args.skill_dir).expanduser(), with_domain=False
    )
    human = (
        f"{'✅ 自检通过' if result.get('ready_for_review') else '⛔ 自检未通过'}：{result.get('skill_name')}\n"
        + ("阻塞：" + "; ".join(result.get("blocked_reasons") or []) + "\n" if result.get("blocked_reasons") else "")
        + ("警告：" + "; ".join(result.get("warnings") or []) + "\n" if result.get("warnings") else "")
        + ("待确认项：\n" + "\n".join(f"  - {t}" for t in (result.get("todo") or [])) if result.get("todo") else "")
    )
    _emit(result, as_json=args.json, human=human)
    return 0 if result.get("ready_for_review") else 0


def _staged_entries(staged_dir: Path) -> list[dict]:
    entries: list[dict] = []
    if not staged_dir.is_dir():
        return entries
    for child in sorted(staged_dir.iterdir()):
        if not child.is_dir():
            continue
        meta_path = child / "_fde_meta.json"
        meta = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                meta = {}
        entries.append(
            {
                "skill_name": child.name,
                "staged_dir": str(child),
                "target_workspace": meta.get("target_workspace", ""),
                "created_at": meta.get("created_at", ""),
                "open_questions": meta.get("open_questions", []),
            }
        )
    return entries


def cmd_list_staged(args) -> int:
    staged_dir = Path(args.staged_dir).expanduser() if args.staged_dir else _default_staged_dir()
    entries = _staged_entries(staged_dir)
    payload = {"staged_dir": str(staged_dir), "skills": entries}
    if entries:
        human = f"staged 目录 {staged_dir}：\n" + "\n".join(
            f"  - {e['skill_name']}  → {e['target_workspace'] or '(未标注目标)'}  ({e['created_at']})"
            for e in entries
        )
    else:
        human = f"staged 目录 {staged_dir} 还没有产物。"
    _emit(payload, as_json=args.json, human=human)
    return 0


def _read_tree(root: Path, *, max_bytes: int) -> list[dict]:
    files: list[dict] = []
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        rel = str(path.relative_to(root))
        size = path.stat().st_size
        entry = {"path": rel, "size": size}
        if size <= min(max_bytes, _MAX_TREE_FILE_BYTES):
            try:
                entry["content"] = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                entry["content"] = None
                entry["binary"] = True
        else:
            entry["content"] = None
            entry["truncated"] = True
        files.append(entry)
    return files


def cmd_show_staged(args) -> int:
    staged_dir = Path(args.staged_dir).expanduser() if args.staged_dir else _default_staged_dir()
    name = normalize_skill_name(args.name)
    skill_dir = staged_dir / name
    if not skill_dir.is_dir():
        _emit({"error": f"未找到 staged 技能 {name}"}, as_json=args.json, human=f"未找到 staged 技能 {name}")
        return 1
    files = _read_tree(skill_dir, max_bytes=args.max_bytes)
    # 加载详情=纯文件呈现，必须秒回：跳过安全扫描（要 import
    # skill_scanner，数秒）和领域审查（LLM，受限流）。点『重新自检』
    # 跑扫描；领域审查在确认安装时权威校验。
    selfcheck = run_selfcheck(skill_dir, with_scan=False, with_domain=False)
    payload = {"skill_name": name, "staged_dir": str(skill_dir), "files": files, "selfcheck": selfcheck}
    human = (
        f"# {name}（{len(files)} 个文件）\n"
        + "\n".join(f"  - {f['path']}  ({f['size']}B)" for f in files)
        + f"\n自检：{'通过' if selfcheck.get('ready_for_review') else '未通过'}"
    )
    _emit(payload, as_json=args.json, human=human)
    return 0


def cmd_probe(args) -> int:
    skill_dir = Path(args.skill_dir).expanduser().resolve()
    bridge = skill_dir / "scripts" / "chat_skill_bridge.py"
    if not bridge.exists():
        _emit({"error": f"找不到 {bridge}"}, as_json=args.json, human=f"找不到 {bridge}")
        return 1
    ctx_path = args.context_file
    tmp_ctx = None
    if not ctx_path:
        scene = skill_dir.name
        tmp_ctx = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(
            {"sessionId": "fde-probe", "intent": "FDE 沙箱试跑示例诉求", "tags": [scene], "target": {}, "params": {}},
            tmp_ctx,
            ensure_ascii=False,
        )
        tmp_ctx.close()
        ctx_path = tmp_ctx.name
    try:
        proc = subprocess.run(
            [sys.executable, "-B", str(bridge), "diagnose", "--context-file", str(ctx_path)],
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
            cwd=str(skill_dir),
        )
        payload = {
            "skill_dir": str(skill_dir),
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "ok": proc.returncode == 0 and bool(proc.stdout.strip()),
        }
    except subprocess.TimeoutExpired:
        payload = {"skill_dir": str(skill_dir), "ok": False, "error": f"超时 {_PROBE_TIMEOUT_SECONDS}s"}
    finally:
        if tmp_ctx is not None:
            try:
                os.unlink(tmp_ctx.name)
            except OSError:
                pass
    human = (
        f"{'✅ 沙箱试跑成功' if payload.get('ok') else '⛔ 沙箱试跑失败'}：{skill_dir.name}\n"
        f"--- diagnose 输出 ---\n{payload.get('stdout') or payload.get('error') or ''}"
        + (f"\n--- stderr ---\n{payload['stderr']}" if payload.get("stderr") else "")
    )
    _emit(payload, as_json=args.json, human=human)
    return 0 if payload.get("ok") else 1


def cmd_create_agent(args) -> int:
    """Create a new business agent (workspace + config profile).

    Goes through ``fde_workbench_service.create_business_agent`` so the
    auto-create-on-install path and this one stay in lockstep.
    """
    from qwenpaw.extensions.api import fde_workbench_service as svc

    active_model = None
    if args.provider or args.model:
        active_model = {
            "provider_id": args.provider or "",
            "model": args.model or "",
        }
    try:
        info = svc.create_business_agent(
            agent_id=args.id,
            name=args.name or args.id,
            description=args.description or "",
            active_model=active_model,
        )
    except svc.FdeWorkbenchError as exc:
        _emit(
            {"error": str(exc)},
            as_json=args.json,
            human=f"⛔ 建业务智能体失败：{exc}",
        )
        return 1
    am = info.get("active_model") or {}
    human = (
        f"✅ 已创建业务智能体 `{info['id']}`（{info['name']}）\n"
        f"   workspace_dir: {info['workspace_dir']}\n"
        + (
            f"   active_model:  {am.get('provider_id', '')}/"
            f"{am.get('model', '')}\n"
            if am
            else "   active_model:  (未设置——继承默认或后续在面板里设)\n"
        )
        + "  下一步：把 staged 技能装到这个工作区，"
        "或者由 FDE 继续生成技能。"
    )
    _emit(info, as_json=args.json, human=human)
    return 0


def cmd_list_agents(args) -> int:
    """List configured business agents (for FDE to decide reuse vs create)."""
    from qwenpaw.config.utils import load_config

    config = load_config()
    profiles = getattr(config.agents, "profiles", {}) or {}
    order = list(getattr(config.agents, "agent_order", []) or [])
    agents = []
    for agent_id in order:
        ref = profiles.get(agent_id)
        if ref is None:
            continue
        agents.append(
            {
                "id": agent_id,
                "workspace_dir": getattr(ref, "workspace_dir", ""),
                "enabled": getattr(ref, "enabled", True),
            }
        )
    # any profiles missing from agent_order get appended
    for agent_id, ref in profiles.items():
        if agent_id in order:
            continue
        agents.append(
            {
                "id": agent_id,
                "workspace_dir": getattr(ref, "workspace_dir", ""),
                "enabled": getattr(ref, "enabled", True),
            }
        )
    payload = {"count": len(agents), "agents": agents}
    human = "已配置的业务智能体：\n" + "\n".join(
        f"  - {a['id']}"
        + ("" if a["enabled"] else "  (停用)")
        + f"  → {a['workspace_dir']}"
        for a in agents
    ) if agents else "还没有配置任何业务智能体。"
    _emit(payload, as_json=args.json, human=human)
    return 0


def cmd_discard(args) -> int:
    staged_dir = Path(args.staged_dir).expanduser() if args.staged_dir else _default_staged_dir()
    name = normalize_skill_name(args.name)
    skill_dir = staged_dir / name
    if not skill_dir.is_dir():
        _emit({"error": f"未找到 staged 技能 {name}"}, as_json=args.json, human=f"未找到 staged 技能 {name}")
        return 1
    shutil.rmtree(skill_dir)
    _emit({"discarded": name}, as_json=args.json, human=f"🗑️ 已删除 staged 技能 {name}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="以 JSON 输出")

    parser = argparse.ArgumentParser(description="skill 构建助手工具")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("scaffold", parents=[common], help="从骨架生成一个 staged 技能")
    p.add_argument("--name", required=True)
    p.add_argument("--target-workspace", required=True, help="这个技能最终装到哪个业务智能体（如 query/fault/resource）")
    p.add_argument("--brief-file", help="交付需求单 JSON（用于渲染占位/记录待确认项）")
    p.add_argument("--out-dir", help="staged 输出目录（默认 fde 工作区的 staged/）")
    p.set_defaults(func=cmd_scaffold)

    p = sub.add_parser("selfcheck", parents=[common], help="对一个 staged 技能跑自检")
    p.add_argument("--skill-dir", required=True)
    p.set_defaults(func=cmd_selfcheck)

    p = sub.add_parser("list-staged", parents=[common], help="列出 staged 技能")
    p.add_argument("--staged-dir")
    p.set_defaults(func=cmd_list_staged)

    p = sub.add_parser("show-staged", parents=[common], help="打印一个 staged 技能的文件树+内容")
    p.add_argument("--name", required=True)
    p.add_argument("--staged-dir")
    p.add_argument("--max-bytes", type=int, default=20_000)
    p.set_defaults(func=cmd_show_staged)

    p = sub.add_parser("probe", parents=[common], help="沙箱里跑一遍生成技能的 diagnose")
    p.add_argument("--skill-dir", required=True)
    p.add_argument("--context-file", help="业务上下文 JSON（不给则用示例）")
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("discard", parents=[common], help="删除一个 staged 技能")
    p.add_argument("--name", required=True)
    p.add_argument("--staged-dir")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_discard)

    p = sub.add_parser(
        "create-agent",
        parents=[common],
        help="创建一个新的业务智能体（workspace + config profile + agent.json）",
    )
    p.add_argument("--id", required=True, help="业务智能体 id（小写字母/数字/-/_）")
    p.add_argument("--name", help="人读名（默认与 --id 同）")
    p.add_argument("--description", default="")
    p.add_argument("--provider", help="active_model.provider_id（默认继承 fde / default agent 的）")
    p.add_argument("--model", help="active_model.model")
    p.set_defaults(func=cmd_create_agent)

    p = sub.add_parser(
        "list-agents",
        parents=[common],
        help="列出已配置的业务智能体（FDE 决定复用还是新建时用）",
    )
    p.set_defaults(func=cmd_list_agents)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "json"):
        args.json = False
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
