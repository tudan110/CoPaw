from __future__ import annotations

from ..models import (
    ActionExecutionResult,
    ActionProposal,
    AgentMessage,
    BusinessContext,
    DiagnosisResult,
    RouterDecision,
)

# FDE 生成时会把下面两个占位替换成具体值。
SCENE_TAG = "{{scene-tag}}"
PLAYBOOK_ID = "{{playbook-id}}"
PLAYBOOK_NAME = "{{Playbook Display Name}}"


class DefaultBusinessPlaybook:
    id = PLAYBOOK_ID
    name = PLAYBOOK_NAME

    def match(self, context: BusinessContext) -> RouterDecision:
        score = 90 if SCENE_TAG and SCENE_TAG in (context.tags or []) else 20
        return RouterDecision(
            playbook_id=self.id,
            playbook_name=self.name,
            score=score,
            matched_by="tag-match",
            reason="命中预定义业务标签" if score >= 90 else "默认承接",
        )

    def diagnose(
        self,
        *,
        context: BusinessContext,
        toolbox,
        reasoner,
        router_decision: RouterDecision,
        session_id: str,
    ) -> DiagnosisResult:
        primary_snapshot, primary_call = toolbox.collect_primary_snapshot(context)
        dependency_snapshot, dependency_call = toolbox.collect_dependency_snapshot(context)
        messages = reasoner.render_diagnosis_messages(
            context=context,
            primary_snapshot=primary_snapshot,
            dependency_snapshot=dependency_snapshot,
            session_id=session_id,
        )
        return DiagnosisResult(
            session_id=session_id,
            router=router_decision,
            playbook_id=self.id,
            playbook_name=self.name,
            reasoner=reasoner.name,
            messages=messages,
            tool_calls=[primary_call, dependency_call],
        )

    def execute_action(
        self,
        *,
        operation: dict,
        toolbox,
        reasoner,
        session_id: str,
    ) -> ActionExecutionResult:
        result, action_call = toolbox.execute_business_action(operation)
        verification, verification_call = toolbox.collect_recovery_verification(operation, result)
        result = {**result, "verification": verification}
        message = reasoner.render_action_result(operation=operation, result=result)
        updated_operation = ActionProposal(
            id=operation.get("id", ""),
            type=operation.get("type", ""),
            title=operation.get("title", ""),
            summary=operation.get("summary", ""),
            status="success" if result.get("success") else "failed",
            risk_level=operation.get("riskLevel", operation.get("risk_level", "medium")),
            params={
                key: value
                for key, value in operation.items()
                if key not in {"status", "result", "id", "type", "title", "summary"}
            }
            | {"result": result},
        )
        return ActionExecutionResult(
            session_id=session_id,
            operation=updated_operation,
            messages=[message],
            tool_calls=[action_call, verification_call],
        )


class FallbackBusinessPlaybook:
    id = "fallback"
    name = "Fallback Business Playbook"

    def match(self, context: BusinessContext) -> RouterDecision:
        return RouterDecision(
            playbook_id=self.id,
            playbook_name=self.name,
            score=1,
            matched_by="default",
            reason="未命中特定业务场景",
        )

    def diagnose(
        self,
        *,
        context: BusinessContext,
        toolbox,
        reasoner,
        router_decision: RouterDecision,
        session_id: str,
    ) -> DiagnosisResult:
        return DiagnosisResult(
            session_id=session_id,
            router=router_decision,
            playbook_id=self.id,
            playbook_name=self.name,
            reasoner=getattr(reasoner, "name", "fallback"),
            messages=[
                AgentMessage(
                    content="当前上下文未匹配到专用业务流程，请补充场景标识或升级路由规则。"
                )
            ],
            tool_calls=[],
        )

    def execute_action(self, *, operation: dict, toolbox, reasoner, session_id: str):
        raise RuntimeError("Fallback 场景不支持执行标准动作")
