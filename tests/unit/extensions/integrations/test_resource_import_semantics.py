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

    assert target_field == "service_port"
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
