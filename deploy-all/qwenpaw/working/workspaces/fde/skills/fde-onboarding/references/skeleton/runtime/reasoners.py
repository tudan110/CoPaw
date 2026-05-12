"""把业务结果组织成 markdown / portal-action / echarts 的"叙述层"。

`TemplateReasoner` 是不依赖 LLM 的确定性渲染（适合给生成的技能起手）。
如果业务需要更自然的叙述，可以再加一个调模型的 reasoner，保持同样的方法签名。
"""
from __future__ import annotations

import json
from typing import Any

from .models import AgentMessage, ProcessBlock


def _fenced(lang: str, payload: Any) -> str:
    body = payload if isinstance(payload, str) else json.dumps(
        payload, ensure_ascii=False, indent=2
    )
    return f"```{lang}\n{body}\n```"


class TemplateReasoner:
    name = "template-reasoner"

    def render_diagnosis_messages(
        self,
        *,
        context,
        primary_snapshot: dict[str, Any],
        dependency_snapshot: dict[str, Any],
        session_id: str,
    ) -> list[AgentMessage]:
        intent = getattr(context, "intent", "") or "（未提供意图）"
        lines = [
            "## 分析结论",
            "",
            f"- 会话：`{session_id}`",
            f"- 诉求：{intent}",
            f"- 关注对象：{json.dumps(getattr(context, 'target', {}), ensure_ascii=False)}",
            "",
            "> 这是由 skill_scaffold 生成的占位实现。把 `runtime/tool_adapters.py` 接上"
            "真实接口、并在这里替换成真实结论后再交付。",
        ]
        message = AgentMessage(
            content="\n".join(lines),
            process_blocks=[
                ProcessBlock(
                    title="主观测快照",
                    content=_fenced("json", primary_snapshot),
                ),
                ProcessBlock(
                    title="依赖侧快照",
                    content=_fenced("json", dependency_snapshot),
                ),
            ],
        )
        return [message]

    def render_action_result(
        self,
        *,
        operation: dict[str, Any],
        result: dict[str, Any],
    ) -> AgentMessage:
        op_title = operation.get("title") or operation.get("type") or "动作"
        lines = [
            f"## 执行结果：{op_title}",
            "",
            f"- 结果：{'成功' if result.get('success') else '失败'}"
            + ("（模拟）" if result.get("simulated") else ""),
            f"- 详情：{result.get('message', '')}",
        ]
        verification = result.get("verification")
        process_blocks = []
        if verification:
            process_blocks.append(
                ProcessBlock(
                    title="恢复验证",
                    content=_fenced("json", verification),
                )
            )
        return AgentMessage(content="\n".join(lines), process_blocks=process_blocks)
