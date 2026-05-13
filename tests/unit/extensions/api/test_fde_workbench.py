# -*- coding: utf-8 -*-
"""Tests for the Portal FDE delivery workbench service.

The lifecycle test exercises the meta-skill end to end through the service
layer (which shells out to ``skills/fde-onboarding/scripts/fde_tools.py``),
pointing the ``fde`` workspace at the repo's deploy seed and the staged dir at
``tmp_path``. The lighter tests cover the FastAPI-free helpers directly.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from qwenpaw.extensions.api import fde_workbench_service as svc

REPO_ROOT = Path(__file__).resolve().parents[4]
FDE_WORKSPACE = (
    REPO_ROOT / "deploy-all" / "qwenpaw" / "working" / "workspaces" / "fde"
)


@pytest.fixture
def fde_env(monkeypatch, tmp_path):
    """Point the service at the repo's fde workspace + a temp staged dir."""
    staged = tmp_path / "staged"
    staged.mkdir()
    monkeypatch.setattr(svc, "fde_workspace_dir", lambda: FDE_WORKSPACE)
    monkeypatch.setenv("QWENPAW_FDE_STAGED_DIR", str(staged))
    return staged


def test_workspace_seed_is_present():
    skill = FDE_WORKSPACE / "skills" / "fde-onboarding"
    skeleton = skill / "references" / "skeleton"
    assert (skill / "scripts" / "fde_tools.py").exists()
    assert (skeleton / "SKILL.md").exists()
    assert (skeleton / "runtime" / "models.py").exists()


def test_workbench_info(fde_env):
    info = svc.workbench_info()
    assert info["available"] is True
    assert info["agentId"] == "fde"
    assert info["onboardingSkill"] == "fde-onboarding"


def test_full_staged_skill_lifecycle(fde_env):
    """generate -> list -> show -> read bundle -> probe -> discard."""
    result = svc.generate_skill(
        name="demo-alarm-stat",
        target_workspace="query",
        brief={
            "description": "演示：按设备分组统计告警并出柱状图",
            "tags": ["alarm", "stat", "monitoring", "network-management"],
            "triggers": ["告警统计", "按设备统计告警"],
            "open_questions": ["确认 realalarm 接口的鉴权方式"],
        },
    )
    assert result["skill_name"] == "demo-alarm-stat"
    assert result["target_workspace"] == "query"
    assert "SKILL.md" in result["files"]
    assert "_fde_meta.json" in result["files"]
    assert result["selfcheck"]["ready_for_review"] is True
    assert any("鉴权" in t for t in result["selfcheck"]["todo"])

    listing = svc.list_staged_skills()
    assert "demo-alarm-stat" in [s["skill_name"] for s in listing["skills"]]

    detail = svc.show_staged_skill("demo-alarm-stat")
    paths = {f["path"] for f in detail["files"]}
    assert "SKILL.md" in paths
    assert "runtime/router.py" in paths
    assert "scripts/chat_skill_bridge.py" in paths
    skill_md = next(f for f in detail["files"] if f["path"] == "SKILL.md")
    assert "name: demo-alarm-stat" in (skill_md["content"] or "")
    assert detail["selfcheck"]["ready_for_review"] is True

    bundle = svc._read_staged_bundle(fde_env / "demo-alarm-stat")
    assert "name: demo-alarm-stat" in bundle["content"]
    assert "chat_skill_bridge.py" in (bundle["scripts"] or {})
    assert "runtime" in (bundle["extra_files"] or {})
    assert "router.py" in bundle["extra_files"]["runtime"]
    # FDE-internal files are excluded from the install payload
    assert "_fde_meta.json" not in (bundle["extra_files"] or {})
    assert "GENERATION.md" not in (bundle["extra_files"] or {})

    # With auto_create_target disabled, installing to an unknown target
    # still raises (the strict behavior — explicit opt-out for tests that
    # mustn't touch the real config).
    with pytest.raises(svc.FdeWorkbenchError):
        svc.install_staged_skill(
            "demo-alarm-stat",
            target_override="no-such-agent-xyz",
            auto_create_target=False,
        )

    probe = svc.probe_staged_skill("demo-alarm-stat")
    assert probe["ok"] is True
    assert "分析结论" in (probe.get("stdout") or "")

    svc.discard_staged_skill("demo-alarm-stat")
    assert svc.list_staged_skills()["skills"] == []


