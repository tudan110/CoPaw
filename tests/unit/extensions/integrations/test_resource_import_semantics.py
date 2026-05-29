from __future__ import annotations

from qwenpaw.extensions.integrations.zgops_cmdb import resource_import


def test_match_field_with_metadata_uses_real_attribute_aliases() -> None:
    metadata = resource_import._enrich_resource_import_metadata(
        {
            "ciTypes": [
                {
                    "name": "CustomService",
                    "alias": "自定义服务",
                    "attributes": ["listen_port", "service_name"],
                    "attributeDefinitions": [
                        {
                            "name": "listen_port",
                            "alias": "监听端口",
                            "required": False,
                            "is_choice": False,
                            "is_list": False,
                            "default_show": True,
                            "value_type": "int",
                            "order": 0,
                            "choices": [],
                        },
                        {
                            "name": "service_name",
                            "alias": "服务名",
                            "required": False,
                            "is_choice": False,
                            "is_list": False,
                            "default_show": True,
                            "value_type": "text",
                            "order": 1,
                            "choices": [],
                        },
                    ],
                    "parentTypes": [],
                }
            ],
            "ciTypeGroups": [
                {
                    "name": "中间件",
                    "ciTypes": [{"name": "CustomService", "alias": "自定义服务"}],
                }
            ],
            "attributeLibrary": [],
        }
    )

    target_field, confidence = resource_import._match_field_with_metadata(
        "实例监听端口",
        metadata,
    )

    # The model exposes the concrete attribute ``listen_port`` (alias 监听端口),
    # which is now preferred as a direct target over the canonical
    # ``service_port`` bucket — and crucially it is the attribute that actually
    # exists on this CI type, so the value is written instead of dropped.
    assert target_field == "listen_port"
    assert confidence in {"medium", "high"}


def test_semantic_lexical_score_can_use_model_attribute_texts() -> None:
    candidate = {
        "name": "StreamHub",
        "alias": "流式平台",
        "groupNames": ["中间件"],
        "parentTypes": [],
        "attributeTexts": ["Broker地址", "Topic名称", "监听端口"],
    }

    score, reason = resource_import._semantic_lexical_score(
        candidate,
        ["消息接入", "broker 地址", "topic_name"],
    )

    assert score > 0
    assert reason


def test_middleware_name_is_name_like_not_code_like() -> None:
    assert resource_import._is_name_like_unique_key("middleware_name")
    assert not resource_import._is_code_like_unique_key("middleware_name")


def test_source_header_can_autofill_name_like_unique_key() -> None:
    source_attributes = {
        "组件实例名": "redis-01-testzg",
        "业务归属": "测试智观",
        "告警等级": "1",
    }

    candidates = resource_import._semantic_source_candidates(
        source_attributes,
        semantic_kind="name",
        unique_key="middleware_name",
        unique_key_label="实例名",
    )

    assert candidates
    assert candidates[0][1] == "组件实例名"
    assert candidates[0][2] == "redis-01-testzg"


def test_default_template_can_resolve_middleware_fields() -> None:
    redis_template = next(
        item for item in resource_import.DEFAULT_MODEL_TEMPLATES if item.get("name") == "redis"
    )
    redis_template = {
        **redis_template,
        "attributes": resource_import.DEFAULT_ATTRIBUTE_FIELDS["redis"],
    }

    assert resource_import._resolve_cmdb_attribute_name(redis_template, "name") == "middleware_name"
    assert resource_import._resolve_cmdb_attribute_name(redis_template, "private_ip") == "middleware_ip"
    assert resource_import._resolve_cmdb_attribute_name(redis_template, "service_port") == "middleware_port"


def test_ci_types_from_preview_snapshot_preserves_runtime_metadata() -> None:
    ci_types = resource_import._ci_types_from_preview_snapshot(
        {
            "ciTypeMetadata": {
                "redis": {
                    "id": 61,
                    "name": "redis",
                    "alias": "Redis",
                    "unique_key": "middleware_name",
                    "attributes": ["middleware_name", "middleware_ip", "middleware_port", "platform"],
                    "attributeDefinitions": [
                        {"name": "middleware_name", "alias": "实例名"},
                        {"name": "middleware_ip", "alias": "IP"},
                        {"name": "middleware_port", "alias": "端口"},
                    ],
                }
            }
        }
    )

    assert len(ci_types) == 1
    assert ci_types[0]["name"] == "redis"
    assert ci_types[0]["unique_key"] == "middleware_name"
    assert [item["name"] for item in ci_types[0]["attributeDefinitions"]] == [
        "middleware_name",
        "middleware_ip",
        "middleware_port",
    ]


