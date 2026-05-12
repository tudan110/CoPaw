"""数据模型 —— 由 FDE 交付助手生成的技能骨架自带。

镜像 `src/qwenpaw/extensions/templates/skill_scaffold/` 的概念，但这里是
一份可直接 import / 运行的最小实现。生成后可以按业务需要扩展字段，
但保持 `BusinessContext.from_payload` / `*.to_dict` 这几个契约不变。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProcessBlock:
    """一段"过程证据"，Portal 会折叠展示。"""

    title: str
    content: str

    def to_dict(self) -> dict[str, Any]:
        return {"title": self.title, "content": self.content}


@dataclass
class ActionProposal:
    """对应 `protocols/portal_action` —— Portal 渲染成动作按钮/确认框。"""

    id: str = ""
    type: str = ""
    title: str = ""
    summary: str = ""
    status: str = "ready"  # ready | running | success | failed
    risk_level: str = "medium"  # low | medium | high
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "summary": self.summary,
            "status": self.status,
            "riskLevel": self.risk_level,
        }
        payload.update(self.params or {})
        return payload


@dataclass
class AgentMessage:
    content: str = ""
    process_blocks: list[ProcessBlock] = field(default_factory=list)
    action: ActionProposal | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "processBlocks": [b.to_dict() for b in self.process_blocks],
            "action": self.action.to_dict() if self.action else None,
        }


@dataclass
class RouterDecision:
    playbook_id: str
    playbook_name: str
    score: int
    matched_by: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "playbookId": self.playbook_id,
            "playbookName": self.playbook_name,
            "score": self.score,
            "matchedBy": self.matched_by,
            "reason": self.reason,
        }


@dataclass
class BusinessContext:
    """从聊天里抽出来的"业务上下文(JSON)"。

    约定字段都是可选的；不同技能按需取用。`raw` 保留完整原始 payload。
    """

    session_id: str = ""
    intent: str = ""
    tags: list[str] = field(default_factory=list)
    target: dict[str, Any] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "BusinessContext":
        payload = dict(payload or {})
        tags = payload.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        return cls(
            session_id=str(payload.get("sessionId") or payload.get("session_id") or ""),
            intent=str(payload.get("intent") or ""),
            tags=[str(t) for t in tags],
            target=dict(payload.get("target") or {}),
            params=dict(payload.get("params") or {}),
            raw=payload,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "sessionId": self.session_id,
            "intent": self.intent,
            "tags": list(self.tags),
            "target": dict(self.target),
            "params": dict(self.params),
        }


# 兼容别名：skill_scaffold 的 playbook 模板用 `TicketContext` 作为类型名。
TicketContext = BusinessContext


@dataclass
class DiagnosisResult:
    session_id: str
    router: RouterDecision
    playbook_id: str
    playbook_name: str
    reasoner: str
    messages: list[AgentMessage] = field(default_factory=list)
    tool_calls: list[Any] = field(default_factory=list)


@dataclass
class ActionExecutionResult:
    session_id: str
    operation: ActionProposal
    messages: list[AgentMessage] = field(default_factory=list)
    tool_calls: list[Any] = field(default_factory=list)