def test_install_staged_skill_into_workspace(fde_env, monkeypatch, tmp_path):
    """generate -> install into a (temp) agent workspace -> verify on disk.

    Exercises the real ``SkillService.create_skill`` / ``set_skill_tags`` path
    (including its security scan) so a broken import there can't slip through.
    """
    workspace = tmp_path / "agent-ws"
    workspace.mkdir()
    monkeypatch.setattr(svc, "_resolve_workspace_dir", lambda ws: workspace)
    # Pretend the target agent already exists so we don't accidentally
    # invoke ``create_business_agent`` (which would touch the real config).
    monkeypatch.setattr(svc, "_target_agent_exists", lambda ws: True)

    svc.generate_skill(
        name="demo-installable",
        target_workspace="some-business-agent",
        brief={
            "description": "演示：按设备分组统计告警并出柱状图",
            "tags": ["alarm", "stat", "monitoring", "network-management"],
            "triggers": ["告警统计"],
        },
    )

    result = svc.install_staged_skill("demo-installable")
    assert result["installed"] is True
    assert result["name"] == "demo-installable"
    assert result["tag"] == "二开"
    assert result["target_created"] is False

    skill_dir = workspace / "skills" / "demo-installable"
    assert (skill_dir / "SKILL.md").exists()
    assert (skill_dir / "runtime" / "router.py").exists()
    assert (skill_dir / "scripts" / "chat_skill_bridge.py").exists()
    assert (skill_dir / ".env.example").exists()
    # FDE-internal files must not be copied into the installed skill
    assert not (skill_dir / "_fde_meta.json").exists()
    assert not (skill_dir / "GENERATION.md").exists()

    import json as _json

    manifest = _json.loads((workspace / "skill.json").read_text("utf-8"))
    entry = manifest["skills"]["demo-installable"]
    assert entry["enabled"] is True
    assert entry["tags"] == ["二开"]

    # installing the same name again is rejected (skill already there)
    with pytest.raises(svc.FdeWorkbenchError):
        svc.install_staged_skill("demo-installable")


def test_install_mirrors_to_gateway_by_default(
    fde_env, monkeypatch, tmp_path,
):
    """二开 skills install into BOTH the business agent AND gateway so the
    portal main chat box can trigger them directly without depending on
    gateway's delegation rules knowing about the target agent."""
    target_ws = tmp_path / "order-ws"
    gateway_ws = tmp_path / "gateway-ws"
    target_ws.mkdir()
    gateway_ws.mkdir()

    def fake_resolve(agent_id):
        if agent_id == "order":
            return target_ws
        if agent_id == "gateway":
            return gateway_ws
        raise svc.FdeWorkbenchError(f"未配置：{agent_id}")

    monkeypatch.setattr(svc, "_resolve_workspace_dir", fake_resolve)
    monkeypatch.setattr(
        svc, "_target_agent_exists", lambda ws: ws in {"order", "gateway"},
    )

    svc.generate_skill(
        name="demo-mirror",
        target_workspace="order",
        brief={
            "description": "演示装到 order 后镜像到 gateway",
            "tags": ["alarm", "fault", "network-management", "workorder"],
            "triggers": ["告警", "工单"],
        },
    )

    result = svc.install_staged_skill("demo-mirror")
    assert result["installed"] is True
    assert result["target_workspace"] == "order"
    assert (target_ws / "skills" / "demo-mirror" / "SKILL.md").is_file()
    # gateway got its own copy
    assert (gateway_ws / "skills" / "demo-mirror" / "SKILL.md").is_file()
    mirror = result["gateway_mirror"]
    assert mirror["mirrored"] is True
    assert mirror["gateway_agent"] == "gateway"
    # gateway's manifest carries the 二开 tag
    import json as _json

    gw_manifest = _json.loads((gateway_ws / "skill.json").read_text("utf-8"))
    assert gw_manifest["skills"]["demo-mirror"]["tags"] == ["二开"]


