#!/usr/bin/env python3
"""生成的技能在 QwenPaw 聊天里的标准入口（FDE scaffold）。

用法::

    python scripts/chat_skill_bridge.py diagnose --context-file /tmp/ctx.json
    python scripts/chat_skill_bridge.py execute  --context-file /tmp/ctx.json

context 文件是一个 JSON 对象（"业务上下文(JSON)"）；至少包含 `sessionId`，
执行动作时还要带 `confirmedAction`。
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path


def _load_runtime():
    skill_root = Path(__file__).resolve().parents[1]
    if str(skill_root) not in sys.path:
        sys.path.insert(0, str(skill_root))
    from runtime.models import BusinessContext
    from runtime.reasoners import TemplateReasoner
    from runtime.router import BusinessRouter
    from runtime.tool_adapters import BusinessToolbox

    return BusinessContext, BusinessRouter, BusinessToolbox, TemplateReasoner, skill_root


def _load_context(context_file: str) -> dict:
    payload = json.loads(Path(context_file).expanduser().read_text(encoding="utf-8") or "{}")
    if not isinstance(payload, dict):
        raise RuntimeError("Context JSON must be an object")
    return payload


def _render_action_block(action_payload: dict) -> str:
    return "```portal-action\n" + json.dumps(action_payload, ensure_ascii=False, indent=2) + "\n```"


def _render_markdown(messages: list, *, include_action_block: bool) -> str:
    sections: list[str] = []
    for message in messages:
        if getattr(message, "content", ""):
            sections.append(str(message.content).strip())
        for block in getattr(message, "process_blocks", []) or []:
            sections.append(f"## {block.title}\n\n{block.content}".strip())
        action = getattr(message, "action", None)
        if action and include_action_block:
            sections.append(_render_action_block(action.to_dict()))
    return "\n\n".join(s for s in sections if s).strip()


def _diagnose(payload: dict) -> str:
    BusinessContext, BusinessRouter, BusinessToolbox, TemplateReasoner, skill_root = _load_runtime()
    context = BusinessContext.from_payload(payload)
    session_id = payload.get("sessionId") or f"skill-{uuid.uuid4().hex[:12]}"
    router_decision, playbook = BusinessRouter().route(context)
    diagnosis = playbook.diagnose(
        context=context,
        toolbox=BusinessToolbox(skill_root),
        reasoner=TemplateReasoner(),
        router_decision=router_decision,
        session_id=session_id,
    )
    return _render_markdown(diagnosis.messages, include_action_block=True)


def _execute(payload: dict) -> str:
    BusinessContext, BusinessRouter, BusinessToolbox, TemplateReasoner, skill_root = _load_runtime()
    context = BusinessContext.from_payload(payload)
    session_id = payload.get("sessionId") or f"skill-{uuid.uuid4().hex[:12]}"
    _decision, playbook = BusinessRouter().route(context)
    execution = playbook.execute_action(
        operation=payload.get("confirmedAction") or {},
        toolbox=BusinessToolbox(skill_root),
        reasoner=TemplateReasoner(),
        session_id=session_id,
    )
    return _render_markdown(execution.messages, include_action_block=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generated CoPAW skill bridge")
    parser.add_argument("command", choices=["diagnose", "execute"])
    parser.add_argument("--context-file", required=True)
    args = parser.parse_args()
    payload = _load_context(args.context_file)
    print(_diagnose(payload) if args.command == "diagnose" else _execute(payload))


if __name__ == "__main__":
    main()
