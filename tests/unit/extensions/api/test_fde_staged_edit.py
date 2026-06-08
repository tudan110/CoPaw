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


def test_update_env_example_sets_values_and_empties_secrets():
    text = "# token\nCMDB_TOKEN=\n# base url\nCMDB_BASE_URL=\n"
    out = svc._update_env_example(
        text,
        {
            "CMDB_TOKEN": "super-secret",      # secret -> emptied (D4)
            "CMDB_BASE_URL": "http://x:8000",  # non-secret -> kept
            "EXTRA_FLAG": "1",                 # new key appended
        },
    )
    assert "CMDB_TOKEN=\n" in out             # value stripped
    assert "super-secret" not in out          # secret never lands on disk
    assert "CMDB_BASE_URL=http://x:8000" in out
    assert "EXTRA_FLAG=1" in out
    # comments preserved
    assert "# token" in out and "# base url" in out


def test_is_secret_env_key_matches_credential_shapes():
    for k in ["CMDB_TOKEN", "API_KEY", "x_secret", "DB_PASSWORD", "AK", "app_sk"]:
        assert svc._is_secret_env_key(k) is True
    for k in ["CMDB_BASE_URL", "TIMEOUT", "TASK_URL", "REGION"]:
        assert svc._is_secret_env_key(k) is False