def test_install_skips_mirror_when_target_is_gateway(
    fde_env, monkeypatch, tmp_path,
):
    """If the operator chose gateway as the target, don't double-install."""
    gateway_ws = tmp_path / "gateway-ws"
    gateway_ws.mkdir()
    monkeypatch.setattr(
        svc, "_resolve_workspace_dir", lambda ws: gateway_ws,
    )
    monkeypatch.setattr(svc, "_target_agent_exists", lambda ws: True)

    svc.generate_skill(
        name="demo-gw-target",
        target_workspace="gateway",
        brief={
            "description": "目标就是 gateway",
            "tags": ["alarm", "fault", "network-management"],
            "triggers": ["告警"],
        },
    )
    result = svc.install_staged_skill("demo-gw-target")
    assert result["installed"] is True
    mirror = result["gateway_mirror"]
    assert mirror["mirrored"] is False
    assert "gateway" in (mirror["skipped_reason"] or "")


def test_install_opt_out_mirror(fde_env, monkeypatch, tmp_path):
    """``mirror_to_gateway=False`` leaves gateway untouched."""
    target_ws = tmp_path / "order-ws"
    gateway_ws = tmp_path / "gateway-ws"
    target_ws.mkdir()
    gateway_ws.mkdir()
    monkeypatch.setattr(
        svc, "_resolve_workspace_dir",
        lambda ws: target_ws if ws == "order" else gateway_ws,
    )
    monkeypatch.setattr(
        svc, "_target_agent_exists", lambda ws: ws in {"order", "gateway"},
    )

    svc.generate_skill(
        name="demo-no-mirror",
        target_workspace="order",
        brief={
            "description": "opt-out",
            "tags": ["alarm", "fault", "network-management"],
            "triggers": ["告警"],
        },
    )
    result = svc.install_staged_skill(
        "demo-no-mirror", mirror_to_gateway=False,
    )
    assert result["installed"] is True
    assert result["gateway_mirror"]["mirrored"] is False
    assert not (gateway_ws / "skills" / "demo-no-mirror").exists()


def test_delete_installed_skill_cleans_gateway_mirror(
    fde_env, monkeypatch, tmp_path,
):
    """Deleting a 二开 skill also wipes its gateway mirror so we don't
    leave orphan code in the entry agent's workspace."""
    target_ws = tmp_path / "order-ws"
    gateway_ws = tmp_path / "gateway-ws"
    target_ws.mkdir()
    gateway_ws.mkdir()

    monkeypatch.setattr(
        svc, "_resolve_workspace_dir",
        lambda ws: gateway_ws if ws == "gateway" else target_ws,
    )
    monkeypatch.setattr(
        svc, "_target_agent_exists", lambda ws: ws in {"order", "gateway"},
    )

    svc.generate_skill(
        name="demo-delete-me",
        target_workspace="order",
        brief={
            "description": "演示删除",
            "tags": ["alarm", "fault", "network-management"],
            "triggers": ["告警"],
        },
    )
    install_result = svc.install_staged_skill("demo-delete-me")
    assert install_result["gateway_mirror"]["mirrored"] is True
    assert (target_ws / "skills" / "demo-delete-me").is_dir()
    assert (gateway_ws / "skills" / "demo-delete-me").is_dir()

    result = svc.delete_installed_skill(
        target_workspace="order", skill_name="demo-delete-me",
    )
    assert result["deleted"] is True
    assert result["gateway_mirror_removed"] is True
    assert not (target_ws / "skills" / "demo-delete-me").exists()
    assert not (gateway_ws / "skills" / "demo-delete-me").exists()


