from __future__ import annotations

from .models import BusinessContext, RouterDecision
from .playbooks import DefaultBusinessPlaybook, FallbackBusinessPlaybook


class BusinessRouter:
    def __init__(self) -> None:
        self.playbooks = [
            DefaultBusinessPlaybook(),
            FallbackBusinessPlaybook(),
        ]

    def route(self, context: BusinessContext) -> tuple[RouterDecision, object]:
        decisions: list[tuple[RouterDecision, object]] = []
        for playbook in self.playbooks:
            decision = playbook.match(context)
            decisions.append((decision, playbook))
        return max(decisions, key=lambda item: item[0].score)
