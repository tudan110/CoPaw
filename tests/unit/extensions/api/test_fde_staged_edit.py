# -*- coding: utf-8 -*-
"""缺口A：引导字段 + 高级直改 + 路径安全。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from qwenpaw.extensions.api import fde_workbench_service as svc

SKILL_MD = (
    "---\n"
    "name: demo\n"
    "category: ops-delivery\n"
    "tags: [fde, demo]\n"
    "triggers: [告警, 查询]\n"
    "description: 老描述\n"
    "---\n\n"
    "# Demo\n\n正文保持不动。\n"
)


def test_rewrite_frontmatter_updates_keys_preserves_body():
    out = svc._rewrite_frontmatter(
        SKILL_MD,
        {
            "description": "新描述: 含冒号也安全",
            "triggers": ["应用拓扑", "查CMDB"],
        },
    )
    # body untouched
    assert "正文保持不动。" in out
    # frontmatter still valid YAML and reflects the edits
    block = out.split("---", 2)[1]
    data = yaml.safe_load(block)
    assert data["description"] == "新描述: 含冒号也安全"
    assert data["triggers"] == ["应用拓扑", "查CMDB"]
    # untouched keys survive
    assert data["name"] == "demo"
    assert data["category"] == "ops-delivery"


def test_rewrite_frontmatter_rejects_missing_frontmatter():
    with pytest.raises(svc.FdeWorkbenchError):
        svc._rewrite_frontmatter("no frontmatter here\n", {"description": "x"})