def test_import_preflight_reports_required_fields_before_cmdb_login(monkeypatch) -> None:
    def fail_if_called(cls):  # noqa: ANN001
        raise AssertionError("CMDB client should not be opened when offline preflight fails")

    monkeypatch.setattr(resource_import.VeopsCmdbClient, "from_skill_env", classmethod(fail_if_called))

    result = resource_import.import_preview_to_cmdb(
        {
            "preview": {
                "metadataConnected": True,
                "ciTypeMetadata": {
                    "networkdevice": {
                        "name": "networkdevice",
                        "alias": "网络设备",
                        "unique_key": "dev_no",
                        "attributes": ["dev_no", "dev_name"],
                        "attributeDefinitions": [
                            {"name": "dev_no", "alias": "设备编码", "required": True},
                            {"name": "dev_name", "alias": "设备名称", "required": False},
                        ],
                    }
                },
            },
            "resourceGroups": [
                {
                    "ciType": "networkdevice",
                    "records": [
                        {
                            "previewKey": "row::bad.xlsx::Sheet1::1",
                            "ciType": "networkdevice",
                            "name": "device-a",
                            "selected": True,
                            "attributes": {"dev_name": "device-a"},
                            "analysisAttributes": {},
                            "sourceAttributes": {},
                        }
                    ],
                }
            ],
            "relations": [],
        }
    )

    assert result["status"] == "failed"
    assert result["failed"] == 1
    assert "设备编码" in result["resourceResults"][0]["message"]


def test_import_preflight_blocks_disconnected_metadata_before_cmdb_login(monkeypatch) -> None:
    def fail_if_called(cls):  # noqa: ANN001
        raise AssertionError("CMDB client should not be opened when metadata is disconnected")

    monkeypatch.setattr(resource_import.VeopsCmdbClient, "from_skill_env", classmethod(fail_if_called))

    result = resource_import.import_preview_to_cmdb(
        {
            "preview": {
                "metadataConnected": False,
                "metadataMessage": "CMDB 元数据不可用",
                "ciTypeMetadata": {},
            },
            "resourceGroups": [
                {
                    "ciType": "networkdevice",
                    "records": [
                        {
                            "previewKey": "row::bad.xlsx::Sheet1::1",
                            "ciType": "networkdevice",
                            "name": "device-a",
                            "selected": True,
                            "attributes": {"name": "device-a"},
                        }
                    ],
                }
            ],
            "relations": [],
        }
    )

    assert result["status"] == "failed"
    assert result["failed"] == 1
    assert "未连接实时 CMDB 模型" in result["resourceResults"][0]["message"]


def test_build_confirmed_cmdb_attributes_only_keeps_allowed_model_fields() -> None:
    type_template = {
        "name": "redis",
        "unique_key": "middleware_name",
        "attributes": ["middleware_name", "middleware_ip", "middleware_port", "platform"],
    }
    record = {
        "name": "redis-01-testzg",
        "attributes": {
            "middleware_name": "redis-01-testzg",
            "middleware_ip": "10.1.1.1",
            "middleware_port": "6379",
            "组件地址": "10.1.1.1",
            "业务归属": "测试智观",
        },
    }

    result = resource_import._build_confirmed_cmdb_attributes(
        record=record,
        type_template=type_template,
    )

    assert result == {
        "middleware_name": "redis-01-testzg",
        "middleware_ip": "10.1.1.1",
        "middleware_port": "6379",
    }


def test_model_aware_mapping_detail_collapses_generic_and_model_specific_candidates() -> None:
    redis_template = next(
        item for item in resource_import.DEFAULT_MODEL_TEMPLATES if item.get("name") == "redis"
    )
    redis_template = {
        **redis_template,
        "attributes": resource_import.DEFAULT_ATTRIBUTE_FIELDS["redis"],
    }

    detail = resource_import._build_sheet_mapping_detail(
        header="组件实例名",
        heuristic_mapping=("name", "high"),
        llm_mapping=("middleware_name", "high"),
        metadata=None,
        type_template=redis_template,
    )

    assert detail["needsConfirmation"] is False
    assert detail["targetField"] == "name"
    assert {
        item.get("effectiveTargetField")
        for item in detail["candidates"]
        if item.get("targetField") in {"name", "middleware_name"}
    } == {"middleware_name"}


def test_collect_confirmation_issues_accepts_model_specific_name_and_port_fields() -> None:
    redis_template = next(
        item for item in resource_import.DEFAULT_MODEL_TEMPLATES if item.get("name") == "redis"
    )
    redis_template = {
        **redis_template,
        "attributes": resource_import.DEFAULT_ATTRIBUTE_FIELDS["redis"],
    }

    issues = resource_import._collect_confirmation_issues(
        "redis",
        {
            "middleware_name": "redis-01-testzg",
            "middleware_port": "6379",
            "version": "7.0",
        },
        type_template=redis_template,
    )

    assert "名称" not in issues
    assert "端口" not in issues


