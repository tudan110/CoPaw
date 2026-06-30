"""把所有外部能力调用收口到一个适配层。

生成后请把这里的 `mock-or-real` 占位替换成真实接口调用（直接 HTTP，或复用
`src/qwenpaw/extensions/integrations/*` 里的适配器）。连接凭证不在 `.env`：由
平台 settings（`settings.db`）materialize 进 `os.environ`，这里用 `os.getenv`
读即可，不要写死在代码里。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def load_env_file(skill_root: Path | None = None) -> dict[str, str]:
    """读取技能目录下可选的 `.env`（如果有）——仅作本地覆盖参数用。连接 secrets
    不在这里：由平台 settings materialize 进 `os.environ`（进程环境变量优先）。"""
    root = skill_root or Path(__file__).resolve().parents[1]
    env_path = root / ".env"
    values: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            values[key.strip()] = val.strip().strip('"').strip("'")
    # 进程环境变量优先
    for key in list(values):
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


@dataclass
class ToolCallRecord:
    name: str
    stage: str
    summary: str
    request: dict[str, Any]
    response: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "stage": self.stage,
            "summary": self.summary,
            "request": self.request,
            "response": self.response,
        }


class BusinessToolbox:
    def __init__(self, skill_root: Path | None = None) -> None:
        self.env = load_env_file(skill_root)

    def collect_primary_snapshot(self, context) -> tuple[dict[str, Any], ToolCallRecord]:
        payload = {
            "source": "mock-or-real",
            "summary": "这里放主观测数据，例如业务状态、实例指标、工单详情。"
            "把它换成真实接口返回。",
        }
        return payload, ToolCallRecord(
            name="collect_primary_snapshot",
            stage="context-collection",
            summary="采集主业务观测快照",
            request=context.to_dict(),
            response=payload,
        )

    def collect_dependency_snapshot(self, context) -> tuple[dict[str, Any], ToolCallRecord]:
        payload = {
            "source": "mock-or-real",
            "summary": "这里放依赖系统观测数据，例如数据库、中间件、外部接口。",
        }
        return payload, ToolCallRecord(
            name="collect_dependency_snapshot",
            stage="dependency-analysis",
            summary="采集依赖侧观测快照",
            request=context.to_dict(),
            response=payload,
        )

    def execute_business_action(self, operation: dict[str, Any]) -> tuple[dict[str, Any], ToolCallRecord]:
        payload = {
            "success": True,
            "simulated": True,
            "message": "当前为模板动作，后续替换为真实执行接口。",
        }
        return payload, ToolCallRecord(
            name="execute_business_action",
            stage="action-execution",
            summary="执行业务动作",
            request=operation,
            response=payload,
        )

    def collect_recovery_verification(
        self,
        operation: dict[str, Any],
        result: dict[str, Any],
    ) -> tuple[dict[str, Any], ToolCallRecord]:
        payload = {
            "mode": "mock-stream",
            "transport": "sse",
            "provider": "mock-business-verifier",
            "beforeSnapshot": {"metricA": 98, "metricB": 8200},
            "afterSnapshot": {"metricA": 35, "metricB": 620},
            "timeline": [],
        }
        return payload, ToolCallRecord(
            name="collect_recovery_verification",
            stage="recovery-verification",
            summary="采集动作执行后的恢复验证数据",
            request={"operation": operation, "result": result},
            response=payload,
        )