def test_delete_installed_skill_missing(monkeypatch, tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setattr(svc, "_resolve_workspace_dir", lambda ws: workspace)
    with pytest.raises(svc.FdeWorkbenchError):
        svc.delete_installed_skill(
            target_workspace="biz", skill_name="nope",
        )


def test_copy_installed_skill_move(fde_env, monkeypatch, tmp_path):
    """Copy an installed skill from one workspace to another (move semantics).

    Mirrors the "FDE put the skill in the wrong agent, gateway routing
    doesn't see it" recovery flow that the panel's 「迁移到其他智能体」
    button drives.
    """
    src = tmp_path / "src-ws"
    dst = tmp_path / "dst-ws"
    src.mkdir()
    dst.mkdir()

    # First seed a real installed skill in src — generate + install via the
    # service (with a stubbed _resolve_workspace_dir / _target_agent_exists
    # so we don't touch the real user config).
    workspaces = {"export": src, "order": dst}
    monkeypatch.setattr(
        svc, "_resolve_workspace_dir", lambda ws: workspaces[ws],
    )
    monkeypatch.setattr(
        svc, "_target_agent_exists", lambda ws: ws in workspaces,
    )

    svc.generate_skill(
        name="demo-migrate-me",
        target_workspace="export",
        brief={
            "description": "演示从一个 agent 迁到另一个",
            "tags": ["alarm", "fault", "network-management"],
            "triggers": ["告警"],
        },
    )
    svc.install_staged_skill("demo-migrate-me")
    assert (src / "skills" / "demo-migrate-me" / "SKILL.md").is_file()

    # Now copy + remove source = move.
    result = svc.copy_installed_skill(
        source_agent="export",
        skill_name="demo-migrate-me",
        target_workspace="order",
        remove_source=True,
        skip_domain_check=True,
    )
    assert result["copied"] is True
    assert result["target_workspace"] == "order"
    assert result["removed_source"] is True
    assert (dst / "skills" / "demo-migrate-me" / "SKILL.md").is_file()
    # source skill files cleaned up
    assert not (src / "skills" / "demo-migrate-me").exists()

    # Target manifest carries the 二开 tag
    import json as _json

    target_manifest = _json.loads((dst / "skill.json").read_text("utf-8"))
    entry = target_manifest["skills"]["demo-migrate-me"]
    assert entry["enabled"] is True
    assert entry["tags"] == ["二开"]


def test_copy_installed_skill_rejects_self_target(monkeypatch, tmp_path):
    src = tmp_path / "ws"
    src.mkdir()
    monkeypatch.setattr(svc, "_resolve_workspace_dir", lambda ws: src)
    with pytest.raises(svc.FdeWorkbenchError):
        svc.copy_installed_skill(
            source_agent="foo",
            skill_name="demo",
            target_workspace="foo",
        )


def test_list_installed_erkai_skills(monkeypatch, tmp_path):
    """Cross-agent scan returns one entry per (agent, 二开-tagged skill)."""
    # Build two fake workspaces with skill.json manifests.
    ws_a = tmp_path / "agent-a"
    (ws_a / "skills" / "alpha").mkdir(parents=True)
    (ws_a / "skill.json").write_text(
        '{"skills":{'
        '"alpha":{"enabled":true,"tags":["二开"],'
        '  "metadata":{"description":"FDE 生成的 alpha 技能",'
        '             "updated_at":"2026-05-13T10:00:00Z"}},'
        '"factory-skill":{"enabled":true,"tags":["出厂"],'
        '  "metadata":{"description":"原厂"}}'
        "}}",
        encoding="utf-8",
    )
    ws_b = tmp_path / "agent-b"
    (ws_b / "skills" / "beta").mkdir(parents=True)
    (ws_b / "skill.json").write_text(
        '{"skills":{'
        '"beta":{"enabled":false,"tags":["二开","preview"],'
        '  "metadata":{"description":"未启用的二开技能"}}}}',
        encoding="utf-8",
    )

    # Fake config with two profiles + fde (fde must be skipped).
    class _Ref:
        def __init__(self, workspace_dir):
            self.workspace_dir = workspace_dir
            self.enabled = True

    class _Agents:
        def __init__(self, profiles):
            self.profiles = profiles

    class _Cfg:
        def __init__(self):
            self.agents = _Agents(
                {
                    "agent-a": _Ref(str(ws_a)),
                    "agent-b": _Ref(str(ws_b)),
                    "fde": _Ref(str(tmp_path / "fde")),
                },
            )

    class _AgentCfg:
        def __init__(self, name):
            self.name = name

    import qwenpaw.config.config as config_mod
    import qwenpaw.config.utils as config_utils

    monkeypatch.setattr(config_utils, "load_config", lambda: _Cfg())
    monkeypatch.setattr(
        config_mod,
        "load_agent_config",
        lambda aid: _AgentCfg({"agent-a": "员工 A", "agent-b": "员工 B"}.get(aid, aid)),
    )

    result = svc.list_installed_erkai_skills()
    skills = result["skills"]
    assert result["count"] == 2
    names = {(s["agent_id"], s["skill_name"]) for s in skills}
    assert names == {("agent-a", "alpha"), ("agent-b", "beta")}
    alpha = next(s for s in skills if s["skill_name"] == "alpha")
    assert alpha["agent_name"] == "员工 A"
    assert alpha["enabled"] is True
    assert "FDE 生成" in alpha["description"]
    beta = next(s for s in skills if s["skill_name"] == "beta")
    assert beta["enabled"] is False
    # FDE workspace skipped even if it had a skill.json
    assert all(s["agent_id"] != "fde" for s in skills)
    # factory-skill (no 二开 tag) excluded
    assert not any(s["skill_name"] == "factory-skill" for s in skills)


def test_parse_env_example_extracts_keys_and_hints():
    text = (
        "# Skill foo credentials.\n"
        "# Get from the admin console.\n"
        "FOO_TOKEN=\n"
        "\n"
        "# Optional override\n"
        "FOO_BASE_URL=https://example.internal/api\n"
        "# stray comment block with no key follows\n"
        "\n"
        "INVALID_LINE_NO_EQUAL\n"
        "BAR=hello world\n"
    )
    fields = svc.parse_env_example(text)
    keys = [f["key"] for f in fields]
    assert keys == ["FOO_TOKEN", "FOO_BASE_URL", "BAR"]
    foo = next(f for f in fields if f["key"] == "FOO_TOKEN")
    assert "Skill foo credentials" in foo["hint"]
    assert "admin console" in foo["hint"]
    assert foo["default"] == ""
    base = next(f for f in fields if f["key"] == "FOO_BASE_URL")
    assert base["default"] == "https://example.internal/api"
    bar = next(f for f in fields if f["key"] == "BAR")
    # the trailing stray comments shouldn't leak into the next field's hint
    assert bar["hint"] == ""


def test_skill_env_read_write_roundtrip(monkeypatch, tmp_path):
    workspace = tmp_path / "ws"
    skill_dir = workspace / "skills" / "demo-env-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / ".env.example").write_text(
        "# token for foo\nFOO_TOKEN=\n# url\nFOO_URL=https://x/\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(svc, "_resolve_workspace_dir", lambda ws: workspace)

    state = svc.read_skill_env_state("biz", "demo-env-skill")
    assert state["has_example"] is True
    assert state["has_env"] is False
    assert state["values"] == {}
    assert [f["key"] for f in state["schema"]] == ["FOO_TOKEN", "FOO_URL"]

    result = svc.write_skill_env(
        target_workspace="biz",
        skill_name="demo-env-skill",
        values={"FOO_TOKEN": "secret-123", "FOO_URL": "https://real/api"},
    )
    assert result["keys"] == ["FOO_TOKEN", "FOO_URL"]
    env_path = skill_dir / ".env"
    assert env_path.is_file()
    assert "FOO_TOKEN=secret-123" in env_path.read_text("utf-8")
    # update one + clear another -> preserves untouched, drops cleared
    svc.write_skill_env(
        target_workspace="biz",
        skill_name="demo-env-skill",
        values={"FOO_TOKEN": "rotated", "FOO_URL": ""},
    )
    state2 = svc.read_skill_env_state("biz", "demo-env-skill")
    assert state2["values"] == {"FOO_TOKEN": "rotated"}


def test_skill_env_rejects_unknown_skill(monkeypatch, tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setattr(svc, "_resolve_workspace_dir", lambda ws: workspace)
    with pytest.raises(svc.FdeWorkbenchError):
        svc.read_skill_env_state("biz", "nope")


def test_install_skip_domain_check_prewarms_cache(
    fde_env, monkeypatch, tmp_path,
):
    """skip_domain_check pre-warms the domain_guard verdict cache."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setattr(svc, "_resolve_workspace_dir", lambda ws: workspace)
    monkeypatch.setattr(svc, "_target_agent_exists", lambda ws: True)

    captured: dict = {}

    def fake_prefill(skill_dir, **kwargs):
        captured["skill_dir"] = skill_dir
        captured["kwargs"] = kwargs
        return True

    monkeypatch.setattr(svc, "prefill_domain_allow_for_staged", fake_prefill)

    # Build a tiny staged skill with a manifest inside the fixture's staged dir
    staged = fde_env / "demo-skip"
    staged.mkdir()
    (staged / "SKILL.md").write_text(
        "---\nname: demo-skip\ndescription: 网管告警相关测试\n---\n",
        encoding="utf-8",
    )
    (staged / "_fde_meta.json").write_text(
        '{"schema":"fde-staged-skill.v1","skill_name":"demo-skip",'
        '"target_workspace":"biz"}',
        encoding="utf-8",
    )

    result = svc.install_staged_skill("demo-skip", skip_domain_check=True)
    assert result["installed"] is True
    assert result["domain_override_applied"] is True
    assert captured["skill_dir"] == staged


def test_install_writes_env_values(fde_env, monkeypatch, tmp_path):
    """env_values get written to the installed skill's .env."""
    workspace = tmp_path / "ws"
    (workspace / "skills").mkdir(parents=True)
    monkeypatch.setattr(svc, "_resolve_workspace_dir", lambda ws: workspace)
    monkeypatch.setattr(svc, "_target_agent_exists", lambda ws: True)

    svc.generate_skill(
        name="demo-env-install",
        target_workspace="biz",
        brief={
            "description": "演示安装时写 env",
            "tags": ["alarm", "fault", "network-management"],
            "triggers": ["告警"],
        },
    )
    result = svc.install_staged_skill(
        "demo-env-install",
        env_values={"FOO_TOKEN": "abc", "FOO_URL": "https://example/api"},
    )
    assert result["env_written"] == ["FOO_TOKEN", "FOO_URL"]
    env_path = workspace / "skills" / "demo-env-install" / ".env"
    assert env_path.is_file()
    text = env_path.read_text("utf-8")
    assert "FOO_TOKEN=abc" in text
    assert "FOO_URL=https://example/api" in text


def test_install_auto_creates_missing_target(fde_env, monkeypatch, tmp_path):
    """Install path auto-creates the target agent if it doesn't exist yet.

    This is the "one-click" UX: the human confirms install → backend
    creates the agent (when missing) AND installs the skill atomically,
    instead of forcing a separate manual create step.
    """
    workspace = tmp_path / "auto-ws"
    workspace.mkdir()

    # Pretend the target ("brand-new-agent") doesn't exist yet, then is
    # available after our stubbed create_business_agent "runs".
    state = {"exists": False, "created": None}

    def fake_exists(agent_id: str) -> bool:
        return state["exists"] and agent_id == "brand-new-agent"

    def fake_create_business_agent(**kwargs):
        state["created"] = kwargs
        state["exists"] = True
        return {
            "id": kwargs["agent_id"],
            "name": kwargs.get("name") or kwargs["agent_id"],
            "workspace_dir": str(workspace),
            "enabled": True,
        }

    def fake_resolve(agent_id: str):
        if not state["exists"]:
            raise svc.FdeWorkbenchError(
                f"目标业务智能体不存在：{agent_id}",
            )
        return workspace

    monkeypatch.setattr(svc, "_target_agent_exists", fake_exists)
    monkeypatch.setattr(svc, "create_business_agent", fake_create_business_agent)
    monkeypatch.setattr(svc, "_resolve_workspace_dir", fake_resolve)
    # _pick_default_active_model also reads real config — stub it too.
    monkeypatch.setattr(svc, "_pick_default_active_model", lambda: None)

    svc.generate_skill(
        name="demo-auto-create",
        target_workspace="brand-new-agent",
        brief={
            "description": "演示自动建 agent + 装 skill",
            "tags": ["alarm", "fault", "network-management"],
            "triggers": ["告警"],
        },
    )

    result = svc.install_staged_skill("demo-auto-create")
    assert result["installed"] is True
    assert result["target_workspace"] == "brand-new-agent"
    assert result["target_created"] is True
    assert state["created"]["agent_id"] == "brand-new-agent"
    assert state["created"]["name"] == "brand-new-agent"
    # default model wasn't set on the stub → passed through as None
    assert state["created"].get("active_model") is None


def test_generate_rejects_bad_name(fde_env):
    with pytest.raises(svc.FdeWorkbenchError):
        svc.generate_skill(name="Bad Name!", target_workspace="query")


def test_generate_requires_target_workspace(fde_env):
    with pytest.raises(svc.FdeWorkbenchError):
        svc.generate_skill(name="ok-name", target_workspace="")


def test_tree_insert_builds_nested_dict():
    tree: dict = {}
    svc._tree_insert(tree, ["runtime", "playbooks", "flow.py"], "x = 1")
    assert tree == {"runtime": {"playbooks": {"flow.py": "x = 1"}}}


def test_install_unknown_skill_errors(fde_env):
    with pytest.raises(svc.FdeWorkbenchError):
        svc.install_staged_skill("nope")


def test_discard_unknown_skill_errors(fde_env):
    with pytest.raises(svc.FdeWorkbenchError):
        svc.discard_staged_skill("nope")