def test_server_default_macro_is_not_filled_into_create_payload() -> None:
    docker_template = {
        "name": "docker",
        "unique_key": "p_id",
        "attributeDefinitions": [
            {
                "name": "p_id",
                "alias": "主键",
                "value_type": "0",
                "required": True,
                "is_required": True,
                "is_choice": False,
                "default": {"default": "$auto_inc_id"},
            },
            {
                "name": "alarm_status",
                "alias": "告警状态",
                "value_type": "2",
                "required": True,
                "is_choice": False,
                "default": {"default": "0"},
            },
        ],
    }

    assert resource_import._is_server_default_macro("$auto_inc_id")
    assert not resource_import._is_server_default_macro("0")
    assert (
        resource_import._extract_attribute_default_value(
            docker_template["attributeDefinitions"][0]
        )
        == ""
    )

    filled = resource_import._autofill_deterministic_cmdb_attributes(
        canonical_attributes={"name": "10.253.0.1", "asset_code": "500013"},
        type_template=docker_template,
        cmdb_attributes={"manage_ip": "10.253.0.1", "platform": "测试智观"},
    )

    # Auto-increment primary key must be omitted so the CMDB resolves it,
    # while a genuine literal default is still applied.
    assert "p_id" not in filled
    assert filled["alarm_status"] == "0"
    assert resource_import._validate_required_cmdb_attributes(
        type_template=docker_template,
        source_attributes={"name": "10.253.0.1"},
        cmdb_attributes=filled,
    ) == []


def test_required_status_with_model_default_does_not_block_import() -> None:
    network_template = {
        "name": "networkdevice",
        "unique_key": "dev_no",
        "attributeDefinitions": [
            {
                "name": "dev_no",
                "alias": "设备编码",
                "required": True,
                "is_choice": False,
            },
            {
                "name": "status",
                "alias": "资产状态",
                "required": True,
                "is_choice": True,
                "choices": _choices("在线", "下线"),
                "default": {"default": "在线"},
            },
        ],
    }

    filled = resource_import._autofill_deterministic_cmdb_attributes(
        canonical_attributes={"dev_no": "TESTZG-BJ-BJ-WLKJC-A-1.MCN.MX.ATN980C"},
        type_template=network_template,
        cmdb_attributes={"dev_no": "TESTZG-BJ-BJ-WLKJC-A-1.MCN.MX.ATN980C"},
    )

    assert filled["status"] == "在线"
    assert resource_import._validate_required_cmdb_attributes(
        type_template=network_template,
        source_attributes={"dev_no": "TESTZG-BJ-BJ-WLKJC-A-1.MCN.MX.ATN980C"},
        cmdb_attributes=filled,
    ) == []


def _choices(*values: str) -> list:
    return [{"value": v, "label": v} for v in values]


def _project_template_with_choices() -> dict:
    return {
        "name": "project",
        "alias": "应用",
        "unique_key": "project_name",
        "attributeDefinitions": [
            {
                "name": "project_name",
                "alias": "应用名称",
                "is_choice": False,
                "choices": [],
            },
            {
                "name": "project_type",
                "alias": "应用类型",
                "is_choice": True,
                "choices": _choices(
                    "IQ", "web", "service", "job", "mq", "api"
                ),
            },
            {
                "name": "project_status",
                "alias": "应用状态",
                "is_choice": True,
                "choices": _choices("normal", "abnormal", "stop"),
            },
            {
                "name": "Level",
                "alias": "等级",
                "is_choice": True,
                "choices": _choices("核心", "重要", "普通"),
            },
        ],
    }


def test_value_choice_candidates_map_by_values_not_header() -> None:
    tmpl = _project_template_with_choices()
    collect = resource_import._collect_value_choice_candidates

    def target(values):
        return [c["targetField"] for c in collect(values, tmpl)]

    # Header text is irrelevant; the values alone identify the attribute.
    assert target(["web"]) == ["project_type"]
    assert target(["normal"]) == ["project_status"]
    assert target(["重要"]) == ["Level"]
    # A value matching no choice attribute yields nothing.
    assert target(["10.253.0.1"]) == []


def test_value_choice_candidate_marks_ambiguous_match() -> None:
    tmpl = {
        "name": "x",
        "attributeDefinitions": [
            {"name": "attr_a", "alias": "甲", "is_choice": True,
             "choices": _choices("shared", "a")},
            {"name": "attr_b", "alias": "乙", "is_choice": True,
             "choices": _choices("shared", "b")},
        ],
    }
    cands = resource_import._collect_value_choice_candidates(["shared"], tmpl)
    assert {c["targetField"] for c in cands} == {"attr_a", "attr_b"}
    assert all(c["confidence"] == "medium" and c["ambiguous"] for c in cands)


