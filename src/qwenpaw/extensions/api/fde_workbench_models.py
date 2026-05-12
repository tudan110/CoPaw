"""Request/response models for the Portal FDE delivery workbench.

Kept free of FastAPI imports so unit tests can use them directly.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FdeGenerateRequest(BaseModel):
    """Generate (scaffold) a new staged skill from the FDE skeleton."""

    # 技能名（小写字母/数字/连字符，不以连字符开头/结尾）
    name: str = Field(..., description="技能名")
    # 生成的技能最终装到哪个业务智能体（如 query / fault / resource）
    target_workspace: str = Field(..., description="目标业务智能体")
    # 交付需求单：用于渲染占位、记录待确认项
    brief: dict[str, Any] = Field(default_factory=dict, description="交付需求单")


class FdeProbeRequest(BaseModel):
    """Optionally provide a sample business context for the sandbox run."""

    context: dict[str, Any] = Field(default_factory=dict)


class FdeInstallRequest(BaseModel):
    """Optionally redirect the install to a different existing agent."""

    # 留空 = 装到 _fde_meta.json 里记录的目标业务智能体
    target_workspace: str = ""
