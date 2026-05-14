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
    """Install knobs the panel can flip per click."""

    # 留空 = 装到 _fde_meta.json 里记录的目标业务智能体
    target_workspace: str = ""
    # 操作员确认的「领域审核服务不可用」覆盖：把代码看过、确认是网管域，再点
    skip_domain_check: bool = False
    # 操作员在面板里填的 .env 凭证（key -> value），安装后写到技能目录
    env_values: dict[str, str] | None = None
    # 默认装好之后也往 gateway 镜像一份（确保 portal 入口能直接触发）；
    # 极少数情况下不希望镜像可以把它设成 False。
    mirror_to_gateway: bool = True


class FdeEnvWriteRequest(BaseModel):
    """Write or update credentials in an already-installed skill's `.env`."""

    target_workspace: str
    skill_name: str
    values: dict[str, str] = Field(default_factory=dict)


class FdeCopyInstalledRequest(BaseModel):
    """Copy or move an installed 二开 skill to another business agent.

    Used when FDE put the skill in the wrong workspace (e.g. invented an
    ``export`` agent that gateway routing doesn't know about), so the
    operator can put it where the entry / business agent will actually
    pick it up — without going back through FDE chat + regenerate.
    """

    target_workspace: str
    # True = move semantics (also deletes the source). False (default) =
    # leave a copy at the source too.
    remove_source: bool = False
    skip_domain_check: bool = False