def test_metadata_catalog_exposes_model_attribute_as_direct_target() -> None:
    metadata = resource_import._enrich_resource_import_metadata(
        {
            "ciTypes": [
                {
                    "name": "project",
                    "alias": "应用",
                    "attributes": ["project_name", "project_type"],
                    "attributeDefinitions": [
                        {
                            "name": "project_name",
                            "alias": "应用名称",
                            "required": True,
                            "is_choice": False,
                            "is_list": False,
                            "value_type": "text",
                            "choices": [],
                        },
                        {
                            "name": "project_type",
                            "alias": "应用类型",
                            "required": False,
                            "is_choice": True,
                            "is_list": False,
                            "value_type": "text",
                            "choices": _choices("web"),
                        },
                    ],
                    "parentTypes": [],
                }
            ],
            "ciTypeGroups": [
                {"name": "应用", "ciTypes": [{"name": "project", "alias": "应用"}]}
            ],
            "attributeLibrary": [],
        }
    )
    catalog = metadata["semanticFieldCatalog"]
    # The model attribute is directly targetable, not collapsed into a
    # canonical bucket.
    assert "project_type" in catalog
    assert "应用类型" in catalog["project_type"]["attributeAliases"]
    # And a header equal to the attribute alias resolves straight to it.
    target_field, _ = resource_import._match_field_with_metadata(
        "应用类型", metadata
    )
    assert target_field == "project_type"


def test_sheet_mapping_detail_applies_strong_value_mapping() -> None:
    detail = resource_import._build_sheet_mapping_detail(
        header="系统分类",
        heuristic_mapping=("unknown", "low"),
        llm_mapping=("unknown", "low"),
        type_template=_project_template_with_choices(),
        value_mapping=("project_type", "high"),
    )
    assert detail["status"] == "mapped"
    assert detail["targetField"] == "project_type"


def test_direct_attribute_wins_over_canonical_bucket_shadow() -> None:
    # ``数据库类别`` matches both the concrete db_type attribute (alias
    # 数据库类型, direct) and the generic ci_type canonical bucket (which the
    # alias leaks into). The direct attribute must win cleanly instead of the
    # pair triggering a needs_confirmation that drops the value.
    metadata = resource_import._enrich_resource_import_metadata(
        {
            "ciTypes": [
                {
                    "name": "database",
                    "alias": "数据库",
                    "attributes": ["db_instance", "db_type"],
                    "attributeDefinitions": [
                        {
                            "name": "db_instance",
                            "alias": "数据库实例名",
                            "required": True,
                            "is_choice": False,
                            "is_list": False,
                            "value_type": "text",
                            "choices": [],
                        },
                        {
                            "name": "db_type",
                            "alias": "数据库类型",
                            "required": False,
                            "is_choice": False,
                            "is_list": False,
                            "value_type": "text",
                            "choices": [],
                        },
                    ],
                    "parentTypes": [],
                }
            ],
            "ciTypeGroups": [
                {
                    "name": "数据库",
                    "ciTypes": [{"name": "database", "alias": "数据库"}],
                }
            ],
            "attributeLibrary": [],
        }
    )
    db_template = metadata["ciTypes"][0]
    detail = resource_import._build_sheet_mapping_detail(
        header="数据库类别",
        heuristic_mapping=resource_import._match_field_with_metadata(
            "数据库类别", metadata
        ),
        llm_mapping=("unknown", "low"),
        metadata=metadata,
        type_template=db_template,
    )
    assert detail["status"] == "mapped"
    assert detail["targetField"] == "db_type"

    # Even when the LLM agrees on the same direct target, the metadata
    # candidate's direct flag must survive the merge so the canonical shadow
    # cannot re-trigger needs_confirmation and drop the value.
    detail_llm_agrees = resource_import._build_sheet_mapping_detail(
        header="数据库类别",
        heuristic_mapping=resource_import._match_field_with_metadata(
            "数据库类别", metadata
        ),
        llm_mapping=("db_type", "high"),
        metadata=metadata,
        type_template=db_template,
    )
    assert detail_llm_agrees["status"] == "mapped"
    assert detail_llm_agrees["targetField"] == "db_type"


def test_sheet_mapping_detail_surfaces_unmapped_column() -> None:
    detail = resource_import._build_sheet_mapping_detail(
        header="某个无法识别的列",
        heuristic_mapping=("unknown", "low"),
        llm_mapping=("unknown", "low"),
        type_template=_project_template_with_choices(),
    )
    assert detail["status"] == "unmapped"
    assert detail["message"]
