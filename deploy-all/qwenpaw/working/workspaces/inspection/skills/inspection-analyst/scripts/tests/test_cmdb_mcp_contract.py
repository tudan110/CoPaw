from pathlib import Path


WORKSPACES_ROOT = Path(__file__).resolve().parents[5]
GATEWAY_SKILL = WORKSPACES_ROOT / "gateway" / "skills" / "inspection-analyst"
INSPECTION_SKILL = WORKSPACES_ROOT / "inspection" / "skills" / "inspection-analyst"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_cmdb_mcp_first_contract_is_synced_across_workspaces():
    gateway = _read(GATEWAY_SKILL / "SKILL.md")
    inspection = _read(INSPECTION_SKILL / "SKILL.md")

    required = [
        "cmdb-query__listCiTypes",
        "cmdb-query__searchCiInstances",
        "cmdb-query__getCiInstance",
        "cmdb-query__getCiRelations",
        "zgops-cmdb-script-fallback",
    ]
    for token in required:
        assert token in gateway
        assert token in inspection

    assert gateway.index("cmdb-query__listCiTypes") < gateway.index(
        "cmdb-query__searchCiInstances"
    ) < gateway.index("cmdb-query__getCiInstance") < gateway.index(
        "cmdb-query__getCiRelations"
    )


def test_cmdb_mcp_contract_requires_real_selection_and_limited_fallback():
    content = _read(GATEWAY_SKILL / "SKILL.md")

    assert "多候选时列出候选让用户选择，禁止自动任选" in content
    assert "只将确认后的 `_id` 作为 `resId`" in content
    assert "模型 `name` 作为 `ciType` / `metricType`" in content
    assert "普通 MCP 成功路径不得调用该脚本" in content
    assert "可解析的业务 4xx/5xx、鉴权、参数或上游错误必须 fail-fast" in content


def test_cmdb_mcp_reference_is_identical_across_workspaces():
    gateway = _read(GATEWAY_SKILL / "references" / "api-config.md")
    inspection = _read(INSPECTION_SKILL / "references" / "api-config.md")

    assert gateway == inspection
    assert "cmdb-query__searchCiInstances" in gateway
    assert "`_type:<模型 name>`" in gateway
    assert "cmdb-query__getCiRelations(root_id=<确认的 _id>)" in gateway
