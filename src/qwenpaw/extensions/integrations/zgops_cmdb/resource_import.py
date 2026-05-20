from __future__ import annotations

import asyncio
import csv
import html
import io
import json
import logging
import os
import re
import threading
import time
import zipfile
import base64
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from ipaddress import ip_address, ip_network
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

import httpx
import pandas as pd
from dotenv import dotenv_values

LOGGER = logging.getLogger(__name__)

DEFAULT_SUPPORTED_FORMATS = [
    ".csv",
    ".tsv",
    ".xlsx",
    ".xls",
    ".json",
    ".txt",
    ".md",
    ".docx",
    ".png",
    ".jpg",
    ".jpeg",
]

DEFAULT_RELATION_TYPES = ["contain", "deploy", "install", "connect"]

OS_LIKE_PLATFORM_TOKENS = {
    "linux",
    "windows",
    "unix",
    "ubuntu",
    "debian",
    "centos",
    "redhat",
    "rhel",
    "suse",
    "aix",
    "macos",
    "osx",
}

DEFAULT_MODEL_TEMPLATES = [
    {"name": "Department", "alias": "部门", "unique_key": "name"},
    {"name": "product", "alias": "产品", "unique_key": "name"},
    {"name": "project", "alias": "应用", "unique_key": "name"},
    {"name": "PhysicalMachine", "alias": "物理机", "unique_key": "name"},
    {"name": "vserver", "alias": "虚拟机", "unique_key": "name"},
    {"name": "networkdevice", "alias": "网络设备", "unique_key": "name"},
    {"name": "database", "alias": "数据库", "unique_key": "db_instance"},
    {"name": "mysql", "alias": "mySQL", "unique_key": "db_instance"},
    {"name": "PostgreSQL", "alias": "PostgreSQL", "unique_key": "db_instance"},
    {"name": "redis", "alias": "Redis", "unique_key": "middleware_name"},
    {"name": "Kafka", "alias": "Kafka", "unique_key": "middleware_name"},
    {"name": "elasticsearch", "alias": "elasticsearch", "unique_key": "middleware_name"},
    {"name": "nginx", "alias": "Nginx", "unique_key": "middleware_name"},
    {"name": "apache", "alias": "Apache", "unique_key": "middleware_name"},
    {"name": "docker", "alias": "docker", "unique_key": "name"},
    {"name": "kubernetes", "alias": "kubernetes", "unique_key": "name"},
    {"name": "dcim_idc", "alias": "数据中心", "unique_key": "name"},
    {"name": "dcim_server_room", "alias": "机房", "unique_key": "name"},
    {"name": "dcim_rack", "alias": "机柜", "unique_key": "name"},
    {"name": "ipam_subnet", "alias": "子网", "unique_key": "name"},
    {"name": "ipam_address", "alias": "IP地址", "unique_key": "name"},
]

DEFAULT_ATTRIBUTE_FIELDS = {
    "Department": ["name"],
    "product": ["name"],
    "project": ["name"],
    "PhysicalMachine": ["name", "asset_code", "private_ip", "status", "vendor", "model", "os_version"],
    "vserver": ["name", "asset_code", "private_ip", "status", "os_version"],
    "networkdevice": ["name", "asset_code", "private_ip", "status", "vendor", "model", "upstream_resource"],
    "database": ["db_instance", "db_ip", "db_port", "db_version", "alarm_status", "platform"],
    "mysql": ["db_instance", "manage_ip", "db_port", "db_version", "AssociatedPhyMachine", "alarm_status", "platform"],
    "PostgreSQL": ["db_instance", "manage_ip", "db_port", "db_version", "deploy_target", "alarm_status", "platform"],
    "redis": ["middleware_name", "middleware_ip", "middleware_port", "alarm_status", "platform"],
    "Kafka": ["middleware_name", "middleware_ip", "middleware_port", "alarm_status", "platform"],
    "elasticsearch": ["middleware_name", "middleware_ip", "middleware_port", "alarm_status", "platform"],
    "nginx": ["middleware_name", "middleware_ip", "middleware_port", "alarm_status", "platform"],
    "apache": ["middleware_name", "middleware_ip", "middleware_port", "alarm_status", "platform"],
    "docker": ["name", "private_ip", "status", "version", "deploy_target"],
    "kubernetes": ["name", "private_ip", "status", "version", "deploy_target"],
    "dcim_idc": ["name"],
    "dcim_server_room": ["name"],
    "dcim_rack": ["name"],
    "ipam_subnet": ["name"],
    "ipam_address": ["name"],
}

DEFAULT_GROUP_HINTS = {
    "Department": "部门组织",
    "users": "部门组织",
    "product": "业务",
    "project": "业务",
    "PhysicalMachine": "计算资源",
    "vserver": "计算资源",
    "networkdevice": "网络设备",
    "database": "数据库",
    "mysql": "数据库",
    "PostgreSQL": "数据库",
    "redis": "中间件",
    "Kafka": "中间件",
    "elasticsearch": "中间件",
    "nginx": "中间件",
    "apache": "中间件",
    "docker": "容器",
    "kubernetes": "容器",
    "dcim_idc": "数据中心",
    "dcim_server_room": "数据中心",
    "dcim_rack": "数据中心",
    "ipam_subnet": "IP地址管理",
    "ipam_address": "IP地址管理",
}

FIELD_ALIASES = {
    "asset_code": [
        "asset_code",
        "资产编号",
        "资源编号",
        "设备编号",
        "设备编码",
        "实例编号",
        "资源主键",
        "主键",
        "唯一标识",
        "唯一键",
        "sn编号",
        "p_id",
        "pid",
    ],
    "name": [
        "name",
        "名称",
        "应用名称",
        "业务应用名称",
        "设备名称",
        "资源名称",
        "实例名",
        "实例名称",
        "主机名",
        "主机名称",
        "主机标识",
        "网络节点名",
        "组件实例",
        "project_name",
        "product_name",
        "db_instance",
        "middleware_name",
        "vserver_name",
        "hostname",
        "host name",
        "server name",
    ],
    "ci_type": ["ci_type", "type", "资源类型", "资源分类", "设备类型", "实例类型", "设备大类", "组件类别", "模型", "类型", "_type"],
    "private_ip": [
        "private_ip",
        "ip",
        "ip地址",
        "内网地址",
        "组件地址",
        "数据库地址",
        "实例地址",
        "内网ip",
        "ip address",
        "address",
        "db_ip",
        "middleware_ip",
    ],
    "public_ip": ["public_ip", "公网ip", "外网ip"],
    "status": ["status", "状态", "运行状态", "设备状态", "上线情况", "当前可用性", "状态描述"],
    "department": ["department", "部门", "bu", "业务单元"],
    "product": ["product", "产品", "产品线"],
    "project": ["project", "应用", "项目", "系统", "业务系统", "业务归属", "所属应用"],
    "idc": ["idc", "机房", "数据中心", "idc机房"],
    "server_room": ["server_room", "机房分区", "机房区域", "server room"],
    "rack": ["rack", "机柜", "机柜位置"],
    "subnet": ["subnet", "网段", "子网", "cidr"],
    "host_name": ["host_name", "宿主机", "部署主机", "主机", "所属主机", "宿主机/集群", "承载物理机"],
    "deploy_target": [
        "deploy_target",
        "部署目标",
        "运行节点",
        "部署节点",
        "部署虚机",
        "宿主机地址",
        "承载物理机",
        "AssociatedVM",
        "AssociatedPhyMachine",
    ],
    "upstream_resource": ["upstream_resource", "上联核心", "上级设备", "上联设备"],
    "os_version": ["os_version", "操作系统", "操作系统版本", "os", "系统版本"],
    "vendor": ["vendor", "厂商", "品牌", "厂商品牌"],
    "model": ["model", "型号", "机型", "规格型号", "服务器型号", "设备型号"],
    "version": ["version", "版本", "版本号", "数据库版本", "设备软件版本"],
    "service_port": ["service_port", "端口", "服务端口", "db_port", "middleware_port"],
    "monitor_status": ["monitor_status", "监控接入", "监控状态"],
    "owner": ["owner", "负责人", "维护团队", "owner", "运维负责人"],
    "environment": ["environment", "环境", "env", "运行环境"],
    "description": ["description", "描述", "备注", "说明"],
    "dev_no": ["dev_no", "设备编码", "设备编号", "网络设备编码", "网络设备编号"],
    "dev_name": ["dev_name", "设备名称", "网络设备名称", "节点名称"],
    "manage_ip": ["manage_ip", "管理ip", "管理地址", "管理ip地址", "设备管理ip"],
    "dev_model": ["dev_model", "设备型号", "设备规格", "网络设备型号"],
    "dev_class": ["dev_class", "设备大类", "网络设备类型", "设备分类"],
    "alarm_status": [
        "alarm_status",
        "告警状态",
        "告警等级",
        "高级状态元数据",
        "状态编码",
    ],
    "dev_software_version": ["dev_software_version", "设备软件版本", "软件版本", "软件版本号"],
    "dev_sn": ["dev_sn", "设备序列号", "序列号", "序列号sn", "设备sn"],
    "property_no": ["property_no"],
    "city": ["city", "地市", "城市"],
    "county": ["county", "区县", "区"],
    "data_center": ["data_center", "所属数据中心"],
    "platform": ["platform", "平台", "采集平台", "纳管平台"],
    "op_duty": ["op_duty", "运维负责人", "运维组", "责任人", "维护人"],
    "u_count": ["u_count", "u数", "设备u数"],
    "u_start": ["u_start", "起始u位", "起始u", "开始u位"],
    "cabinet": ["cabinet", "所属机柜", "机柜柜位"],
    "cpu_architecture": [
        "cpu_architecture",
        "cpu架构",
        "处理器架构",
        "架构",
    ],
    "mem_total": ["mem_total", "内存容量", "内存总量", "总内存"],
    "mem_free": ["mem_free", "可用内存", "空闲内存"],
    "mem_used": ["mem_used", "已用内存", "已使用内存"],
    "disk_total": [
        "disk_total",
        "磁盘总量",
        "磁盘容量",
        "总磁盘",
    ],
    "disk_free": [
        "disk_free",
        "可用磁盘",
        "剩余磁盘",
        "空闲磁盘",
    ],
    "disk_used": ["disk_used", "已用磁盘", "已使用磁盘"],
    "login_user": [
        "login_user",
        "登录用户",
        "登录账号",
        "登录账户",
        "用户账号",
    ],
    "login_pwd": [
        "login_pwd",
        "登录口令",
        "登录密码",
        "访问口令",
        "访问密码",
        "口令",
    ],
    "db_memory": ["db_memory", "内存配置", "数据库内存"],
    "db_connect": [
        "db_connect",
        "连接串",
        "连接字符串",
        "数据库连接",
    ],
}

RELATION_FIELD_ALIASES = {
    "source_model": [
        "source_model",
        "源模型",
        "源资源模型",
        "源类型",
        "源资源类型",
        "父模型",
        "上游模型",
        "上游资源模型",
        "上游类型",
        "上游资源类型",
        "from_model",
        "upstream_model",
    ],
    "source_field": [
        "source_field",
        "source_unique_field",
        "源字段",
        "源属性",
        "源唯一字段",
        "源标识字段",
        "父字段",
        "上游字段",
        "上游匹配字段",
        "上游标识字段",
        "from_field",
        "upstream_field",
    ],
    "source_value": [
        "source_value",
        "source_unique_value",
        "源值",
        "源资源",
        "源资源标识",
        "源实例",
        "源名称",
        "源资源名称",
        "父资源",
        "上游资源",
        "上游匹配值",
        "上游值",
        "上游资源名称",
        "from",
        "source",
        "upstream_value",
    ],
    "target_model": [
        "target_model",
        "目标模型",
        "目标资源模型",
        "目标类型",
        "目标资源类型",
        "子模型",
        "下游模型",
        "下游资源模型",
        "下游类型",
        "下游资源类型",
        "to_model",
        "downstream_model",
    ],
    "target_field": [
        "target_field",
        "target_unique_field",
        "目标字段",
        "目标属性",
        "目标唯一字段",
        "目标标识字段",
        "子字段",
        "下游字段",
        "下游匹配字段",
        "下游标识字段",
        "to_field",
        "downstream_field",
    ],
    "target_value": [
        "target_value",
        "target_unique_value",
        "目标值",
        "目标资源",
        "目标资源标识",
        "目标实例",
        "目标名称",
        "目标资源名称",
        "子资源",
        "下游资源",
        "下游匹配值",
        "下游值",
        "下游资源名称",
        "to",
        "target",
        "downstream_value",
    ],
    "relation_type": ["relation_type", "关系", "关系类型", "关联类型", "连接类型", "link_type", "relation"],
}

RELATION_TYPE_ALIASES = {
    "contain": ["contain", "包含", "归属", "属于", "所属", "拥有", "纳管"],
    "deploy": ["deploy", "部署", "运行于", "部署于", "宿主", "挂载"],
    "install": ["install", "安装", "安装于", "实例化"],
    "connect": ["connect", "连接", "关联", "依赖", "上联", "下联", "通信"],
}

CI_TYPE_ALIASES = {
    "Department": ["department", "部门", "bu", "业务单元"],
    "product": ["product", "产品", "产品线"],
    "project": ["project", "应用", "项目", "业务系统", "应用系统", "系统应用", "业务应用", "application", "app", "system"],
    "PhysicalMachine": ["physicalmachine", "物理机", "服务器", "server", "裸机"],
    "vserver": ["vserver", "虚拟机", "vm", "虚机", "云主机", "云服务器", "ecs"],
    "networkdevice": ["networkdevice", "交换机", "路由器", "防火墙", "网络设备", "switch", "router", "firewall"],
    "database": ["database", "数据库", "数据库服务", "通用数据库", "通用数据库资源", "时序数据库", "victoriametrics"],
    "mysql": ["mysql", "my sql", "mysql实例", "mysql资源"],
    "PostgreSQL": ["postgresql", "postgres", "pgsql", "pg", "pg实例", "pg资源", "postgresql实例"],
    "redis": ["redis", "缓存", "缓存服务", "缓存组件", "redis服务"],
    "Kafka": ["kafka", "消息队列", "消息队列组件", "mq", "broker"],
    "elasticsearch": ["elasticsearch", "es", "搜索引擎", "搜索组件", "检索引擎"],
    "nginx": ["nginx"],
    "apache": ["apache"],
    "docker": ["docker", "容器", "容器实例", "容器实例清单", "container", "containerinstance"],
    "kubernetes": ["kubernetes", "k8s"],
    "dcim_idc": ["dcim_idc", "数据中心", "idc", "机房"],
    "dcim_server_room": ["dcim_server_room", "机房分区", "机房区域"],
    "dcim_rack": ["dcim_rack", "机柜", "rack"],
    "ipam_subnet": ["ipam_subnet", "子网", "网段", "cidr"],
    "ipam_address": ["ipam_address", "ip地址", "ip"],
}

STATUS_ALIASES = {
    "运行中": "在线",
    "正常": "在线",
    "在线": "在线",
    "active": "在线",
    "up": "在线",
    "已在cmdb": "已纳管",
    "已关联采集": "已纳管",
    "已接入": "已纳管",
    "y": "已纳管",
    "是": "已纳管",
    "已纳管": "已纳管",
    "已纳观": "已纳管",
    "未监控": "未监控",
    "pending": "未监控",
    "未接管": "未监控",
    "待纳管": "未监控",
    "n": "未监控",
    "否": "未监控",
    "offline": "离线",
    "关机": "离线",
    "停机": "离线",
    "离线": "离线",
    "down": "离线",
}

RESOURCE_DEPLOY_TYPES = {"PhysicalMachine", "vserver", "docker", "kubernetes"}
RESOURCE_CONTAIN_TYPES = {
    "networkdevice",
    "database",
    "mysql",
    "PostgreSQL",
    "redis",
    "Kafka",
    "elasticsearch",
    "nginx",
    "apache",
}
SOFTWARE_RESOURCE_TYPES = {
    "database",
    "mysql",
    "PostgreSQL",
    "redis",
    "Kafka",
    "elasticsearch",
    "nginx",
    "apache",
    "docker",
    "kubernetes",
}

SEMANTIC_MODEL_RULES = [
    {
        "name": "PhysicalMachine",
        "keywords": ["physical", "baremetal", "物理机", "裸机", "实体机", "服务器", "宿主机"],
        "field_keywords": ["rack", "cabinet", "u_count", "u_start", "vendor", "model", "property_no"],
        "preferred_models": ["PhysicalMachine"],
        "specific": False,
    },
    {
        "name": "vserver",
        "keywords": ["virtual", "vm", "vserver", "虚拟机", "虚机", "云主机", "云服务器", "ecs"],
        "field_keywords": ["host_ip", "host_name", "ssh_port"],
        "preferred_models": ["vserver"],
        "specific": False,
    },
    {
        "name": "networkdevice",
        "keywords": [
            "network",
            "switch",
            "router",
            "firewall",
            "loadbalance",
            "网络设备",
            "交换机",
            "路由器",
            "防火墙",
            "负载均衡",
        ],
        "field_keywords": [
            "dev_no",
            "dev_name",
            "dev_model",
            "dev_class",
            "dev_sn",
            "manage_ip",
            "proto_snmp",
            "snmp_port",
        ],
        "preferred_models": ["networkdevice"],
        "specific": False,
    },
    {
        "name": "database",
        "keywords": [
            "database",
            "数据库",
            "db实例",
            "dbinstance",
            "datasource",
            "sql",
            "时序",
            "timeseries",
            "metrics",
            "victoria",
            "victoriametrics",
            "tsdb",
        ],
        "field_keywords": ["db_instance", "db_port", "db_ip", "db_name", "db_type"],
        "preferred_models": ["database"],
        "specific": False,
    },
    {
        "name": "mysql",
        "keywords": ["mysql", "mariadb"],
        "port_values": ["3306"],
        "preferred_models": ["mysql"],
        "specific": True,
    },
    {
        "name": "PostgreSQL",
        "keywords": ["postgres", "postgresql", "pgsql", "pg实例", "pg数据库", "postgres实例", "postgres库", "pg"],
        "port_values": ["5432"],
        "preferred_models": ["PostgreSQL"],
        "specific": True,
    },
    {
        "name": "redis",
        "keywords": ["redis", "cache", "缓存", "缓存服务", "keyvalue", "key-value", "kv"],
        "field_keywords": ["middleware_name", "middleware_port", "cache_port", "redis_port"],
        "port_values": ["6379"],
        "preferred_models": ["redis"],
        "specific": True,
    },
    {
        "name": "Kafka",
        "keywords": ["kafka", "mq", "messagequeue", "消息", "消息队列", "topic", "stream", "broker"],
        "field_keywords": ["middleware_name", "middleware_port", "topic", "broker"],
        "port_values": ["9092"],
        "preferred_models": ["Kafka"],
        "specific": True,
    },
    {
        "name": "elasticsearch",
        "keywords": ["elasticsearch", "opensearch", "solr", "search", "搜索", "检索", "搜索引擎", "索引"],
        "field_keywords": ["middleware_name", "middleware_port", "index", "search_cluster"],
        "port_values": ["9200", "9300"],
        "preferred_models": ["elasticsearch"],
        "specific": True,
    },
    {
        "name": "nginx",
        "keywords": ["nginx", "gateway", "proxy", "ingress", "网关", "反向代理"],
        "field_keywords": ["middleware_name", "middleware_port", "upstream_resource"],
        "port_values": ["80", "443"],
        "preferred_models": ["nginx"],
        "specific": True,
    },
    {
        "name": "apache",
        "keywords": ["apache", "httpd", "webserver", "web服务", "http服务"],
        "field_keywords": ["middleware_name", "middleware_port"],
        "port_values": ["80", "443"],
        "preferred_models": ["apache"],
        "specific": True,
    },
    {
        "name": "docker",
        "keywords": ["docker", "container", "容器", "容器实例", "containerinstance", "镜像", "image"],
        "field_keywords": ["container_id", "image", "container_name", "container_image"],
        "preferred_models": ["docker"],
        "specific": True,
    },
    {
        "name": "kubernetes",
        "keywords": ["kubernetes", "k8s", "cluster", "namespace", "pod", "集群", "容器平台"],
        "field_keywords": ["namespace", "pod", "cluster", "node", "service_name"],
        "preferred_models": ["kubernetes"],
        "specific": True,
    },
]

SEMANTIC_REFINEMENT_MODELS = {
    "unknown",
    "database",
    "networkdevice",
    "PhysicalMachine",
    "vserver",
}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
PRIMARY_RESOURCE_FIELDS = {
    "asset_code",
    "name",
    "private_ip",
    "ci_type",
    "deploy_target",
    "host_name",
    "upstream_resource",
}
RESOURCE_VALUE_FIELDS = PRIMARY_RESOURCE_FIELDS | {
    "status",
    "vendor",
    "model",
    "version",
    "service_port",
    "monitor_status",
    "project",
    "department",
    "environment",
    "description",
}
EXCLUDED_SHEET_KEYWORDS = ("测试", "说明", "readme", "示例", "样例")
RELATION_SHEET_KEYWORDS = ("relation", "relations", "关系", "拓扑", "链路", "依赖", "mapping")
RESOURCE_IMPORT_LLM_STEP_TIMEOUT_SECONDS = float(
    os.environ.get("RESOURCE_IMPORT_LLM_STEP_TIMEOUT", "45"),
)
RESOURCE_IMPORT_LLM_STEP_TIMEOUT_MAX_SECONDS = float(
    os.environ.get("RESOURCE_IMPORT_LLM_STEP_TIMEOUT_MAX", "120"),
)
RESOURCE_IMPORT_LLM_RETRY_COUNT = max(
    1,
    int(os.environ.get("RESOURCE_IMPORT_LLM_RETRY_COUNT", "4")),
)
RESOURCE_IMPORT_LLM_RETRY_BACKOFF_SECONDS = max(
    0.0,
    float(os.environ.get("RESOURCE_IMPORT_LLM_RETRY_BACKOFF_SECONDS", "1.5")),
)
RESOURCE_IMPORT_LLM_SHEET_PARALLELISM = max(
    1,
    # Per-sheet LLM round-trips dominate preview latency. Bumping default
    # from 2 to 4 roughly halves wall time for ~9-sheet imports (the
    # observed common case) while staying well under typical per-account
    # concurrent-request limits. Tune via env if you hit provider rate
    # limits or want more parallelism for big imports.
    int(os.environ.get("RESOURCE_IMPORT_LLM_SHEET_PARALLELISM", "4")),
)
RESOURCE_IMPORT_LLM_BLOCKING_RECOVERY_RETRY_COUNT = max(
    1,
    int(os.environ.get("RESOURCE_IMPORT_LLM_BLOCKING_RECOVERY_RETRY_COUNT", "3")),
)
RESOURCE_IMPORT_PRECHECK_LIMIT = int(
    os.environ.get("RESOURCE_IMPORT_PRECHECK_LIMIT", "12"),
)

ProgressCallback = Callable[[dict[str, Any]], None]


@dataclass
class ParsedFile:
    filename: str
    extension: str
    rows: list[dict[str, Any]]
    warnings: list[str]
    logs: list[str]


@dataclass
class SheetMappingPlan:
    sheet_kind: str
    default_ci_type: str
    mappings: dict[str, tuple[str, str]]
    reason: str = ""
    mapping_details: dict[str, dict[str, Any]] | None = None


@dataclass
class ResourceImportRuntime:
    client: Any | None
    source: str


@dataclass
class SemanticModelPlan:
    best_model: str
    confidence: str
    reason: str = ""
    candidates: list[dict[str, Any]] | None = None
    source: str = "heuristic"


def _emit_progress(
    progress_callback: ProgressCallback | None,
    *,
    stage: str,
    message: str,
    percent: int | None = None,
) -> None:
    if not progress_callback:
        return
    payload: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "message": message,
    }
    if percent is not None:
        payload["percent"] = max(0, min(100, int(percent)))
    progress_callback(payload)


def _should_retry_llm_mapping(exc: Exception) -> bool:
    text = _clean_text(exc).lower()
    if not text:
        return False
    return any(
        token in text
        for token in (
            "too_many_requests",
            "rate limit",
            "429",
            "503",
            "504",
            "connection",
            "connect",
            "temporarily unavailable",
            "service unavailable",
            "network",
            "reset by peer",
            "gateway timeout",
            "timeout",
            "timed out",
        )
    )


def _llm_retry_sleep_seconds(attempt_index: int) -> float:
    if attempt_index <= 0:
        return 0.0
    base_delay = RESOURCE_IMPORT_LLM_RETRY_BACKOFF_SECONDS
    return min(base_delay * (2 ** (attempt_index - 1)), 12.0)


def _llm_retry_sleep_seconds_for_error(exc: Exception | None, attempt_index: int) -> float:
    if attempt_index <= 0:
        return 0.0
    text = _clean_text(exc).lower()
    if any(token in text for token in ("too_many_requests", "rate limit", "429", "700010", "并发已达上限")):
        base_delay = max(RESOURCE_IMPORT_LLM_RETRY_BACKOFF_SECONDS, 3.0)
        return min(base_delay * (2 ** (attempt_index - 1)), 24.0)
    if any(token in text for token in ("timeout", "timed out", "gateway timeout", "504")):
        base_delay = max(RESOURCE_IMPORT_LLM_RETRY_BACKOFF_SECONDS, 2.0)
        return min(base_delay * (2 ** (attempt_index - 1)), 18.0)
    return _llm_retry_sleep_seconds(attempt_index)


def _build_analysis_issue(
    *,
    kind: str,
    severity: str,
    message: str,
    file_name: str = "",
    sheet_name: str = "",
) -> dict[str, str]:
    return {
        "kind": kind,
        "severity": severity,
        "message": message,
        "fileName": file_name,
        "sheetName": sheet_name,
    }


def _mapping_mode_to_analysis_issue(
    *,
    file_name: str,
    sheet_name: str,
    mapping_mode: str,
    sheet_kind: str,
) -> dict[str, str] | None:
    if sheet_kind != "asset":
        return None
    normalized_mode = _clean_text(mapping_mode)
    if normalized_mode.startswith("规则映射（LLM不可用"):
        return _build_analysis_issue(
            kind="sheet_mapping",
            severity="blocking",
            file_name=file_name,
            sheet_name=sheet_name,
            message=(
                f"{file_name} / {sheet_name} 在字段语义映射阶段因 LLM 不可用降级为规则映射，"
                "当前结果可能遗漏部分资源类型或字段，请重新解析后再导入。"
            ),
        )
    if normalized_mode.startswith("规则映射（LLM超时"):
        return _build_analysis_issue(
            kind="sheet_mapping",
            severity="blocking",
            file_name=file_name,
            sheet_name=sheet_name,
            message=(
                f"{file_name} / {sheet_name} 在字段语义映射阶段因 LLM 超时降级为规则映射，"
                "当前结果可能不完整，请重新解析后再导入。"
            ),
        )
    return None


def _is_retryable_blocking_mapping_mode(mapping_mode: str, sheet_kind: str) -> bool:
    if _clean_text(sheet_kind) != "asset":
        return False
    normalized_mode = _clean_text(mapping_mode)
    return (
        normalized_mode.startswith("规则映射（LLM不可用")
        or normalized_mode.startswith("规则映射（LLM超时")
    )


def _validate_preview_analysis_for_import(preview: dict[str, Any]) -> None:
    analysis_status = _clean_text(preview.get("analysisStatus"))
    analysis_issues = preview.get("analysisIssues") or []
    if analysis_status != "blocking":
        return
    blocking_messages = [
        _clean_text(item.get("message"))
        for item in analysis_issues
        if isinstance(item, dict) and _clean_text(item.get("severity")) == "blocking" and _clean_text(item.get("message"))
    ]
    detail = "；".join(blocking_messages[:3])
    if not detail:
        detail = "本次解析存在关键分析失败，当前不允许导入。"
    raise RuntimeError(f"本次资源解析结果不完整，已禁止导入：{detail}")


def _validate_preview_analysis_for_preview(preview: dict[str, Any]) -> None:
    analysis_status = _clean_text(preview.get("analysisStatus"))
    if analysis_status != "blocking":
        return
    analysis_issues = preview.get("analysisIssues") or []
    blocking_messages = [
        _clean_text(item.get("message"))
        for item in analysis_issues
        if isinstance(item, dict) and _clean_text(item.get("severity")) == "blocking" and _clean_text(item.get("message"))
    ]
    detail = "；".join(blocking_messages[:3])
    if not detail:
        detail = "本次智能解析存在关键失败，未生成可继续使用的预览结果。"
    raise RuntimeError(f"本次智能解析存在关键失败，已终止后续步骤：{detail}")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


def _default_env_file() -> Path:
    return Path.cwd() / ".env"


def _normalize_token(value: str) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("（", "(").replace("）", ")")
    return re.sub(r"[\s_\-()/\\:：]+", "", text)


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def _normalize_header(header: str) -> str:
    text = _clean_text(header).lower()
    text = text.replace("（", "(").replace("）", ")")
    return re.sub(r"[\s_\-()/\\:：]+", "", text)


def _looks_like_os_or_runtime_value(value: Any) -> bool:
    normalized = _normalize_token(_clean_text(value))
    if not normalized:
        return False
    return normalized in OS_LIKE_PLATFORM_TOKENS


def _semantic_field_candidates(header: str) -> list[dict[str, str]]:
    raw = _clean_text(header)
    lowered = raw.lower()
    normalized = _normalize_header(header)
    candidates: dict[str, dict[str, str]] = {}

    def register(target: str, confidence: str, *, source: str = "semantic_rule") -> None:
        if not target or target == "unknown":
            return
        current = candidates.get(target)
        payload = {
            "targetField": target,
            "confidence": confidence,
            "source": source,
        }
        if current is None or _confidence_rank(confidence) > _confidence_rank(str(current.get("confidence", ""))):
            candidates[target] = payload

    if any(token in raw for token in ("资源主键", "业务主键", "实例主键", "设备主键", "主键", "唯一标识", "唯一键", "资源编码", "资源编号")):
        register("asset_code", "high")
    elif any(token in raw for token in ("资产标识", "资产编号", "资产编码")):
        register("asset_code", "medium")

    if any(token in raw for token in ("组件实例名", "数据库实例名", "服务实例名", "应用实例名", "实例名称", "实例名", "应用名称", "设备名称", "主机名称", "主机名", "节点名称", "节点名")):
        register("name", "high")
    elif (
        any(token in raw for token in ("名称", "名字"))
        and any(token in raw for token in ("组件", "数据库", "服务", "应用", "设备", "实例", "主机", "节点"))
    ):
        register("name", "high")
    elif normalized.endswith("name"):
        register("name", "medium")

    if any(token in raw for token in ("管理地址", "管理IP", "管理ip", "设备管理IP", "设备管理ip", "管理地址IP", "管理地址ip")):
        register("manage_ip", "high")

    if any(token in raw for token in ("内网地址", "内网IP", "内网ip", "组件地址", "数据库地址", "实例地址", "服务地址")):
        register("private_ip", "high")
    elif (
        ("地址" in raw or "ip" in lowered)
        and any(token in raw for token in ("组件", "数据库", "实例", "服务", "内网"))
    ):
        register("private_ip", "medium")

    if any(token in raw for token in ("服务端口", "组件端口", "数据库端口", "实例端口", "访问端口")):
        register("service_port", "high")
    elif "端口" in raw and any(token in raw for token in ("监听", "接入", "暴露", "服务", "组件", "数据库", "实例")):
        register("service_port", "high")
    elif "端口" in raw or normalized.endswith("port"):
        register("service_port", "medium")

    if any(token in raw for token in ("版本信息", "版本号", "软件版本", "数据库版本", "系统版本")):
        register("version", "high")

    return sorted(
        candidates.values(),
        key=lambda item: (-_confidence_rank(str(item.get("confidence", ""))), str(item.get("targetField", ""))),
    )


def _candidate_env_files() -> list[Path]:
    """Return ordered candidate paths for the CMDB env file.

    Resolution order (first non-empty file wins):
      1. ``$VEOPS_ENV_FILE`` if set.
      2. ``<cwd>/.env`` — bridge runs cwd'd into the skill dir, so this
         is the per-skill override slot.
      3. ``$QWENPAW_WORKING_DIR/secrets/zgops-cmdb.env`` (or COPAW
         fallback) — stable shared location all CMDB skills can read.
      4. ``~/.qwenpaw/secrets/zgops-cmdb.env`` — default working dir.
      5. ``<repo>/deploy-all/qwenpaw/working/secrets/zgops-cmdb.env`` —
         dev fallback when running directly out of a checkout.
    """

    candidates: list[Path] = []

    explicit = os.environ.get("VEOPS_ENV_FILE")
    if explicit:
        candidates.append(Path(explicit).expanduser())

    candidates.append(_default_env_file())

    working_dir = (
        os.environ.get("QWENPAW_WORKING_DIR")
        or os.environ.get("COPAW_WORKING_DIR")
    )
    if working_dir:
        candidates.append(
            Path(working_dir).expanduser() / "secrets" / "zgops-cmdb.env"
        )

    candidates.append(
        Path("~/.qwenpaw").expanduser() / "secrets" / "zgops-cmdb.env"
    )

    try:
        repo_secrets = (
            _repo_root()
            / "deploy-all"
            / "qwenpaw"
            / "working"
            / "secrets"
            / "zgops-cmdb.env"
        )
        candidates.append(repo_secrets)
    except Exception:
        pass

    seen: set[str] = set()
    unique: list[Path] = []
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _parse_env() -> dict[str, str]:
    candidates = _candidate_env_files()
    for path in candidates:
        try:
            if not path.is_file():
                continue
        except OSError:
            continue
        values = {
            key: str(value)
            for key, value in dotenv_values(path).items()
            if value is not None
        }
        if values:
            return values

    listing = "\n".join(f"  - {p}" for p in candidates)
    raise RuntimeError(
        "未找到可用的 CMDB 环境文件，已按以下顺序尝试：\n"
        f"{listing}\n"
        "请在任一位置创建 .env（参考同级 .env.example），"
        "推荐填写到共享路径 secrets/zgops-cmdb.env。"
    )


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return response.text


def _parse_json_loose(text: str) -> Any:
    cleaned = str(text or "").strip()
    if not cleaned:
        raise RuntimeError("LLM 返回为空")

    fenced_match = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", cleaned, flags=re.IGNORECASE)
    if fenced_match:
        cleaned = fenced_match.group(1).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    first_object = cleaned.find("{")
    last_object = cleaned.rfind("}")
    if first_object != -1 and last_object > first_object:
        candidate = cleaned[first_object:last_object + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    first_array = cleaned.find("[")
    last_array = cleaned.rfind("]")
    if first_array != -1 and last_array > first_array:
        candidate = cleaned[first_array:last_array + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    raise RuntimeError(f"LLM 返回不是合法 JSON: {cleaned}")


class VeopsCmdbClient:
    def __init__(self, base_url: str, username: str, password: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        self.client = httpx.Client(
            timeout=timeout,
            headers={"Accept-Language": "zh"},
            trust_env=False,
        )
        self.relation_type_map: dict[str, int] = {}

    @classmethod
    def from_skill_env(cls) -> "VeopsCmdbClient":
        env = _parse_env()
        return cls(
            base_url=env["VEOPS_BASE_URL"],
            username=env["VEOPS_USERNAME"],
            password=env["VEOPS_PASSWORD"],
        )

    def login(self) -> None:
        response = self.client.post(
            f"{self.base_url}/api/v1/acl/login",
            json={"username": self.username, "password": self.password},
        )
        payload = _safe_json(response)
        if response.status_code >= 400:
            raise RuntimeError(f"CMDB 登录失败: {payload}")
        token = payload.get("token") if isinstance(payload, dict) else None
        if not token:
            raise RuntimeError("CMDB 登录响应缺少 token")
        self.client.headers["Access-Token"] = str(token)

    def close(self) -> None:
        self.client.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_payload: Any = None,
    ) -> Any:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        response = self.client.request(method, url, params=params, json=json_payload)
        payload = _safe_json(response)
        if response.status_code >= 400:
            raise RuntimeError(f"{method.upper()} {path} 失败: {payload}")
        return payload

    def get_ci_types(self) -> list[dict[str, Any]]:
        payload = self.request("GET", "/api/v0.1/ci_types", params={"per_page": 200})
        return payload.get("ci_types", []) if isinstance(payload, dict) else []

    def get_ci_type_groups(self) -> list[dict[str, Any]]:
        payload = self.request("GET", "/api/v0.1/ci_types/groups", params={"need_other": True})
        if isinstance(payload, list):
            return payload
        return payload.get("groups", payload.get("result", [])) or []

    def create_ci_type_group(self, name: str) -> Any:
        return self.request(
            "POST",
            "/api/v0.1/ci_types/groups",
            json_payload={"name": name},
        )

    def update_ci_type_group(self, group_id: int | str, *, name: str, type_ids: list[int]) -> Any:
        return self.request(
            "PUT",
            f"/api/v0.1/ci_types/groups/{group_id}",
            json_payload={
                "name": name,
                "type_ids": type_ids,
            },
        )

    def create_ci_type(
        self,
        *,
        name: str,
        alias: str,
        unique_key: int | str,
        parent_ids: list[int] | None = None,
        icon: str = "",
    ) -> tuple[Any, Any]:
        payload = {
            "name": name,
            "alias": alias or name,
            "unique_key": unique_key,
        }
        if parent_ids:
            payload["parent_ids"] = parent_ids
        if icon is not None:
            payload["icon"] = icon
        response = self.request(
            "POST",
            "/api/v0.1/ci_types",
            json_payload=payload,
        )
        type_id = None
        if isinstance(response, dict):
            type_id = response.get("type_id") or response.get("id")
            if type_id is None and isinstance(response.get("result"), dict):
                type_id = response["result"].get("type_id") or response["result"].get("id")
        return type_id, response

    def create_ci_type_inheritance(self, parent_ids: list[int], child_id: int | str) -> Any:
        return self.request(
            "POST",
            "/api/v0.1/ci_types/inheritance",
            json_payload={
                "parent_ids": parent_ids,
                "child_id": child_id,
            },
        )

    def get_relation_types(self) -> list[dict[str, Any]]:
        payload = self.request("GET", "/api/v0.1/relation_types")
        relation_types = payload if isinstance(payload, list) else payload.get("result", payload)
        results = relation_types if isinstance(relation_types, list) else []
        self.relation_type_map = {
            str(item.get("name")): int(item.get("id"))
            for item in results
            if item.get("name") and item.get("id") is not None
        }
        return results

    def get_ci_type_attributes(self, type_id: int | str) -> list[dict[str, Any]]:
        payload = self.request("GET", f"/api/v0.1/ci_types/{type_id}/attributes")
        if isinstance(payload, list):
            return payload
        return payload.get("attributes", payload.get("result", [])) or []

    def get_ci_type_preference_attributes(self, type_id: int | str) -> list[dict[str, Any]]:
        payload = self.request("GET", f"/api/v0.1/preference/ci_types/{type_id}/attributes")
        if isinstance(payload, list):
            return payload
        return payload.get("attributes", payload.get("result", [])) or []

    def get_attribute_library(self, *, page_size: int = 500, page: int = 1) -> list[dict[str, Any]]:
        payload = self.request(
            "GET",
            "/api/v0.1/attributes/s",
            params={"page_size": page_size, "page": page},
        )
        if isinstance(payload, list):
            return payload
        return payload.get("attributes", payload.get("result", [])) or []

    def get_ci_type_parent_relations(self, type_id: int | str) -> list[dict[str, Any]]:
        payload = self.request("GET", f"/api/v0.1/ci_type_relations/{type_id}/parents")
        if isinstance(payload, list):
            return payload
        return payload.get("parents", payload.get("result", [])) or []

    def get_ci_type_relations(self, type_id: int | str) -> list[dict[str, Any]]:
        payload = self.request("GET", "/api/v0.1/ci_type_relations", params={"ci_type_id": type_id})
        if isinstance(payload, list):
            return payload
        return payload.get("relations", payload.get("result", [])) or []

    def create_ci_type_relation(
        self,
        parent_type_id: int | str,
        child_type_id: int | str,
        *,
        relation_type_id: int | str,
        constraint: str = "0",
        parent_attr_ids: list[int | str] | None = None,
        child_attr_ids: list[int | str] | None = None,
    ) -> tuple[Any, Any]:
        payload: dict[str, Any] = {
            "relation_type_id": relation_type_id,
        }
        if constraint != "":
            payload["constraint"] = str(constraint)
        if parent_attr_ids is not None:
            payload["parent_attr_ids"] = parent_attr_ids
        if child_attr_ids is not None:
            payload["child_attr_ids"] = child_attr_ids
        response = self.request(
            "POST",
            f"/api/v0.1/ci_type_relations/{parent_type_id}/{child_type_id}",
            json_payload=payload,
        )
        relation_id = None
        if isinstance(response, dict):
            relation_id = response.get("ctr_id") or response.get("id")
            if relation_id is None and isinstance(response.get("result"), dict):
                relation_id = response["result"].get("ctr_id") or response["result"].get("id")
        return relation_id, response

    def query_ci(self, query: str, *, count: int = 5) -> list[dict[str, Any]]:
        payload = self.request("GET", "/api/v0.1/ci/s", params={"q": query, "count": count})
        if isinstance(payload, list):
            return payload
        for key in ("result", "items", "cis", "rows"):
            if isinstance(payload.get(key), list):
                return payload[key]
        if isinstance(payload.get("data"), list):
            return payload["data"]
        return []

    def create_ci(
        self,
        ci_type: str,
        attributes: dict[str, Any],
        *,
        exist_policy: str = "reject",
        unique_key: str = "",
    ) -> tuple[Any, Any]:
        payload = {
            "ci_type": ci_type,
            "no_attribute_policy": "ignore",
            "exist_policy": exist_policy,
            **attributes,
        }
        response = self.request("POST", "/api/v0.1/ci", json_payload=payload)
        ci_id = _extract_ci_id(response)
        if ci_id is None:
            ci_id = self.lookup_ci_id(ci_type, attributes, unique_key=unique_key)
        return ci_id, response

    def update_ci(self, ci_id: Any, ci_type: str, attributes: dict[str, Any]) -> tuple[Any, Any]:
        payload = {
            "ci_type": ci_type,
            "no_attribute_policy": "ignore",
            **attributes,
        }
        response = self.request("PUT", f"/api/v0.1/ci/{ci_id}", json_payload=payload)
        updated_ci_id = _extract_ci_id(response) or ci_id
        return updated_ci_id, response

    def delete_ci(self, ci_id: Any) -> Any:
        return self.request("DELETE", f"/api/v0.1/ci/{ci_id}")

    def get_ci_by_id(self, ci_id: Any) -> dict[str, Any] | None:
        items = self.query_ci(f"id:{ci_id}", count=1)
        if items:
            return items[0]
        return None

    def lookup_ci_id(self, ci_type: str, attributes: dict[str, Any], *, unique_key: str = "") -> Any:
        filters = [f"_type:{ci_type}"]
        for key in [unique_key, "asset_code", "private_ip", "name"]:
            key = _clean_text(key)
            if not key:
                continue
            value = _clean_text(attributes.get(key))
            if value:
                filters.append(f"{key}:{quote(value, safe='._-:/')}")
                break
        items = self.query_ci(",".join(filters), count=1)
        if items:
            return _extract_ci_id(items[0])
        return None

    def create_relation(self, src_ci_id: Any, dst_ci_id: Any, relation_type: str) -> tuple[Any, Any]:
        response = self.request("POST", f"/api/v0.1/ci_relations/{src_ci_id}/{dst_ci_id}")
        return _extract_ci_relation_id(response), response

    def delete_relation(self, relation_id: Any) -> Any:
        return self.request("DELETE", f"/api/v0.1/ci_relations/{relation_id}")


class ResourceImportLLMClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        vision_model: str | None = None,
        timeout: float = 300.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.vision_model = vision_model or model
        self.timeout = timeout
        self.client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                **({"Authorization": f"Bearer {api_key}"} if api_key else {}),
                "Content-Type": "application/json",
            },
        )

    @classmethod
    def from_env_optional(cls) -> "ResourceImportLLMClient | None":
        try:
            env = _parse_env()
        except Exception:
            return None
        base_url = str(env.get("RESOURCE_IMPORT_LLM_BASE_URL") or "").strip()
        api_key = str(env.get("RESOURCE_IMPORT_LLM_API_KEY") or "").strip()
        model = str(env.get("RESOURCE_IMPORT_LLM_MODEL") or "").strip()
        vision_model = str(env.get("RESOURCE_IMPORT_LLM_VISION_MODEL") or "").strip()
        timeout = float(env.get("RESOURCE_IMPORT_LLM_TIMEOUT") or 300.0)
        if not base_url or not api_key or not model:
            return None
        return cls(
            base_url=base_url,
            api_key=api_key,
            model=model,
            vision_model=vision_model or None,
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self.client.aclose()

    def _extract_text(self, payload: Any) -> str:
        if isinstance(payload, dict):
            if isinstance(payload.get("choices"), list) and payload["choices"]:
                message = payload["choices"][0].get("message") or {}
                content = message.get("content")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    text_parts = []
                    for item in content:
                        if item.get("type") == "text":
                            text_parts.append(str(item.get("text") or ""))
                    return "\n".join(text_parts).strip()
            if isinstance(payload.get("output"), list):
                fragments: list[str] = []
                for item in payload["output"]:
                    for content in item.get("content", []) or []:
                        if content.get("type") == "output_text":
                            fragments.append(str(content.get("text") or ""))
                if fragments:
                    return "\n".join(fragments).strip()
        return str(payload)

    async def _request_json(self, *, model: str, messages: list[dict[str, Any]]) -> Any:
        response = await self.client.post(
            f"{self.base_url}/chat/completions",
            json={
                "model": model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": messages,
            },
        )
        payload = _safe_json(response)
        if response.status_code >= 400:
            raise RuntimeError(f"LLM 请求失败: {payload}")
        text = self._extract_text(payload).strip()
        return _parse_json_loose(text)

    async def map_sheet_headers(
        self,
        *,
        sheet_name: str,
        headers: list[str],
        sample_rows: list[dict[str, Any]],
        ci_types: list[str],
        field_candidates: dict[str, list[dict[str, Any]]] | None = None,
        ci_type_catalog: list[dict[str, Any]] | None = None,
    ) -> SheetMappingPlan:
        prompt = {
            "sheet_name": sheet_name,
            "headers": headers,
            "sample_rows": sample_rows,
            "available_fields": sorted({*FIELD_ALIASES.keys(), *RELATION_FIELD_ALIASES.keys()}),
            "available_ci_types": ci_types,
            "field_candidates": field_candidates or {},
            "ci_type_catalog": ci_type_catalog or [],
            "rules": [
                "只做字段语义匹配，不要臆造字段。",
                "如果这个 sheet 明显不是资产/配置清单，而是说明、备注、测试点，sheet_kind 返回 note。",
                "如果这个 sheet 明显是在描述资源之间的关系、上下游、父子依赖、关系映射，sheet_kind 返回 relation。",
                "如果字段无法确定，target 填 unknown。",
                "default_ci_type 仅在 sheet 整体语义明确时填写，否则留空。",
                "如果某个 header 已提供 field_candidates，请优先在这些候选中重排；只有候选明显都不对时，才可选择候选外字段。",
                "需要综合表头、样例值、候选字段在 CMDB 中出现的模型/分组、候选模型目录一起判断。",
            ],
            "output_schema": {
                "sheet_kind": "asset|relation|note|unknown",
                "default_ci_type": "string",
                "reason": "string",
                "mappings": [{"source": "string", "target": "string", "confidence": "high|medium|low"}],
            },
        }
        result = await self._request_json(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "你是 CMDB 资源导入映射助手。你的任务是把客户原始字段映射到标准字段，只能依据表头、sheet 名称和样例值判断，不能补造不存在的信息。",
                },
                {
                    "role": "user",
                    "content": json.dumps(prompt, ensure_ascii=False),
                },
            ],
        )
        mappings: dict[str, tuple[str, str]] = {}
        for item in result.get("mappings", []) or []:
            source = _clean_text(item.get("source"))
            target = _clean_text(item.get("target")) or "unknown"
            confidence = _clean_text(item.get("confidence")) or "low"
            if source:
                mappings[source] = (target, confidence)
        return SheetMappingPlan(
            sheet_kind=_clean_text(result.get("sheet_kind")) or "unknown",
            default_ci_type=_clean_text(result.get("default_ci_type")),
            mappings=mappings,
            reason=_clean_text(result.get("reason")),
        )

    async def infer_resource_model(
        self,
        *,
        prompt: dict[str, Any],
    ) -> Any:
        return await self._request_json(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是 CMDB 模型归属助手。"
                        "你的任务是把一组资源归到最合适的已有 CMDB 模型。"
                        "只能从给定候选中选择，不能新增模型，也不能输出候选外的名字。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(prompt, ensure_ascii=False),
                },
            ],
        )

    async def extract_rows_from_image(self, *, filename: str, content: bytes) -> list[dict[str, Any]]:
        encoded = base64.b64encode(content).decode("ascii")
        suffix = Path(filename).suffix.lower().lstrip(".") or "png"
        prompt = {
            "task": "从图片中的资源清单或表格中提取结构化记录。",
            "rules": [
                "只提取图片中明确可见的信息。",
                "每一行记录保留原始字段名，不要映射成标准字段。",
                "如果图片不是资产清单而只是说明文字，返回 rows=[]。",
            ],
            "output_schema": {
                "rows": [{"原始字段名": "字段值"}],
            },
        }
        result = await self._request_json(
            model=self.vision_model,
            messages=[
                {
                    "role": "system",
                    "content": "你是图片资产清单提取助手，只能抽取可见内容，不能推测缺失信息。",
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": json.dumps(prompt, ensure_ascii=False)},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/{suffix};base64,{encoded}"},
                        },
                    ],
                },
            ],
        )
        rows = result.get("rows")
        if not isinstance(rows, list):
            return []
        return [item for item in rows if isinstance(item, dict)]


def _extract_response_text(payload: Any) -> str:
    if hasattr(payload, "text") and isinstance(getattr(payload, "text"), str):
        return str(getattr(payload, "text") or "").strip()

    content = getattr(payload, "content", None)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        fragments: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text" and item.get("text"):
                    fragments.append(str(item.get("text")))
                elif item.get("type") == "output_text" and item.get("text"):
                    fragments.append(str(item.get("text")))
            elif hasattr(item, "text") and getattr(item, "text"):
                fragments.append(str(getattr(item, "text")))
        return "\n".join(fragment.strip() for fragment in fragments if fragment).strip()

    if isinstance(payload, str):
        return payload.strip()

    return str(payload).strip()


async def _consume_model_response(response: Any) -> str:
    if hasattr(response, "__aiter__"):
        accumulated = ""
        async for chunk in response:
            current = _extract_response_text(chunk)
            if not current:
                continue
            if current.startswith(accumulated):
                accumulated = current
            else:
                accumulated += current
        return accumulated.strip()
    return _extract_response_text(response)


class AnthropicResourceImportLLMClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        vision_model: str | None = None,
        timeout: float = 300.0,
    ) -> None:
        import anthropic

        self.model = model
        self.vision_model = vision_model or model
        self.timeout = timeout
        self.client = anthropic.AsyncAnthropic(
            api_key=api_key,
            base_url=base_url or None,
            timeout=timeout,
        )

    async def aclose(self) -> None:
        return None

    async def _request_json(self, *, model: str, content: list[dict[str, Any]]) -> Any:
        response = await self.client.messages.create(
            model=model,
            max_tokens=1800,
            messages=[{"role": "user", "content": content}],
        )
        text = _extract_response_text(response)
        return _parse_json_loose(text)

    async def map_sheet_headers(
        self,
        *,
        sheet_name: str,
        headers: list[str],
        sample_rows: list[dict[str, Any]],
        ci_types: list[str],
        field_candidates: dict[str, list[dict[str, Any]]] | None = None,
        ci_type_catalog: list[dict[str, Any]] | None = None,
    ) -> SheetMappingPlan:
        prompt = {
            "sheet_name": sheet_name,
            "headers": headers,
            "sample_rows": sample_rows,
            "available_fields": sorted({*FIELD_ALIASES.keys(), *RELATION_FIELD_ALIASES.keys()}),
            "available_ci_types": ci_types,
            "field_candidates": field_candidates or {},
            "ci_type_catalog": ci_type_catalog or [],
            "rules": [
                "只做字段语义匹配，不要臆造字段。",
                "如果这个 sheet 明显不是资产/配置清单，而是说明、备注、测试点，sheet_kind 返回 note。",
                "如果这个 sheet 明显是在描述资源之间的关系、上下游、父子依赖、关系映射，sheet_kind 返回 relation。",
                "如果字段无法确定，target 填 unknown。",
                "default_ci_type 仅在 sheet 整体语义明确时填写，否则留空。",
                "输出必须是 JSON。",
                "如果某个 header 已提供 field_candidates，请优先在这些候选中重排；只有候选明显都不对时，才可选择候选外字段。",
                "需要综合表头、样例值、候选字段在 CMDB 中出现的模型/分组、候选模型目录一起判断。",
            ],
            "output_schema": {
                "sheet_kind": "asset|relation|note|unknown",
                "default_ci_type": "string",
                "reason": "string",
                "mappings": [{"source": "string", "target": "string", "confidence": "high|medium|low"}],
            },
        }
        result = await self._request_json(
            model=self.model,
            content=[
                {
                    "type": "text",
                    "text": (
                        "你是 CMDB 资源导入映射助手。"
                        "只能依据表头、sheet 名称和样例值判断，不能补造不存在的信息。"
                        "请直接输出 JSON。"
                    ),
                },
                {"type": "text", "text": json.dumps(prompt, ensure_ascii=False)},
            ],
        )
        mappings: dict[str, tuple[str, str]] = {}
        for item in result.get("mappings", []) or []:
            source = _clean_text(item.get("source"))
            target = _clean_text(item.get("target")) or "unknown"
            confidence = _clean_text(item.get("confidence")) or "low"
            if source:
                mappings[source] = (target, confidence)
        return SheetMappingPlan(
            sheet_kind=_clean_text(result.get("sheet_kind")) or "unknown",
            default_ci_type=_clean_text(result.get("default_ci_type")),
            mappings=mappings,
            reason=_clean_text(result.get("reason")),
        )

    async def infer_resource_model(
        self,
        *,
        prompt: dict[str, Any],
    ) -> Any:
        return await self._request_json(
            model=self.model,
            content=[
                {
                    "type": "text",
                    "text": (
                        "你是 CMDB 模型归属助手。"
                        "只能从给定候选模型中选择，不能新增模型，不能输出候选外的名字。"
                        "请直接输出 JSON。"
                    ),
                },
                {"type": "text", "text": json.dumps(prompt, ensure_ascii=False)},
            ],
        )

    async def extract_rows_from_image(self, *, filename: str, content: bytes) -> list[dict[str, Any]]:
        encoded = base64.b64encode(content).decode("ascii")
        suffix = Path(filename).suffix.lower()
        media_type = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
        }.get(suffix, "image/png")
        prompt = {
            "task": "从图片中的资源清单或表格中提取结构化记录。",
            "rules": [
                "只提取图片中明确可见的信息。",
                "每一行记录保留原始字段名，不要映射成标准字段。",
                "如果图片不是资产清单而只是说明文字，返回 rows=[]。",
                "输出必须是 JSON。",
            ],
            "output_schema": {"rows": [{"原始字段名": "字段值"}]},
        }
        result = await self._request_json(
            model=self.vision_model,
            content=[
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": encoded,
                    },
                },
                {"type": "text", "text": json.dumps(prompt, ensure_ascii=False)},
            ],
        )
        rows = result.get("rows")
        if not isinstance(rows, list):
            return []
        return [item for item in rows if isinstance(item, dict)]


class GeminiResourceImportLLMClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        vision_model: str | None = None,
        timeout: float = 300.0,
    ) -> None:
        from google import genai
        from google.genai import types as genai_types

        self.model = model
        self.vision_model = vision_model or model
        self.timeout = timeout
        self._genai_types = genai_types
        self.client = genai.Client(
            api_key=api_key,
            http_options=genai_types.HttpOptions(timeout=int(timeout * 1000)),
        )

    async def aclose(self) -> None:
        return None

    async def _request_json(self, *, model: str, parts: list[Any]) -> Any:
        response = await self.client.aio.models.generate_content(
            model=model,
            contents=parts,
            config=self._genai_types.GenerateContentConfig(
                max_output_tokens=1800,
                response_mime_type="application/json",
            ),
        )
        text = _extract_response_text(response)
        return _parse_json_loose(text)

    async def map_sheet_headers(
        self,
        *,
        sheet_name: str,
        headers: list[str],
        sample_rows: list[dict[str, Any]],
        ci_types: list[str],
        field_candidates: dict[str, list[dict[str, Any]]] | None = None,
        ci_type_catalog: list[dict[str, Any]] | None = None,
    ) -> SheetMappingPlan:
        prompt = {
            "sheet_name": sheet_name,
            "headers": headers,
            "sample_rows": sample_rows,
            "available_fields": sorted({*FIELD_ALIASES.keys(), *RELATION_FIELD_ALIASES.keys()}),
            "available_ci_types": ci_types,
            "field_candidates": field_candidates or {},
            "ci_type_catalog": ci_type_catalog or [],
            "rules": [
                "只做字段语义匹配，不要臆造字段。",
                "如果这个 sheet 明显不是资产/配置清单，而是说明、备注、测试点，sheet_kind 返回 note。",
                "如果这个 sheet 明显是在描述资源之间的关系、上下游、父子依赖、关系映射，sheet_kind 返回 relation。",
                "如果字段无法确定，target 填 unknown。",
                "default_ci_type 仅在 sheet 整体语义明确时填写，否则留空。",
                "输出必须是 JSON。",
                "如果某个 header 已提供 field_candidates，请优先在这些候选中重排；只有候选明显都不对时，才可选择候选外字段。",
                "需要综合表头、样例值、候选字段在 CMDB 中出现的模型/分组、候选模型目录一起判断。",
            ],
            "output_schema": {
                "sheet_kind": "asset|relation|note|unknown",
                "default_ci_type": "string",
                "reason": "string",
                "mappings": [{"source": "string", "target": "string", "confidence": "high|medium|low"}],
            },
        }
        result = await self._request_json(
            model=self.model,
            parts=[
                self._genai_types.Part(
                    text=(
                        "你是 CMDB 资源导入映射助手。"
                        "只能依据表头、sheet 名称和样例值判断，不能补造不存在的信息。"
                        "请直接输出 JSON。"
                    ),
                ),
                self._genai_types.Part(text=json.dumps(prompt, ensure_ascii=False)),
            ],
        )
        mappings: dict[str, tuple[str, str]] = {}
        for item in result.get("mappings", []) or []:
            source = _clean_text(item.get("source"))
            target = _clean_text(item.get("target")) or "unknown"
            confidence = _clean_text(item.get("confidence")) or "low"
            if source:
                mappings[source] = (target, confidence)
        return SheetMappingPlan(
            sheet_kind=_clean_text(result.get("sheet_kind")) or "unknown",
            default_ci_type=_clean_text(result.get("default_ci_type")),
            mappings=mappings,
            reason=_clean_text(result.get("reason")),
        )

    async def infer_resource_model(
        self,
        *,
        prompt: dict[str, Any],
    ) -> Any:
        return await self._request_json(
            model=self.model,
            parts=[
                self._genai_types.Part(
                    text=(
                        "你是 CMDB 模型归属助手。"
                        "只能从给定候选模型中选择，不能新增模型，不能输出候选外的名字。"
                        "请直接输出 JSON。"
                    ),
                ),
                self._genai_types.Part(text=json.dumps(prompt, ensure_ascii=False)),
            ],
        )

    async def extract_rows_from_image(self, *, filename: str, content: bytes) -> list[dict[str, Any]]:
        suffix = Path(filename).suffix.lower()
        mime_type = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
        }.get(suffix, "image/png")
        prompt = {
            "task": "从图片中的资源清单或表格中提取结构化记录。",
            "rules": [
                "只提取图片中明确可见的信息。",
                "每一行记录保留原始字段名，不要映射成标准字段。",
                "如果图片不是资产清单而只是说明文字，返回 rows=[]。",
                "输出必须是 JSON。",
            ],
            "output_schema": {"rows": [{"原始字段名": "字段值"}]},
        }
        result = await self._request_json(
            model=self.vision_model,
            parts=[
                self._genai_types.Part(
                    inline_data=self._genai_types.Blob(
                        mime_type=mime_type,
                        data=content,
                    ),
                ),
                self._genai_types.Part(text=json.dumps(prompt, ensure_ascii=False)),
            ],
        )
        rows = result.get("rows")
        if not isinstance(rows, list):
            return []
        return [item for item in rows if isinstance(item, dict)]


def _build_runtime_client_from_agent(agent_id: str) -> Any | None:
    try:
        from qwenpaw.config.config import load_agent_config
        from qwenpaw.providers.provider_manager import ProviderManager

        manager = ProviderManager.get_instance()
        model_slot = load_agent_config(agent_id).active_model or manager.get_active_model()
        if not model_slot or not model_slot.provider_id or not model_slot.model:
            return None

        provider = manager.get_provider(model_slot.provider_id)
        if not provider:
            return None

        if provider.chat_model == "AnthropicChatModel":
            return AnthropicResourceImportLLMClient(
                base_url=provider.base_url,
                api_key=provider.api_key,
                model=model_slot.model,
            )
        if provider.chat_model == "GeminiChatModel":
            return GeminiResourceImportLLMClient(
                api_key=provider.api_key,
                model=model_slot.model,
            )
        return ResourceImportLLMClient(
            base_url=provider.base_url,
            api_key=provider.api_key,
            model=model_slot.model,
        )
    except Exception:
        return None


async def resolve_resource_import_runtime(agent_id: str | None = None) -> ResourceImportRuntime:
    if agent_id:
        agent_client = _build_runtime_client_from_agent(agent_id)
        if agent_client:
            return ResourceImportRuntime(
                client=agent_client,
                source=f"当前页面模型配置({agent_id})",
            )
    return ResourceImportRuntime(client=None, source="规则映射")


async def resolve_resource_import_llm_client(agent_id: str | None = None) -> Any | None:
    runtime = await resolve_resource_import_runtime(agent_id)
    return runtime.client


def _extract_ci_id(payload: Any) -> Any:
    if isinstance(payload, dict):
        for key in ("id", "ci_id", "_id"):
            value = payload.get(key)
            if value not in (None, ""):
                return value
        for key in ("result", "data", "ci", "item"):
            value = payload.get(key)
            result = _extract_ci_id(value)
            if result not in (None, ""):
                return result
    if isinstance(payload, list):
        for item in payload:
            result = _extract_ci_id(item)
            if result not in (None, ""):
                return result
    return None


def _extract_ci_type_relation_id(payload: Any) -> Any:
    if isinstance(payload, dict):
        for key in ("ctr_id", "id", "relation_id"):
            value = payload.get(key)
            if value not in (None, ""):
                return value
        for key in ("result", "data", "item"):
            value = payload.get(key)
            result = _extract_ci_type_relation_id(value)
            if result not in (None, ""):
                return result
    if isinstance(payload, list):
        for item in payload:
            result = _extract_ci_type_relation_id(item)
            if result not in (None, ""):
                return result
    return None


def _extract_ci_relation_id(payload: Any) -> Any:
    if isinstance(payload, dict):
        for key in ("cr_id", "id", "relation_id"):
            value = payload.get(key)
            if value not in (None, ""):
                return value
        for key in ("result", "data", "item"):
            value = payload.get(key)
            result = _extract_ci_relation_id(value)
            if result not in (None, ""):
                return result
    if isinstance(payload, list):
        for item in payload:
            result = _extract_ci_relation_id(item)
            if result not in (None, ""):
                return result
    return None


def _match_field(header: str) -> tuple[str, str]:
    normalized = _normalize_header(header)
    for target, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            if normalized == _normalize_header(alias):
                return target, "high"
    semantic_candidates = _semantic_field_candidates(header)
    if semantic_candidates:
        first = semantic_candidates[0]
        return str(first.get("targetField") or "unknown"), str(first.get("confidence") or "low")
    for target, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            alias_token = _normalize_header(alias)
            if alias_token and len(alias_token) >= 5 and (alias_token in normalized or normalized in alias_token):
                return target, "medium"
    return "unknown", "low"


def _match_relation_field(header: str) -> tuple[str, str]:
    normalized = _normalize_header(header)
    for target, aliases in RELATION_FIELD_ALIASES.items():
        for alias in aliases:
            if normalized == _normalize_header(alias):
                return target, "high"
    for target, aliases in RELATION_FIELD_ALIASES.items():
        for alias in aliases:
            alias_token = _normalize_header(alias)
            if alias_token and len(alias_token) >= 3 and (alias_token in normalized or normalized in alias_token):
                return target, "medium"
    return "unknown", "low"


def _confidence_rank(value: str) -> int:
    return {
        "low": 0,
        "medium": 1,
        "high": 2,
    }.get(_clean_text(value).lower(), 0)


def _dedupe_non_empty(values: list[Any], *, limit: int | None = None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = _clean_text(value)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
        if limit is not None and len(result) >= limit:
            break
    return result


def _semantic_terms(value: str) -> list[str]:
    cleaned = _clean_text(value).lower()
    if not cleaned:
        return []
    terms = re.split(r"[^a-z0-9\u4e00-\u9fff]+", cleaned)
    return [
        term
        for term in terms
        if term and (len(term) >= 2 or re.search(r"[\u4e00-\u9fff]", term))
    ]


def _semantic_text_similarity(header: str, candidate_text: str) -> tuple[int, str]:
    header_raw = _clean_text(header)
    candidate_raw = _clean_text(candidate_text)
    if not header_raw or not candidate_raw:
        return 0, ""

    normalized_header = _normalize_header(header_raw)
    normalized_candidate = _normalize_header(candidate_raw)
    if not normalized_header or not normalized_candidate:
        return 0, ""
    if normalized_header == normalized_candidate:
        return 100, f"与 {candidate_raw} 完全一致"
    if len(normalized_candidate) >= 4 and (
        normalized_candidate in normalized_header or normalized_header in normalized_candidate
    ):
        return 88, f"与 {candidate_raw} 文本非常接近"

    ratio = SequenceMatcher(None, normalized_header, normalized_candidate).ratio()
    if ratio >= 0.92:
        return 82, f"与 {candidate_raw} 高度相似"
    if ratio >= 0.80:
        return 70, f"与 {candidate_raw} 相似"
    if ratio >= 0.68:
        return 58, f"与 {candidate_raw} 存在近似语义"

    header_terms = set(_semantic_terms(header_raw))
    candidate_terms = set(_semantic_terms(candidate_raw))
    if header_terms and candidate_terms:
        overlap = header_terms & candidate_terms
        if overlap:
            score = 52 + min(12, len(overlap) * 6)
            return score, f"与 {candidate_raw} 共享关键词 {', '.join(sorted(overlap)[:3])}"
    return 0, ""


def _score_to_confidence(score: int) -> str:
    if score >= 86:
        return "high"
    if score >= 64:
        return "medium"
    return "low"


def _infer_canonical_field_from_metadata_attribute(
    *,
    attribute_name: str,
    attribute_alias: str,
) -> tuple[str, str]:
    ranked: list[dict[str, Any]] = []
    for raw_value in [attribute_name, attribute_alias]:
        direct_target, direct_confidence = _match_field(raw_value)
        ranked.append({"target": direct_target, "confidence": direct_confidence, "score": 100})
        for target_field, aliases in FIELD_ALIASES.items():
            best_score = 0
            for candidate_text in [target_field, *aliases]:
                score, _reason = _semantic_text_similarity(raw_value, candidate_text)
                best_score = max(best_score, score)
            if best_score >= 64:
                ranked.append(
                    {
                        "target": target_field,
                        "confidence": _score_to_confidence(best_score),
                        "score": best_score,
                    }
                )

    ranked.sort(
        key=lambda item: (
            -int(item.get("score") or 0),
            -_confidence_rank(str(item.get("confidence") or "")),
            str(item.get("target") or ""),
        ),
    )
    for item in ranked:
        target = _clean_text(item.get("target"))
        if target and target != "unknown":
            return target, _clean_text(item.get("confidence")) or "low"
    return "unknown", "low"


def _build_metadata_field_catalog(metadata: dict[str, Any]) -> dict[str, dict[str, Any]]:
    groups_by_model: dict[str, list[str]] = defaultdict(list)
    for group in (metadata.get("ciTypeGroups") or []):
        if not isinstance(group, dict):
            continue
        group_name = _clean_text(group.get("name"))
        if not group_name:
            continue
        for item in (group.get("ciTypes") or []):
            if not isinstance(item, dict):
                continue
            model_name = _clean_text(item.get("name"))
            if model_name and group_name not in groups_by_model[model_name]:
                groups_by_model[model_name].append(group_name)

    catalog: dict[str, dict[str, Any]] = {}

    def ensure_entry(target_field: str) -> dict[str, Any]:
        return catalog.setdefault(
            target_field,
            {
                "targetField": target_field,
                "canonicalAliases": [],
                "attributeNames": [],
                "attributeAliases": [],
                "models": [],
                "modelAliases": [],
                "groups": [],
            },
        )

    for target_field, aliases in FIELD_ALIASES.items():
        entry = ensure_entry(target_field)
        entry["canonicalAliases"] = _dedupe_non_empty(
            [*entry.get("canonicalAliases", []), target_field, *aliases],
            limit=24,
        )

    for ci_type in (metadata.get("ciTypes") or []):
        if not isinstance(ci_type, dict):
            continue
        model_name = _clean_text(ci_type.get("name"))
        model_alias = _clean_text(ci_type.get("alias")) or model_name
        if not model_name:
            continue
        group_names = groups_by_model.get(model_name) or _dedupe_non_empty(
            [*(ci_type.get("groupNames") or []), DEFAULT_GROUP_HINTS.get(model_name, "")],
            limit=6,
        )

        for definition in (ci_type.get("attributeDefinitions") or []):
            if not isinstance(definition, dict):
                continue
            attribute_name = _clean_text(definition.get("name"))
            attribute_alias = _clean_text(definition.get("alias")) or attribute_name
            if attribute_name:
                # Always expose the model attribute as its own direct mapping
                # target so distinct attributes never collapse into a single
                # canonical bucket (e.g. project_type/project_description both
                # inferring "project"). Canonical bucketing below still runs as
                # a cross-CMDB normalization fallback.
                direct_entry = ensure_entry(attribute_name)
                direct_entry["attributeNames"] = _dedupe_non_empty(
                    [*direct_entry.get("attributeNames", []), attribute_name],
                    limit=36,
                )
                direct_entry["attributeAliases"] = _dedupe_non_empty(
                    [
                        *direct_entry.get("attributeAliases", []),
                        attribute_alias,
                    ],
                    limit=36,
                )
                direct_entry["models"] = _dedupe_non_empty(
                    [*direct_entry.get("models", []), model_name],
                    limit=24,
                )
                direct_entry["modelAliases"] = _dedupe_non_empty(
                    [*direct_entry.get("modelAliases", []), model_alias],
                    limit=24,
                )
                direct_entry["groups"] = _dedupe_non_empty(
                    [*direct_entry.get("groups", []), *group_names],
                    limit=12,
                )
            canonical_field, confidence = _infer_canonical_field_from_metadata_attribute(
                attribute_name=attribute_name,
                attribute_alias=attribute_alias,
            )
            if canonical_field == "unknown" or _confidence_rank(confidence) <= 0:
                continue
            if canonical_field == attribute_name:
                continue
            entry = ensure_entry(canonical_field)
            entry["attributeNames"] = _dedupe_non_empty(
                [*entry.get("attributeNames", []), attribute_name],
                limit=36,
            )
            entry["attributeAliases"] = _dedupe_non_empty(
                [*entry.get("attributeAliases", []), attribute_alias],
                limit=36,
            )
            entry["models"] = _dedupe_non_empty(
                [*entry.get("models", []), model_name],
                limit=24,
            )
            entry["modelAliases"] = _dedupe_non_empty(
                [*entry.get("modelAliases", []), model_alias],
                limit=24,
            )
            entry["groups"] = _dedupe_non_empty(
                [*entry.get("groups", []), *group_names],
                limit=12,
            )

    return catalog


def _collect_metadata_field_candidates(
    header: str,
    metadata: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not metadata:
        return []
    field_catalog = metadata.get("semanticFieldCatalog") or {}
    if not isinstance(field_catalog, dict):
        return []

    candidates: list[dict[str, Any]] = []
    for target_field, entry in field_catalog.items():
        if not isinstance(entry, dict):
            continue
        best_score = 0
        best_reason = ""
        best_match_text = ""
        for candidate_text in _dedupe_non_empty(
            [
                target_field,
                *(entry.get("canonicalAliases") or []),
                *(entry.get("attributeNames") or []),
                *(entry.get("attributeAliases") or []),
            ],
            limit=40,
        ):
            score, reason = _semantic_text_similarity(header, candidate_text)
            if score > best_score:
                best_score = score
                best_reason = reason
                best_match_text = candidate_text
        if best_score < 54:
            continue
        models = _dedupe_non_empty(entry.get("models") or [], limit=4)
        is_direct = target_field in (entry.get("attributeNames") or [])
        candidates.append(
            {
                "targetField": target_field,
                "confidence": _score_to_confidence(best_score),
                "source": "metadata",
                "score": best_score,
                "reason": best_reason,
                "matchedText": best_match_text,
                "models": models,
                "groups": _dedupe_non_empty(entry.get("groups") or [], limit=3),
                "direct": is_direct,
            }
        )

    # On equal score, prefer a direct model-attribute target over a canonical
    # bucket so distinct attributes that infer the same canonical (project_type
    # vs project) don't get shadowed by the bucket label.
    candidates.sort(
        key=lambda item: (
            -int(item.get("score") or 0),
            not bool(item.get("direct")),
            str(item.get("targetField") or ""),
        ),
    )
    return candidates[:8]


def _collect_field_candidates(header: str, metadata: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    normalized = _normalize_header(header)
    candidates: dict[str, dict[str, Any]] = {}

    def register(target: str, confidence: str, source: str, **extra: Any) -> None:
        if not target or target == "unknown":
            return
        current = candidates.get(target)
        payload = {
            "targetField": target,
            "confidence": confidence,
            "source": source,
            **extra,
        }
        if current is None or _confidence_rank(confidence) > _confidence_rank(current.get("confidence", "")):
            candidates[target] = payload

    for target, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            if normalized == _normalize_header(alias):
                register(target, "high", "rule")

    for candidate in _semantic_field_candidates(header):
        register(
            str(candidate.get("targetField") or ""),
            str(candidate.get("confidence") or "low"),
            str(candidate.get("source") or "semantic_rule"),
            reason=_clean_text(candidate.get("reason")),
        )

    for candidate in _collect_metadata_field_candidates(header, metadata):
        register(
            str(candidate.get("targetField") or ""),
            str(candidate.get("confidence") or "low"),
            str(candidate.get("source") or "metadata"),
            score=int(candidate.get("score") or 0),
            reason=_clean_text(candidate.get("reason")),
            matchedText=_clean_text(candidate.get("matchedText")),
            models=list(candidate.get("models") or []),
            groups=list(candidate.get("groups") or []),
            direct=bool(candidate.get("direct")),
        )

    if not candidates:
        for target, aliases in FIELD_ALIASES.items():
            for alias in aliases:
                alias_token = _normalize_header(alias)
                if alias_token and len(alias_token) >= 5 and (alias_token in normalized or normalized in alias_token):
                    register(target, "medium", "rule")

    return sorted(
        candidates.values(),
        key=lambda item: (
            -int(item.get("score") or 0),
            -_confidence_rank(item.get("confidence", "")),
            not bool(item.get("direct")),
            item.get("targetField", ""),
        ),
    )


def _match_field_with_metadata(
    header: str,
    metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    candidates = _collect_field_candidates(header, metadata)
    if candidates:
        first = candidates[0]
        return _clean_text(first.get("targetField")) or "unknown", _clean_text(first.get("confidence")) or "low"
    return _match_field(header)


def _collect_value_choice_candidates(
    column_values: list[Any],
    type_template: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    # Header-agnostic mapping signal: if every distinct value in a column falls
    # within a choice attribute's allowed value/label set, that attribute is a
    # strong candidate regardless of how the source column is named. This
    # rescues AI-/human-renamed headers (e.g. "系统分类"->project_type) that no
    # alias table or lexical match would catch.
    if not type_template:
        return []
    distinct: list[str] = []
    seen: set[str] = set()
    for value in column_values:
        cleaned = _clean_text(value)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            distinct.append(cleaned)
    if not distinct:
        return []
    distinct_tokens = {_normalize_token(value) for value in distinct}

    matches: list[str] = []
    for definition in _attribute_definitions(type_template):
        if not definition.get("is_choice"):
            continue
        attr_name = _clean_text(definition.get("name"))
        if not attr_name:
            continue
        allowed: set[str] = set()
        for item in (definition.get("choices") or []):
            if not isinstance(item, dict):
                continue
            for key in ("value", "label"):
                token = _normalize_token(_clean_text(item.get(key)))
                if token:
                    allowed.add(token)
        if not allowed:
            continue
        if distinct_tokens <= allowed:
            matches.append(attr_name)

    ambiguous = len(matches) > 1
    confidence = "medium" if ambiguous else "high"
    return [
        {
            "targetField": attr_name,
            "confidence": confidence,
            "source": "value",
            "ambiguous": ambiguous,
        }
        for attr_name in matches
    ]


def _sheet_value_choice_mappings(
    *,
    headers: list[str],
    rows: list[dict[str, Any]],
    type_template: dict[str, Any] | None,
) -> dict[str, tuple[str, str]]:
    # Per-header strong value mapping: only an unambiguous single
    # choice-attribute match is treated as authoritative; ambiguous matches are
    # left to the normal heuristic/LLM flow to avoid mis-binding.
    if not type_template:
        return {}
    result: dict[str, tuple[str, str]] = {}
    for header in headers:
        values = [row.get(header) for row in rows]
        candidates = _collect_value_choice_candidates(values, type_template)
        if len(candidates) == 1 and candidates[0].get("confidence") == "high":
            result[header] = (
                _clean_text(candidates[0].get("targetField")),
                "high",
            )
    return result


def _merge_sheet_header_mapping(
    *,
    header: str,
    heuristic_mapping: tuple[str, str],
    llm_mapping: tuple[str, str],
) -> tuple[str, str]:
    heuristic_target, heuristic_confidence = heuristic_mapping
    llm_target, llm_confidence = llm_mapping
    if heuristic_target != "unknown" and heuristic_confidence == "high":
        return heuristic_mapping
    if llm_target == "unknown":
        return heuristic_mapping
    if heuristic_target != "unknown" and heuristic_target == llm_target:
        confidence_rank = {"low": 0, "medium": 1, "high": 2}
        return heuristic_mapping if confidence_rank.get(heuristic_confidence, 0) >= confidence_rank.get(llm_confidence, 0) else llm_mapping
    if heuristic_target != "unknown" and heuristic_confidence == "medium" and llm_confidence == "low":
        return heuristic_mapping
    return llm_mapping


def _mapping_effective_target_field(
    target_field: str,
    type_template: dict[str, Any] | None,
) -> str:
    cleaned_target = _clean_text(target_field)
    if cleaned_target in {"", "unknown"}:
        return ""
    if not type_template:
        return cleaned_target
    resolved = _resolve_import_target_key(
        type_template=type_template,
        canonical_field=cleaned_target,
    )
    return _clean_text(resolved) or cleaned_target


def _build_sheet_mapping_detail(
    *,
    header: str,
    heuristic_mapping: tuple[str, str],
    llm_mapping: tuple[str, str],
    metadata: dict[str, Any] | None = None,
    type_template: dict[str, Any] | None = None,
    value_mapping: tuple[str, str] | None = None,
) -> dict[str, Any]:
    # A strong (unambiguous) value-based match is the most reliable signal we
    # have: the column's own values fall within exactly one choice attribute's
    # allowed set, so it wins outright over header heuristics / LLM guesses.
    value_target, value_confidence = value_mapping or ("", "")
    if value_target not in {"", "unknown"} and value_confidence == "high":
        effective = _mapping_effective_target_field(
            value_target, type_template
        )
        return {
            "sourceField": header,
            "targetField": value_target,
            "suggestedTargetField": value_target,
            "confidence": "high",
            "status": "mapped",
            "resolvedBy": "value",
            "candidates": [
                {
                    "targetField": value_target,
                    "confidence": "high",
                    "source": "value",
                    "effectiveTargetField": effective,
                }
            ],
            "needsConfirmation": False,
            "message": "",
        }

    heuristic_target, heuristic_confidence = heuristic_mapping
    llm_target, llm_confidence = llm_mapping
    merged_target, merged_confidence = _merge_sheet_header_mapping(
        header=header,
        heuristic_mapping=heuristic_mapping,
        llm_mapping=llm_mapping,
    )
    candidates = _collect_field_candidates(header, metadata)
    candidate_map: dict[str, dict[str, Any]] = {
        item["targetField"]: dict(item)
        for item in candidates
        if _clean_text(item.get("targetField"))
    }
    if llm_target not in {"", "unknown"}:
        current = candidate_map.get(llm_target)
        llm_confidence_value = llm_confidence or "low"
        if current is None:
            candidate_map[llm_target] = {
                "targetField": llm_target,
                "confidence": llm_confidence_value,
                "source": "llm",
            }
        else:
            # Merge into the existing candidate instead of replacing it, so the
            # metadata candidate's ``direct`` flag (and score) survive when the
            # LLM happens to agree on the same target. Dropping ``direct`` here
            # caused a correct LLM agreement to re-expose the canonical shadow
            # and spuriously flag needs_confirmation.
            if _confidence_rank(llm_confidence_value) > _confidence_rank(
                str(current.get("confidence", ""))
            ):
                current["confidence"] = llm_confidence_value
            current["source"] = (
                f"{current.get('source', 'metadata')}+llm"
            )
    # An ambiguous value match (column values fit several choice attributes) is
    # surfaced as a candidate so the operator can disambiguate instead of the
    # value being silently dropped.
    if (
        value_target not in {"", "unknown"}
        and value_confidence
        and value_confidence != "high"
    ):
        current = candidate_map.get(value_target)
        value_payload = {
            "targetField": value_target,
            "confidence": value_confidence,
            "source": "value",
        }
        current_rank = (
            _confidence_rank(str(current.get("confidence", "")))
            if current
            else -1
        )
        if _confidence_rank(value_confidence) > current_rank:
            candidate_map[value_target] = value_payload

    ordered_candidates = sorted(
        candidate_map.values(),
        key=lambda item: (-_confidence_rank(str(item.get("confidence", ""))), str(item.get("targetField", ""))),
    )
    for item in ordered_candidates:
        item["effectiveTargetField"] = _mapping_effective_target_field(
            str(item.get("targetField") or ""),
            type_template,
        )
    strong_rule_targets = {
        str(item.get("targetField", ""))
        for item in ordered_candidates
        if item.get("source") == "rule" and _confidence_rank(str(item.get("confidence", ""))) >= 1
    }
    strong_effective_targets = {
        _clean_text(item.get("effectiveTargetField"))
        for item in ordered_candidates
        if _confidence_rank(str(item.get("confidence", ""))) >= 1
        and _clean_text(item.get("effectiveTargetField"))
    }
    # A strong *direct* candidate is a concrete model attribute. Canonical
    # buckets that merely echo the same attribute alias (e.g. db_type's alias
    # "数据库类型" leaking into the generic ci_type bucket) must not manufacture
    # a phantom conflict, so when a direct candidate is present only direct
    # candidates count toward ambiguity, and a sole direct match owns the
    # column.
    strong_direct = [
        item
        for item in ordered_candidates
        if _confidence_rank(str(item.get("confidence", ""))) >= 1
        and item.get("direct")
        and _clean_text(item.get("effectiveTargetField"))
    ]
    strong_direct_targets = {
        _clean_text(item.get("effectiveTargetField")) for item in strong_direct
    }
    if strong_direct_targets:
        competing_targets = strong_direct_targets
    else:
        competing_targets = strong_effective_targets
    dominant_direct = (
        strong_direct[0]
        if len(strong_direct_targets) == 1
        else None
    )
    llm_is_strong = llm_target not in {"", "unknown"} and _confidence_rank(llm_confidence) >= 1
    heuristic_effective_target = _mapping_effective_target_field(heuristic_target, type_template)
    llm_effective_target = _mapping_effective_target_field(llm_target, type_template)
    needs_confirmation = False
    if len(competing_targets) >= 2:
        needs_confirmation = True
    elif len(strong_rule_targets) >= 2 and len(competing_targets) > 1:
        needs_confirmation = True
    elif (
        not dominant_direct
        and heuristic_target not in {"", "unknown"}
        and llm_target not in {"", "unknown", heuristic_target}
        and _confidence_rank(heuristic_confidence) >= 1
        and llm_is_strong
        and heuristic_effective_target != llm_effective_target
    ):
        needs_confirmation = True

    if dominant_direct and not needs_confirmation:
        # The single strong concrete attribute wins outright over any
        # canonical-bucket shadow or weaker heuristic/LLM guess.
        merged_target = (
            _clean_text(dominant_direct.get("targetField")) or merged_target
        )
        merged_confidence = (
            _clean_text(dominant_direct.get("confidence")) or merged_confidence
        )

    low_confidence_unmapped = (
        not needs_confirmation
        and merged_target not in {"", "unknown"}
        and _confidence_rank(merged_confidence) <= 0
    )
    applied_target = "" if (needs_confirmation or low_confidence_unmapped) else merged_target
    status = (
        "needs_confirmation"
        if needs_confirmation
        else "unmapped"
        if low_confidence_unmapped or applied_target in {"", "unknown"}
        else "mapped"
    )
    message = ""
    if needs_confirmation:
        candidate_text = " / ".join(
            item.get("targetField", "")
            for item in ordered_candidates
            if _clean_text(item.get("targetField"))
        )
        message = f"字段 {header} 同时匹配多个语义候选：{candidate_text}，需人工确认后再决定是否写入"
    elif low_confidence_unmapped:
        message = f"字段 {header} 当前只有低置信候选 {merged_target}，不会自动写入，请人工确认"
    elif applied_target not in {"", "unknown"} and llm_target == applied_target and heuristic_target in {"", "unknown"}:
        message = f"字段 {header} 当前由 LLM 提供候选语义 {applied_target}"
    elif status == "unmapped":
        # No candidate at all: make the silent drop explicit so the operator
        # can see this source column will not be written into the CMDB.
        message = f"字段 {header} 未匹配到任何目标字段，本列数据不会写入 CMDB，请人工确认"

    return {
        "sourceField": header,
        "targetField": applied_target or "unknown",
        "suggestedTargetField": merged_target or "unknown",
        "confidence": merged_confidence or "low",
        "status": status,
        "resolvedBy": "rule" if (applied_target == heuristic_target and heuristic_target not in {"", "unknown"}) else "llm" if applied_target not in {"", "unknown"} else "",
        "candidates": ordered_candidates,
        "needsConfirmation": needs_confirmation,
        "message": message,
    }


def _sheet_name_hint(sheet_name: str, alias_index: dict[str, str]) -> str:
    normalized = _normalize_ci_type(sheet_name, alias_index)
    return "" if normalized == sheet_name else normalized


def _sample_sheet_rows(rows: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    sampled: list[dict[str, Any]] = []
    if len(rows) <= limit:
        candidate_rows = rows
    else:
        middle_index = max(0, len(rows) // 2)
        tail_count = max(1, limit - 3)
        candidate_rows = [
            *rows[:2],
            rows[middle_index],
            *rows[-tail_count:],
        ]
    seen_rows: set[str] = set()
    for row in candidate_rows:
        fingerprint = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
        if fingerprint in seen_rows:
            continue
        seen_rows.add(fingerprint)
        sampled.append(
            {
                key: _clean_text(value)
                for key, value in row.items()
                if key != "_sheet" and _clean_text(value)
            }
        )
    return sampled


def _should_skip_llm_for_sheet(
    *,
    heuristic_plan: SheetMappingPlan,
    headers: list[str],
) -> bool:
    if heuristic_plan.sheet_kind in {"relation", "note"}:
        return True
    if heuristic_plan.sheet_kind != "asset":
        return False
    if not headers:
        return True

    details = heuristic_plan.mapping_details or {}
    mapped_count = 0
    high_count = 0
    value_field_hits = 0
    for header in headers:
        detail = details.get(header) or {}
        target_field = _clean_text(detail.get("targetField"))
        confidence = _clean_text(detail.get("confidence"))
        status = _clean_text(detail.get("status"))
        if status == "mapped" and target_field not in {"", "unknown"}:
            mapped_count += 1
        if confidence == "high" and status == "mapped" and target_field not in {"", "unknown"}:
            high_count += 1
        if target_field in RESOURCE_VALUE_FIELDS:
            value_field_hits += 1

    if mapped_count != len(headers):
        return False
    if high_count != len(headers):
        return False
    if value_field_hits <= 0:
        return False
    return True


def _semantic_keyword_in_text(keyword: str, raw_text: str, normalized_text: str) -> bool:
    normalized_keyword = _normalize_token(keyword)
    if not normalized_keyword:
        return False
    if normalized_keyword.isascii() and len(normalized_keyword) <= 2:
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(normalized_keyword)}(?![a-z0-9])", raw_text.lower()))
    return normalized_keyword in normalized_text


COMMON_MODEL_ATTRIBUTE_HINTS = {
    _normalize_token(value)
    for value in (
        "name",
        "名称",
        "status",
        "状态",
        "private_ip",
        "ip",
        "manage_ip",
        "version",
        "service_port",
        "project",
        "platform",
        "owner",
    )
}


def _sample_structure_records(records: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    if not records:
        return []
    if len(records) <= limit:
        candidate_records = records
    else:
        middle_index = max(0, len(records) // 2)
        candidate_records = [records[0], records[middle_index], records[-1]]

    preferred_order = {
        "name": 0,
        "ci_type": 1,
        "private_ip": 2,
        "service_port": 3,
        "host_name": 4,
        "deploy_target": 5,
        "description": 6,
    }
    sampled: list[dict[str, Any]] = []
    seen_rows: set[str] = set()
    for record in candidate_records:
        analysis_attributes = record.get("analysisAttributes") or {}
        cleaned_items = [
            (key, _clean_text(value))
            for key, value in analysis_attributes.items()
            if key and not str(key).startswith("_") and _clean_text(value)
        ]
        cleaned_items.sort(key=lambda item: (preferred_order.get(item[0], 50), item[0]))
        payload = dict(cleaned_items[:12])
        fingerprint = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if not payload or fingerprint in seen_rows:
            continue
        seen_rows.add(fingerprint)
        sampled.append(payload)
    return sampled


def _build_ci_type_catalog(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    ci_type_groups = [
        _normalize_group_snapshot(item)
        for item in (metadata.get("ciTypeGroups") or [])
        if isinstance(item, dict)
    ]
    if not ci_type_groups:
        ci_type_groups = _build_default_ci_type_groups(metadata.get("ciTypes") or DEFAULT_MODEL_TEMPLATES)

    groups_by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for group in ci_type_groups:
        for ci_type in group.get("ciTypes") or []:
            name = _clean_text(ci_type.get("name"))
            if not name:
                continue
            groups_by_model[name].append(group)

    catalog: list[dict[str, Any]] = []
    for item in (metadata.get("ciTypes") or DEFAULT_MODEL_TEMPLATES):
        if not isinstance(item, dict):
            continue
        name = _clean_text(item.get("name"))
        if not name:
            continue
        group_names = [
            _clean_text(group.get("name"))
            for group in groups_by_model.get(name, [])
            if _clean_text(group.get("name"))
        ]
        fallback_group = DEFAULT_GROUP_HINTS.get(name, "")
        if fallback_group and fallback_group not in group_names:
            group_names.append(fallback_group)
        parent_types = [
            {
                "name": _clean_text(parent.get("name")),
                "alias": _clean_text(parent.get("alias")) or _clean_text(parent.get("name")),
            }
            for parent in (item.get("parentTypes") or [])
            if isinstance(parent, dict) and _clean_text(parent.get("name"))
        ]
        attribute_definitions = [
            definition
            for definition in (item.get("attributeDefinitions") or [])
            if isinstance(definition, dict) and _clean_text(definition.get("name"))
        ]
        attribute_names = _dedupe_non_empty(
            [_clean_text(definition.get("name")) for definition in attribute_definitions],
            limit=24,
        )
        attribute_aliases = _dedupe_non_empty(
            [
                _clean_text(definition.get("alias")) or _clean_text(definition.get("name"))
                for definition in attribute_definitions
            ],
            limit=24,
        )
        catalog.append(
            {
                "id": item.get("id"),
                "name": name,
                "alias": _clean_text(item.get("alias")) or name,
                "groupNames": group_names,
                "groupName": group_names[0] if group_names else "",
                "attributes": [str(attr) for attr in (item.get("attributes") or []) if _clean_text(attr)],
                "attributeNames": attribute_names,
                "attributeAliases": attribute_aliases,
                "attributeTexts": _dedupe_non_empty([*attribute_names, *attribute_aliases], limit=24),
                "parentTypes": parent_types,
            }
        )
    return catalog


def _collect_structure_context(group: dict[str, Any]) -> dict[str, Any]:
    records = group.get("records") or []
    raw_type_hints = _collect_raw_type_hints(records)
    sampled_records = _sample_structure_records(records)
    source_fields: list[str] = []
    field_names: list[str] = []
    sample_values: list[str] = []
    ports: list[str] = []

    for record in records[: min(len(records), 5)]:
        analysis_attributes = record.get("analysisAttributes") or {}
        for key, value in analysis_attributes.items():
            cleaned_key = _clean_text(key)
            cleaned_value = _clean_text(value)
            if cleaned_key and not cleaned_key.startswith("_") and cleaned_key not in field_names:
                field_names.append(cleaned_key)
            if cleaned_value and len(sample_values) < 20 and cleaned_value not in sample_values:
                sample_values.append(cleaned_value)
            if cleaned_key == "service_port" and cleaned_value and cleaned_value not in ports:
                ports.append(cleaned_value)
        for item in (record.get("mapping") or []):
            source_field = _clean_text(item.get("sourceField"))
            if source_field and source_field not in source_fields:
                source_fields.append(source_field)

    texts = [
        _clean_text(group.get("ciType")),
        _clean_text(group.get("label")),
        *raw_type_hints,
    ]
    return {
        "resourceCiType": _clean_text(group.get("ciType")),
        "resourceLabel": _clean_text(group.get("label")),
        "rawTypeHints": raw_type_hints,
        "primaryTexts": [item for item in texts if item],
        "texts": [item for item in texts if item],
        "fieldNames": field_names,
        "sourceFields": source_fields,
        "sampleValues": sample_values,
        "ports": ports,
        "sampleRecords": sampled_records,
    }


def _candidate_rule_names(candidate: dict[str, Any]) -> set[str]:
    candidate_name = _clean_text(candidate.get("name"))
    candidate_alias = _clean_text(candidate.get("alias"))
    texts = [
        candidate_name,
        candidate_alias,
        *[str(item) for item in (candidate.get("groupNames") or []) if _clean_text(item)],
        *[str(item) for item in (candidate.get("attributes") or []) if _clean_text(item)],
        *[str(item) for item in (candidate.get("attributeTexts") or []) if _clean_text(item)],
        *[
            _clean_text(parent.get("name")) or _clean_text(parent.get("alias"))
            for parent in (candidate.get("parentTypes") or [])
            if isinstance(parent, dict)
        ],
    ]
    normalized_texts = [(_clean_text(text).lower(), _normalize_token(text)) for text in texts if _clean_text(text)]
    field_names = {
        _normalize_header(str(item))
        for item in [*(candidate.get("attributes") or []), *(candidate.get("attributeTexts") or [])]
        if _clean_text(item)
    }
    matched: set[str] = set()
    for rule in SEMANTIC_MODEL_RULES:
        if candidate_name in set(rule.get("preferred_models") or []):
            matched.add(str(rule["name"]))
            continue
        keyword_hit = any(
            _semantic_keyword_in_text(keyword, raw_text, normalized_text)
            for keyword in (rule.get("keywords") or [])
            for raw_text, normalized_text in normalized_texts
        )
        field_hit = any(
            _normalize_header(keyword) in field_names
            for keyword in (rule.get("field_keywords") or [])
        )
        if keyword_hit or field_hit:
            matched.add(str(rule["name"]))
    return matched


def _match_semantic_rule(rule: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    primary_text_hits: list[str] = []
    sample_value_hits: list[str] = []
    field_hits: list[str] = []
    port_hits: list[str] = []
    normalized_primary_texts = [
        (_clean_text(text).lower(), _normalize_token(text))
        for text in (context.get("primaryTexts") or [])
        if _clean_text(text)
    ]
    normalized_sample_value_texts = [
        (_clean_text(text).lower(), _normalize_token(text))
        for text in (context.get("sampleValues") or [])
        if _clean_text(text)
    ]
    normalized_fields = {
        _normalize_header(str(field))
        for field in [*context.get("fieldNames", []), *context.get("sourceFields", [])]
        if _clean_text(field)
    }
    for keyword in (rule.get("keywords") or []):
        if any(
            _semantic_keyword_in_text(keyword, raw_text, normalized_text)
            for raw_text, normalized_text in normalized_primary_texts
        ):
            primary_text_hits.append(str(keyword))
            continue
        if any(
            _semantic_keyword_in_text(keyword, raw_text, normalized_text)
            for raw_text, normalized_text in normalized_sample_value_texts
        ):
            sample_value_hits.append(str(keyword))
    for keyword in (rule.get("field_keywords") or []):
        if _normalize_header(keyword) in normalized_fields:
            field_hits.append(str(keyword))
    for port in (rule.get("port_values") or []):
        if str(port) in {str(item) for item in context.get("ports", []) if _clean_text(item)}:
            port_hits.append(str(port))

    score = 0
    if primary_text_hits:
        score += 32 + min(16, (len(set(primary_text_hits)) - 1) * 4)
    if sample_value_hits:
        score += 8 + min(6, (len(set(sample_value_hits)) - 1) * 3)
    if field_hits:
        score += 10 + min(8, (len(set(field_hits)) - 1) * 4)
    if port_hits:
        score += 18
    max_score = 72 if rule.get("specific") else 56
    score = min(score, max_score)

    reasons: list[str] = []
    if primary_text_hits:
        reasons.append(f"原文类型命中 {', '.join(sorted(set(primary_text_hits))[:3])}")
    if sample_value_hits:
        reasons.append(f"样例值命中 {', '.join(sorted(set(sample_value_hits))[:3])}")
    if field_hits:
        reasons.append(f"字段特征命中 {', '.join(sorted(set(field_hits))[:3])}")
    if port_hits:
        reasons.append(f"端口特征命中 {', '.join(sorted(set(port_hits))[:2])}")
    return {
        "score": score,
        "reason": "；".join(reasons),
    }


def _semantic_lexical_score(candidate: dict[str, Any], texts: list[str]) -> tuple[int, str]:
    candidate_texts: list[tuple[str, str]] = []
    for value in [
        _clean_text(candidate.get("name")),
        _clean_text(candidate.get("alias")),
    ]:
        if value:
            candidate_texts.append((value, "identity"))
    for value in candidate.get("groupNames") or []:
        cleaned = _clean_text(value)
        if cleaned:
            candidate_texts.append((cleaned, "group"))
    for item in candidate.get("parentTypes") or []:
        if not isinstance(item, dict):
            continue
        for value in [_clean_text(item.get("name")), _clean_text(item.get("alias"))]:
            if value:
                candidate_texts.append((value, "parent"))
    for value in candidate.get("attributeTexts") or []:
        cleaned = _clean_text(value)
        if not cleaned or _normalize_token(cleaned) in COMMON_MODEL_ATTRIBUTE_HINTS:
            continue
        candidate_texts.append((cleaned, "attribute"))

    best_score = 0
    best_reason = ""
    for text in texts:
        cleaned_text = _clean_text(text)
        if not cleaned_text:
            continue
        for candidate_text, text_kind in candidate_texts:
            raw_score, reason = _semantic_text_similarity(cleaned_text, candidate_text)
            if raw_score <= 0:
                continue
            if text_kind == "identity":
                score = raw_score
                semantic_reason = reason or f"资源提示与模型 {candidate_text} 匹配"
            elif text_kind == "group":
                score = min(raw_score, 28)
                semantic_reason = reason or f"资源提示与分组 {candidate_text} 匹配"
            elif text_kind == "parent":
                score = min(raw_score, 24)
                semantic_reason = reason or f"资源提示与父模型 {candidate_text} 匹配"
            else:
                score = min(raw_score, 20)
                semantic_reason = reason or f"资源提示与属性 {candidate_text} 匹配"

            if score > best_score:
                best_score = score
                best_reason = semantic_reason
    return best_score, best_reason


def _semantic_confidence(best_score: int, second_score: int) -> str:
    if best_score >= 88 or (best_score >= 72 and best_score - second_score >= 12):
        return "high"
    if best_score >= 50:
        return "medium"
    return "low"


def _has_clear_low_confidence_leader(plan: SemanticModelPlan) -> bool:
    candidates = list(plan.candidates or [])
    if not candidates:
        return False
    best_score = int(candidates[0].get("score") or 0)
    second_score = int(candidates[1].get("score") or 0) if len(candidates) > 1 else 0
    if best_score >= 36 and best_score - second_score >= 8:
        return True
    if best_score >= 42:
        return True
    return False


def _heuristic_semantic_model_candidates(
    group: dict[str, Any],
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    context = _collect_structure_context(group)
    catalog = _build_ci_type_catalog(metadata)
    rule_results = {
        str(rule["name"]): _match_semantic_rule(rule, context)
        for rule in SEMANTIC_MODEL_RULES
    }
    raw_type_hints = context.get("rawTypeHints") or []
    generic_server_hint = _is_generic_server_hint(raw_type_hints)
    middleware_or_data_family_score = max(
        int((rule_results.get(rule_name) or {}).get("score") or 0)
        for rule_name in ("database", "mysql", "PostgreSQL", "redis", "Kafka", "elasticsearch", "nginx", "apache")
    )
    ranked_candidates: list[dict[str, Any]] = []

    for candidate in catalog:
        candidate_name = _clean_text(candidate.get("name"))
        lexical_score, lexical_reason = _semantic_lexical_score(candidate, context.get("texts", []))
        score = lexical_score
        reasons = [lexical_reason] if lexical_reason else []
        matched_rules = _candidate_rule_names(candidate)
        matched_specific_rules = {
            rule_name
            for rule_name in matched_rules
            if next((rule for rule in SEMANTIC_MODEL_RULES if rule["name"] == rule_name and rule.get("specific")), None)
        }
        for rule_name in matched_rules:
            result = rule_results.get(rule_name) or {}
            rule_score = int(result.get("score") or 0)
            if not rule_score:
                continue
            score += rule_score
            if result.get("reason"):
                reasons.append(str(result["reason"]))

        if candidate_name == "database" and any(
            int((rule_results.get(rule_name) or {}).get("score") or 0) >= 40
            for rule_name in ("mysql", "PostgreSQL")
        ):
            score -= 10
        if candidate_name in {"mysql", "PostgreSQL"} and not any(
            int((rule_results.get(rule_name) or {}).get("score") or 0) >= 30 for rule_name in matched_specific_rules
        ) and int((rule_results.get("database") or {}).get("score") or 0) >= 30:
            score -= 8
        if candidate_name == "kubernetes" and int((rule_results.get("docker") or {}).get("score") or 0) >= 28:
            score -= 10
        if candidate_name == "docker" and int((rule_results.get("kubernetes") or {}).get("score") or 0) >= 28:
            score -= 10
        if candidate_name in {"docker", "kubernetes"} and middleware_or_data_family_score >= 28:
            score -= 22
            reasons.append("同时存在更强的中间件/数据库语义")
        if generic_server_hint and candidate_name in {"PhysicalMachine", "vserver"}:
            score += 18
            reasons.append("原始类型只表达通用服务器语义")

        if score <= 0:
            continue

        ranked_candidates.append(
            {
                "id": candidate.get("id"),
                "name": candidate_name,
                "alias": _clean_text(candidate.get("alias")) or candidate_name,
                "groupName": _clean_text(candidate.get("groupName")),
                "groupNames": candidate.get("groupNames") or [],
                "existing": True,
                "score": score,
                "reason": "；".join(dict.fromkeys([item for item in reasons if item])),
            }
        )

    ranked_candidates.sort(
        key=lambda item: (
            -int(item.get("score") or 0),
            _clean_text(item.get("name")) not in SEMANTIC_REFINEMENT_MODELS,
            _clean_text(item.get("name")),
        )
    )
    if not ranked_candidates:
        return []

    best_score = int(ranked_candidates[0].get("score") or 0)
    second_score = int(ranked_candidates[1].get("score") or 0) if len(ranked_candidates) > 1 else 0
    for index, item in enumerate(ranked_candidates):
        current_score = int(item.get("score") or 0)
        base_confidence = _semantic_confidence(current_score, second_score if index == 0 else best_score)
        if index > 0 and current_score + 8 < best_score:
            base_confidence = "low"
        item["confidence"] = base_confidence
    return ranked_candidates[:6]


def _build_heuristic_semantic_plan(
    group: dict[str, Any],
    metadata: dict[str, Any],
) -> SemanticModelPlan:
    candidates = _heuristic_semantic_model_candidates(group, metadata)
    if not candidates:
        return SemanticModelPlan(
            best_model="",
            confidence="low",
            reason="未根据现有语义线索匹配到稳定的系统模型。",
            candidates=[],
            source="heuristic",
        )
    best_candidate = candidates[0]
    return SemanticModelPlan(
        best_model=_clean_text(best_candidate.get("name")),
        confidence=_clean_text(best_candidate.get("confidence")) or "low",
        reason=_clean_text(best_candidate.get("reason")) or "启发式语义推断",
        candidates=candidates,
        source="heuristic",
    )


def _build_semantic_model_prompt(
    *,
    group: dict[str, Any],
    metadata: dict[str, Any],
    heuristic_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    context = _collect_structure_context(group)
    ci_type_meta = {
        _clean_text(item.get("name")): item
        for item in (metadata.get("ciTypes") or [])
        if isinstance(item, dict) and _clean_text(item.get("name"))
    }
    candidate_models = []
    for candidate in heuristic_candidates[:6]:
        model_meta = ci_type_meta.get(_clean_text(candidate.get("name"))) or {}
        candidate_models.append(
            {
                "name": _clean_text(candidate.get("name")),
                "alias": _clean_text(candidate.get("alias")),
                "group_name": _clean_text(candidate.get("groupName")),
                "attributes": [
                    str(item)
                    for item in (
                        (model_meta.get("attributeTexts") or [])
                        or (model_meta.get("attributes") or [])
                    )
                    if _clean_text(item)
                ][:12],
                "parent_types": [
                    _clean_text(item.get("alias")) or _clean_text(item.get("name"))
                    for item in (model_meta.get("parentTypes") or [])
                    if isinstance(item, dict) and (_clean_text(item.get("alias")) or _clean_text(item.get("name")))
                ],
                "heuristic_score": int(candidate.get("score") or 0),
                "heuristic_reason": _clean_text(candidate.get("reason")),
            }
        )
    return {
        "resource_label": context.get("resourceLabel"),
        "normalized_ci_type": context.get("resourceCiType"),
        "raw_type_hints": context.get("rawTypeHints"),
        "observed_fields": list(dict.fromkeys([*context.get("fieldNames", []), *context.get("sourceFields", [])]))[:20],
        "sample_records": context.get("sampleRecords"),
        "candidate_models": candidate_models,
        "rules": [
            "只能从 candidate_models 中选择，不允许创建新模型。",
            "优先复用现有模型；如果线索只支持数据库/容器/服务器等通用语义，不要强行指定到过细模型。",
            "结合原始类型提示、字段名、端口、样例值、候选模型分组/属性/父模型一起判断。",
            "返回 1-3 个候选，按最可能顺序排序。",
            "如果没有合适候选，best_model 留空，confidence 返回 low。",
        ],
        "output_schema": {
            "best_model": "string",
            "confidence": "high|medium|low",
            "reason": "string",
            "candidates": [
                {
                    "model": "string",
                    "confidence": "high|medium|low",
                    "reason": "string",
                }
            ],
        },
    }


def _parse_semantic_model_plan(
    result: Any,
    *,
    heuristic_candidates: list[dict[str, Any]],
) -> SemanticModelPlan:
    candidate_index = {
        _clean_text(item.get("name")): item
        for item in heuristic_candidates
        if _clean_text(item.get("name"))
    }
    ranked_candidates: list[dict[str, Any]] = []
    for raw_candidate in result.get("candidates", []) or []:
        model_name = _clean_text(raw_candidate.get("model"))
        if not model_name or model_name not in candidate_index:
            continue
        base_candidate = dict(candidate_index[model_name])
        base_candidate["confidence"] = _clean_text(raw_candidate.get("confidence")) or _clean_text(base_candidate.get("confidence")) or "low"
        if _clean_text(raw_candidate.get("reason")):
            base_candidate["reason"] = _clean_text(raw_candidate.get("reason"))
        ranked_candidates.append(base_candidate)
    for candidate in heuristic_candidates:
        candidate_name = _clean_text(candidate.get("name"))
        if candidate_name and all(_clean_text(item.get("name")) != candidate_name for item in ranked_candidates):
            ranked_candidates.append(dict(candidate))

    best_model = _clean_text(result.get("best_model"))
    if best_model not in candidate_index:
        best_model = _clean_text(ranked_candidates[0].get("name")) if ranked_candidates else ""
    confidence = _clean_text(result.get("confidence")) or (
        _clean_text(candidate_index.get(best_model, {}).get("confidence")) if best_model else "low"
    )
    reason = _clean_text(result.get("reason")) or (
        _clean_text(candidate_index.get(best_model, {}).get("reason")) if best_model else "LLM 未返回明确原因"
    )
    return SemanticModelPlan(
        best_model=best_model,
        confidence=confidence or "low",
        reason=reason,
        candidates=ranked_candidates[:6],
        source="llm",
    )


def _should_run_semantic_inference(resource_ci_type: str, exact_groups: list[dict[str, Any]], raw_type_hints: list[str]) -> bool:
    if resource_ci_type == "unknown":
        return True
    if not exact_groups:
        return True
    if resource_ci_type in SEMANTIC_REFINEMENT_MODELS:
        return True
    return _is_generic_server_hint(raw_type_hints)


async def _infer_semantic_model_plan(
    *,
    group: dict[str, Any],
    metadata: dict[str, Any],
    llm_client: Any | None,
) -> SemanticModelPlan:
    heuristic_plan = _build_heuristic_semantic_plan(group, metadata)
    heuristic_candidates = heuristic_plan.candidates or []
    if not llm_client or not heuristic_candidates or heuristic_plan.confidence == "high":
        return heuristic_plan

    prompt = _build_semantic_model_prompt(
        group=group,
        metadata=metadata,
        heuristic_candidates=heuristic_candidates,
    )
    try:
        record_count = int(group.get("count") or len(group.get("records") or []))
        timeout_seconds = min(
            max(45.0, RESOURCE_IMPORT_LLM_STEP_TIMEOUT_SECONDS / 3.0 + record_count * 2.0),
            max(60.0, RESOURCE_IMPORT_LLM_STEP_TIMEOUT_MAX_SECONDS / 2.0),
        )
        last_exception: Exception | None = None
        for attempt in range(RESOURCE_IMPORT_LLM_RETRY_COUNT):
            try:
                result = await asyncio.wait_for(
                    llm_client.infer_resource_model(
                        prompt=prompt,
                    ),
                    timeout=timeout_seconds,
                )
                if isinstance(result, SemanticModelPlan):
                    return result
                return _parse_semantic_model_plan(result, heuristic_candidates=heuristic_candidates)
            except asyncio.TimeoutError as exc:
                last_exception = exc
                if attempt >= RESOURCE_IMPORT_LLM_RETRY_COUNT - 1:
                    raise
                sleep_seconds = _llm_retry_sleep_seconds_for_error(exc, attempt + 1)
                if sleep_seconds > 0:
                    await asyncio.sleep(sleep_seconds)
            except Exception as exc:
                last_exception = exc
                if attempt >= RESOURCE_IMPORT_LLM_RETRY_COUNT - 1 or not _should_retry_llm_mapping(exc):
                    raise
                sleep_seconds = _llm_retry_sleep_seconds_for_error(exc, attempt + 1)
                if sleep_seconds > 0:
                    await asyncio.sleep(sleep_seconds)
        if last_exception is not None:
            raise last_exception
    except Exception:
        return heuristic_plan


def _sheet_llm_timeout_seconds(*, row_count: int, header_count: int) -> float:
    base_timeout = max(RESOURCE_IMPORT_LLM_STEP_TIMEOUT_SECONDS, 30.0)
    scaled_timeout = base_timeout + max(0.0, header_count - 12) * 6.0 + max(0.0, row_count - 20) * 0.6
    return min(max(base_timeout, scaled_timeout), RESOURCE_IMPORT_LLM_STEP_TIMEOUT_MAX_SECONDS)


def _looks_like_note_sheet(sheet_name: str, headers: list[str]) -> bool:
    normalized_sheet_name = _clean_text(sheet_name)
    if any(token in normalized_sheet_name for token in EXCLUDED_SHEET_KEYWORDS):
        return True
    normalized_headers = {_normalize_header(header) for header in headers}
    note_header_groups = [
        {"测试点", "说明"},
        {"说明", "备注"},
    ]
    for group in note_header_groups:
        if all(_normalize_header(item) in normalized_headers for item in group):
            return True
    return False


def _looks_like_relation_sheet(sheet_name: str, headers: list[str]) -> bool:
    normalized_sheet_name = _clean_text(sheet_name).lower()
    if any(token in normalized_sheet_name for token in RELATION_SHEET_KEYWORDS):
        return True

    matched_fields = {
        _match_relation_field(header)[0]
        for header in headers
        if _match_relation_field(header)[0] != "unknown"
    }
    if {"source_value", "target_value"} <= matched_fields:
        return True
    if {"source_model", "target_model"} <= matched_fields and (
        "relation_type" in matched_fields or "source_value" in matched_fields or "target_value" in matched_fields
    ):
        return True
    return False


def _row_has_relation_signal(fields: dict[str, Any]) -> bool:
    source_value = _clean_text(fields.get("source_value"))
    target_value = _clean_text(fields.get("target_value"))
    if source_value and target_value:
        return True
    return False


def _normalize_relation_type(value: str) -> str:
    cleaned = _clean_text(value)
    if not cleaned:
        return ""
    normalized = _normalize_token(cleaned)
    for relation_type, aliases in RELATION_TYPE_ALIASES.items():
        if normalized == _normalize_token(relation_type):
            return relation_type
        for alias in aliases:
            if normalized == _normalize_token(alias):
                return relation_type
    return cleaned


async def _resolve_sheet_mapping_plan(
    *,
    sheet_name: str,
    rows: list[dict[str, Any]],
    alias_index: dict[str, str],
    model_templates: list[dict[str, Any]],
    metadata: dict[str, Any] | None,
    llm_client: Any | None,
    retry_count_override: int | None = None,
) -> tuple[SheetMappingPlan, str]:
    headers = sorted({key for row in rows for key in row.keys() if key != "_sheet"})
    type_template_map = {
        _clean_text(item.get("name")): item
        for item in model_templates
        if isinstance(item, dict) and _clean_text(item.get("name"))
    }
    sheet_timeout_seconds = _sheet_llm_timeout_seconds(
        row_count=len(rows),
        header_count=len(headers),
    )
    retry_timeout_seconds = min(
        RESOURCE_IMPORT_LLM_STEP_TIMEOUT_MAX_SECONDS,
        max(sheet_timeout_seconds + 15.0, sheet_timeout_seconds * 1.25),
    )
    default_ci_type = _sheet_name_hint(sheet_name, alias_index)
    heuristic_sheet_kind = (
        "note"
        if _looks_like_note_sheet(sheet_name, headers)
        else "relation"
        if _looks_like_relation_sheet(sheet_name, headers)
        else "asset"
    )
    heuristic_mappings = {
        header: (
            _match_relation_field(header)
            if heuristic_sheet_kind == "relation"
            else _match_field_with_metadata(header, metadata)
        )
        for header in headers
    }
    heuristic_value_mappings = _sheet_value_choice_mappings(
        headers=headers,
        rows=rows,
        type_template=type_template_map.get(default_ci_type),
    )
    heuristic_plan = SheetMappingPlan(
        sheet_kind=heuristic_sheet_kind,
        default_ci_type=default_ci_type,
        mappings=heuristic_mappings,
        reason="规则映射",
        mapping_details={
            header: _build_sheet_mapping_detail(
                header=header,
                heuristic_mapping=heuristic_mappings.get(header, ("unknown", "low")),
                llm_mapping=("unknown", "low"),
                metadata=metadata,
                type_template=type_template_map.get(default_ci_type),
                value_mapping=heuristic_value_mappings.get(header),
            )
            for header in headers
        },
    )

    if not llm_client or heuristic_sheet_kind in {"relation", "note"}:
        return heuristic_plan, "规则映射"

    if _should_skip_llm_for_sheet(
        heuristic_plan=heuristic_plan,
        headers=headers,
    ):
        return heuristic_plan, "规则映射（高置信直出）"

    try:
        llm_plan = None
        last_exception: Exception | None = None
        retry_count = max(1, int(retry_count_override or RESOURCE_IMPORT_LLM_RETRY_COUNT))
        field_candidate_catalog = {
            header: [
                {
                    "targetField": _clean_text(item.get("targetField")),
                    "confidence": _clean_text(item.get("confidence")) or "low",
                    "source": _clean_text(item.get("source")),
                    "reason": _clean_text(item.get("reason")),
                    "matchedText": _clean_text(item.get("matchedText")),
                    "models": list(item.get("models") or []),
                    "groups": list(item.get("groups") or []),
                }
                for item in _collect_field_candidates(header, metadata)[:6]
            ]
            for header in headers
        }
        ci_type_catalog = [
            {
                "name": _clean_text(item.get("name")),
                "alias": _clean_text(item.get("alias")),
                "groupNames": list(item.get("groupNames") or []),
                "attributeTexts": list(item.get("attributeTexts") or [])[:10],
                "parentTypes": [
                    _clean_text(parent.get("alias")) or _clean_text(parent.get("name"))
                    for parent in (item.get("parentTypes") or [])
                    if isinstance(parent, dict)
                ][:4],
            }
            for item in (metadata.get("semanticModelCatalog") or [])
            if isinstance(item, dict) and _clean_text(item.get("name"))
        ][:80]
        for attempt in range(retry_count):
            try:
                current_timeout_seconds = sheet_timeout_seconds if attempt == 0 else retry_timeout_seconds
                llm_plan = await asyncio.wait_for(
                    llm_client.map_sheet_headers(
                        sheet_name=sheet_name,
                        headers=headers,
                        sample_rows=_sample_sheet_rows(rows),
                        ci_types=[str(item.get("name") or "") for item in model_templates if item.get("name")],
                        field_candidates=field_candidate_catalog,
                        ci_type_catalog=ci_type_catalog,
                    ),
                    timeout=current_timeout_seconds,
                )
                break
            except asyncio.TimeoutError:
                last_exception = asyncio.TimeoutError(
                    f"单个sheet映射超过 {current_timeout_seconds:.0f}s"
                )
                if attempt >= retry_count - 1:
                    raise
                sleep_seconds = _llm_retry_sleep_seconds_for_error(last_exception, attempt + 1)
                if sleep_seconds > 0:
                    await asyncio.sleep(sleep_seconds)
                continue
            except Exception as exc:  # noqa: BLE001
                last_exception = exc
                if attempt >= retry_count - 1 or not _should_retry_llm_mapping(exc):
                    raise
                sleep_seconds = _llm_retry_sleep_seconds_for_error(exc, attempt + 1)
                if sleep_seconds > 0:
                    await asyncio.sleep(sleep_seconds)
        if llm_plan is None and last_exception is not None:
            raise last_exception
        merged_mappings: dict[str, tuple[str, str]] = {}
        mapping_details: dict[str, dict[str, Any]] = {}
        resolved_default_ci_type = llm_plan.default_ci_type or heuristic_plan.default_ci_type
        resolved_type_template = type_template_map.get(_clean_text(resolved_default_ci_type))
        resolved_value_mappings = _sheet_value_choice_mappings(
            headers=headers,
            rows=rows,
            type_template=resolved_type_template,
        )
        for header in headers:
            detail = _build_sheet_mapping_detail(
                header=header,
                heuristic_mapping=heuristic_mappings.get(header, ("unknown", "low")),
                llm_mapping=llm_plan.mappings.get(header, ("unknown", "low")),
                metadata=metadata,
                type_template=resolved_type_template,
                value_mapping=resolved_value_mappings.get(header),
            )
            mapping_details[header] = detail
            merged_mappings[header] = (str(detail.get("targetField") or "unknown"), str(detail.get("confidence") or "low"))
        return SheetMappingPlan(
            sheet_kind=llm_plan.sheet_kind or heuristic_plan.sheet_kind,
            default_ci_type=resolved_default_ci_type,
            mappings=merged_mappings,
            reason=llm_plan.reason or "LLM 映射",
            mapping_details=mapping_details,
        ), "LLM辅助映射"
    except asyncio.TimeoutError:
        return heuristic_plan, (
            "规则映射"
            f"（LLM超时: 单个sheet映射超过 {sheet_timeout_seconds:.0f}s）"
        )
    except Exception as exc:  # noqa: BLE001
        return heuristic_plan, f"规则映射（LLM不可用: {exc}）"


def _build_type_alias_index(model_templates: list[dict[str, Any]]) -> dict[str, str]:
    alias_map: dict[str, str] = {}
    for template in model_templates:
        name = str(template.get("name") or "").strip()
        alias = str(template.get("alias") or "").strip()
        if name:
            alias_map[_normalize_token(name)] = name
        if alias:
            alias_map[_normalize_token(alias)] = name
    for ci_type, aliases in CI_TYPE_ALIASES.items():
        alias_map[_normalize_token(ci_type)] = ci_type
        for alias in aliases:
            alias_map[_normalize_token(alias)] = ci_type
    return alias_map


def _normalize_ci_type(value: str, alias_index: dict[str, str]) -> str:
    raw = _clean_text(value)
    if not raw:
        return ""
    direct = alias_index.get(_normalize_token(raw))
    if direct:
        return direct
    lowered = raw.lower()
    if "redis" in lowered:
        return "redis"
    if "mysql" in lowered:
        return "mysql"
    if "postgres" in lowered:
        return "PostgreSQL"
    if any(token in lowered for token in ("pg实例", "pg资源", "pgsql", "pg ")):
        return "PostgreSQL"
    if "kafka" in lowered:
        return "Kafka"
    if any(token in lowered for token in ("消息队列", "messagequeue", "mq", "broker", "topic", "stream")):
        return "Kafka"
    if lowered in {"es", "elasticsearch"}:
        return "elasticsearch"
    if any(token in lowered for token in ("搜索引擎", "搜索组件", "检索", "search", "opensearch", "solr")):
        return "elasticsearch"
    if "nginx" in lowered:
        return "nginx"
    if "docker" in lowered:
        return "docker"
    if any(token in lowered for token in ("容器实例", "容器", "container")):
        return "docker"
    if "k8s" in lowered or "kubernetes" in lowered:
        return "kubernetes"
    if any(token in lowered for token in ("缓存服务", "缓存组件", "缓存", "cache", "key-value", "keyvalue")):
        return "redis"
    if any(token in lowered for token in ("victoriametrics", "时序数据库")):
        return "database"
    if any(token in lowered for token in ("switch", "router", "network", "交换机", "交换", "路由", "防火墙", "负载均衡", "loadbalance", "lb")):
        return "networkdevice"
    if any(token in lowered for token in ("vm", "vserver", "虚拟")):
        return "vserver"
    if any(token in lowered for token in ("server", "服务器", "物理机", "baremetal")):
        return "PhysicalMachine"
    return raw


def _normalize_status(value: str) -> str:
    raw = _clean_text(value)
    if not raw:
        return ""
    direct = STATUS_ALIASES.get(raw)
    if direct:
        return direct
    lowered = raw.lower()
    return STATUS_ALIASES.get(lowered, raw)


def _normalize_ip(value: str) -> tuple[str, bool]:
    text = _clean_text(value)
    if not text:
        return "", False
    text = text.replace("；", ";").split(";", 1)[0].strip()
    if "/" in text:
        candidate = text.split("/", 1)[0].strip()
    else:
        candidate = text
    try:
        normalized = str(ip_address(candidate))
        return normalized, normalized != value.strip()
    except ValueError:
        octets = candidate.split(".")
        if len(octets) == 4 and all(part.isdigit() for part in octets):
            try:
                normalized = ".".join(str(int(part, 10)) for part in octets)
                ip_address(normalized)
                return normalized, normalized != value.strip()
            except ValueError:
                pass
        return text, False


def _infer_subnet(explicit_subnet: str, private_ip: str) -> str:
    if explicit_subnet:
        return explicit_subnet
    if not private_ip:
        return ""
    try:
        network = ip_network(f"{private_ip}/24", strict=False)
        return str(network)
    except ValueError:
        return ""


def _normalize_service_port(value: str) -> tuple[str, bool, bool]:
    text = _clean_text(value)
    if not text:
        return "", False, False
    compact = re.sub(r"\s+", "", text)
    if compact.isdigit():
        return compact, compact != text, False
    parts = [part for part in re.split(r"[/,;|]+", compact) if part]
    if len(parts) == 1 and parts[0].isdigit():
        normalized = parts[0]
        return normalized, normalized != text, False
    if len(parts) > 1 and all(part.isdigit() for part in parts):
        return "", True, True
    return text, False, True


def _read_csv_rows(filename: str, content: bytes) -> list[dict[str, Any]]:
    text = content.decode("utf-8-sig", errors="ignore")
    sample = text[:2048]
    dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|") if sample.strip() else csv.excel
    frame = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False, sep=dialect.delimiter)
    return frame.fillna("").to_dict(orient="records")


def _read_excel_rows(filename: str, content: bytes) -> list[dict[str, Any]]:
    try:
        suffix = Path(filename).suffix.lower()
        engine = "openpyxl" if suffix in {".xlsx", ".xlsm"} else None
        workbook = pd.read_excel(
            io.BytesIO(content),
            sheet_name=None,
            dtype=str,
            engine=engine,
        )
    except ImportError as exc:
        raise RuntimeError(
            "当前服务运行环境缺少 Excel 解析依赖 openpyxl，"
            "请在启动 QwenPaw 的 Python 环境中安装 `openpyxl` 后重试。"
        ) from exc

    rows: list[dict[str, Any]] = []
    for sheet_name, frame in workbook.items():
        for row in frame.fillna("").to_dict(orient="records"):
            normalized = dict(row)
            normalized["_sheet"] = sheet_name
            rows.append(normalized)
    return rows


def _read_json_rows(content: bytes) -> list[dict[str, Any]]:
    payload = json.loads(content.decode("utf-8"))
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("items", "rows", "data", "result"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload]
    return []


def _parse_text_blocks(text: str) -> list[dict[str, Any]]:
    blocks = re.split(r"\n\s*\n", text)
    rows: list[dict[str, Any]] = []
    for block in blocks:
        row: dict[str, Any] = {}
        for line in block.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                row[_clean_text(key)] = _clean_text(value)
            elif "：" in line:
                key, value = line.split("：", 1)
                row[_clean_text(key)] = _clean_text(value)
        if row:
            rows.append(row)
    return rows


def _read_docx_rows(content: bytes) -> list[dict[str, Any]]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        xml = archive.read("word/document.xml").decode("utf-8", errors="ignore")
    text = re.sub(r"</w:p>", "\n", xml)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return _parse_text_blocks(text)


async def _read_image_rows(
    filename: str,
    content: bytes,
    llm_client: Any | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    if not llm_client:
        return [], ["当前页面所选模型未提供可用的多模态解析能力，图片文件暂时无法自动抽取。"]
    try:
        rows = await llm_client.extract_rows_from_image(filename=filename, content=content)
        return rows, []
    except Exception as exc:  # noqa: BLE001
        return [], [f"{filename} 图片解析失败：{exc}"]


async def parse_uploaded_file(
    filename: str,
    content: bytes,
    *,
    llm_client: Any | None = None,
    progress_callback: ProgressCallback | None = None,
) -> ParsedFile:
    suffix = Path(filename).suffix.lower()
    logs = [f"开始解析文件：{filename}"]
    warnings: list[str] = []
    rows: list[dict[str, Any]] = []
    _emit_progress(
        progress_callback,
        stage="file_reading",
        message=f"正在读取文件 {filename}",
        percent=8,
    )
    if suffix in {".csv", ".tsv"}:
        rows = await asyncio.to_thread(_read_csv_rows, filename, content)
    elif suffix in {".xlsx", ".xls"}:
        rows = await asyncio.to_thread(_read_excel_rows, filename, content)
    elif suffix == ".json":
        rows = await asyncio.to_thread(_read_json_rows, content)
    elif suffix in {".txt", ".md"}:
        rows = await asyncio.to_thread(
            _parse_text_blocks,
            content.decode("utf-8", errors="ignore"),
        )
    elif suffix == ".docx":
        rows = await asyncio.to_thread(_read_docx_rows, content)
    elif suffix in IMAGE_SUFFIXES:
        rows, image_warnings = await _read_image_rows(filename, content, llm_client=llm_client)
        warnings.extend(image_warnings)
    else:
        warnings.append(f"{filename} 暂不支持自动解析，将保留为待扩展格式。")
    logs.append(f"读取到 {len(rows)} 条原始行（含说明页/非资产行，后续步骤会继续筛除）")
    _emit_progress(
        progress_callback,
        stage="file_reading",
        message=f"{filename} 读取完成，共识别到 {len(rows)} 条原始行",
        percent=16,
    )
    return ParsedFile(
        filename=filename,
        extension=suffix,
        rows=rows,
        warnings=warnings,
        logs=logs,
    )


def _resource_key(ci_type: str, name: str, private_ip: str) -> str:
    anchor = private_ip or name
    return f"{ci_type}::{anchor}".lower()


def _ensure_node(
    nodes: dict[str, dict[str, Any]],
    *,
    ci_type: str,
    name: str,
    category: str,
    generated: bool,
    attributes: dict[str, Any] | None = None,
    source_rows: list[dict[str, Any]] | None = None,
) -> str | None:
    name = _clean_text(name)
    if not name:
        return None
    key = _resource_key(ci_type, name, "")
    existing = nodes.get(key)
    payload = {
        "previewKey": key,
        "ciType": ci_type,
        "name": name,
        "category": category,
        "generated": generated,
        "attributes": attributes or {"name": name},
        "sourceRows": source_rows or [],
        "selected": True,
    }
    if existing:
        existing["sourceRows"] = [*existing.get("sourceRows", []), *(payload["sourceRows"] or [])]
        return key
    nodes[key] = payload
    return key


def _append_relation(
    relations: dict[tuple[str, str, str], dict[str, Any]],
    *,
    source_key: str | None,
    target_key: str | None,
    relation_type: str,
    confidence: str,
    reason: str,
) -> None:
    if not source_key or not target_key or source_key == target_key:
        return
    key = (source_key, target_key, relation_type)
    if key in relations:
        return
    relations[key] = {
        "sourceKey": source_key,
        "targetKey": target_key,
        "relationType": relation_type,
        "confidence": confidence,
        "reason": reason,
        "selected": True,
    }


def _build_preview_key(parsed_file: ParsedFile | str, sheet_name: str, row_index: int) -> str:
    filename = parsed_file if isinstance(parsed_file, str) else parsed_file.filename
    return f"row::{filename}::{sheet_name or 'Sheet1'}::{row_index}"


def _row_has_resource_signal(fields: dict[str, Any]) -> bool:
    value_fields = [key for key in RESOURCE_VALUE_FIELDS if _clean_text(fields.get(key))]
    if not value_fields:
        return False
    if any(key in PRIMARY_RESOURCE_FIELDS for key in value_fields):
        return True
    return len(value_fields) >= 3


def _collect_confirmation_issues(
    ci_type: str,
    attributes: dict[str, Any],
    type_template: dict[str, Any] | None = None,
) -> list[str]:
    issues: list[str] = []
    if type_template is None:
        for item in DEFAULT_MODEL_TEMPLATES:
            if _clean_text(item.get("name")) == _clean_text(ci_type):
                type_template = item
                break

    def has_value_for(canonical_field: str) -> bool:
        if _clean_text(attributes.get(canonical_field)):
            return True
        if type_template:
            resolved_key = _resolve_import_target_key(
                type_template=type_template,
                canonical_field=canonical_field,
            )
            if resolved_key and _clean_text(attributes.get(resolved_key)):
                return True
        return False

    if not has_value_for("name"):
        issues.append("名称")
    if ci_type in {"PhysicalMachine", "vserver", "networkdevice"} and not has_value_for("private_ip"):
        issues.append("IP")
    if ci_type == "networkdevice" and not _clean_text(attributes.get("model")):
        issues.append("型号")
    if ci_type in SOFTWARE_RESOURCE_TYPES and not _clean_text(attributes.get("version")):
        issues.append("版本")
    if ci_type in SOFTWARE_RESOURCE_TYPES and not has_value_for("service_port"):
        issues.append("端口")
    if ci_type in SOFTWARE_RESOURCE_TYPES and not _clean_text(attributes.get("deploy_target")):
        issues.append("部署节点")
    return issues


def _find_existing_ci(
    client: VeopsCmdbClient | None,
    ci_type: str,
    attributes: dict[str, Any],
    *,
    fallback_name: str = "",
    unique_key: str = "",
) -> dict[str, Any] | None:
    if client is None or not ci_type or ci_type == "unknown":
        return None

    candidates: list[tuple[str, str]] = []
    for field in [unique_key, "asset_code", "private_ip", "name"]:
        field = _clean_text(field)
        if not field:
            continue
        value = _clean_text(attributes.get(field))
        if value and all(existing_field != field for existing_field, _ in candidates):
            candidates.append((field, value))
    if fallback_name and all(name != "name" for name, _ in candidates):
        candidates.append(("name", fallback_name))

    for field, value in candidates:
        try:
            items = client.query_ci(
                f"_type:{ci_type},{field}:{quote(value, safe='._-:/')}",
                count=1,
            )
        except Exception:
            continue
        if not items:
            continue
        item = items[0]
        ci_id = _extract_ci_id(item)
        if ci_id in (None, ""):
            continue
        return {
            "ciId": ci_id,
            "matchField": field,
            "matchValue": value,
            "name": _clean_text(
                item.get("name")
                or item.get("ci_name")
                or item.get("label")
                or item.get("title")
            ),
            "status": _clean_text(item.get("status") or item.get("state")),
        }
    return None


def _extract_type_id(payload: Any) -> int | None:
    if payload is None:
        return None
    if isinstance(payload, bool):
        return None
    if isinstance(payload, int):
        return payload
    text = _clean_text(payload)
    if text.isdigit():
        return int(text)
    return None


def _resolve_attribute_id_from_metadata(
    metadata: dict[str, Any],
    attribute_name: str,
    *,
    preferred_ci_type: str = "",
) -> int | None:
    direct_id = _extract_type_id(attribute_name)
    if direct_id is not None:
        return direct_id

    target_name = _clean_text(attribute_name)
    if not target_name:
        return None

    def _find_definition_id(
        definitions: list[dict[str, Any]],
        names: list[str],
    ) -> int | None:
        exact_names = [_clean_text(item) for item in names if _clean_text(item)]
        if not exact_names:
            return None

        for candidate_name in exact_names:
            normalized_candidate = _normalize_token(candidate_name)
            for definition in definitions:
                if not isinstance(definition, dict):
                    continue
                attribute_id = _extract_type_id(definition.get("id"))
                if attribute_id is None:
                    continue
                definition_name = _clean_text(definition.get("name"))
                definition_alias = _clean_text(definition.get("alias"))
                if definition_name == candidate_name or definition_alias == candidate_name:
                    return attribute_id
                if normalized_candidate and (
                    _normalize_token(definition_name) == normalized_candidate
                    or _normalize_token(definition_alias) == normalized_candidate
                ):
                    return attribute_id
        return None

    ci_types = [
        item
        for item in (metadata.get("ciTypes") or [])
        if isinstance(item, dict)
    ]
    preferred_type = next(
        (item for item in ci_types if _clean_text(item.get("name")) == _clean_text(preferred_ci_type)),
        None,
    )
    preferred_definitions = list((preferred_type or {}).get("attributeDefinitions") or [])
    all_definitions = [
        definition
        for ci_type in ci_types
        for definition in (ci_type.get("attributeDefinitions") or [])
        if isinstance(definition, dict)
    ]

    direct_match = _find_definition_id(preferred_definitions, [target_name]) or _find_definition_id(
        all_definitions,
        [target_name],
    )
    if direct_match is not None:
        return direct_match

    canonical_field, _confidence = _match_field(target_name)
    canonical_names: list[str] = [target_name]
    if canonical_field != "unknown":
        canonical_names.append(canonical_field)
        canonical_names.extend(FIELD_ALIASES.get(canonical_field, []))
        canonical_names.extend(SPECIAL_ATTRIBUTE_NAME_CANDIDATES.get(canonical_field, []))

    if preferred_type and canonical_field != "unknown":
        resolved_name = _resolve_cmdb_attribute_name(preferred_type, canonical_field)
        if resolved_name:
            canonical_names.insert(0, resolved_name)

    mapped_match = _find_definition_id(preferred_definitions, canonical_names) or _find_definition_id(
        all_definitions,
        canonical_names,
    )
    if mapped_match is not None:
        return mapped_match

    attribute_library = [
        item
        for item in (metadata.get("attributeLibrary") or [])
        if isinstance(item, dict)
    ]
    library_match = _find_definition_id(attribute_library, canonical_names)
    if library_match is not None:
        return library_match

    return None


def _build_ci_type_state(
    ci_types: list[dict[str, Any]],
    ci_type_groups: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    type_map = {
        _clean_text(item.get("name")): item
        for item in ci_types
        if isinstance(item, dict) and _clean_text(item.get("name"))
    }
    group_map = {
        _clean_text(group.get("name")): group
        for group in (
            _normalize_group_snapshot(item)
            for item in ci_type_groups
            if isinstance(item, dict)
        )
        if _clean_text(group.get("name"))
    }
    return type_map, group_map


def _refresh_ci_type_state(
    client: VeopsCmdbClient,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    return _build_ci_type_state(client.get_ci_types(), client.get_ci_type_groups())


def _attach_model_to_group(
    client: VeopsCmdbClient,
    *,
    group: dict[str, Any],
    group_name: str,
    model_id: int,
) -> bool:
    group_id = _extract_type_id(group.get("id"))
    if group_id is None:
        raise RuntimeError(f"分组 {group_name} 缺少可用 id，无法挂接模型")

    type_ids = {
        ci_type_id
        for ci_type_id in (
            _extract_type_id(item.get("id"))
            for item in (group.get("ciTypes") or [])
            if isinstance(item, dict)
        )
        if ci_type_id is not None
    }
    if model_id in type_ids:
        return False
    type_ids.add(model_id)
    client.update_ci_type_group(group_id, name=group_name, type_ids=sorted(type_ids))
    return True


def _prepare_import_structure(
    client: VeopsCmdbClient,
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    preview = payload.get("preview") or {}
    structure_analysis = preview.get("structureAnalysis") or {}
    items = structure_analysis.get("items") or []
    if not isinstance(items, list):
        return []

    metadata: dict[str, Any] | None = None
    type_map, group_map = _refresh_ci_type_state(client)
    results: list[dict[str, Any]] = []

    for raw_item in items:
        if not isinstance(raw_item, dict):
            continue
        resource_label = _clean_text(raw_item.get("resourceLabel")) or _clean_text(raw_item.get("resourceCiType")) or "待确认资源"
        group_name = _clean_text(raw_item.get("selectedGroupName")) or _clean_text(raw_item.get("suggestedGroupName"))
        raw_model_name = _clean_text(raw_item.get("selectedModelName")) or _clean_text(raw_item.get("resourceCiType"))
        model_name = _resolve_payload_ci_type(
            raw_model_name,
            type_templates=type_map,
        ) or raw_model_name
        model_draft = raw_item.get("modelDraft") or {}
        model_alias = _clean_text(model_draft.get("alias")) or model_name
        unique_key_name = _clean_text(model_draft.get("uniqueKey"))
        inherit_from = _clean_text(model_draft.get("inheritFrom"))
        group = group_map.get(group_name) if group_name else None
        group_missing = bool(group_name) and group is None
        if group_missing:
            if not raw_item.get("createGroupApproved"):
                raise RuntimeError(f"{resource_label} 尚未确认创建分组，当前不能继续导入")
            client.create_ci_type_group(group_name)
            _type_map, group_map = _refresh_ci_type_state(client)
            type_map.update(_type_map)
            group = group_map.get(group_name)
            if group is None:
                raise RuntimeError(f"分组 {group_name} 创建后未能在 CMDB 中查询到")
            results.append(
                {
                    "kind": "group",
                    "name": group_name,
                    "status": "created",
                    "message": f"已创建分组 {group_name}",
                }
            )

        if not model_name:
            if group_missing or raw_item.get("createModelApproved"):
                raise RuntimeError(f"{resource_label} 缺少目标模型名称，当前不能继续导入")
            continue

        model = type_map.get(model_name)
        model_missing = model is None
        if model_missing:
            if not raw_item.get("createModelApproved"):
                raise RuntimeError(f"{resource_label} 尚未确认创建模型，当前不能继续导入")
            if not unique_key_name:
                raise RuntimeError(f"{resource_label} 缺少模型唯一标识配置，当前不能继续导入")

            if metadata is None:
                metadata = load_resource_import_metadata()
            unique_key_id = _resolve_attribute_id_from_metadata(
                metadata,
                unique_key_name,
                preferred_ci_type=inherit_from or model_name,
            )
            if unique_key_id is None:
                raise RuntimeError(
                    f"{resource_label} 的唯一标识字段 {unique_key_name} 未在 CMDB 属性库中找到，当前不能创建模型"
                )
            parent_ids: list[int] = []
            if inherit_from:
                parent = type_map.get(inherit_from)
                parent_id = _extract_type_id((parent or {}).get("id"))
                if parent_id is None:
                    raise RuntimeError(f"模型 {model_name} 继承失败：未找到父模型 {inherit_from}")
                parent_ids = [parent_id]
            model_id, _response = client.create_ci_type(
                name=model_name,
                alias=model_alias or model_name,
                unique_key=unique_key_id,
                parent_ids=parent_ids,
            )
            _type_map, group_map = _refresh_ci_type_state(client)
            type_map.update(_type_map)
            group = group_map.get(group_name) if group_name else group
            model = type_map.get(model_name)
            resolved_model_id = _extract_type_id(model_id) or _extract_type_id((model or {}).get("id"))
            if model is None or resolved_model_id is None:
                raise RuntimeError(f"模型 {model_name} 创建后未能在 CMDB 中查询到")
            results.append(
                {
                    "kind": "model",
                    "name": model_name,
                    "groupName": group_name,
                    "status": "created",
                    "message": f"已创建模型 {model_name}",
                }
            )

        if group_name:
            model_id = _extract_type_id((model or {}).get("id"))
            if model_id is None:
                raise RuntimeError(f"模型 {model_name} 缺少 id，无法继续导入")
            if group is None:
                raise RuntimeError(f"目标分组 {group_name} 不存在，无法挂接模型 {model_name}")
            attached = _attach_model_to_group(
                client,
                group=group,
                group_name=group_name,
                model_id=model_id,
            )
            if attached:
                _type_map, group_map = _refresh_ci_type_state(client)
                type_map.update(_type_map)
                results.append(
                    {
                        "kind": "group-binding",
                        "name": model_name,
                        "groupName": group_name,
                        "status": "attached",
                        "message": f"已将模型 {model_name} 绑定到分组 {group_name}",
                    }
                )

    return results


def _attribute_definitions(type_template: dict[str, Any] | None) -> list[dict[str, Any]]:
    definitions = (type_template or {}).get("attributeDefinitions") or []
    return [item for item in definitions if isinstance(item, dict) and item.get("name")]


def _allowed_attribute_names(type_template: dict[str, Any] | None) -> set[str]:
    definition_names = {
        _clean_text(item.get("name"))
        for item in _attribute_definitions(type_template)
        if _clean_text(item.get("name"))
    }
    if definition_names:
        return definition_names
    return {
        _clean_text(item)
        for item in ((type_template or {}).get("attributes") or [])
        if _clean_text(item)
    }


def _find_attribute_definition(type_template: dict[str, Any] | None, attribute_name: str) -> dict[str, Any] | None:
    target = _clean_text(attribute_name)
    for item in _attribute_definitions(type_template):
        if _clean_text(item.get("name")) == target:
            return item
    return None


def _resolve_attribute_label(type_template: dict[str, Any] | None, attribute_name: str) -> str:
    for item in _attribute_definitions(type_template):
        if _clean_text(item.get("name")) == _clean_text(attribute_name):
            return str(item.get("alias") or item.get("name") or attribute_name)
    return attribute_name


def _format_choice_options(attribute_definition: dict[str, Any] | None, *, limit: int = 8) -> str:
    if not attribute_definition:
        return ""
    labels: list[str] = []
    for item in (attribute_definition.get("choices") or []):
        if not isinstance(item, dict):
            continue
        label = _clean_text(item.get("label")) or _clean_text(item.get("value"))
        if label and label not in labels:
            labels.append(label)
    if not labels:
        return ""
    trimmed = labels[:limit]
    suffix = " 等" if len(labels) > limit else ""
    return " / ".join(trimmed) + suffix


def _semantic_tokens(value: str) -> list[str]:
    return [
        item
        for item in re.split(
            r"[^a-z0-9\u4e00-\u9fff]+",
            re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", _clean_text(value)).lower(),
        )
        if item
    ]


def _is_name_like_unique_key(unique_key: str) -> bool:
    normalized = _normalize_token(unique_key)
    raw = _clean_text(unique_key).lower()
    tokens = set(_semantic_tokens(unique_key))
    return (
        normalized.endswith("name")
        or "name" in tokens
        or "instance" in tokens
        or "hostname" in tokens
        or "servername" in tokens
        or "devname" in tokens
        or "vservername" in tokens
        or any(token in raw for token in ("名称", "名字", "主机名", "设备名", "实例名", "实例名称", "组件实例名", "数据库实例名"))
    )


def _is_ip_like_unique_key(unique_key: str) -> bool:
    normalized = _normalize_token(unique_key)
    raw = _clean_text(unique_key).lower()
    return "ip" in normalized or any(
        token in raw
        for token in ("管理地址", "管理ip", "内网地址", "内网ip", "ip地址", "主机地址", "数据库地址", "组件地址")
    )


def _is_code_like_unique_key(unique_key: str) -> bool:
    raw = _clean_text(unique_key).lower()
    normalized = _normalize_token(unique_key)
    tokens = set(_semantic_tokens(unique_key))
    if any(token in raw for token in ("主键", "唯一", "唯一标识", "资源主键", "资产标识", "编号", "编码", "标识")):
        return True
    if normalized in {"rowid", "ciid", "pid"}:
        return True
    return any(token in tokens for token in ("code", "no", "id", "key", "pk", "unique", "identifier"))


def _clean_source_attributes(row: dict[str, Any]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for raw_key, raw_value in row.items():
        if raw_key == "_sheet":
            continue
        field_name = _clean_text(raw_key)
        field_value = _clean_text(raw_value)
        if field_name and field_value:
            cleaned[field_name] = field_value
    return cleaned


def _semantic_source_candidates(
    source_attributes: dict[str, str],
    *,
    semantic_kind: str,
    unique_key: str = "",
    unique_key_label: str = "",
) -> list[tuple[int, str, str]]:
    candidates: list[tuple[int, str, str]] = []
    target_text = " ".join(item for item in (unique_key, unique_key_label) if _clean_text(item)).strip()
    for field_name, field_value in source_attributes.items():
        if not _clean_text(field_value):
            continue
        matched = (
            semantic_kind == "name"
            and _is_name_like_unique_key(field_name)
        ) or (
            semantic_kind == "ip"
            and _is_ip_like_unique_key(field_name)
        ) or (
            semantic_kind == "code"
            and _is_code_like_unique_key(field_name)
        )
        if not matched:
            continue
        similarity_score = _semantic_text_similarity(field_name, target_text or semantic_kind)[0] if (target_text or semantic_kind) else 0
        candidates.append((100 + similarity_score, field_name, field_value))
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return candidates


def _is_system_generated_unique_key(type_template: dict[str, Any] | None) -> bool:
    unique_key = _clean_text((type_template or {}).get("unique_key"))
    if not unique_key:
        return False

    normalized = _normalize_token(unique_key)
    if normalized in {"pid", "rowid", "ciid"}:
        return True

    definition = _find_attribute_definition(type_template, unique_key)
    alias = _clean_text((definition or {}).get("alias")).lower()
    value_type = _clean_text((definition or {}).get("value_type")).lower()
    numeric_types = {"int", "integer", "bigint", "smallint", "long", "number"}
    if normalized in {"id", "_id"} and alias in {"主键", "系统主键"} and value_type in numeric_types:
        return True
    return False


def _get_import_required_unique_key(type_template: dict[str, Any] | None) -> str:
    if _is_system_generated_unique_key(type_template):
        return ""
    return _clean_text((type_template or {}).get("unique_key"))


SPECIAL_ATTRIBUTE_NAME_CANDIDATES = {
    "asset_code": ["asset_code", "property_no", "dev_no", "p_id"],
    "name": ["name", "serverName", "dev_name", "db_instance", "middleware_name", "project_name", "product_name", "vserver_name"],
    "private_ip": ["private_ip", "privateIp", "manage_ip", "host_ip", "ip", "db_ip", "middleware_ip"],
    "status": ["status"],
    "platform": ["platform", "project", "project_name", "app_name"],
    "project": ["project", "platform", "project_name", "app_name"],
    "model": ["model", "device_spec", "dev_model"],
    "version": ["version", "db_version", "dev_software_version"],
    "service_port": ["service_port", "db_port", "middleware_port", "snmp_port"],
    "owner": ["owner", "op_duty"],
    "deploy_target": ["deploy_target", "AssociatedPhyMachine"],
    "host_name": ["host_name"],
    "os_version": ["os_version", "osVersion"],
    "server_room": ["server_room"],
    "rack": ["rack", "cabinet"],
    "idc": ["idc", "data_center"],
}


def _resolve_cmdb_attribute_name(type_template: dict[str, Any] | None, canonical_field: str) -> str:
    definitions = _attribute_definitions(type_template)
    system_generated_unique_key = _clean_text((type_template or {}).get("unique_key")) if _is_system_generated_unique_key(type_template) else ""
    ordered_candidates: list[str] = [canonical_field]
    ordered_candidates.extend(item for item in FIELD_ALIASES.get(canonical_field, []) if _clean_text(item))
    ordered_candidates.extend(item for item in SPECIAL_ATTRIBUTE_NAME_CANDIDATES.get(canonical_field, []) if _clean_text(item))
    candidate_tokens = {_normalize_token(canonical_field)}
    candidate_tokens.update(_normalize_token(item) for item in FIELD_ALIASES.get(canonical_field, []))
    candidate_tokens.update(_normalize_token(item) for item in SPECIAL_ATTRIBUTE_NAME_CANDIDATES.get(canonical_field, []))

    if definitions:
        attribute_names = {_clean_text(item.get("name")) for item in definitions}
    else:
        attribute_names = {
            _clean_text(item)
            for item in ((type_template or {}).get("attributes") or [])
            if _clean_text(item)
        }

    unique_key = _get_import_required_unique_key(type_template)
    if unique_key:
        if canonical_field == "name" and _is_name_like_unique_key(unique_key) and unique_key in attribute_names:
            return unique_key
        if canonical_field == "private_ip" and _is_ip_like_unique_key(unique_key) and unique_key in attribute_names:
            return unique_key
        if canonical_field == "asset_code" and _is_code_like_unique_key(unique_key) and unique_key in attribute_names:
            return unique_key
        if canonical_field == "name" and _is_name_like_unique_key(unique_key):
            candidate_tokens.add(_normalize_token(unique_key))
        if canonical_field == "private_ip" and _is_ip_like_unique_key(unique_key):
            candidate_tokens.add(_normalize_token(unique_key))
        if canonical_field == "asset_code" and _is_code_like_unique_key(unique_key):
            candidate_tokens.add(_normalize_token(unique_key))

    if not definitions:
        for candidate_name in ordered_candidates:
            normalized_candidate = _clean_text(candidate_name)
            if normalized_candidate and normalized_candidate in attribute_names:
                return normalized_candidate
        for attr_name in attribute_names:
            if _normalize_token(attr_name) in candidate_tokens:
                return attr_name
        return canonical_field

    for candidate_name in ordered_candidates:
        normalized_candidate = _normalize_token(candidate_name)
        for item in definitions:
            attr_name = str(item.get("name") or "")
            attr_alias = str(item.get("alias") or "")
            if not normalized_candidate:
                continue
            if system_generated_unique_key and _clean_text(attr_name) == system_generated_unique_key:
                continue
            if (
                _normalize_token(attr_name) == normalized_candidate
                or _normalize_token(attr_alias) == normalized_candidate
            ):
                return attr_name

    for item in definitions:
        attr_name = str(item.get("name") or "")
        attr_alias = str(item.get("alias") or "")
        if system_generated_unique_key and _clean_text(attr_name) == system_generated_unique_key:
            continue
        if _normalize_token(attr_name) in candidate_tokens or _normalize_token(attr_alias) in candidate_tokens:
            return attr_name
    return canonical_field


def _resolve_import_target_key(
    *,
    type_template: dict[str, Any] | None,
    canonical_field: str,
) -> str:
    target_key = _resolve_cmdb_attribute_name(type_template, canonical_field)
    if canonical_field != "project":
        return target_key
    type_name = _clean_text((type_template or {}).get("name"))
    if type_name == "project":
        return target_key
    platform_key = _resolve_cmdb_attribute_name(type_template, "platform")
    if platform_key and _find_attribute_definition(type_template, platform_key):
        return platform_key
    return target_key


def _first_non_empty_value(*values: Any) -> str:
    for value in values:
        cleaned = _clean_text(value)
        if cleaned:
            return cleaned
    return ""


def _first_non_empty_preserving_list(*values: Any) -> Any:
    """Like ``_first_non_empty_value`` but keeps list-typed sources as lists.

    Multi-valued CMDB attributes (e.g. ``private_ip`` / ``manage_ip``) are
    stored as lists. Passing them through ``_first_non_empty_value`` collapses
    the list into ``str(list)`` (e.g. ``"['10.0.0.1']"``), which then gets
    written back as a literal stringified list. Use this helper whenever the
    fallback chain may include list-typed CMDB values.
    """
    for value in values:
        if isinstance(value, list):
            cleaned_list = [item for item in value if _clean_text(item)]
            if cleaned_list:
                return cleaned_list
            continue
        cleaned = _clean_text(value)
        if cleaned:
            return cleaned
    return ""


def _autofill_deterministic_cmdb_attributes(
    *,
    canonical_attributes: dict[str, Any],
    type_template: dict[str, Any] | None,
    cmdb_attributes: dict[str, Any],
) -> dict[str, Any]:
    if not type_template:
        return cmdb_attributes

    next_attributes = dict(cmdb_attributes)
    manage_ip_key = _resolve_cmdb_attribute_name(type_template, "manage_ip")
    private_ip_key = _resolve_cmdb_attribute_name(type_template, "private_ip")

    if manage_ip_key and not _clean_text(next_attributes.get(manage_ip_key)):
        manage_ip_value = _first_non_empty_preserving_list(
            next_attributes.get(private_ip_key),
            canonical_attributes.get("manage_ip"),
            canonical_attributes.get("private_ip"),
            canonical_attributes.get("host_ip"),
        )
        if manage_ip_value:
            next_attributes[manage_ip_key] = manage_ip_value

    if private_ip_key and not _clean_text(next_attributes.get(private_ip_key)):
        private_ip_value = _first_non_empty_preserving_list(
            next_attributes.get(manage_ip_key),
            canonical_attributes.get("private_ip"),
            canonical_attributes.get("manage_ip"),
            canonical_attributes.get("host_ip"),
        )
        if private_ip_value:
            next_attributes[private_ip_key] = private_ip_value

    unique_value = ""
    unique_key = _get_import_required_unique_key(type_template)
    if unique_key and not _clean_text(next_attributes.get(unique_key)):
        if _is_code_like_unique_key(unique_key):
            unique_value = _first_non_empty_value(
                next_attributes.get(_resolve_import_target_key(type_template=type_template, canonical_field="asset_code")),
                canonical_attributes.get("asset_code"),
                canonical_attributes.get("property_no"),
                canonical_attributes.get("dev_no"),
                canonical_attributes.get("p_id"),
            )
        elif _is_ip_like_unique_key(unique_key):
            unique_value = _first_non_empty_value(
                next_attributes.get(private_ip_key),
                next_attributes.get(manage_ip_key),
                canonical_attributes.get("private_ip"),
                canonical_attributes.get("manage_ip"),
                canonical_attributes.get("host_ip"),
            )
        else:
            unique_value = _first_non_empty_value(
                next_attributes.get(_resolve_import_target_key(type_template=type_template, canonical_field="name")),
                canonical_attributes.get("name"),
                canonical_attributes.get("dev_name"),
                canonical_attributes.get("serverName"),
                canonical_attributes.get("hostname"),
                canonical_attributes.get("db_instance"),
                canonical_attributes.get("middleware_name"),
                canonical_attributes.get("asset_code"),
                canonical_attributes.get("private_ip"),
                canonical_attributes.get("manage_ip"),
            )
    if unique_value:
        next_attributes[unique_key] = unique_value

    for definition in _attribute_definitions(type_template):
        attr_name = _clean_text(definition.get("name"))
        if not attr_name or _clean_text(next_attributes.get(attr_name)):
            continue
        if not bool(definition.get("required") or definition.get("is_required")):
            continue
        default_value = _extract_attribute_default_value(definition)
        if not default_value:
            continue
        normalized_value, unresolved_choice = _normalize_choice_attribute_value(
            attribute_definition=definition,
            value=default_value,
        )
        if unresolved_choice or not normalized_value:
            continue
        next_attributes[attr_name] = normalized_value

    # Fall back to the canonical "name" for required name-like attributes
    # (e.g. ``vserver_name`` / ``host_name`` / ``db_instance_name``). Many CMDB
    # models declare both a generic ``name`` and a model-specific ``*_name``
    # field as required, but source spreadsheets typically supply only one
    # name column. Without this fallback, preflight rejects the record with
    # "缺少必填字段：虚拟机名" even though the value is right there in ``name``.
    canonical_name = _first_non_empty_value(
        next_attributes.get("name"),
        canonical_attributes.get("name"),
        canonical_attributes.get("dev_name"),
        canonical_attributes.get("hostname"),
        canonical_attributes.get("host_name"),
        canonical_attributes.get("db_instance"),
        canonical_attributes.get("middleware_name"),
        canonical_attributes.get("instance_name"),
    )
    if canonical_name:
        for definition in _attribute_definitions(type_template):
            attr_name = _clean_text(definition.get("name"))
            if not attr_name or attr_name == "name":
                continue
            if not bool(definition.get("required") or definition.get("is_required")):
                continue
            if _clean_text(next_attributes.get(attr_name)):
                continue
            if definition.get("is_choice"):
                continue
            # Heuristic: the technical name ends in ``_name`` OR the alias
            # contains "名" / "name" (case-insensitive). Catches vserver_name,
            # host_name, db_instance_name, instance_name, etc.
            alias_text = _clean_text(definition.get("alias")).lower()
            if not (
                attr_name.endswith("_name")
                or attr_name == "instance_name"
                or "名" in alias_text
                or "name" in alias_text
            ):
                continue
            next_attributes[attr_name] = canonical_name

    return next_attributes


def _is_server_default_macro(value: Any) -> bool:
    # VEOPS server-side computed defaults (e.g. ``$auto_inc_id``) must never be
    # sent literally in a create payload; the CMDB resolves them when the
    # attribute is omitted.
    return _clean_text(value).startswith("$")


def _extract_attribute_default_value(attribute_definition: dict[str, Any] | None) -> str:
    if not attribute_definition:
        return ""
    raw_default = attribute_definition.get("default")
    if isinstance(raw_default, dict):
        for key in ("default", "value", "label"):
            value = _clean_text(raw_default.get(key))
            if value and not _is_server_default_macro(value):
                return value
    elif isinstance(raw_default, list):
        for item in raw_default:
            value = _clean_text(item)
            if value and not _is_server_default_macro(value):
                return value
    else:
        cleaned_default = _clean_text(raw_default)
        if cleaned_default and not _is_server_default_macro(cleaned_default):
            return cleaned_default

    attr_name = _clean_text(attribute_definition.get("name")).lower()
    attr_alias = _clean_text(attribute_definition.get("alias"))
    if attr_name == "status" or attr_alias == "资产状态":
        for item in (attribute_definition.get("choices") or []):
            if not isinstance(item, dict):
                continue
            label = _clean_text(item.get("label"))
            value = _clean_text(item.get("value"))
            if label == "在线" or value == "在线":
                return value or label
        for item in (attribute_definition.get("choices") or []):
            if not isinstance(item, dict):
                continue
            value = _clean_text(item.get("value")) or _clean_text(item.get("label"))
            if value:
                return value
    return ""


def _collect_deterministic_autofill_hints(
    *,
    canonical_attributes: dict[str, Any],
    type_template: dict[str, Any] | None,
    cmdb_attributes: dict[str, Any],
) -> list[str]:
    if not type_template:
        return []

    hints: list[str] = []
    manage_ip_key = _resolve_cmdb_attribute_name(type_template, "manage_ip")
    private_ip_key = _resolve_cmdb_attribute_name(type_template, "private_ip")
    if (
        manage_ip_key
        and _clean_text(cmdb_attributes.get(manage_ip_key))
        and not _clean_text(canonical_attributes.get("manage_ip"))
        and _clean_text(canonical_attributes.get("private_ip"))
    ):
        hints.append(f"{_resolve_attribute_label(type_template, manage_ip_key)}已补全")

    unique_key = _get_import_required_unique_key(type_template)
    if unique_key and _clean_text(cmdb_attributes.get(unique_key)):
        if _is_code_like_unique_key(unique_key) and (
            not _clean_text(canonical_attributes.get(unique_key))
            and _first_non_empty_value(
                canonical_attributes.get("asset_code"),
                canonical_attributes.get("property_no"),
                canonical_attributes.get("dev_no"),
                canonical_attributes.get("p_id"),
            )
        ):
            hints.append(f"{_resolve_attribute_label(type_template, unique_key)}已补全")
        elif _is_ip_like_unique_key(unique_key) and (
            not _clean_text(canonical_attributes.get(unique_key))
            and _first_non_empty_value(
                canonical_attributes.get("private_ip"),
                canonical_attributes.get("manage_ip"),
                canonical_attributes.get("host_ip"),
            )
        ):
            hints.append(f"{_resolve_attribute_label(type_template, unique_key)}已补全")
        elif _is_name_like_unique_key(unique_key) and (
            not _clean_text(canonical_attributes.get(unique_key))
            and _clean_text(canonical_attributes.get("name"))
        ):
            hints.append(f"{_resolve_attribute_label(type_template, unique_key)}已补全")

    return list(dict.fromkeys(hints))


def _normalize_choice_attribute_value(
    *,
    attribute_definition: dict[str, Any] | None,
    value: str,
    extra_choices: list[dict[str, str]] | None = None,
) -> tuple[str, bool]:
    cleaned_value = _clean_text(value)
    if not cleaned_value:
        return "", False
    if not attribute_definition or not attribute_definition.get("is_choice"):
        return cleaned_value, False

    choice_values = list(attribute_definition.get("choices") or [])
    if extra_choices:
        choice_values.extend(extra_choices)
    if not choice_values:
        return cleaned_value, False

    normalized_input = _normalize_token(cleaned_value)
    for item in choice_values:
        choice_value = _clean_text(item.get("value"))
        choice_label = _clean_text(item.get("label"))
        if cleaned_value == choice_value or normalized_input == _normalize_token(choice_value):
            return choice_value, False
        if choice_label and (cleaned_value == choice_label or normalized_input == _normalize_token(choice_label)):
            return choice_value or choice_label, False

    return "", True


def _attribute_name_by_id(type_template: dict[str, Any] | None, attr_id: Any) -> str:
    if not type_template or attr_id in (None, ""):
        return ""
    try:
        wanted = int(attr_id)
    except Exception:
        return ""
    for item in _attribute_definitions(type_template):
        try:
            current = int(item.get("id"))
        except Exception:
            continue
        if current == wanted:
            return _clean_text(item.get("name"))
    return ""


def _collect_pending_choice_values(
    *,
    type_templates: dict[str, dict[str, Any]],
    ordered_records: list[dict[str, Any]],
) -> dict[tuple[str, str], list[dict[str, str]]]:
    type_name_by_id: dict[int, str] = {}
    records_by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for name, template in type_templates.items():
        try:
            type_id = int(template.get("id"))
        except Exception:
            continue
        type_name_by_id[type_id] = name
    for record in ordered_records:
        ci_type = _clean_text(record.get("ciType"))
        if ci_type:
            records_by_type[ci_type].append(record)

    pending: dict[tuple[str, str], list[dict[str, str]]] = {}
    for ci_type, type_template in type_templates.items():
        for item in _attribute_definitions(type_template):
            attr_name = _clean_text(item.get("name"))
            ref_attr_id = item.get("choice_reference_attr_id")
            ref_type_ids = item.get("choice_reference_type_ids") or []
            if not attr_name or not ref_attr_id or not ref_type_ids:
                continue
            collected: list[dict[str, str]] = []
            seen_values = {
                _clean_text(choice.get("value"))
                for choice in (item.get("choices") or [])
                if _clean_text(choice.get("value"))
            }
            for ref_type_id in ref_type_ids:
                try:
                    normalized_ref_type_id = int(ref_type_id)
                except Exception:
                    continue
                ref_type_name = type_name_by_id.get(normalized_ref_type_id)
                if not ref_type_name:
                    continue
                ref_template = type_templates.get(ref_type_name)
                ref_attr_name = _attribute_name_by_id(ref_template, ref_attr_id)
                if not ref_attr_name:
                    continue
                for record in records_by_type.get(ref_type_name, []):
                    record_attributes = record.get("attributes") or {}
                    value = _clean_text(record_attributes.get(ref_attr_name))
                    if not value:
                        resolved_name_key = _resolve_import_target_key(type_template=ref_template, canonical_field="name")
                        resolved_platform_key = _resolve_import_target_key(type_template=ref_template, canonical_field="platform")
                        resolved_project_key = _resolve_import_target_key(type_template=ref_template, canonical_field="project")
                        if ref_attr_name == resolved_name_key:
                            value = _clean_text(record_attributes.get("name")) or _clean_text(record.get("name"))
                        elif ref_attr_name == resolved_platform_key:
                            value = _clean_text(record_attributes.get("platform")) or _clean_text(record_attributes.get("project"))
                        elif ref_attr_name == resolved_project_key:
                            value = _clean_text(record_attributes.get("project")) or _clean_text(record_attributes.get("platform"))
                    if not value:
                        continue
                    if value in seen_values:
                        continue
                    seen_values.add(value)
                    collected.append({"value": value, "label": value})
            if collected:
                pending[(ci_type, attr_name)] = collected
    return pending


def _merge_pending_choice_value(
    pending: dict[tuple[str, str], list[dict[str, str]]],
    *,
    ci_type: str,
    attr_name: str,
    value: str,
) -> None:
    cleaned_value = _clean_text(value)
    if not ci_type or not attr_name or not cleaned_value:
        return
    key = (ci_type, attr_name)
    values = pending.setdefault(key, [])
    if any(_clean_text(item.get("value")) == cleaned_value for item in values if isinstance(item, dict)):
        return
    values.append({"value": cleaned_value, "label": cleaned_value})


def _collect_existing_reference_choice_values(
    client: VeopsCmdbClient,
    *,
    type_templates: dict[str, dict[str, Any]],
    ordered_records: list[dict[str, Any]],
) -> dict[tuple[str, str], list[dict[str, str]]]:
    type_name_by_id: dict[int, str] = {}
    for name, template in type_templates.items():
        try:
            type_name_by_id[int(template.get("id"))] = name
        except Exception:
            continue

    pending: dict[tuple[str, str], list[dict[str, str]]] = {}
    lookup_cache: dict[tuple[str, str, str], bool] = {}
    for record in ordered_records:
        ci_type = _clean_text(record.get("ciType"))
        type_template = type_templates.get(ci_type)
        if not ci_type or not type_template:
            continue
        for item in _attribute_definitions(type_template):
            attr_name = _clean_text(item.get("name"))
            ref_attr_id = item.get("choice_reference_attr_id")
            ref_type_ids = item.get("choice_reference_type_ids") or []
            if not attr_name or not ref_attr_id or not ref_type_ids:
                continue
            reference_value = _choice_reference_value_for_record(
                record=record,
                attr_name=attr_name,
                type_template=type_template,
            )
            if not reference_value:
                continue
            existing_values = {
                _clean_text(choice.get("value"))
                for choice in (item.get("choices") or [])
                if isinstance(choice, dict) and _clean_text(choice.get("value"))
            }
            if reference_value in existing_values:
                continue
            for ref_type_id in ref_type_ids:
                try:
                    ref_type_name = type_name_by_id.get(int(ref_type_id))
                except Exception:
                    ref_type_name = None
                ref_template = type_templates.get(ref_type_name or "")
                ref_attr_name = _attribute_name_by_id(ref_template, ref_attr_id)
                if not ref_type_name or not ref_attr_name:
                    continue
                cache_key = (ref_type_name, ref_attr_name, reference_value)
                if cache_key not in lookup_cache:
                    try:
                        rows = client.query_ci(
                            f"_type:{ref_type_name},{ref_attr_name}:{quote(reference_value, safe='._-:/')}",
                            count=1,
                        )
                    except Exception:
                        rows = []
                    lookup_cache[cache_key] = bool(rows)
                if lookup_cache[cache_key]:
                    _merge_pending_choice_value(
                        pending,
                        ci_type=ci_type,
                        attr_name=attr_name,
                        value=reference_value,
                    )
                    break
    return pending


def _merge_pending_choice_values(
    *sources: dict[tuple[str, str], list[dict[str, str]]] | None,
) -> dict[tuple[str, str], list[dict[str, str]]]:
    merged: dict[tuple[str, str], list[dict[str, str]]] = {}
    for source in sources:
        for key, values in (source or {}).items():
            ci_type, attr_name = key
            for item in values:
                if not isinstance(item, dict):
                    continue
                _merge_pending_choice_value(
                    merged,
                    ci_type=ci_type,
                    attr_name=attr_name,
                    value=_clean_text(item.get("value")) or _clean_text(item.get("label")),
                )
    return merged


def _choice_extras_for_attribute(
    *,
    ci_type: str,
    attribute_name: str,
    pending_choice_values: dict[tuple[str, str], list[dict[str, str]]] | None,
) -> list[dict[str, str]]:
    if not pending_choice_values or not ci_type or not attribute_name:
        return []
    return list(pending_choice_values.get((ci_type, attribute_name), []))


def _get_single_pending_choice_value(
    *,
    ci_type: str,
    attribute_name: str,
    pending_choice_values: dict[tuple[str, str], list[dict[str, str]]] | None,
) -> str:
    extras = _choice_extras_for_attribute(
        ci_type=ci_type,
        attribute_name=attribute_name,
        pending_choice_values=pending_choice_values,
    )
    values = [
        _clean_text(item.get("value"))
        for item in extras
        if isinstance(item, dict) and _clean_text(item.get("value"))
    ]
    unique_values = list(dict.fromkeys(values))
    if len(unique_values) == 1:
        return unique_values[0]
    return ""


def _runtime_choice_extras_for_attribute(
    *,
    ci_type: str,
    attribute_name: str,
    type_template: dict[str, Any] | None,
    source_attributes: dict[str, Any],
    pending_choice_values: dict[tuple[str, str], list[dict[str, str]]] | None,
) -> list[dict[str, str]]:
    return _choice_extras_for_attribute(
        ci_type=ci_type,
        attribute_name=attribute_name,
        pending_choice_values=pending_choice_values,
    )


def _normalize_cmdb_attribute_values(
    *,
    ci_type: str,
    type_template: dict[str, Any] | None,
    source_attributes: dict[str, Any],
    cmdb_attributes: dict[str, Any],
    pending_choice_values: dict[tuple[str, str], list[dict[str, str]]] | None = None,
) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in cmdb_attributes.items():
        attr_name = _clean_text(key)
        if not attr_name or value in (None, "", []):
            continue
        attribute_definition = _find_attribute_definition(type_template, attr_name)
        if isinstance(value, list):
            normalized_items: list[str] = []
            unresolved_choice = False
            for item in value:
                normalized_value, unresolved_choice = _normalize_choice_attribute_value(
                    attribute_definition=attribute_definition,
                    value=_clean_text(item),
                    extra_choices=_runtime_choice_extras_for_attribute(
                        ci_type=ci_type,
                        attribute_name=attr_name,
                        type_template=type_template,
                        source_attributes=source_attributes,
                        pending_choice_values=pending_choice_values,
                    ),
                )
                if unresolved_choice:
                    break
                if normalized_value:
                    normalized_items.append(normalized_value)
            if not unresolved_choice and normalized_items:
                normalized[attr_name] = normalized_items
            continue

        normalized_value, unresolved_choice = _normalize_choice_attribute_value(
            attribute_definition=attribute_definition,
            value=_clean_text(value),
            extra_choices=_runtime_choice_extras_for_attribute(
                ci_type=ci_type,
                attribute_name=attr_name,
                type_template=type_template,
                source_attributes=source_attributes,
                pending_choice_values=pending_choice_values,
            ),
        )
        if not unresolved_choice and normalized_value:
            normalized[attr_name] = normalized_value
    return normalized


def _split_deferred_self_referential_choice_attributes(
    *,
    ci_type: str,
    type_template: dict[str, Any] | None,
    source_attributes: dict[str, Any],
    cmdb_attributes: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not type_template:
        return cmdb_attributes, {}
    try:
        current_type_id = int(type_template.get("id"))
    except Exception:
        return cmdb_attributes, {}

    immediate = dict(cmdb_attributes)
    deferred: dict[str, Any] = {}
    for item in _attribute_definitions(type_template):
        attr_name = _clean_text(item.get("name"))
        ref_attr_id = item.get("choice_reference_attr_id")
        ref_type_ids = item.get("choice_reference_type_ids") or []
        if not attr_name or attr_name not in immediate or not ref_attr_id or current_type_id not in ref_type_ids:
            continue
        ref_attr_name = _attribute_name_by_id(type_template, ref_attr_id)
        if not ref_attr_name:
            continue
        ref_value = _clean_text(source_attributes.get(ref_attr_name))
        if not ref_value and ref_attr_name == _resolve_cmdb_attribute_name(type_template, "name"):
            ref_value = _clean_text(source_attributes.get(ref_attr_name)) or _clean_text(source_attributes.get("name"))
        if not ref_value:
            continue

        current_value = immediate.get(attr_name)
        if isinstance(current_value, list):
            matches_self = ref_value in {_clean_text(entry) for entry in current_value if _clean_text(entry)}
        else:
            matches_self = _clean_text(current_value) == ref_value
        if not matches_self:
            continue
        deferred[attr_name] = immediate.pop(attr_name)
    return immediate, deferred


def _build_cmdb_attributes(
    *,
    ci_type: str,
    canonical_attributes: dict[str, Any],
    type_template: dict[str, Any] | None,
    pending_choice_values: dict[tuple[str, str], list[dict[str, str]]] | None = None,
) -> dict[str, Any]:
    normalized_canonical_attributes = dict(canonical_attributes)
    type_name = _clean_text((type_template or {}).get("name"))
    project_value = _clean_text(normalized_canonical_attributes.get("project"))
    platform_value = _clean_text(normalized_canonical_attributes.get("platform"))
    if type_name != "project" and project_value and platform_value and project_value != platform_value:
        normalized_canonical_attributes.pop("platform", None)
    elif type_name != "project" and platform_value and _looks_like_os_or_runtime_value(platform_value):
        LOGGER.warning(
            "resource-import dropping suspicious platform value before CMDB write: ci_type=%s platform=%s project=%s attrs=%s",
            ci_type,
            platform_value,
            project_value,
            {
                key: _clean_text(value)
                for key, value in normalized_canonical_attributes.items()
                if _clean_text(value)
            },
        )
        normalized_canonical_attributes.pop("platform", None)

    attributes: dict[str, Any] = {}
    for key, value in normalized_canonical_attributes.items():
        cleaned_value = _clean_text(value)
        if not cleaned_value or key == "ci_type" or str(key).startswith("_"):
            continue
        target_key = _resolve_import_target_key(type_template=type_template, canonical_field=key)
        if not target_key or target_key == "ci_type":
            continue
        attribute_definition = _find_attribute_definition(type_template, target_key)
        if attribute_definition and attribute_definition.get("is_list"):
            raw_items = _split_reference_values(cleaned_value) or [cleaned_value]
            normalized_items: list[str] = []
            unresolved_choice = False
            extra_choices = _choice_extras_for_attribute(
                ci_type=ci_type,
                attribute_name=target_key,
                pending_choice_values=pending_choice_values,
            )
            extra_choices = _runtime_choice_extras_for_attribute(
                ci_type=ci_type,
                attribute_name=target_key,
                type_template=type_template,
                source_attributes=normalized_canonical_attributes,
                pending_choice_values=pending_choice_values,
            )
            for item in raw_items:
                normalized_value, unresolved_choice = _normalize_choice_attribute_value(
                    attribute_definition=attribute_definition,
                    value=item,
                    extra_choices=extra_choices,
                )
                if unresolved_choice:
                    break
                if normalized_value:
                    normalized_items.append(normalized_value)
            if unresolved_choice:
                continue
            if normalized_items:
                attributes[target_key] = normalized_items
            continue

        normalized_value, unresolved_choice = _normalize_choice_attribute_value(
            attribute_definition=attribute_definition,
            value=cleaned_value,
            extra_choices=_runtime_choice_extras_for_attribute(
                ci_type=ci_type,
                attribute_name=target_key,
                type_template=type_template,
                source_attributes=normalized_canonical_attributes,
                pending_choice_values=pending_choice_values,
            ),
        )
        if unresolved_choice:
            continue
        attributes[target_key] = normalized_value

    platform_key = _resolve_import_target_key(type_template=type_template, canonical_field="platform")
    platform_definition = _find_attribute_definition(type_template, platform_key)
    if (
        type_name != "project"
        and platform_key
        and platform_definition
        and not _clean_text(attributes.get(platform_key))
    ):
        single_platform_value = _get_single_pending_choice_value(
            ci_type=ci_type,
            attribute_name=platform_key,
            pending_choice_values=pending_choice_values,
        )
        if single_platform_value:
            normalized_value, unresolved_choice = _normalize_choice_attribute_value(
                attribute_definition=platform_definition,
                value=single_platform_value,
                extra_choices=_runtime_choice_extras_for_attribute(
                    ci_type=ci_type,
                    attribute_name=platform_key,
                    type_template=type_template,
                    source_attributes=normalized_canonical_attributes,
                    pending_choice_values=pending_choice_values,
                ),
            )
            if not unresolved_choice and normalized_value:
                attributes[platform_key] = normalized_value

    unique_key = _get_import_required_unique_key(type_template)
    if unique_key and not _clean_text(attributes.get(unique_key)):
        fallback_field = ""
        if _is_name_like_unique_key(unique_key):
            fallback_field = "name"
        elif _is_ip_like_unique_key(unique_key):
            fallback_field = "private_ip"
        elif _is_code_like_unique_key(unique_key):
            fallback_field = "asset_code"
        fallback_value = _clean_text(normalized_canonical_attributes.get(fallback_field)) if fallback_field else ""
        if fallback_value:
            attributes[unique_key] = fallback_value

    return _autofill_deterministic_cmdb_attributes(
        canonical_attributes=normalized_canonical_attributes,
        type_template=type_template,
        cmdb_attributes=attributes,
    )


def _build_import_record_debug_context(
    *,
    record: dict[str, Any],
    ci_type: str,
    import_action: str,
    source_attributes: dict[str, Any],
    cmdb_attributes: dict[str, Any],
    type_template: dict[str, Any] | None,
    existing_ci: dict[str, Any] | None = None,
    deferred_attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "previewKey": _clean_text(record.get("previewKey")),
        "name": _clean_text(record.get("name")),
        "rawCiType": _clean_text(record.get("ciType")),
        "resolvedCiType": ci_type,
        "importAction": import_action,
        "sourceRows": record.get("sourceRows") or [],
        "uniqueKey": _get_import_required_unique_key(type_template),
        "existingCi": existing_ci or {},
        "sourceAttributes": {
            key: value
            for key, value in source_attributes.items()
            if value not in (None, "", [])
        },
        "cmdbAttributes": {
            key: value
            for key, value in cmdb_attributes.items()
            if value not in (None, "", [])
        },
        "deferredAttributes": {
            key: value
            for key, value in (deferred_attributes or {}).items()
            if value not in (None, "", [])
        },
    }


def _build_relation_debug_context(
    *,
    relation: dict[str, Any],
    source_type: str,
    target_type: str,
    relation_type: str,
    source_ci_id: Any = None,
    target_ci_id: Any = None,
    allowed: bool | None = None,
) -> dict[str, Any]:
    return {
        "sourceKey": _clean_text(relation.get("sourceKey")),
        "targetKey": _clean_text(relation.get("targetKey")),
        "sourceType": source_type,
        "targetType": target_type,
        "relationType": relation_type,
        "sourceName": _clean_text(relation.get("sourceName")),
        "targetName": _clean_text(relation.get("targetName")),
        "reason": _clean_text(relation.get("reason")),
        "requiresModelRelation": bool(relation.get("requiresModelRelation")),
        "selected": bool(relation.get("selected", True)),
        "sourceCiId": source_ci_id,
        "targetCiId": target_ci_id,
        "allowed": allowed,
    }


def _build_preview_attributes(
    attributes: dict[str, Any],
    type_template: dict[str, Any] | None,
) -> dict[str, str]:
    preview_attributes: dict[str, str] = {}
    for key, value in attributes.items():
        cleaned_value = _clean_text(value)
        if not cleaned_value or key == "ci_type" or str(key).startswith("_"):
            continue
        target_key = _resolve_import_target_key(type_template=type_template, canonical_field=key)
        attr_definition = _find_attribute_definition(type_template, target_key)
        if attr_definition:
            preview_attributes.setdefault(target_key, cleaned_value)
            continue
        preview_attributes.setdefault(key, cleaned_value)
    return preview_attributes


def _resolve_record_display_name(
    attributes: dict[str, Any],
    type_template: dict[str, Any] | None,
) -> str:
    candidate_fields = [
        "name",
        "dev_name",
        _get_import_required_unique_key(type_template),
        "asset_code",
        "dev_no",
        "private_ip",
        "manage_ip",
    ]
    for field in candidate_fields:
        value = _clean_text(attributes.get(field))
        if value:
            return value
    return ""


def _build_record_issues(
    *,
    ci_type: str,
    attributes: dict[str, Any],
    mapping_preview: list[dict[str, Any]],
    existing_ci: dict[str, Any] | None,
    type_template: dict[str, Any] | None = None,
    pending_choice_values: dict[tuple[str, str], list[dict[str, str]]] | None = None,
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    def to_target_field(field_name: str) -> str:
        resolved = _resolve_import_target_key(type_template=type_template, canonical_field=field_name)
        return resolved or field_name

    confirmation_labels = _collect_confirmation_issues(
        ci_type,
        attributes,
        type_template=type_template,
    )
    label_to_field = {
        "名称": "name",
        "IP": "private_ip",
        "型号": "model",
        "版本": "version",
        "端口": "service_port",
        "部署节点": "deploy_target",
    }
    for label in confirmation_labels:
        issues.append(
            {
                "field": to_target_field(label_to_field.get(label, "")),
                "level": "warning",
                "message": f"{label}待确认",
            }
        )

    unique_key = _get_import_required_unique_key(type_template)
    cmdb_attributes = _build_cmdb_attributes(
        ci_type=ci_type,
        canonical_attributes=attributes,
        type_template=type_template,
        pending_choice_values=pending_choice_values,
    )
    if unique_key and not _clean_text(cmdb_attributes.get(unique_key)):
        target_field = "name"
        if _is_ip_like_unique_key(unique_key):
            target_field = "private_ip"
        elif _is_code_like_unique_key(unique_key):
            target_field = "asset_code"
        issues.append(
            {
                "field": to_target_field(target_field),
                "level": "warning",
                "message": f"唯一标识 {_resolve_attribute_label(type_template, unique_key)} 待确认",
            }
        )

    seen_mapping_fields: set[str] = set()
    for item in mapping_preview:
        target_field = _clean_text(item.get("targetField"))
        confidence = _clean_text(item.get("confidence"))
        source_field = _clean_text(item.get("sourceField"))
        status = _clean_text(item.get("status"))
        if status == "needs_confirmation":
            candidate_text = " / ".join(
                _clean_text(candidate.get("targetField"))
                for candidate in (item.get("candidates") or [])
                if _clean_text(candidate.get("targetField"))
            )
            issues.append(
                {
                    "field": "mapping",
                    "level": "warning",
                    "message": f"{source_field} 存在多语义候选（{candidate_text or '待确认'}），请人工确认后再导入",
                }
            )
            continue
        if target_field in {"", "unknown"} or confidence in {"", "high"} or target_field in seen_mapping_fields:
            continue
        seen_mapping_fields.add(target_field)
        issues.append(
            {
                "field": to_target_field(target_field),
                "level": "warning",
                "message": f"{source_field} 映射到 {target_field} 的置信度为 {confidence}",
            }
        )

    for canonical_field, raw_value in attributes.items():
        if canonical_field == "ci_type":
            continue
        cleaned_value = _clean_text(raw_value)
        if not cleaned_value:
            continue
        target_key = _resolve_import_target_key(type_template=type_template, canonical_field=canonical_field)
        attr_definition = _find_attribute_definition(type_template, target_key)
        normalized_value, unresolved_choice = _normalize_choice_attribute_value(
            attribute_definition=attr_definition,
            value=cleaned_value,
            extra_choices=_runtime_choice_extras_for_attribute(
                ci_type=ci_type,
                attribute_name=target_key,
                type_template=type_template,
                source_attributes=attributes,
                pending_choice_values=pending_choice_values,
            ),
        )
        if unresolved_choice:
            option_text = _format_choice_options(attr_definition)
            message = f"{_resolve_attribute_label(type_template, target_key)} 的值 {cleaned_value} 不在系统预定义值中，请手动确认"
            if option_text:
                message += f"。可选值：{option_text}"
            issues.append(
                {
                    "field": target_key or canonical_field,
                    "level": "warning",
                    "message": message,
                }
            )

    if existing_ci:
        match_field = _clean_text(existing_ci.get("matchField")) or "name"
        match_value = _clean_text(existing_ci.get("matchValue"))
        issues.append(
            {
                "field": "importAction",
                "level": "warning",
                "message": f"CMDB 中已存在匹配资源（{match_field}: {match_value}），请确认更新还是跳过",
            }
        )

    return issues


def _validate_required_cmdb_attributes(
    *,
    type_template: dict[str, Any] | None,
    source_attributes: dict[str, Any],
    cmdb_attributes: dict[str, Any],
    pending_choice_values: dict[tuple[str, str], list[dict[str, str]]] | None = None,
) -> list[str]:
    issues: list[str] = []
    ci_type = _clean_text((type_template or {}).get("name"))
    for item in _attribute_definitions(type_template):
        attr_name = _clean_text(item.get("name"))
        if not attr_name or not item.get("required"):
            continue
        if _is_system_generated_unique_key(type_template) and attr_name == _clean_text((type_template or {}).get("unique_key")):
            continue

        value = cmdb_attributes.get(attr_name)
        if isinstance(value, list):
            present = any(_clean_text(entry) for entry in value)
        else:
            present = bool(_clean_text(value))
        if present:
            continue

        raw_value = source_attributes.get(attr_name)
        if raw_value in (None, "") and attr_name == "platform":
            raw_value = source_attributes.get("project")
        raw_values: list[str] = []
        if isinstance(raw_value, list):
            raw_values = [_clean_text(entry) for entry in raw_value if _clean_text(entry)]
        else:
            cleaned_raw_value = _clean_text(raw_value)
            if cleaned_raw_value:
                raw_values = [cleaned_raw_value]

        label = _resolve_attribute_label(type_template, attr_name)
        option_text = _format_choice_options(item)
        if raw_values and item.get("is_choice"):
            message = f"{label} 的值 {' / '.join(raw_values)} 不在系统预定义值中"
            extra_choice_text = _format_choice_options(
                {
                    **item,
                    "choices": (item.get("choices") or [])
                    + _runtime_choice_extras_for_attribute(
                        ci_type=ci_type,
                        attribute_name=attr_name,
                        type_template=type_template,
                        source_attributes=source_attributes,
                        pending_choice_values=pending_choice_values,
                    ),
                }
            )
            option_text = extra_choice_text or option_text
            if option_text:
                message += f"，可选值：{option_text}"
            issues.append(message)
            continue

        message = f"缺少必填字段：{label}"
        if option_text:
            message += f"（可选值：{option_text}）"
        issues.append(message)
    return issues


def _snapshot_ci_attributes(
    record: dict[str, Any] | None,
    *,
    type_template: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(record, dict):
        return {}
    allowed_fields = {
        _clean_text(item.get("name"))
        for item in _attribute_definitions(type_template)
        if _clean_text(item.get("name"))
    }
    snapshot: dict[str, Any] = {}
    for key, value in record.items():
        field_name = _clean_text(key)
        if not field_name or field_name.startswith("_"):
            continue
        if field_name in {"ci_type", "ci_type_alias", "unique", "unique_alias"}:
            continue
        if allowed_fields and field_name not in allowed_fields:
            continue
        snapshot[field_name] = value
    return snapshot


def _selected_record_map(resource_groups: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for group in resource_groups:
        for record in (group.get("records") or []):
            if not isinstance(record, dict) or not record.get("selected", True):
                continue
            preview_key = str(record.get("previewKey") or "").strip()
            if preview_key:
                selected[preview_key] = record
    return selected


def _choice_reference_value_for_record(
    *,
    record: dict[str, Any],
    attr_name: str,
    type_template: dict[str, Any] | None,
) -> str:
    attributes = _merged_resource_attributes(record)
    direct_value = _clean_text(attributes.get(attr_name))
    if direct_value:
        return direct_value

    platform_key = _resolve_import_target_key(type_template=type_template, canonical_field="platform")
    project_key = _resolve_import_target_key(type_template=type_template, canonical_field="project")
    if attr_name == platform_key:
        return _first_non_empty_value(
            attributes.get("platform"),
            attributes.get("project"),
            attributes.get(platform_key),
            attributes.get(project_key),
        )
    if attr_name == project_key:
        return _first_non_empty_value(
            attributes.get("project"),
            attributes.get("platform"),
            attributes.get(project_key),
            attributes.get(platform_key),
        )
    return ""


def _reference_value_for_target_record(
    *,
    record: dict[str, Any],
    ref_attr_name: str,
    ref_template: dict[str, Any] | None,
) -> str:
    attributes = _merged_resource_attributes(record)
    value = _clean_text(attributes.get(ref_attr_name))
    if value:
        return value

    resolved_name_key = _resolve_import_target_key(type_template=ref_template, canonical_field="name")
    resolved_platform_key = _resolve_import_target_key(type_template=ref_template, canonical_field="platform")
    resolved_project_key = _resolve_import_target_key(type_template=ref_template, canonical_field="project")
    if ref_attr_name == resolved_name_key:
        return _first_non_empty_value(attributes.get("name"), record.get("name"))
    if ref_attr_name == resolved_platform_key:
        return _first_non_empty_value(attributes.get("platform"), attributes.get("project"))
    if ref_attr_name == resolved_project_key:
        return _first_non_empty_value(attributes.get("project"), attributes.get("platform"))
    return ""


def _add_choice_reference_dependencies(
    *,
    selected: dict[str, dict[str, Any]],
    type_templates: dict[str, dict[str, Any]],
    adjacency: dict[str, set[str]],
    indegree: dict[str, int],
) -> None:
    if not selected or not type_templates:
        return

    type_name_by_id: dict[int, str] = {}
    records_by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for name, template in type_templates.items():
        try:
            type_name_by_id[int(template.get("id"))] = name
        except Exception:
            continue
    for record in selected.values():
        ci_type = _clean_text(record.get("ciType"))
        if ci_type:
            records_by_type[ci_type].append(record)

    for preview_key, record in selected.items():
        ci_type = _clean_text(record.get("ciType"))
        type_template = type_templates.get(ci_type)
        if not ci_type or not type_template:
            continue
        for item in _attribute_definitions(type_template):
            attr_name = _clean_text(item.get("name"))
            ref_attr_id = item.get("choice_reference_attr_id")
            ref_type_ids = item.get("choice_reference_type_ids") or []
            if not attr_name or not ref_attr_id or not ref_type_ids:
                continue

            reference_value = _choice_reference_value_for_record(
                record=record,
                attr_name=attr_name,
                type_template=type_template,
            )

            matched_targets: list[str] = []
            for ref_type_id in ref_type_ids:
                try:
                    ref_type_name = type_name_by_id.get(int(ref_type_id))
                except Exception:
                    ref_type_name = None
                if not ref_type_name:
                    continue
                ref_template = type_templates.get(ref_type_name)
                ref_attr_name = _attribute_name_by_id(ref_template, ref_attr_id)
                if not ref_attr_name:
                    continue
                candidates = records_by_type.get(ref_type_name, [])
                if not candidates:
                    continue
                if reference_value:
                    for candidate in candidates:
                        candidate_key = str(candidate.get("previewKey") or "").strip()
                        if not candidate_key or candidate_key == preview_key:
                            continue
                        target_value = _reference_value_for_target_record(
                            record=candidate,
                            ref_attr_name=ref_attr_name,
                            ref_template=ref_template,
                        )
                        if target_value and _normalize_token(target_value) == _normalize_token(reference_value):
                            matched_targets.append(candidate_key)
                elif len(candidates) == 1:
                    candidate_key = str(candidates[0].get("previewKey") or "").strip()
                    if candidate_key and candidate_key != preview_key:
                        matched_targets.append(candidate_key)

            for target_key in list(dict.fromkeys(matched_targets)):
                targets = adjacency.setdefault(target_key, set())
                if preview_key in targets:
                    continue
                targets.add(preview_key)
                indegree[preview_key] = indegree.get(preview_key, 0) + 1
                indegree.setdefault(target_key, 0)


def _ordered_selected_records(
    resource_groups: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    *,
    type_templates: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    ordered_records: list[dict[str, Any]] = []
    selected = _selected_record_map(resource_groups)
    if not selected:
        return ordered_records

    original_order: dict[str, int] = {}
    for group in resource_groups:
        for record in (group.get("records") or []):
            preview_key = str(record.get("previewKey") or "").strip()
            if preview_key and preview_key in selected and preview_key not in original_order:
                original_order[preview_key] = len(original_order)

    adjacency: dict[str, set[str]] = {key: set() for key in selected}
    indegree: dict[str, int] = {key: 0 for key in selected}
    for relation in relations or []:
        if not isinstance(relation, dict) or not relation.get("selected", True):
            continue
        source_key = str(relation.get("sourceKey") or "").strip()
        target_key = str(relation.get("targetKey") or "").strip()
        if source_key not in selected or target_key not in selected or source_key == target_key:
            continue
        targets = adjacency.setdefault(source_key, set())
        if target_key in targets:
            continue
        targets.add(target_key)
        indegree[target_key] = indegree.get(target_key, 0) + 1
        indegree.setdefault(source_key, 0)

    _add_choice_reference_dependencies(
        selected=selected,
        type_templates=type_templates or {},
        adjacency=adjacency,
        indegree=indegree,
    )

    ready = sorted((key for key, degree in indegree.items() if degree == 0), key=lambda item: original_order.get(item, 10**9))
    ordered_keys: list[str] = []
    while ready:
        current = ready.pop(0)
        ordered_keys.append(current)
        for target in sorted(adjacency.get(current, set()), key=lambda item: original_order.get(item, 10**9)):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
                ready.sort(key=lambda item: original_order.get(item, 10**9))

    if len(ordered_keys) != len(selected):
        remaining = [key for key in selected if key not in ordered_keys]
        remaining.sort(key=lambda item: original_order.get(item, 10**9))
        ordered_keys.extend(remaining)

    return [selected[key] for key in ordered_keys]


def _build_structure_selected_model_map(preview: dict[str, Any] | None) -> dict[str, str]:
    structure_analysis = (preview or {}).get("structureAnalysis") or {}
    items = structure_analysis.get("items") or []
    if not isinstance(items, list):
        return {}

    resolved: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        selected_model_name = _clean_text(item.get("selectedModelName")) or _clean_text(item.get("suggestedModelName"))
        if not selected_model_name:
            continue
        for raw_key in (
            item.get("resourceCiType"),
            item.get("resourceLabel"),
            item.get("key"),
        ):
            normalized_key = _clean_text(raw_key)
            if normalized_key and normalized_key not in resolved:
                resolved[normalized_key] = selected_model_name
    return resolved


def _pick_existing_structure_model_name(
    *,
    current_model_name: str,
    resource_ci_type: str,
    raw_type_hints: list[str],
    semantic_plan: SemanticModelPlan,
    model_options: list[dict[str, Any]],
    type_templates: dict[str, dict[str, Any]],
) -> str:
    existing_names = [
        _clean_text(item.get("name"))
        for item in model_options
        if isinstance(item, dict) and item.get("existing", True) and _clean_text(item.get("name"))
    ]
    if not existing_names:
        return current_model_name

    existing_name_set = set(existing_names)
    preferred_names = [
        _clean_text(semantic_plan.best_model),
        _clean_text(current_model_name),
        _clean_text(resource_ci_type),
    ]
    for raw_hint in raw_type_hints:
        preferred_names.append(
            _resolve_payload_ci_type(
                raw_hint,
                type_templates=type_templates,
            )
        )

    for name in preferred_names:
        normalized_name = _clean_text(name)
        if normalized_name in existing_name_set:
            return normalized_name

    if len(existing_names) == 1:
        return existing_names[0]
    return current_model_name


def _resolve_payload_ci_type(
    raw_ci_type: Any,
    *,
    type_templates: dict[str, dict[str, Any]],
    structure_selected_model_map: dict[str, str] | None = None,
) -> str:
    ci_type = _clean_text(raw_ci_type)
    if not ci_type:
        return ""
    if ci_type in type_templates:
        return ci_type
    mapped_ci_type = _clean_text((structure_selected_model_map or {}).get(ci_type))
    if mapped_ci_type in type_templates:
        return mapped_ci_type
    alias_index = _build_type_alias_index(list(type_templates.values()))
    normalized_ci_type = _normalize_ci_type(ci_type, alias_index)
    if normalized_ci_type in type_templates:
        return normalized_ci_type

    normalized_text = _normalize_token(ci_type)
    semantic_candidates: list[tuple[int, str]] = []
    for rule in SEMANTIC_MODEL_RULES:
        preferred_models = [
            _clean_text(model_name)
            for model_name in (rule.get("preferred_models") or [])
            if _clean_text(model_name) in type_templates
        ]
        if not preferred_models:
            continue
        matched_score = 0
        for keyword in (rule.get("keywords") or []):
            normalized_keyword = _normalize_token(str(keyword))
            if normalized_keyword and normalized_keyword in normalized_text:
                matched_score = max(matched_score, len(normalized_keyword))
        if matched_score <= 0:
            continue
        semantic_candidates.append((matched_score, preferred_models[0]))
    if semantic_candidates:
        semantic_candidates.sort(key=lambda item: (-item[0], item[1]))
        return semantic_candidates[0][1]
    return ci_type


def _parallel_prefetch_existing_cis(
    client: VeopsCmdbClient | None,
    *,
    type_templates: dict[str, dict[str, Any]],
    ordered_records: list[dict[str, Any]],
    structure_selected_model_map: dict[str, str] | None,
    pending_choice_values: dict[tuple[str, str], list[dict[str, str]]] | None,
) -> dict[str, dict[str, Any]]:
    """Pre-fetch existing CMDB entries for every record in parallel.

    Returns a map keyed by ``previewKey``. Records whose ci_type/template
    can't be resolved are simply absent from the returned map; callers should
    treat a missing key as "not yet found in CMDB" and either re-query or
    fall back to the per-record ``existingCi`` snapshot from the preview.

    Both preflight and the main import loop call ``_find_existing_ci`` for
    the same set of records — running these in parallel up-front instead of
    serially per phase saves ~10s + ~10s on a ~45-record import.
    """
    if client is None or not ordered_records:
        return {}

    tasks: list[tuple[str, str, dict[str, Any], str, str]] = []
    for record in ordered_records:
        preview_key = str(record.get("previewKey") or "")
        if not preview_key:
            continue
        ci_type = _resolve_payload_ci_type(
            record.get("ciType"),
            type_templates=type_templates,
            structure_selected_model_map=structure_selected_model_map or {},
        )
        if not ci_type or ci_type == "unknown":
            continue
        type_template = type_templates.get(ci_type) or {}
        if not type_template:
            continue
        attributes = {
            key: value
            for key, value in _merged_resource_attributes(record).items()
            if _clean_text(value)
        }
        display_name = _clean_text(record.get("name")) or _resolve_record_display_name(
            attributes, type_template
        )
        if display_name and not _resolve_record_display_name(attributes, type_template):
            fallback_field = _resolve_cmdb_attribute_name(type_template, "name")
            if fallback_field and _find_attribute_definition(type_template, fallback_field):
                attributes[fallback_field] = display_name
        cmdb_attributes = _build_cmdb_attributes(
            ci_type=ci_type,
            canonical_attributes=attributes,
            type_template=type_template,
            pending_choice_values=pending_choice_values,
        )
        unique_key = _get_import_required_unique_key(type_template)
        tasks.append((preview_key, ci_type, cmdb_attributes, display_name, unique_key))

    if not tasks:
        return {}

    def _fetch(args: tuple[str, str, dict[str, Any], str, str]):
        preview_key, ci_type, cmdb_attrs, display_name, unique_key = args
        try:
            return preview_key, _find_existing_ci(
                client,
                ci_type,
                cmdb_attrs,
                fallback_name=display_name,
                unique_key=unique_key,
            ) or {}
        except Exception:
            return preview_key, {}

    # Always record every queried preview_key — even when the lookup returns
    # {} ("queried, not present in CMDB"). Callers distinguish "queried"
    # from "not queried" via key presence so the queried-but-empty case
    # avoids a redundant live re-fetch on the consumer side.
    result: dict[str, dict[str, Any]] = {}
    worker_count = min(_METADATA_FETCH_CONCURRENCY, max(1, len(tasks)))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        for preview_key, existing in executor.map(_fetch, tasks):
            result[preview_key] = existing
    return result


def _preflight_import_resources(
    client: VeopsCmdbClient,
    *,
    type_templates: dict[str, dict[str, Any]],
    ordered_records: list[dict[str, Any]],
    structure_selected_model_map: dict[str, str] | None = None,
    existing_ci_map: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    pending_choice_values = _merge_pending_choice_values(
        _collect_pending_choice_values(
            type_templates=type_templates,
            ordered_records=ordered_records,
        ),
        _collect_existing_reference_choice_values(
            client,
            type_templates=type_templates,
            ordered_records=ordered_records,
        ),
    )
    for record in ordered_records:
        import_action = _clean_text(record.get("importAction")) or "create"
        ci_type = _resolve_payload_ci_type(
            record.get("ciType"),
            type_templates=type_templates,
            structure_selected_model_map=structure_selected_model_map,
        )
        preview_key = record.get("previewKey")
        if not ci_type or ci_type == "unknown":
            LOGGER.warning(
                "resource-import preflight failed: %s",
                json.dumps(
                    {
                        "previewKey": _clean_text(preview_key),
                        "reason": "unknown_ci_type",
                        "rawCiType": _clean_text(record.get("ciType")),
                    },
                    ensure_ascii=False,
                    default=str,
                ),
            )
            results.append({"previewKey": preview_key, "status": "failed", "message": "资源类型未确认，无法导入"})
            continue

        type_template = type_templates.get(ci_type, {})
        if not type_template:
            LOGGER.warning(
                "resource-import preflight failed: %s",
                json.dumps(
                    {
                        "previewKey": _clean_text(preview_key),
                        "reason": "missing_type_template",
                        "rawCiType": _clean_text(record.get("ciType")),
                        "resolvedCiType": ci_type,
                    },
                    ensure_ascii=False,
                    default=str,
                ),
            )
            results.append({"previewKey": preview_key, "status": "failed", "message": f"目标模型 {ci_type} 不存在或尚未创建完成，当前不能导入"})
            continue

        attributes = {
            key: value
            for key, value in _merged_resource_attributes(record).items()
            if _clean_text(value)
        }
        display_name = _clean_text(record.get("name")) or _resolve_record_display_name(attributes, type_template)
        if display_name and not _resolve_record_display_name(attributes, type_template):
            fallback_field = _resolve_cmdb_attribute_name(type_template, "name")
            if fallback_field and _find_attribute_definition(type_template, fallback_field):
                attributes[fallback_field] = display_name

        cmdb_attributes = _build_cmdb_attributes(
            ci_type=ci_type,
            canonical_attributes=attributes,
            type_template=type_template,
            pending_choice_values=pending_choice_values,
        )
        unique_key = _get_import_required_unique_key(type_template)
        if not display_name and not _clean_text(cmdb_attributes.get(unique_key)):
            LOGGER.warning(
                "resource-import preflight failed: %s",
                json.dumps(
                    {
                        **_build_import_record_debug_context(
                            record=record,
                            ci_type=ci_type,
                            import_action=import_action,
                            source_attributes=attributes,
                            cmdb_attributes=cmdb_attributes,
                            type_template=type_template,
                        ),
                        "reason": "missing_display_name_and_unique_key",
                    },
                    ensure_ascii=False,
                    default=str,
                ),
            )
            results.append({"previewKey": preview_key, "status": "failed", "message": "缺少资源名称或模型唯一标识，无法导入"})
            continue
        if unique_key and not _clean_text(cmdb_attributes.get(unique_key)):
            LOGGER.warning(
                "resource-import preflight failed: %s",
                json.dumps(
                    {
                        **_build_import_record_debug_context(
                            record=record,
                            ci_type=ci_type,
                            import_action=import_action,
                            source_attributes=attributes,
                            cmdb_attributes=cmdb_attributes,
                            type_template=type_template,
                        ),
                        "reason": "missing_required_unique_key",
                    },
                    ensure_ascii=False,
                    default=str,
                ),
            )
            results.append({"previewKey": preview_key, "status": "failed", "message": f"缺少模型唯一标识字段：{_resolve_attribute_label(type_template, unique_key)}"})
            continue

        required_attribute_issues = _validate_required_cmdb_attributes(
            type_template=type_template,
            source_attributes=attributes,
            cmdb_attributes=cmdb_attributes,
            pending_choice_values=pending_choice_values,
        )
        if required_attribute_issues:
            LOGGER.warning(
                "resource-import preflight failed: %s",
                json.dumps(
                    {
                        **_build_import_record_debug_context(
                            record=record,
                            ci_type=ci_type,
                            import_action=import_action,
                            source_attributes=attributes,
                            cmdb_attributes=cmdb_attributes,
                            type_template=type_template,
                        ),
                        "reason": "missing_required_attributes",
                        "requiredIssues": required_attribute_issues,
                    },
                    ensure_ascii=False,
                    default=str,
                ),
            )
            results.append({"previewKey": preview_key, "status": "failed", "message": "；".join(required_attribute_issues)})
            continue

        preview_key_str = str(record.get("previewKey") or "")
        if existing_ci_map is not None and preview_key_str in existing_ci_map:
            existing_ci = existing_ci_map[preview_key_str] or (
                record.get("existingCi") or {}
            )
        else:
            existing_ci = _find_existing_ci(
                client,
                ci_type,
                cmdb_attributes,
                fallback_name=display_name,
                unique_key=unique_key,
            ) or (record.get("existingCi") or {})

        if existing_ci and import_action == "create":
            LOGGER.warning(
                "resource-import preflight failed: %s",
                json.dumps(
                    {
                        **_build_import_record_debug_context(
                            record=record,
                            ci_type=ci_type,
                            import_action=import_action,
                            source_attributes=attributes,
                            cmdb_attributes=cmdb_attributes,
                            type_template=type_template,
                            existing_ci=existing_ci,
                        ),
                        "reason": "existing_ci_conflict",
                    },
                    ensure_ascii=False,
                    default=str,
                ),
            )
            results.append({"previewKey": preview_key, "status": "failed", "ciId": existing_ci.get("ciId"), "message": "CMDB 中已存在匹配资源，请改为更新或跳过"})
            continue
        if not existing_ci and import_action == "update":
            LOGGER.warning(
                "resource-import preflight failed: %s",
                json.dumps(
                    {
                        **_build_import_record_debug_context(
                            record=record,
                            ci_type=ci_type,
                            import_action=import_action,
                            source_attributes=attributes,
                            cmdb_attributes=cmdb_attributes,
                            type_template=type_template,
                        ),
                        "reason": "missing_existing_ci_for_update",
                    },
                    ensure_ascii=False,
                    default=str,
                ),
            )
            results.append({"previewKey": preview_key, "status": "failed", "message": "CMDB 中未找到待更新资源，请改为新建或重新预览"})
            continue
    return results


def _split_reference_values(value: str) -> list[str]:
    raw = _clean_text(value)
    if not raw:
        return []
    parts = re.split(r"[;,；、/\n]+", raw)
    return [item.strip() for item in parts if item.strip() and item.strip() != "-"]


def _merged_resource_attributes(resource: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for source in (
        resource.get("attributes") or {},
        resource.get("analysisAttributes") or {},
        resource.get("sourceAttributes") or {},
    ):
        if not isinstance(source, dict):
            continue
        for field_name, field_value in source.items():
            if field_name not in merged:
                merged[field_name] = field_value
    return merged


def _build_confirmed_cmdb_attributes(
    *,
    record: dict[str, Any],
    type_template: dict[str, Any] | None,
) -> dict[str, Any]:
    confirmed = record.get("attributes") or {}
    if not isinstance(confirmed, dict):
        confirmed = {}

    allowed_attribute_names = _allowed_attribute_names(type_template)
    filtered: dict[str, Any] = {}
    for key, value in confirmed.items():
        field_name = _clean_text(key)
        if not field_name or field_name.startswith("_") or field_name == "ci_type":
            continue
        if allowed_attribute_names and field_name not in allowed_attribute_names:
            continue
        if value in (None, "", []):
            continue
        filtered[field_name] = value

    resolved_name_key = _resolve_import_target_key(type_template=type_template, canonical_field="name")
    display_name = _clean_text(record.get("name"))
    if (
        display_name
        and resolved_name_key
        and (not allowed_attribute_names or resolved_name_key in allowed_attribute_names)
        and not _clean_text(filtered.get(resolved_name_key))
    ):
        filtered[resolved_name_key] = display_name

    return filtered


def _build_reference_indexes(resources: list[dict[str, Any]]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    name_index: dict[str, list[str]] = defaultdict(list)
    ip_index: dict[str, list[str]] = defaultdict(list)
    for item in resources:
        name = _normalize_token(item.get("name"))
        if name:
            name_index[name].append(item["previewKey"])
        analysis_attributes = _merged_resource_attributes(item)
        private_ip = _clean_text(analysis_attributes.get("private_ip") or analysis_attributes.get("manage_ip"))
        if private_ip:
            ip_index[private_ip].append(item["previewKey"])
    return name_index, ip_index


def _find_reference_keys(
    value: str,
    *,
    name_index: dict[str, list[str]],
    ip_index: dict[str, list[str]],
) -> list[str]:
    matches: list[str] = []
    for token in _split_reference_values(value):
        normalized_name = _normalize_token(token)
        if normalized_name in name_index:
            matches.extend(name_index[normalized_name])
            continue
        normalized_ip, _ = _normalize_ip(token)
        if normalized_ip in ip_index:
            matches.extend(ip_index[normalized_ip])
    return list(dict.fromkeys(matches))


def _relation_lookup_tokens(value: Any) -> list[str]:
    tokens: list[str] = []
    for raw_token in _split_reference_values(_clean_text(value)) or [_clean_text(value)]:
        cleaned = _clean_text(raw_token)
        if not cleaned:
            continue
        normalized_text = _normalize_token(cleaned)
        if normalized_text:
            tokens.append(f"text::{normalized_text}")
        normalized_ip, _ = _normalize_ip(cleaned)
        if normalized_ip:
            tokens.append(f"ip::{normalized_ip}")
    return list(dict.fromkeys(tokens))


def _is_relation_lookup_field(field_name: str) -> bool:
    normalized = _normalize_token(field_name)
    if not normalized:
        return False
    if normalized in {
        "name",
        "assetcode",
        "privateip",
        "manageip",
        "pid",
        "project",
        "product",
        "department",
        "platform",
        "projectname",
        "devno",
        "devname",
        "dbinstance",
        "middlewarename",
        "vservername",
        "hostname",
    }:
        return True
    return any(token in normalized for token in ("name", "ip", "code", "instance", "host", "device", "resource", "id"))


def _build_resource_relation_lookup(
    resources: list[dict[str, Any]],
    type_templates: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    global_index: dict[str, list[str]] = defaultdict(list)
    type_index: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    field_index: dict[str, dict[str, dict[str, list[str]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

    def add_index(container: dict[str, list[str]], token: str, preview_key: str) -> None:
        if not token:
            return
        if preview_key not in container[token]:
            container[token].append(preview_key)

    for item in resources:
        preview_key = str(item.get("previewKey") or "")
        ci_type = _clean_text(item.get("ciType"))
        if not preview_key or not ci_type:
            continue
        type_template = type_templates.get(ci_type) or {}
        unique_key = _get_import_required_unique_key(type_template)
        candidate_fields: dict[str, Any] = {}

        if _clean_text(item.get("name")):
            candidate_fields["name"] = item.get("name")

        for source in (item.get("attributes") or {}, item.get("analysisAttributes") or {}):
            for field_name, field_value in source.items():
                if not _clean_text(field_name):
                    continue
                if field_name == unique_key or _is_relation_lookup_field(field_name):
                    candidate_fields.setdefault(field_name, field_value)

        for field_name, field_value in candidate_fields.items():
            for token in _relation_lookup_tokens(field_value):
                add_index(global_index, token, preview_key)
                add_index(type_index[ci_type], token, preview_key)
                add_index(field_index[ci_type][field_name], token, preview_key)

    return {
        "global": global_index,
        "by_type": type_index,
        "by_type_field": field_index,
    }


def _resolve_relation_reference_keys(
    value: Any,
    *,
    lookup: dict[str, Any],
    preferred_type: str = "",
    preferred_field: str | list[str] = "",
    allow_global_fallback: bool = True,
) -> list[str]:
    matches: list[str] = []
    tokens = _relation_lookup_tokens(value)
    if not tokens:
        return []

    if isinstance(preferred_field, str):
        preferred_fields = [_clean_text(preferred_field)] if _clean_text(preferred_field) else []
    else:
        preferred_fields = []
        for item in preferred_field:
            cleaned = _clean_text(item)
            if cleaned and cleaned not in preferred_fields:
                preferred_fields.append(cleaned)

    if preferred_type and preferred_fields:
        for field_name in preferred_fields:
            field_values = lookup["by_type_field"].get(preferred_type, {}).get(field_name, {})
            for token in tokens:
                matches.extend(field_values.get(token, []))
            if matches:
                return list(dict.fromkeys(matches))

    if preferred_type:
        type_values = lookup["by_type"].get(preferred_type, {})
        for token in tokens:
            matches.extend(type_values.get(token, []))
        if matches:
            return list(dict.fromkeys(matches))

    if not allow_global_fallback:
        return []

    for token in tokens:
        matches.extend(lookup["global"].get(token, []))
    return list(dict.fromkeys(matches))


def _infer_relation_type_for_models(
    source_type: str,
    target_type: str,
    type_templates: dict[str, dict[str, Any]],
) -> str:
    target_template = type_templates.get(target_type) or {}
    for parent in (target_template.get("parentTypes") or []):
        if _clean_text(parent.get("name")) == source_type:
            return _normalize_relation_type(parent.get("relationType")) or "contain"
    if source_type in {"project", "product", "Department"}:
        return "contain"
    if target_type in SOFTWARE_RESOURCE_TYPES and source_type in RESOURCE_DEPLOY_TYPES:
        return "deploy"
    return "connect"


def _candidate_parent_values(
    resource: dict[str, Any],
    parent_type: dict[str, Any],
) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    attributes = _merged_resource_attributes(resource)
    parent_name = _clean_text(parent_type.get("name"))
    show_key = _clean_text(parent_type.get("showKey")) or "name"
    child_attr_names = [
        _clean_text(item)
        for item in (parent_type.get("childAttrNames") or [])
        if _clean_text(item)
    ]

    candidate_fields = [*child_attr_names, show_key, parent_name]
    if parent_name == "project":
        candidate_fields.extend(["project", "platform", "project_name"])
    elif parent_name == "product":
        candidate_fields.extend(["product"])
    elif parent_name == "Department":
        candidate_fields.extend(["department"])

    normalized_show_key = _normalize_token(show_key)
    if "ip" in normalized_show_key:
        candidate_fields.extend(["deploy_target", "private_ip", "manage_ip", "host_ip"])
    elif any(token in normalized_show_key for token in ("id", "code", "instance", "name")):
        candidate_fields.extend(["deploy_target", "asset_code", "name", "host_name"])

    for field_name in candidate_fields:
        raw_value = attributes.get(field_name)
        for token in _split_reference_values(_clean_text(raw_value)):
            if token and token not in seen:
                seen.add(token)
                values.append(token)
    return values


def _parent_lookup_fields(parent_type: dict[str, Any]) -> list[str]:
    fields: list[str] = []
    for item in parent_type.get("parentAttrNames") or []:
        cleaned = _clean_text(item)
        if cleaned and cleaned not in fields:
            fields.append(cleaned)
    show_key = _clean_text(parent_type.get("showKey"))
    if show_key and show_key not in fields:
        fields.append(show_key)
    if not fields:
        fields.append("name")
    return fields


def _infer_parent_field_relations(
    resources: list[dict[str, Any]],
    relations: dict[tuple[str, str, str], dict[str, Any]],
    type_templates: dict[str, dict[str, Any]],
) -> None:
    lookup = _build_resource_relation_lookup(resources, type_templates)
    for item in resources:
        ci_type = _clean_text(item.get("ciType"))
        preview_key = str(item.get("previewKey") or "")
        if not ci_type or not preview_key:
            continue
        type_template = type_templates.get(ci_type) or {}
        for parent_type in (type_template.get("parentTypes") or []):
            parent_name = _clean_text(parent_type.get("name"))
            if not parent_name:
                continue
            relation_type = _normalize_relation_type(parent_type.get("relationType")) or _infer_relation_type_for_models(
                parent_name,
                ci_type,
                type_templates,
            )
            parent_lookup_fields = _parent_lookup_fields(parent_type)
            for candidate_value in _candidate_parent_values(item, parent_type):
                for parent_key in _resolve_relation_reference_keys(
                    candidate_value,
                    lookup=lookup,
                    preferred_type=parent_name,
                    preferred_field=parent_lookup_fields,
                    allow_global_fallback=False,
                ):
                    _append_relation(
                        relations,
                        source_key=parent_key,
                        target_key=preview_key,
                        relation_type=relation_type,
                        confidence="high",
                        reason=f"基于 {parent_name} 关联字段自动识别父子关系",
                    )


def _infer_explicit_relation_rows(
    relation_rows: list[dict[str, Any]],
    resources: list[dict[str, Any]],
    relations: dict[tuple[str, str, str], dict[str, Any]],
    type_templates: dict[str, dict[str, Any]],
) -> list[str]:
    lookup = _build_resource_relation_lookup(resources, type_templates)
    alias_index = _build_type_alias_index(list(type_templates.values()))
    warnings: list[str] = []

    for row in relation_rows:
        source_model = _normalize_ci_type(_clean_text(row.get("source_model")), alias_index)
        source_field = _clean_text(row.get("source_field"))
        source_value = _clean_text(row.get("source_value"))
        target_model = _normalize_ci_type(_clean_text(row.get("target_model")), alias_index)
        target_field = _clean_text(row.get("target_field"))
        target_value = _clean_text(row.get("target_value"))
        if source_model and source_field:
            source_canonical_field, _ = _match_field(source_field)
            source_field = _resolve_cmdb_attribute_name(
                type_templates.get(source_model),
                source_canonical_field if source_canonical_field != "unknown" else source_field,
            )
        if target_model and target_field:
            target_canonical_field, _ = _match_field(target_field)
            target_field = _resolve_cmdb_attribute_name(
                type_templates.get(target_model),
                target_canonical_field if target_canonical_field != "unknown" else target_field,
            )
        relation_type = _normalize_relation_type(row.get("relation_type")) or _infer_relation_type_for_models(
            source_model,
            target_model,
            type_templates,
        )

        source_matches = _resolve_relation_reference_keys(
            source_value,
            lookup=lookup,
            preferred_type=source_model,
            preferred_field=source_field,
        )
        target_matches = _resolve_relation_reference_keys(
            target_value,
            lookup=lookup,
            preferred_type=target_model,
            preferred_field=target_field,
        )

        row_label = (
            f"{row.get('filename') or ''} / {row.get('sheet') or ''} 第 {row.get('rowIndex') or ''} 行"
        ).strip(" /")
        if not source_matches or not target_matches:
            warnings.append(
                f"{row_label} 关系未能解析：源 {source_model or '?'}={source_value or '?'}，"
                f"目标 {target_model or '?'}={target_value or '?'}。"
            )
            continue
        if len(source_matches) > 1 or len(target_matches) > 1:
            warnings.append(
                f"{row_label} 关系解析存在歧义：源匹配 {len(source_matches)} 条，目标匹配 {len(target_matches)} 条，已跳过。"
            )
            continue
        resolved_source_type = source_model or _clean_text(
            next((item.get("ciType") for item in resources if item.get("previewKey") == source_matches[0]), "")
        )
        resolved_target_type = target_model or _clean_text(
            next((item.get("ciType") for item in resources if item.get("previewKey") == target_matches[0]), "")
        )
        configured_relation_type = _infer_relation_type_for_models(
            resolved_source_type,
            resolved_target_type,
            type_templates,
        )
        final_relation_type = configured_relation_type or relation_type or "contain"
        _append_relation(
            relations,
            source_key=source_matches[0],
            target_key=target_matches[0],
            relation_type=final_relation_type,
            confidence="high",
            reason="基于显式关系表识别",
        )

    return warnings


def _infer_existing_resource_relations(
    resources: list[dict[str, Any]],
    relations: dict[tuple[str, str, str], dict[str, Any]],
    type_templates: dict[str, dict[str, Any]],
) -> None:
    name_index, ip_index = _build_reference_indexes(resources)
    subnet_network_devices: dict[str, list[str]] = defaultdict(list)
    subnet_compute_resources: dict[str, list[str]] = defaultdict(list)
    resource_type_map = {
        str(item.get("previewKey")): _clean_text(item.get("ciType"))
        for item in resources
        if item.get("previewKey")
    }

    for item in resources:
        preview_key = item["previewKey"]
        ci_type = item["ciType"]
        attributes = _merged_resource_attributes(item)

        for target_key in _find_reference_keys(
            attributes.get("deploy_target") or attributes.get("host_name") or "",
            name_index=name_index,
            ip_index=ip_index,
        ):
            source_type = resource_type_map.get(target_key, "")
            relation_type = _infer_relation_type_for_models(
                source_type,
                ci_type,
                type_templates,
            ) or "deploy"
            _append_relation(
                relations,
                source_key=target_key,
                target_key=preview_key,
                relation_type=relation_type,
                confidence="high" if ci_type in SOFTWARE_RESOURCE_TYPES else "medium",
                reason="基于宿主机/部署节点字段建立部署关系",
            )

        for upstream_key in _find_reference_keys(
            attributes.get("upstream_resource", ""),
            name_index=name_index,
            ip_index=ip_index,
        ):
            _append_relation(
                relations,
                source_key=upstream_key,
                target_key=preview_key,
                relation_type="connect",
                confidence="high",
                reason="基于上联设备字段建立连接关系",
            )

        private_ip = _clean_text(attributes.get("private_ip"))
        if not private_ip:
            continue
        subnet = _infer_subnet("", private_ip)
        if not subnet:
            continue
        if ci_type == "networkdevice":
            subnet_network_devices[subnet].append(preview_key)
        elif ci_type in {"PhysicalMachine", "vserver"} | SOFTWARE_RESOURCE_TYPES:
            subnet_compute_resources[subnet].append(preview_key)

    for subnet, target_keys in subnet_compute_resources.items():
        if subnet not in subnet_network_devices:
            continue
        source_key = subnet_network_devices[subnet][0]
        for target_key in target_keys:
            _append_relation(
                relations,
                source_key=source_key,
                target_key=target_key,
                relation_type="connect",
                confidence="medium",
                reason=f"基于 {subnet} 网段自动推断网络连通关系",
            )


def _build_allowed_relation_rules(
    client: VeopsCmdbClient | None,
    type_templates: dict[str, dict[str, Any]],
    involved_types: set[str],
) -> set[tuple[str, str, str]]:
    if client is None or not involved_types:
        return set()

    type_ids: list[str] = []
    seen_ids: set[str] = set()
    for ci_type in involved_types:
        template = type_templates.get(ci_type) or {}
        type_id = str(template.get("id") or "").strip()
        if type_id and type_id not in seen_ids:
            seen_ids.add(type_id)
            type_ids.append(type_id)
    if not type_ids:
        return set()

    def _fetch(type_id: str) -> list[dict[str, Any]]:
        try:
            return client.get_ci_type_relations(type_id)
        except Exception:
            return []

    # Reuses the same concurrency knob as metadata loading. CMDB returns each
    # ci_type's relations as a separate REST call (typically ~700ms), so for
    # 9 distinct types this collapses ~6s of serial wait into ~1s.
    worker_count = min(_METADATA_FETCH_CONCURRENCY, max(1, len(type_ids)))
    relation_rules: set[tuple[str, str, str]] = set()
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        for relations in executor.map(_fetch, type_ids):
            for item in relations:
                parent_name = _clean_text((item.get("parent") or {}).get("name"))
                child_name = _clean_text((item.get("child") or {}).get("name"))
                relation_name = _clean_text(
                    ((item.get("relation_type") or {}).get("name"))
                    or item.get("relation_type_name")
                )
                if parent_name and child_name and relation_name:
                    relation_rules.add((parent_name, relation_name, child_name))
    return relation_rules


def _filter_supported_relations(
    relations: dict[tuple[str, str, str], dict[str, Any]],
    resources: list[dict[str, Any]],
    allowed_rules: set[tuple[str, str, str]],
) -> tuple[dict[tuple[str, str, str], dict[str, Any]], list[str]]:
    if not allowed_rules:
        return relations, []

    resource_type_map = {
        str(item.get("previewKey")): _clean_text(item.get("ciType"))
        for item in resources
        if item.get("previewKey")
    }
    filtered: dict[tuple[str, str, str], dict[str, Any]] = {}
    skipped_messages: list[str] = []
    for key, relation in relations.items():
        source_key = str(relation.get("sourceKey") or "")
        target_key = str(relation.get("targetKey") or "")
        relation_type = _clean_text(relation.get("relationType"))
        source_type = resource_type_map.get(source_key, "")
        target_type = resource_type_map.get(target_key, "")
        if (source_type, relation_type, target_type) in allowed_rules:
            filtered[key] = relation
            continue
        filtered[key] = {
            **relation,
            "selected": bool(relation.get("selected", True)),
            "requiresModelRelation": True,
            "reason": (
                f"{relation.get('reason') or '已识别关系'}；"
                f"CMDB 尚未配置 {source_type or '?'} -> {relation_type or '?'} -> {target_type or '?'}，"
                "导入时需先创建模型关系"
            ),
        }
        skipped_messages.append(
            f"待创建模型关系：{source_type or '?'} -> {relation_type or '?'} -> {target_type or '?'}"
        )
    return filtered, skipped_messages


def _prune_redundant_root_relations(
    relations: dict[tuple[str, str, str], dict[str, Any]],
    resources: list[dict[str, Any]],
) -> dict[tuple[str, str, str], dict[str, Any]]:
    resource_type_map = {
        str(item.get("previewKey")): _clean_text(item.get("ciType"))
        for item in resources
        if item.get("previewKey")
    }
    root_types = {"project", "product", "Department"}
    stronger_incoming_targets: set[str] = set()

    for relation in relations.values():
        source_key = str(relation.get("sourceKey") or "")
        target_key = str(relation.get("targetKey") or "")
        relation_type = _clean_text(relation.get("relationType"))
        source_type = resource_type_map.get(source_key, "")
        target_type = resource_type_map.get(target_key, "")
        if not target_key or not source_type or not target_type:
            continue
        if source_type in root_types:
            continue
        if relation_type in {"deploy", "install", "connect", "contain"}:
            stronger_incoming_targets.add(target_key)

    pruned: dict[tuple[str, str, str], dict[str, Any]] = {}
    for key, relation in relations.items():
        source_key = str(relation.get("sourceKey") or "")
        target_key = str(relation.get("targetKey") or "")
        relation_type = _clean_text(relation.get("relationType"))
        source_type = resource_type_map.get(source_key, "")
        target_type = resource_type_map.get(target_key, "")
        if (
            target_key in stronger_incoming_targets
            and source_type in root_types
            and target_type in SOFTWARE_RESOURCE_TYPES
            and relation_type in {"contain", "deploy"}
        ):
            continue
        pruned[key] = relation
    return pruned


def _ensure_selected_model_relations(
    client: VeopsCmdbClient,
    payload: dict[str, Any],
    *,
    type_templates: dict[str, dict[str, Any]],
    resource_type_map: dict[str, str],
    allowed_relation_rules: set[tuple[str, str, str]],
) -> tuple[set[tuple[str, str, str]], list[dict[str, Any]]]:
    ensured_rules = set(allowed_relation_rules)
    results: list[dict[str, Any]] = []
    pending_rules: dict[tuple[str, str, str], dict[str, str]] = {}

    for relation in payload.get("relations") or []:
        if not relation.get("selected", True):
            continue
        source_type = resource_type_map.get(str(relation.get("sourceKey") or ""), "")
        target_type = resource_type_map.get(str(relation.get("targetKey") or ""), "")
        relation_type = _clean_text(relation.get("relationType")) or "contain"
        if not source_type or not target_type:
            continue
        rule = (source_type, relation_type, target_type)
        if rule in ensured_rules:
            continue
        pending_rules.setdefault(
            rule,
            {
                "sourceType": source_type,
                "targetType": target_type,
                "relationType": relation_type,
            },
        )

    for source_type, relation_type, target_type in sorted(pending_rules.keys()):
        source_template = type_templates.get(source_type) or {}
        target_template = type_templates.get(target_type) or {}
        source_type_id = _extract_type_id(source_template.get("id"))
        target_type_id = _extract_type_id(target_template.get("id"))
        relation_type_id = client.relation_type_map.get(relation_type)

        if source_type_id is None or target_type_id is None:
            results.append(
                {
                    "kind": "relation-config",
                    "status": "failed",
                    "sourceType": source_type,
                    "targetType": target_type,
                    "relationType": relation_type,
                    "message": (
                        f"模型关系 {source_type} -> {relation_type} -> {target_type} 缺少模型 ID，"
                        "当前不能创建关系配置"
                    ),
                }
            )
            continue

        if relation_type_id is None:
            results.append(
                {
                    "kind": "relation-config",
                    "status": "failed",
                    "sourceType": source_type,
                    "targetType": target_type,
                    "relationType": relation_type,
                    "message": f"关系类型 {relation_type} 未在 CMDB 关系类型列表中找到，当前不能创建",
                }
            )
            continue

        try:
            relation_config_id, response = client.create_ci_type_relation(
                source_type_id,
                target_type_id,
                relation_type_id=relation_type_id,
                constraint="0",
            )
            ensured_rules.add((source_type, relation_type, target_type))
            results.append(
                {
                    "kind": "relation-config",
                    "status": "success",
                    "sourceType": source_type,
                    "targetType": target_type,
                    "relationType": relation_type,
                    "ctrId": relation_config_id or _extract_ci_type_relation_id(response),
                    "message": f"已创建模型关系 {source_type} -> {relation_type} -> {target_type}",
                }
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                {
                    "kind": "relation-config",
                    "status": "failed",
                    "sourceType": source_type,
                    "targetType": target_type,
                    "relationType": relation_type,
                    "message": f"创建模型关系失败：{exc}",
                }
            )

    return ensured_rules, results


async def preview_resource_import(
    parsed_files: list[ParsedFile],
    metadata: dict[str, Any],
    *,
    llm_client: Any | None = None,
    runtime_source: str = "",
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    model_templates = metadata.get("ciTypes") or DEFAULT_MODEL_TEMPLATES
    alias_index = _build_type_alias_index(model_templates)
    type_template_map = {
        str(item.get("name")): item
        for item in model_templates
        if isinstance(item, dict) and item.get("name")
    }
    managed_runtime = None
    managed_llm_client = llm_client
    if managed_llm_client is None:
        managed_runtime = await resolve_resource_import_runtime()
        managed_llm_client = managed_runtime.client
        if not runtime_source:
            runtime_source = managed_runtime.source
    field_stats: dict[tuple[str, str], int] = defaultdict(int)
    mapping_summary_entries: list[dict[str, Any]] = []
    cleaning_changes: Counter[str] = Counter()
    warnings: list[str] = []
    logs: list[str] = []
    analysis_issues: list[dict[str, str]] = []
    raw_resources: list[dict[str, Any]] = []
    explicit_relation_rows: list[dict[str, Any]] = []
    skipped_rows = 0
    raw_row_total = sum(len(parsed_file.rows) for parsed_file in parsed_files)
    existing_client: VeopsCmdbClient | None = None
    existing_detected_count = 0
    remaining_existing_prechecks = max(0, RESOURCE_IMPORT_PRECHECK_LIMIT)
    precheck_limit_hit = False
    total_sheet_count = sum(
        len({
            _clean_text(row.get("_sheet")) or "Sheet1"
            for row in parsed_file.rows
        })
        for parsed_file in parsed_files
    )
    processed_sheet_count = 0

    try:
        if runtime_source:
            logs.append(f"导入解析引擎：{runtime_source}")
            _emit_progress(
                progress_callback,
                stage="runtime",
                message=f"已切换到解析引擎：{runtime_source}",
                percent=4,
            )
        try:
            if remaining_existing_prechecks > 0:
                existing_client = VeopsCmdbClient.from_skill_env()
                existing_client.login()
                logs.append(
                    f"已连接 CMDB，预览阶段最多预检查 {remaining_existing_prechecks} 条资源是否已存在"
                )
                _emit_progress(
                    progress_callback,
                    stage="cmdb_precheck",
                    message=f"已连接 CMDB，预览阶段将抽样预检查 {remaining_existing_prechecks} 条资源",
                    percent=10,
                )
            else:
                logs.append("预览阶段已关闭存量校验，最终导入时会再次检查资源是否已存在")
        except Exception as exc:  # noqa: BLE001
            existing_client = None
            logs.append(f"CMDB 预检查不可用，将跳过存量校验：{exc}")
            _emit_progress(
                progress_callback,
                stage="cmdb_precheck",
                message=f"CMDB 预检查不可用，稍后导入前会再次校验：{exc}",
                percent=10,
            )

        sheet_work_items: list[dict[str, Any]] = []
        for parsed_file in parsed_files:
            warnings.extend(parsed_file.warnings)
            logs.extend(parsed_file.logs)

            rows_by_sheet: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
            for row_index, row in enumerate(parsed_file.rows, start=1):
                rows_by_sheet[_clean_text(row.get("_sheet")) or "Sheet1"].append((row_index, row))

            for sheet_name, sheet_rows in rows_by_sheet.items():
                sheet_work_items.append(
                    {
                        "filename": parsed_file.filename,
                        "sheetName": sheet_name,
                        "sheetRows": sheet_rows,
                    }
                )

        async def _resolve_sheet_work_item(index: int, item: dict[str, Any], semaphore: asyncio.Semaphore) -> dict[str, Any]:
            filename = str(item.get("filename") or "")
            sheet_name = str(item.get("sheetName") or "")
            sheet_rows = item.get("sheetRows") or []
            llm_target = "将调用 LLM 做字段语义映射"
            if not managed_llm_client:
                llm_target = "当前未连接 LLM，将使用规则映射兜底"
            _emit_progress(
                progress_callback,
                stage="sheet_mapping",
                message=(
                    f"正在解析 {filename} / {sheet_name} "
                    f"({index + 1}/{max(total_sheet_count, 1)})，{llm_target}"
                ),
                percent=12 + int(index / max(total_sheet_count, 1) * 60),
            )
            async with semaphore:
                plan, mapping_mode = await _resolve_sheet_mapping_plan(
                    sheet_name=sheet_name,
                    rows=[row for _, row in sheet_rows],
                    alias_index=alias_index,
                    model_templates=model_templates,
                    metadata=metadata,
                    llm_client=managed_llm_client,
                )
            return {
                **item,
                "index": index,
                "plan": plan,
                "mappingMode": mapping_mode,
            }

        if sheet_work_items:
            mapping_semaphore = asyncio.Semaphore(RESOURCE_IMPORT_LLM_SHEET_PARALLELISM)
            resolved_sheet_results = await asyncio.gather(
                *[
                    _resolve_sheet_work_item(index, item, mapping_semaphore)
                    for index, item in enumerate(sheet_work_items)
                ]
            )
        else:
            resolved_sheet_results = []

        if managed_llm_client and resolved_sheet_results:
            retryable_failed_sheets = [
                item
                for item in resolved_sheet_results
                if _is_retryable_blocking_mapping_mode(
                    str(item.get("mappingMode") or ""),
                    _clean_text((item.get("plan") or {}).sheet_kind if item.get("plan") else ""),
                )
            ]
            for retry_index, failed_sheet in enumerate(
                sorted(retryable_failed_sheets, key=lambda item: int(item.get("index") or 0)),
                start=1,
            ):
                parsed_filename = str(failed_sheet.get("filename") or "")
                sheet_name = str(failed_sheet.get("sheetName") or "")
                sheet_rows = failed_sheet.get("sheetRows") or []
                _emit_progress(
                    progress_callback,
                    stage="sheet_mapping_recovery",
                    message=(
                        f"关键 sheet 首轮解析失败，正在串行重试 {parsed_filename} / {sheet_name} "
                        f"({retry_index}/{len(retryable_failed_sheets)})"
                    ),
                    percent=56,
                )
                retry_plan, retry_mapping_mode = await _resolve_sheet_mapping_plan(
                    sheet_name=sheet_name,
                    rows=[row for _, row in sheet_rows],
                    alias_index=alias_index,
                    model_templates=model_templates,
                    metadata=metadata,
                    llm_client=managed_llm_client,
                    retry_count_override=RESOURCE_IMPORT_LLM_RETRY_COUNT + RESOURCE_IMPORT_LLM_BLOCKING_RECOVERY_RETRY_COUNT,
                )
                failed_sheet["plan"] = retry_plan
                failed_sheet["mappingMode"] = retry_mapping_mode

        for resolved_sheet in sorted(resolved_sheet_results, key=lambda item: int(item.get("index") or 0)):
            parsed_filename = str(resolved_sheet.get("filename") or "")
            sheet_name = str(resolved_sheet.get("sheetName") or "")
            sheet_rows = resolved_sheet.get("sheetRows") or []
            plan = resolved_sheet.get("plan")
            mapping_mode = str(resolved_sheet.get("mappingMode") or "规则映射")
            processed_sheet_count += 1
            logs.append(f"{parsed_filename} / {sheet_name}: {mapping_mode}")
            analysis_issue = _mapping_mode_to_analysis_issue(
                file_name=parsed_filename,
                sheet_name=sheet_name,
                mapping_mode=mapping_mode,
                sheet_kind=plan.sheet_kind,
            )
            if analysis_issue:
                analysis_issues.append(analysis_issue)
                warnings.append(str(analysis_issue.get("message") or ""))
            for detail in (plan.mapping_details or {}).values():
                non_empty_count = sum(
                    1 for _, row in sheet_rows
                    if _clean_text(row.get(_clean_text(detail.get("sourceField"))))
                )
                mapping_summary_entries.append(
                    {
                        "fileName": parsed_filename,
                        "sheetName": sheet_name,
                        "sourceField": _clean_text(detail.get("sourceField")),
                        "targetField": _clean_text(detail.get("targetField")),
                        "suggestedTargetField": _clean_text(detail.get("suggestedTargetField")),
                        "count": non_empty_count or len(sheet_rows),
                        "confidence": _clean_text(detail.get("confidence")) or "low",
                        "status": _clean_text(detail.get("status")) or "unmapped",
                        "resolvedBy": _clean_text(detail.get("resolvedBy")),
                        "candidates": detail.get("candidates") or [],
                        "message": _clean_text(detail.get("message")),
                        "needsConfirmation": bool(detail.get("needsConfirmation")),
                    }
                )
                if not detail.get("needsConfirmation"):
                    continue
                message = _clean_text(detail.get("message")) or "字段语义存在歧义，需人工确认"
                analysis_issues.append(
                    _build_analysis_issue(
                        kind="ambiguous_mapping",
                        severity="warning",
                        message=message,
                        file_name=parsed_filename,
                        sheet_name=sheet_name,
                    )
                )
                warnings.append(message)
            _emit_progress(
                progress_callback,
                stage="sheet_mapping",
                message=f"{parsed_filename} / {sheet_name}: {mapping_mode}",
                percent=12 + int(processed_sheet_count / max(total_sheet_count, 1) * 60),
            )

            if plan.sheet_kind == "note":
                skipped_rows += len(sheet_rows)
                logs.append(f"{parsed_filename} / {sheet_name}: 识别为说明页，已跳过 {len(sheet_rows)} 行")
                continue

            if plan.sheet_kind == "relation":
                relation_row_count = 0
                for row_index, row in sheet_rows:
                    standardized_relation: dict[str, Any] = {}
                    for raw_key, raw_value in row.items():
                        if raw_key == "_sheet":
                            continue
                        mapped_field, _confidence = plan.mappings.get(raw_key, _match_relation_field(raw_key))
                        if mapped_field != "unknown" and mapped_field in RELATION_FIELD_ALIASES and not standardized_relation.get(mapped_field):
                            standardized_relation[mapped_field] = _clean_text(raw_value)

                    if not _row_has_relation_signal(standardized_relation):
                        skipped_rows += 1
                        continue

                    explicit_relation_rows.append(
                        {
                            **standardized_relation,
                            "relation_type": _normalize_relation_type(standardized_relation.get("relation_type")),
                            "filename": parsed_filename,
                            "sheet": sheet_name,
                            "rowIndex": row_index,
                        }
                    )
                    relation_row_count += 1
                logs.append(f"{parsed_filename} / {sheet_name}: 识别为关系表，提取 {relation_row_count} 条关系候选")
                continue

            for row_index, row in sheet_rows:
                standardized: dict[str, Any] = {}
                source_attributes = _clean_source_attributes(row)
                mapping_preview: list[dict[str, Any]] = []
                for raw_key, raw_value in row.items():
                    if raw_key == "_sheet":
                        continue
                    detail = (plan.mapping_details or {}).get(raw_key) or {}
                    mapped_field, confidence = plan.mappings.get(raw_key, _match_field(raw_key))
                    target_field_for_stats = _clean_text(detail.get("suggestedTargetField")) or mapped_field
                    if target_field_for_stats != "unknown":
                        field_stats[(f"{parsed_filename} / {sheet_name} / {raw_key}", target_field_for_stats)] += 1
                    mapping_preview.append(
                        {
                            "sourceField": raw_key,
                            "targetField": _clean_text(detail.get("suggestedTargetField")) or mapped_field,
                            "confidence": confidence,
                            "status": _clean_text(detail.get("status")) or "mapped",
                            "resolvedBy": _clean_text(detail.get("resolvedBy")),
                            "candidates": detail.get("candidates") or [],
                            "message": _clean_text(detail.get("message")),
                            "needsConfirmation": bool(detail.get("needsConfirmation")),
                        }
                    )
                    effective_target_field = "" if detail.get("needsConfirmation") else mapped_field
                    if effective_target_field != "unknown" and effective_target_field and not standardized.get(effective_target_field):
                        standardized[effective_target_field] = _clean_text(raw_value)
                    elif detail.get("needsConfirmation") and _clean_text(raw_value):
                        standardized.setdefault("_ambiguous_fields", "")
                        ambiguous_field_name = _clean_text(raw_key)
                        current_ambiguous = [
                            item for item in standardized["_ambiguous_fields"].split(" / ")
                            if _clean_text(item)
                        ]
                        if ambiguous_field_name and ambiguous_field_name not in current_ambiguous:
                            current_ambiguous.append(ambiguous_field_name)
                        standardized["_ambiguous_fields"] = " / ".join(current_ambiguous)
                    if effective_target_field == "ci_type" and not standardized.get("_raw_ci_type_value"):
                        standardized["_raw_ci_type_value"] = _clean_text(raw_value)

                if not _row_has_resource_signal(standardized):
                    skipped_rows += 1
                    continue

                normalized_ip, ip_changed = _normalize_ip(standardized.get("private_ip", ""))
                if ip_changed:
                    cleaning_changes["IP地址标准化"] += 1
                if normalized_ip:
                    standardized["private_ip"] = normalized_ip

                normalized_status = _normalize_status(standardized.get("status", ""))
                if normalized_status and normalized_status != _clean_text(standardized.get("status", "")):
                    cleaning_changes["状态标准化"] += 1
                standardized["status"] = normalized_status

                normalized_port, port_changed, port_ambiguous = _normalize_service_port(standardized.get("service_port", ""))
                if port_changed:
                    cleaning_changes["端口标准化"] += 1
                if normalized_port:
                    standardized["service_port"] = normalized_port
                elif port_ambiguous:
                    standardized["service_port"] = ""
                    warnings.append(
                        f"{parsed_filename} / {sheet_name} 第 {row_index} 行端口值存在多个候选，已标记为待确认。"
                    )

                raw_type = _clean_text(standardized.get("ci_type"))
                normalized_type = _normalize_ci_type(raw_type, alias_index)
                if normalized_type and normalized_type != raw_type:
                    cleaning_changes["类型标准化"] += 1
                if not normalized_type and plan.default_ci_type:
                    normalized_type = plan.default_ci_type
                standardized["ci_type"] = normalized_type
                if normalized_type == "networkdevice" and not _clean_text(standardized.get("dev_class")):
                    raw_ci_type_value = _clean_text(standardized.get("_raw_ci_type_value"))
                    if raw_ci_type_value and raw_ci_type_value.lower() != "networkdevice":
                        standardized["dev_class"] = raw_ci_type_value

                if not standardized["ci_type"]:
                    warnings.append(f"{parsed_filename} / {sheet_name} 第 {row_index} 行未识别到资源类型，请在确认步骤手动选择。")

                type_template = type_template_map.get(standardized["ci_type"] or "")
                preview_attributes = _build_preview_attributes(standardized, type_template)
                display_name = _resolve_record_display_name(preview_attributes, type_template)
                if not display_name:
                    name_candidates = _semantic_source_candidates(
                        source_attributes,
                        semantic_kind="name",
                    )
                    if name_candidates:
                        display_name = name_candidates[0][2]
                if not display_name:
                    ip_candidates = _semantic_source_candidates(
                        source_attributes,
                        semantic_kind="ip",
                    )
                    if ip_candidates:
                        display_name = ip_candidates[0][2]
                if not display_name:
                    warnings.append(f"{parsed_filename} / {sheet_name} 第 {row_index} 行缺少资源名称/唯一标识，请在确认步骤手动补齐。")

                cmdb_attributes = _build_cmdb_attributes(
                    ci_type=standardized["ci_type"] or "unknown",
                    canonical_attributes=preview_attributes,
                    type_template=type_template,
                )
                unique_key = _get_import_required_unique_key(type_template)
                unique_key_label = _resolve_attribute_label(type_template, unique_key) if unique_key else ""
                if unique_key and not _clean_text(cmdb_attributes.get(unique_key)):
                    semantic_kind = (
                        "code" if _is_code_like_unique_key(unique_key_label or unique_key)
                        else "ip" if _is_ip_like_unique_key(unique_key_label or unique_key)
                        else "name" if _is_name_like_unique_key(unique_key_label or unique_key)
                        else ""
                    )
                    if semantic_kind:
                        source_candidates = _semantic_source_candidates(
                            source_attributes,
                            semantic_kind=semantic_kind,
                            unique_key=unique_key,
                            unique_key_label=unique_key_label,
                        )
                        if source_candidates and (
                            len(source_candidates) == 1 or source_candidates[0][0] > source_candidates[1][0]
                        ):
                            cmdb_attributes[unique_key] = source_candidates[0][2]
                autofill_hints = _collect_deterministic_autofill_hints(
                    canonical_attributes=preview_attributes,
                    type_template=type_template,
                    cmdb_attributes=cmdb_attributes,
                )
                existing_ci = None
                if existing_client and remaining_existing_prechecks > 0:
                    existing_ci = _find_existing_ci(
                        existing_client,
                        standardized["ci_type"] or "unknown",
                        cmdb_attributes,
                        fallback_name=display_name,
                        unique_key=_get_import_required_unique_key(type_template),
                    )
                    remaining_existing_prechecks -= 1
                elif existing_client and not precheck_limit_hit:
                    precheck_limit_hit = True
                    logs.append(
                        "预览资源较多，已跳过剩余存量校验；提交导入时会再次精确检查是否已存在。"
                    )
                    _emit_progress(
                        progress_callback,
                        stage="cmdb_precheck",
                        message="资源量较大，剩余存量校验已延后到正式导入阶段执行。",
                        percent=74,
                    )
                if existing_ci:
                    existing_detected_count += 1

                record_issues = _build_record_issues(
                    ci_type=standardized["ci_type"] or "unknown",
                    attributes=standardized,
                    mapping_preview=mapping_preview,
                    existing_ci=existing_ci,
                    type_template=type_template,
                )

                preview_key = _build_preview_key(parsed_filename, sheet_name, row_index)
                attributes = {
                    key: _clean_text(value)
                    for key, value in preview_attributes.items()
                    if key
                }

                raw_resources.append(
                    {
                        "previewKey": preview_key,
                        "name": display_name,
                        "ciType": standardized["ci_type"] or "unknown",
                        "status": standardized.get("status", ""),
                        "attributes": attributes,
                        "analysisAttributes": standardized,
                        "sourceAttributes": source_attributes,
                        "mapping": mapping_preview,
                        "autoFilledHints": autofill_hints,
                        "sourceRows": [
                            {
                                "filename": parsed_filename,
                                "sheet": sheet_name,
                                "rowIndex": row_index,
                            }
                        ],
                        "selected": True,
                        "generated": False,
                        "category": "resource",
                        "importAction": "update" if existing_ci else "create",
                        "existingCi": existing_ci,
                        "issues": record_issues,
                        "attentionFields": [
                            _clean_text(item.get("field"))
                            for item in record_issues
                            if _clean_text(item.get("field"))
                        ],
                    }
                )

                confirmation_issues = _collect_confirmation_issues(
                    standardized["ci_type"] or "unknown",
                    standardized,
                    type_template=type_template,
                )
                if confirmation_issues:
                    warnings.append(
                        f"{parsed_filename} / {sheet_name} 第 {row_index} 行仍需人工确认：{', '.join(confirmation_issues)}。"
                    )

        relations: dict[tuple[str, str, str], dict[str, Any]] = {}
        _emit_progress(
            progress_callback,
            stage="relation_inference",
            message="正在推断资源关系与拓扑连接",
            percent=82,
        )
        _infer_parent_field_relations(raw_resources, relations, type_template_map)
        warnings.extend(
            _infer_explicit_relation_rows(
                explicit_relation_rows,
                raw_resources,
                relations,
                type_template_map,
            )
        )
        _infer_existing_resource_relations(raw_resources, relations, type_template_map)
        allowed_relation_rules = _build_allowed_relation_rules(
            existing_client,
            type_template_map,
            {str(item.get("ciType") or "") for item in raw_resources if item.get("ciType")},
        )
        relations = _prune_redundant_root_relations(relations, raw_resources)
        relations, skipped_relation_messages = _filter_supported_relations(relations, raw_resources, allowed_relation_rules)
        logs.extend(skipped_relation_messages)
        preview_pending_choice_values = _collect_pending_choice_values(
            type_templates=type_template_map,
            ordered_records=raw_resources,
        )
        for item in raw_resources:
            type_template = type_template_map.get(_clean_text(item.get("ciType")))
            record_issues = _build_record_issues(
                ci_type=_clean_text(item.get("ciType")) or "unknown",
                attributes=item.get("analysisAttributes") or {},
                mapping_preview=item.get("mapping") or [],
                existing_ci=item.get("existingCi"),
                type_template=type_template,
                pending_choice_values=preview_pending_choice_values,
            )
            item["issues"] = record_issues
            item["attentionFields"] = [
                _clean_text(issue.get("field"))
                for issue in record_issues
                if _clean_text(issue.get("field"))
            ]
        resource_type_map = {
            str(item.get("previewKey")): _clean_text(item.get("ciType"))
            for item in raw_resources
            if item.get("previewKey")
        }
        resource_name_map = {
            str(item.get("previewKey")): _clean_text(item.get("name"))
            for item in raw_resources
            if item.get("previewKey")
        }

        grouped_resources: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in raw_resources:
            grouped_resources[item["ciType"]].append(item)

        _emit_progress(
            progress_callback,
            stage="structure_analysis",
            message="正在生成待确认的数据结构和模型归属建议",
            percent=91,
        )
        resource_groups = [
            {
                "ciType": ci_type,
                "label": _resolve_type_label(ci_type, model_templates),
                "count": len(items),
                "records": sorted(items, key=lambda item: (item["name"] == "", item["name"], item["previewKey"])),
            }
            for ci_type, items in sorted(grouped_resources.items(), key=lambda item: (-len(item[1]), item[0]))
        ]
        structure_analysis = await _build_structure_analysis(
            resource_groups,
            metadata,
            llm_client=managed_llm_client,
        )

        unknown_count = sum(1 for item in raw_resources if item["ciType"] == "unknown")
        attention_record_count = sum(
            1 for item in raw_resources if (item.get("issues") or [])
        )
        quality_penalty = unknown_count * 7 + len(warnings) * 2
        quality_score = max(48, min(100, 96 - quality_penalty))
        blocking_analysis_count = sum(
            1 for item in analysis_issues if _clean_text(item.get("severity")) == "blocking"
        )
        analysis_status = "blocking" if blocking_analysis_count else "ok"
        mapping_summary = mapping_summary_entries or [
            {
                "sourceField": source_field,
                "targetField": target_field,
                "suggestedTargetField": target_field,
                "count": count,
                "confidence": "high" if target_field != "unknown" else "low",
                "status": "mapped" if target_field != "unknown" else "unmapped",
                "resolvedBy": "rule",
                "candidates": [],
                "message": "",
                "needsConfirmation": False,
            }
            for (source_field, target_field), count in sorted(field_stats.items(), key=lambda item: (-item[1], item[0][0]))
        ]
        cleaning_summary = [
            {"label": label, "count": count}
            for label, count in cleaning_changes.items()
        ]
        if skipped_rows:
            cleaning_summary.append({"label": "已过滤非资产行", "count": skipped_rows})
        if existing_detected_count:
            cleaning_summary.append({"label": "检测到 CMDB 已存在资源", "count": existing_detected_count})
        if explicit_relation_rows:
            cleaning_summary.append({"label": "识别到显式关系行", "count": len(explicit_relation_rows)})

        _emit_progress(
            progress_callback,
            stage="finalizing",
            message="解析完成，正在整理预览结果",
            percent=98,
        )
        return {
            "summary": {
                "fileCount": len(parsed_files),
                "rawRowCount": raw_row_total,
                "resourceCount": len(raw_resources),
                "relationCount": len(relations),
                "qualityScore": quality_score,
                "autoCleaned": sum(cleaning_changes.values()),
                "needsConfirmation": max(attention_record_count, unknown_count) + len(warnings),
                "analysisIssueCount": len(analysis_issues),
                "blockingIssueCount": blocking_analysis_count,
            },
            "mappingSummary": mapping_summary,
            "cleaningSummary": cleaning_summary,
            "resourceGroups": resource_groups,
            "relations": [
                {
                    **relation,
                    "sourceType": resource_type_map.get(str(relation.get("sourceKey") or ""), ""),
                    "targetType": resource_type_map.get(str(relation.get("targetKey") or ""), ""),
                    "sourceName": resource_name_map.get(str(relation.get("sourceKey") or ""), ""),
                    "targetName": resource_name_map.get(str(relation.get("targetKey") or ""), ""),
                }
                for relation in relations.values()
            ],
            "ciTypeMetadata": {
                str(item.get("name")): item
                for item in model_templates
                if item.get("name")
            },
            # Snapshot the allowed-relation rules so import_preview_to_cmdb can
            # skip the second per-type get_ci_type_relations fan-out (~10s
            # serial HTTP for ~9 distinct ci_types). The set is serialized as
            # a list of [parent, relationType, child] triples and rebuilt on
            # the import side.
            "allowedRelationRules": sorted(
                [list(rule) for rule in allowed_relation_rules]
            ),
            "structureAnalysis": structure_analysis,
            "analysisStatus": analysis_status,
            "analysisIssues": analysis_issues,
            "logs": logs,
            "warnings": warnings,
        }
    finally:
        if existing_client:
            existing_client.close()
        if managed_llm_client and managed_llm_client is not llm_client:
            await managed_llm_client.aclose()


def _resolve_type_label(ci_type: str, model_templates: list[dict[str, Any]]) -> str:
    for template in model_templates:
        if template.get("name") == ci_type:
            return str(template.get("alias") or ci_type)
    return ci_type


def _normalize_group_snapshot(group: dict[str, Any]) -> dict[str, Any]:
    ci_types: list[dict[str, Any]] = []
    for item in (group.get("ci_types") or group.get("ciTypes") or []):
        if not isinstance(item, dict):
            continue
        name = _clean_text(item.get("name"))
        if not name:
            continue
        ci_types.append(
            {
                "id": item.get("id"),
                "name": name,
                "alias": _clean_text(item.get("alias")) or name,
            }
        )
    return {
        "id": group.get("id"),
        "name": _clean_text(group.get("name")),
        "ciTypes": ci_types,
    }


def _build_default_ci_type_groups(model_templates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in model_templates:
        name = _clean_text(item.get("name"))
        if not name:
            continue
        group_name = DEFAULT_GROUP_HINTS.get(name, "未分组")
        grouped[group_name].append(
            {
                "id": item.get("id"),
                "name": name,
                "alias": _clean_text(item.get("alias")) or name,
            }
        )
    return [
        {"id": None, "name": group_name, "ciTypes": sorted(ci_types, key=lambda ci: ci["name"])}
        for group_name, ci_types in sorted(grouped.items(), key=lambda item: item[0])
    ]


def _find_groups_for_model(ci_type_groups: list[dict[str, Any]], ci_type: str) -> list[dict[str, Any]]:
    target = _clean_text(ci_type)
    if not target:
        return []
    matched: list[dict[str, Any]] = []
    for group in ci_type_groups:
        for item in group.get("ciTypes") or []:
            if _clean_text(item.get("name")) == target:
                matched.append(group)
                break
    return matched


def _collect_raw_type_hints(records: list[dict[str, Any]]) -> list[str]:
    hints: list[str] = []
    for record in records:
        analysis_attributes = record.get("analysisAttributes") or {}
        raw_hint = _clean_text(analysis_attributes.get("_raw_ci_type_value"))
        if raw_hint and raw_hint not in hints:
            hints.append(raw_hint)
    return hints


def _is_generic_server_hint(raw_hints: list[str]) -> bool:
    for hint in raw_hints:
        lowered = _clean_text(hint).lower()
        if any(token in lowered for token in ("vserver", "虚拟机", "虚机", "vm")):
            continue
        if any(token in lowered for token in ("physicalmachine", "物理机", "裸机", "baremetal")):
            continue
        if any(token in lowered for token in ("server", "服务器", "主机")):
            return True
    return False


async def _build_structure_analysis(
    resource_groups: list[dict[str, Any]],
    metadata: dict[str, Any],
    *,
    llm_client: Any | None = None,
) -> dict[str, Any]:
    ci_type_groups = [
        _normalize_group_snapshot(item)
        for item in (metadata.get("ciTypeGroups") or [])
        if isinstance(item, dict)
    ]
    if not ci_type_groups:
        ci_type_groups = _build_default_ci_type_groups(metadata.get("ciTypes") or DEFAULT_MODEL_TEMPLATES)

    ci_type_meta = {
        _clean_text(item.get("name")): item
        for item in (metadata.get("ciTypes") or [])
        if isinstance(item, dict) and _clean_text(item.get("name"))
    }
    ci_type_catalog = _build_ci_type_catalog(metadata)
    catalog_by_name = {
        _clean_text(item.get("name")): item
        for item in ci_type_catalog
        if _clean_text(item.get("name"))
    }

    default_semantic_plan = SemanticModelPlan(
        best_model="",
        confidence="low",
        reason="",
        candidates=[],
        source="heuristic",
    )
    group_contexts: list[dict[str, Any]] = []
    semantic_plan_by_index: dict[int, SemanticModelPlan] = {}
    semantic_semaphore = asyncio.Semaphore(RESOURCE_IMPORT_LLM_SHEET_PARALLELISM)

    async def _resolve_group_semantic_plan(
        index: int,
        group: dict[str, Any],
    ) -> tuple[int, SemanticModelPlan]:
        async with semantic_semaphore:
            return index, await _infer_semantic_model_plan(
                group=group,
                metadata=metadata,
                llm_client=llm_client,
            )

    semantic_tasks: list[Any] = []
    for index, group in enumerate(resource_groups):
        resource_ci_type = _clean_text(group.get("ciType"))
        records = group.get("records") or []
        raw_type_hints = _collect_raw_type_hints(records)
        exact_groups = _find_groups_for_model(ci_type_groups, resource_ci_type)
        group_contexts.append(
            {
                "group": group,
                "resource_ci_type": resource_ci_type,
                "records": records,
                "raw_type_hints": raw_type_hints,
                "exact_groups": exact_groups,
            }
        )
        if _should_run_semantic_inference(resource_ci_type or "unknown", exact_groups, raw_type_hints):
            semantic_tasks.append(_resolve_group_semantic_plan(index, group))

    if semantic_tasks:
        semantic_results = await asyncio.gather(*semantic_tasks)
        semantic_plan_by_index.update(dict(semantic_results))

    items: list[dict[str, Any]] = []
    for index, context in enumerate(group_contexts):
        group = context["group"]
        resource_ci_type = context["resource_ci_type"]
        records = context["records"]
        raw_type_hints = context["raw_type_hints"]
        exact_groups = context["exact_groups"]
        suggested_group_name = DEFAULT_GROUP_HINTS.get(resource_ci_type, "")
        status = "matched"
        reason = ""
        selected_group_name = ""
        selected_model_name = resource_ci_type
        create_group_approved = False
        create_model_approved = False
        needs_confirmation = False
        group_option_map = {
            _clean_text(item.get("name")): {
                "id": item.get("id"),
                "name": _clean_text(item.get("name")),
                "existing": True,
            }
            for item in exact_groups
            if _clean_text(item.get("name"))
        }
        model_option_map: dict[str, dict[str, Any]] = {}

        def add_model_option(model_name: str, *, group_name: str = "") -> None:
            normalized_name = _clean_text(model_name)
            if not normalized_name:
                return
            catalog_item = catalog_by_name.get(normalized_name)
            if catalog_item:
                resolved_group_name = group_name or _clean_text(catalog_item.get("groupName"))
                model_option_map[normalized_name] = {
                    "id": catalog_item.get("id"),
                    "name": normalized_name,
                    "alias": _clean_text(catalog_item.get("alias")) or normalized_name,
                    "groupName": resolved_group_name,
                    "existing": True,
                }
                if resolved_group_name and resolved_group_name not in group_option_map:
                    group_option_map[resolved_group_name] = {
                        "id": None,
                        "name": resolved_group_name,
                        "existing": True,
                    }
                return
            model_meta = ci_type_meta.get(normalized_name) or {}
            resolved_group_name = group_name or DEFAULT_GROUP_HINTS.get(normalized_name, "")
            model_option_map[normalized_name] = {
                "id": model_meta.get("id"),
                "name": normalized_name,
                "alias": _clean_text(model_meta.get("alias")) or normalized_name,
                "groupName": resolved_group_name,
                "existing": True,
            }

        for exact_group in exact_groups:
            exact_group_name = _clean_text(exact_group.get("name"))
            for model in (exact_group.get("ciTypes") or []):
                add_model_option(_clean_text(model.get("name")), group_name=exact_group_name)

        semantic_plan = semantic_plan_by_index.get(index, default_semantic_plan)
        for candidate in semantic_plan.candidates or []:
            add_model_option(
                _clean_text(candidate.get("name")),
                group_name=_clean_text(candidate.get("groupName")),
            )

        generic_server_ambiguous = (
            _is_generic_server_hint(raw_type_hints)
            and any(_clean_text(group_item.get("name")) for group_item in exact_groups)
            and any(
                {"PhysicalMachine", "vserver"}.issubset(
                    {_clean_text(item.get("name")) for item in (group_item.get("ciTypes") or [])}
                )
                for group_item in exact_groups
            )
        )
        semantic_best_model = _clean_text(semantic_plan.best_model)
        semantic_best_catalog = catalog_by_name.get(semantic_best_model)

        if generic_server_ambiguous:
            status = "ambiguous_model"
            needs_confirmation = True
            selected_group_name = _clean_text(exact_groups[0].get("name")) if exact_groups else _clean_text(
                (semantic_best_catalog or {}).get("groupName")
            )
            selected_model_name = semantic_best_model or (resource_ci_type if resource_ci_type in {"PhysicalMachine", "vserver"} else "")
            model_option_map = {}
            add_model_option("PhysicalMachine", group_name=selected_group_name)
            add_model_option("vserver", group_name=selected_group_name)
            reason = (
                "源数据只表达了“服务器/主机”这一类通用语义，"
                "当前系统同时存在 PhysicalMachine 和 vserver，需要人工确认最终模型。"
            )
        elif semantic_best_catalog:
            selected_group_name = _clean_text(semantic_best_catalog.get("groupName"))
            selected_model_name = semantic_best_model
            reason = semantic_plan.reason or f"根据语义线索建议使用现有模型 {selected_model_name}。"
            if semantic_plan.confidence == "high":
                status = "matched"
                needs_confirmation = False
            elif semantic_plan.confidence == "medium":
                status = "ambiguous_model"
                needs_confirmation = True
            elif _has_clear_low_confidence_leader(semantic_plan):
                status = "ambiguous_model"
                needs_confirmation = True
                reason = (
                    f"现有模型 {semantic_best_model} 是当前最接近的候选，但整体置信度仍偏低，"
                    "请人工确认后再继续。"
                )
            else:
                status = "missing_model" if selected_group_name else "missing_group"
                needs_confirmation = True
                selected_model_name = resource_ci_type or _clean_text(group.get("label")) or selected_model_name
                reason = (
                    f"现有模型 {semantic_best_model} 仅为低置信候选，系统不会直接套用。"
                    f"{'建议先确认是否新建模型，或手动改选现有模型。' if selected_group_name else '当前也未锁定合适分组，请先确认是否新建分组。'}"
                )
        elif resource_ci_type == "unknown":
            status = "unknown"
            reason = "当前资源尚未识别出可用模型，请先确认模型归属。"
            needs_confirmation = True
        elif exact_groups:
            selected_group_name = _clean_text(exact_groups[0].get("name"))
            add_model_option(resource_ci_type, group_name=selected_group_name)
            reason = f"已在现有分组 {selected_group_name} 中找到模型 {resource_ci_type}。"
        else:
            hinted_group = next(
                (
                    item for item in ci_type_groups
                    if _clean_text(item.get("name")) == suggested_group_name
                ),
                None,
            )
            if hinted_group:
                status = "missing_model"
                selected_group_name = _clean_text(hinted_group.get("name"))
                needs_confirmation = True
                reason = f"建议归入现有分组 {selected_group_name}，但未找到可直接复用的模型 {resource_ci_type}。"
                group_option_map[selected_group_name] = {
                    "id": hinted_group.get("id"),
                    "name": selected_group_name,
                    "existing": True,
                }
            else:
                status = "missing_group"
                selected_group_name = suggested_group_name or _clean_text(group.get("label"))
                needs_confirmation = True
                reason = (
                    f"建议为当前资源创建分组 {selected_group_name}。"
                    if selected_group_name
                    else "当前资源未匹配到合适分组，需要人工确认是否新建分组。"
                )

        if not selected_model_name:
            selected_model_name = resource_ci_type or _clean_text(group.get("label"))
        if status == "missing_model":
            model_meta = ci_type_meta.get(resource_ci_type) or {}
            selected_model_name = resource_ci_type or _clean_text(model_meta.get("alias")) or _clean_text(group.get("label"))
        if status == "missing_group":
            create_group_approved = False
        if status == "missing_model":
            create_model_approved = False

        group_options = sorted(group_option_map.values(), key=lambda item: item["name"])
        model_options = sorted(model_option_map.values(), key=lambda item: item["name"])
        if not model_options and selected_model_name:
            add_model_option(selected_model_name, group_name=selected_group_name)
            model_options = sorted(model_option_map.values(), key=lambda item: item["name"])

        resolved_existing_model_name = _pick_existing_structure_model_name(
            current_model_name=selected_model_name,
            resource_ci_type=resource_ci_type,
            raw_type_hints=raw_type_hints,
            semantic_plan=semantic_plan,
            model_options=model_options,
            type_templates=ci_type_meta,
        )
        if resolved_existing_model_name and resolved_existing_model_name != selected_model_name:
            selected_model_name = resolved_existing_model_name
            if status == "missing_model":
                status = "ambiguous_model"
                needs_confirmation = True
                reason = (
                    f"原始类型暂未能直接锁定模型，已结合现有模型候选优先推荐 {selected_model_name}，"
                    "请确认后再导入。"
                )

        items.append(
            {
                "key": resource_ci_type or _clean_text(group.get("label")) or f"group-{len(items) + 1}",
                "resourceCiType": resource_ci_type,
                "resourceLabel": _clean_text(group.get("label")) or resource_ci_type or "待确认模型",
                "recordCount": int(group.get("count") or len(records)),
                "status": status,
                "reason": reason,
                "originalTypeText": raw_type_hints[0] if raw_type_hints else resource_ci_type or _clean_text(group.get("label")),
                "rawTypeHints": raw_type_hints,
                "semanticConfidence": (
                    semantic_plan.confidence
                    if semantic_plan.best_model
                    else "high"
                    if status == "matched" and exact_groups
                    else "low"
                ),
                "suggestedGroupName": selected_group_name,
                "suggestedModelName": selected_model_name,
                "selectedGroupName": selected_group_name,
                "selectedModelName": selected_model_name,
                "createGroupApproved": create_group_approved,
                "createModelApproved": create_model_approved,
                "needsConfirmation": needs_confirmation,
                "groupOptions": group_options,
                "modelOptions": model_options,
            }
        )

    return {"items": items}


def _extract_choice_definitions(attribute: dict[str, Any]) -> list[dict[str, str]]:
    choices: list[dict[str, str]] = []
    for choice in (attribute.get("choice_value") or []):
        if not isinstance(choice, (list, tuple)) or not choice:
            continue
        raw_value = _clean_text(choice[0])
        raw_meta = choice[1] if len(choice) > 1 and isinstance(choice[1], dict) else {}
        raw_label = _clean_text(raw_meta.get("label")) or raw_value
        if raw_value:
            choices.append({"value": raw_value, "label": raw_label})
    return choices


def _extract_choice_reference_definition(attribute: dict[str, Any]) -> tuple[Any, list[Any]]:
    choice_other = attribute.get("choice_other")
    if not isinstance(choice_other, dict):
        return None, []

    attr_id = choice_other.get("attr_id")
    if attr_id in (None, ""):
        attr_id = choice_other.get("id")

    raw_type_ids = choice_other.get("type_ids")
    if raw_type_ids in (None, ""):
        raw_type_ids = choice_other.get("type_id")

    normalized_type_ids: list[Any] = []
    if isinstance(raw_type_ids, list):
        normalized_type_ids = [item for item in raw_type_ids if item not in (None, "")]
    elif raw_type_ids not in (None, ""):
        normalized_type_ids = [raw_type_ids]

    return attr_id, normalized_type_ids


def _attribute_names_from_ids(
    attributes: list[dict[str, Any]] | None,
    attr_ids: list[Any] | None,
) -> list[str]:
    if not attributes or not attr_ids:
        return []
    wanted = {int(item) for item in attr_ids if str(item).strip().isdigit()}
    names: list[str] = []
    for attr in attributes:
        attr_id = attr.get("id")
        try:
            normalized_id = int(attr_id)
        except Exception:
            continue
        if normalized_id not in wanted:
            continue
        name = _clean_text(attr.get("name"))
        if name and name not in names:
            names.append(name)
    return names


def _merge_attribute_definitions(
    attributes: list[dict[str, Any]],
    preference_attributes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    definitions: dict[str, dict[str, Any]] = {}
    preferred_order = {
        _clean_text(item.get("name")): index
        for index, item in enumerate(preference_attributes)
        if _clean_text(item.get("name"))
    }

    for index, attr in enumerate(attributes):
        name = _clean_text(attr.get("name"))
        if not name:
            continue
        choice_reference_attr_id, choice_reference_type_ids = _extract_choice_reference_definition(attr)
        definitions[name] = {
            "id": attr.get("id"),
            "name": name,
            "alias": _clean_text(attr.get("alias")) or name,
            "required": bool(attr.get("is_required")),
            "is_choice": bool(attr.get("is_choice")),
            "is_list": bool(attr.get("is_list")),
            "default": attr.get("default"),
            "default_show": bool(attr.get("default_show")) or name in preferred_order,
            "value_type": _clean_text(attr.get("value_type")),
            "order": preferred_order.get(name, int(attr.get("order") or index)),
            "choices": _extract_choice_definitions(attr),
            "choice_reference_attr_id": choice_reference_attr_id,
            "choice_reference_type_ids": choice_reference_type_ids,
        }

    for index, attr in enumerate(preference_attributes):
        name = _clean_text(attr.get("name"))
        if not name:
            continue
        choice_reference_attr_id, choice_reference_type_ids = _extract_choice_reference_definition(attr)
        definitions.setdefault(
            name,
            {
                "id": attr.get("id"),
                "name": name,
                "alias": _clean_text(attr.get("alias")) or name,
                "required": False,
                "is_choice": bool(attr.get("is_choice")),
                "is_list": bool(attr.get("is_list")),
                "default": attr.get("default"),
                "default_show": True,
                "value_type": _clean_text(attr.get("value_type")),
                "order": preferred_order.get(name, index),
                "choices": _extract_choice_definitions(attr),
                "choice_reference_attr_id": choice_reference_attr_id,
                "choice_reference_type_ids": choice_reference_type_ids,
            },
        )
        definitions[name]["default_show"] = True
        definitions[name]["order"] = preferred_order.get(name, definitions[name].get("order", index))
        if not definitions[name].get("choices"):
            definitions[name]["choices"] = _extract_choice_definitions(attr)
        if definitions[name].get("default") in (None, "", [], {}) and attr.get("default") not in (None, "", [], {}):
            definitions[name]["default"] = attr.get("default")
        if not definitions[name].get("choice_reference_attr_id") and choice_reference_attr_id not in (None, ""):
            definitions[name]["choice_reference_attr_id"] = choice_reference_attr_id
        if not definitions[name].get("choice_reference_type_ids") and choice_reference_type_ids:
            definitions[name]["choice_reference_type_ids"] = choice_reference_type_ids

    return sorted(
        definitions.values(),
        key=lambda item: (int(item.get("order", 0)), str(item.get("alias") or item.get("name") or "")),
    )


def _enrich_resource_import_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(metadata)
    enriched["semanticModelCatalog"] = _build_ci_type_catalog(enriched)
    enriched["semanticFieldCatalog"] = _build_metadata_field_catalog(enriched)
    return enriched


_METADATA_CACHE_LOCK = threading.Lock()
# CMDB schema (CI types / attributes / parent relations) changes only when an
# admin edits models in the CMDB UI — typically rare in production. A long
# default TTL kills the ~25s cold-load cost across daily user sessions; users
# can force-refresh via invalidate_resource_import_metadata_cache() or by
# clearing the cache file. Override with RESOURCE_IMPORT_METADATA_CACHE_TTL.
_METADATA_CACHE_TTL_SECONDS = max(
    0.0,
    float(os.environ.get("RESOURCE_IMPORT_METADATA_CACHE_TTL", "86400")),
)
_METADATA_FETCH_CONCURRENCY = max(
    1,
    int(os.environ.get("RESOURCE_IMPORT_METADATA_CONCURRENCY", "8")),
)


def _resource_import_metadata_cache_path() -> Path:
    working_dir = (
        os.environ.get("QWENPAW_WORKING_DIR")
        or os.environ.get("COPAW_WORKING_DIR")
        or "~/.qwenpaw"
    )
    return Path(working_dir).expanduser() / ".cache" / "resource_import_metadata.json"


def _resource_import_metadata_env_signature() -> str:
    try:
        env = _parse_env()
    except Exception:
        return ""
    return f"{env.get('VEOPS_BASE_URL') or ''}|{env.get('VEOPS_USERNAME') or ''}"


def _read_resource_import_metadata_cache(env_signature: str) -> dict[str, Any] | None:
    if not env_signature or _METADATA_CACHE_TTL_SECONDS <= 0:
        return None
    path = _resource_import_metadata_cache_path()
    try:
        stat_result = path.stat()
    except OSError:
        return None
    if (time.time() - stat_result.st_mtime) > _METADATA_CACHE_TTL_SECONDS:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("envSignature") != env_signature:
        return None
    cached = payload.get("metadata")
    return cached if isinstance(cached, dict) else None


def _write_resource_import_metadata_cache(env_signature: str, metadata: dict[str, Any]) -> None:
    if not env_signature or _METADATA_CACHE_TTL_SECONDS <= 0:
        return
    path = _resource_import_metadata_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(
                {"envSignature": env_signature, "metadata": metadata},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        tmp_path.replace(path)
    except OSError:
        pass


def invalidate_resource_import_metadata_cache() -> None:
    with _METADATA_CACHE_LOCK:
        path = _resource_import_metadata_cache_path()
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _fetch_ci_type_details(
    client: VeopsCmdbClient,
    item: dict[str, Any],
) -> tuple[str, list[str], list[dict[str, Any]], list[dict[str, Any]]] | None:
    """Fetch attributes, preference attributes and parent relations for one CI type.

    Each call hits the CMDB so we run these per-type fan-outs in parallel.
    """

    type_id = item.get("id")
    name = str(item.get("name") or "")
    if not type_id or not name:
        return None
    try:
        attributes = client.get_ci_type_attributes(type_id)
        preference_attributes = client.get_ci_type_preference_attributes(type_id)
        merged = _merge_attribute_definitions(attributes, preference_attributes)
        attribute_names = [
            str(attr.get("name")) for attr in merged if attr.get("name")
        ]
        child_attr_names_by_id = _attribute_names_from_ids(
            attributes, [attr.get("id") for attr in attributes]
        )
        parent_relations = client.get_ci_type_parent_relations(type_id)
        parent_types = [
            {
                "name": _clean_text(parent.get("name")),
                "alias": _clean_text(parent.get("alias"))
                or _clean_text(parent.get("name")),
                "relationType": _clean_text(parent.get("relation_type")),
                "showKey": _clean_text(parent.get("show_key")) or "name",
                "parentAttrNames": _attribute_names_from_ids(
                    parent.get("attributes") or [],
                    parent.get("parent_attr_ids") or [],
                ),
                "childAttrNames": [
                    child_name
                    for child_name in _attribute_names_from_ids(
                        attributes,
                        parent.get("child_attr_ids") or [],
                    )
                    if child_name in child_attr_names_by_id
                ],
            }
            for parent in parent_relations
            if _clean_text(parent.get("name"))
        ]
        return name, attribute_names, merged, parent_types
    except Exception:
        return name, DEFAULT_ATTRIBUTE_FIELDS.get(name, ["name"]), [], []


def load_resource_import_metadata() -> dict[str, Any]:
    env_signature = _resource_import_metadata_env_signature()
    with _METADATA_CACHE_LOCK:
        cached = _read_resource_import_metadata_cache(env_signature)
    if cached is not None:
        # Cache stores the enriched payload (semanticModelCatalog +
        # semanticFieldCatalog already materialized) so warm reads skip
        # the ~4s _build_metadata_field_catalog pass entirely.
        if "semanticModelCatalog" in cached and "semanticFieldCatalog" in cached:
            return cached
        return _enrich_resource_import_metadata(cached)

    metadata = {
        "supportedFormats": DEFAULT_SUPPORTED_FORMATS,
        "ciTypes": DEFAULT_MODEL_TEMPLATES,
        "ciTypeGroups": _build_default_ci_type_groups(DEFAULT_MODEL_TEMPLATES),
        "attributeLibrary": [],
        "relationTypes": DEFAULT_RELATION_TYPES,
        "connected": False,
        "message": "使用默认 CMDB 模板",
    }
    client: VeopsCmdbClient | None = None
    try:
        client = VeopsCmdbClient.from_skill_env()
        client.login()
        ci_types = client.get_ci_types()
        ci_type_groups = client.get_ci_type_groups()
        relation_types = client.get_relation_types()
        attribute_library = client.get_attribute_library()
        attributes_map: dict[str, list[str]] = {}
        attribute_definitions_map: dict[str, list[dict[str, Any]]] = {}
        parent_type_map: dict[str, list[dict[str, Any]]] = {}

        worker_count = min(_METADATA_FETCH_CONCURRENCY, max(1, len(ci_types)))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            results = list(
                executor.map(lambda item: _fetch_ci_type_details(client, item), ci_types)
            )

        for result in results:
            if result is None:
                continue
            name, attr_names, attr_defs, parent_types = result
            attributes_map[name] = attr_names
            attribute_definitions_map[name] = attr_defs
            parent_type_map[name] = parent_types

        metadata.update(
            {
                "ciTypes": [
                    {
                        "id": item.get("id"),
                        "name": item.get("name"),
                        "alias": item.get("alias"),
                        "unique_key": item.get("unique_key"),
                        "attributes": attributes_map.get(str(item.get("name") or ""), ["name"]),
                        "attributeDefinitions": attribute_definitions_map.get(str(item.get("name") or ""), []),
                        "parentTypes": parent_type_map.get(str(item.get("name") or ""), []),
                        "system_generated_unique_key": _is_system_generated_unique_key(
                            {
                                "unique_key": item.get("unique_key"),
                                "attributeDefinitions": attribute_definitions_map.get(str(item.get("name") or ""), []),
                            }
                        ),
                    }
                    for item in ci_types
                ],
                "ciTypeGroups": [
                    _normalize_group_snapshot(item)
                    for item in ci_type_groups
                    if isinstance(item, dict) and _clean_text(item.get("name"))
                ] or _build_default_ci_type_groups(ci_types),
                "attributeLibrary": [
                    {
                        "id": item.get("id"),
                        "name": _clean_text(item.get("name")),
                        "alias": _clean_text(item.get("alias")) or _clean_text(item.get("name")),
                        "value_type": _clean_text(item.get("value_type")),
                        "is_choice": bool(item.get("is_choice")),
                        "is_list": bool(item.get("is_list")),
                    }
                    for item in attribute_library
                    if _clean_text(item.get("name"))
                ],
                "relationTypes": [item.get("name") for item in relation_types if item.get("name")] or DEFAULT_RELATION_TYPES,
                "connected": True,
                "message": "已连接 CMDB，模板来自实时模型元数据",
            }
        )
    except Exception as exc:  # noqa: BLE001
        metadata["message"] = f"CMDB 元数据不可用，已降级为默认模板：{exc}"
    finally:
        if client:
            client.close()

    enriched = _enrich_resource_import_metadata(metadata)

    if metadata.get("connected"):
        with _METADATA_CACHE_LOCK:
            _write_resource_import_metadata_cache(env_signature, enriched)

    return enriched


def _ci_types_from_preview_snapshot(preview: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(preview, dict):
        return []
    ci_type_metadata = preview.get("ciTypeMetadata") or {}
    if not isinstance(ci_type_metadata, dict):
        return []

    items: list[dict[str, Any]] = []
    for ci_type, raw_meta in ci_type_metadata.items():
        if not isinstance(raw_meta, dict):
            continue
        name = _clean_text(raw_meta.get("name")) or _clean_text(ci_type)
        if not name:
            continue
        items.append(
            {
                "id": raw_meta.get("id"),
                "name": name,
                "alias": _clean_text(raw_meta.get("alias")) or name,
                "unique_key": _clean_text(raw_meta.get("unique_key")),
                "attributes": [
                    _clean_text(item)
                    for item in (raw_meta.get("attributes") or [])
                    if _clean_text(item)
                ],
                "attributeDefinitions": [
                    item
                    for item in (raw_meta.get("attributeDefinitions") or [])
                    if isinstance(item, dict) and _clean_text(item.get("name"))
                ],
                "parentTypes": [
                    item
                    for item in (raw_meta.get("parentTypes") or [])
                    if isinstance(item, dict) and _clean_text(item.get("name"))
                ],
                "system_generated_unique_key": bool(raw_meta.get("system_generated_unique_key")),
            }
        )
    return items


def import_preview_to_cmdb(payload: dict[str, Any]) -> dict[str, Any]:
    client = VeopsCmdbClient.from_skill_env()
    report = {
        "status": "success",
        "created": 0,
        "relationsCreated": 0,
        "skipped": 0,
        "failed": 0,
        "structureResults": [],
        "resourceResults": [],
        "relationResults": [],
        "rollbackResults": [],
    }
    ci_id_map: dict[str, Any] = {}
    created_ci_ids: list[Any] = []
    updated_ci_snapshots: list[dict[str, Any]] = []
    created_relation_ids: list[Any] = []
    try:
        _validate_preview_analysis_for_import(payload.get("preview") or {})
        client.login()
        report["structureResults"] = _prepare_import_structure(client, payload)
        client.get_relation_types()
        preview_ci_types = _ci_types_from_preview_snapshot(payload.get("preview") or {})
        if preview_ci_types:
            type_templates = {
                item["name"]: item
                for item in preview_ci_types
                if item.get("name")
            }
            LOGGER.info(
                "resource-import using preview ciTypeMetadata snapshot for import: models=%s",
                sorted(type_templates.keys()),
            )
        else:
            type_templates = {
                item["name"]: item
                for item in load_resource_import_metadata().get("ciTypes", [])
                if item.get("name")
            }
            LOGGER.warning(
                "resource-import preview missing ciTypeMetadata; falling back to live/default metadata for import",
            )
        structure_selected_model_map = _build_structure_selected_model_map(payload.get("preview") or {})
        resource_type_map = {
            str(record.get("previewKey")): _resolve_payload_ci_type(
                record.get("ciType"),
                type_templates=type_templates,
                structure_selected_model_map=structure_selected_model_map,
            )
            for group in (payload.get("resourceGroups") or [])
            for record in (group.get("records") or [])
            if record.get("previewKey")
        }
        # Reuse the allowed-relation snapshot baked into the preview payload
        # (see preview_resource_import return) — this saves a serial fan-out
        # of get_ci_type_relations, which costs ~10s for a ~10-ci_type import.
        # Falls back to a live fetch when the snapshot is missing, e.g. for
        # legacy preview payloads or direct CLI flows.
        snapshot_rules = (payload.get("preview") or {}).get("allowedRelationRules")
        if isinstance(snapshot_rules, list) and snapshot_rules:
            allowed_relation_rules = {
                tuple(rule)
                for rule in snapshot_rules
                if isinstance(rule, (list, tuple)) and len(rule) == 3
            }
        else:
            allowed_relation_rules = _build_allowed_relation_rules(
                client,
                type_templates,
                {ci_type for ci_type in resource_type_map.values() if ci_type},
            )
        allowed_relation_rules, relation_structure_results = _ensure_selected_model_relations(
            client,
            payload,
            type_templates=type_templates,
            resource_type_map=resource_type_map,
            allowed_relation_rules=allowed_relation_rules,
        )
        report["structureResults"].extend(relation_structure_results)
        resource_groups = payload.get("resourceGroups") or []
        ordered_records = _ordered_selected_records(
            resource_groups,
            payload.get("relations") or [],
            type_templates=type_templates,
        )
        pending_choice_values = _merge_pending_choice_values(
            _collect_pending_choice_values(
                type_templates=type_templates,
                ordered_records=ordered_records,
            ),
            _collect_existing_reference_choice_values(
                client,
                type_templates=type_templates,
                ordered_records=ordered_records,
            ),
        )
        # Parallel pre-fetch existing-CI lookups for every record. Both
        # preflight and the main import loop need this same data; running
        # the fetches in parallel up-front collapses ~20s of serial HTTP
        # (preflight: 44 calls × ~0.2s, main loop: ~44 more) into ~2s.
        existing_ci_map = _parallel_prefetch_existing_cis(
            client,
            type_templates=type_templates,
            ordered_records=ordered_records,
            structure_selected_model_map=structure_selected_model_map,
            pending_choice_values=pending_choice_values,
        )
        preflight_results = _preflight_import_resources(
            client,
            type_templates=type_templates,
            ordered_records=ordered_records,
            structure_selected_model_map=structure_selected_model_map,
            existing_ci_map=existing_ci_map,
        )
        if preflight_results:
            report["failed"] += len(preflight_results)
            report["resourceResults"].extend(preflight_results)
            report["status"] = "failed"
            report["error"] = "原子导入预检失败，未写入任何资源"
            return report

        for group in resource_groups:
            for record in group.get("records", []) or []:
                if not record.get("selected", True):
                    report["skipped"] += 1

        for record in ordered_records:
            import_action = _clean_text(record.get("importAction")) or "create"
            existing_ci = record.get("existingCi") or {}
            ci_type = _resolve_payload_ci_type(
                record.get("ciType"),
                type_templates=type_templates,
                structure_selected_model_map=structure_selected_model_map,
            )
            type_template = type_templates.get(ci_type, {})
            merged_attributes = {
                key: value
                for key, value in _merged_resource_attributes(record).items()
                if _clean_text(value)
            }
            confirmed_cmdb_attributes = _build_confirmed_cmdb_attributes(
                record=record,
                type_template=type_template,
            )
            display_name = _clean_text(record.get("name")) or _resolve_record_display_name(merged_attributes, type_template)
            if display_name and not _resolve_record_display_name(confirmed_cmdb_attributes, type_template):
                fallback_field = _resolve_cmdb_attribute_name(type_template, "name")
                if fallback_field and _find_attribute_definition(type_template, fallback_field):
                    confirmed_cmdb_attributes.setdefault(fallback_field, display_name)

            supplemental_cmdb_attributes = _build_cmdb_attributes(
                ci_type=ci_type,
                canonical_attributes=merged_attributes,
                type_template=type_template,
                pending_choice_values=pending_choice_values,
            )
            cmdb_attributes = {
                **supplemental_cmdb_attributes,
                **confirmed_cmdb_attributes,
            }
            cmdb_attributes = _normalize_cmdb_attribute_values(
                ci_type=ci_type,
                type_template=type_template,
                source_attributes=merged_attributes,
                cmdb_attributes=cmdb_attributes,
                pending_choice_values=pending_choice_values,
            )
            allowed_attribute_names = _allowed_attribute_names(type_template)
            if allowed_attribute_names:
                cmdb_attributes = {
                    key: value
                    for key, value in cmdb_attributes.items()
                    if _clean_text(key) in allowed_attribute_names and value not in (None, "", [])
                }
            unique_key = _get_import_required_unique_key(type_template)
            # Reuse the parallel-prefetched map; an entry of {} means the
            # parallel pass already queried CMDB and confirmed nothing
            # matched, so we must NOT re-fetch. Only records that weren't
            # queried at prefetch time fall back to a live lookup.
            preview_key = str(record.get("previewKey") or "")
            if existing_ci_map is not None and preview_key in existing_ci_map:
                current_existing_ci = existing_ci_map[preview_key] or existing_ci
            else:
                current_existing_ci = _find_existing_ci(
                    client,
                    ci_type,
                    cmdb_attributes,
                    fallback_name=display_name,
                    unique_key=unique_key,
                ) or existing_ci

            if current_existing_ci and import_action == "skip":
                ci_id_map[str(record.get("previewKey"))] = current_existing_ci.get("ciId")
                report["skipped"] += 1
                report["resourceResults"].append(
                    {
                        "previewKey": record.get("previewKey"),
                        "ciId": current_existing_ci.get("ciId"),
                        "status": "skipped",
                        "message": "CMDB 中已存在，已按选择跳过更新",
                    }
                )
                continue

            if current_existing_ci:
                existing_ci_id = current_existing_ci.get("ciId")
                if existing_ci_id is not None:
                    snapshot = client.get_ci_by_id(existing_ci_id)
                    if snapshot:
                        updated_ci_snapshots.append(
                            {
                                "ciId": existing_ci_id,
                                "ciType": ci_type,
                                "attributes": _snapshot_ci_attributes(snapshot, type_template=type_template),
                            }
                        )
                debug_context = _build_import_record_debug_context(
                    record=record,
                    ci_type=ci_type,
                    import_action=import_action,
                    source_attributes=merged_attributes,
                    cmdb_attributes=cmdb_attributes,
                    type_template=type_template,
                    existing_ci=current_existing_ci,
                )
                try:
                    ci_id, _response = client.update_ci(
                        current_existing_ci.get("ciId"),
                        ci_type,
                        cmdb_attributes,
                    )
                except Exception as exc:
                    LOGGER.error(
                        "resource-import update failed: %s | context=%s",
                        exc,
                        json.dumps(debug_context, ensure_ascii=False, default=str),
                    )
                    raise RuntimeError(
                        f"{exc} | 调试上下文: {json.dumps(debug_context, ensure_ascii=False, default=str)}"
                    ) from exc
            else:
                immediate_attributes, deferred_attributes = _split_deferred_self_referential_choice_attributes(
                    ci_type=ci_type,
                    type_template=type_template,
                    source_attributes=merged_attributes,
                    cmdb_attributes=cmdb_attributes,
                )
                debug_context = _build_import_record_debug_context(
                    record=record,
                    ci_type=ci_type,
                    import_action=import_action,
                    source_attributes=merged_attributes,
                    cmdb_attributes=immediate_attributes,
                    type_template=type_template,
                    existing_ci=current_existing_ci,
                    deferred_attributes=deferred_attributes,
                )
                try:
                    ci_id, _response = client.create_ci(
                        ci_type,
                        immediate_attributes,
                        exist_policy="reject",
                        unique_key=unique_key,
                    )
                except Exception as exc:
                    LOGGER.error(
                        "resource-import create failed: %s | context=%s",
                        exc,
                        json.dumps(debug_context, ensure_ascii=False, default=str),
                    )
                    raise RuntimeError(
                        f"{exc} | 调试上下文: {json.dumps(debug_context, ensure_ascii=False, default=str)}"
                    ) from exc
                if ci_id is not None:
                    created_ci_ids.append(ci_id)
                    if deferred_attributes:
                        try:
                            client.update_ci(ci_id, ci_type, deferred_attributes)
                        except Exception as exc:
                            LOGGER.error(
                                "resource-import deferred update failed: %s | context=%s",
                                exc,
                                json.dumps(debug_context, ensure_ascii=False, default=str),
                            )
                            raise RuntimeError(
                                f"{exc} | 调试上下文: {json.dumps(debug_context, ensure_ascii=False, default=str)}"
                            ) from exc
            if ci_id is None:
                raise RuntimeError(f"{record.get('name')} 创建后未能解析 CI ID")
            ci_id_map[str(record.get("previewKey"))] = ci_id
            report["created"] += 1
            report["resourceResults"].append(
                {
                    "previewKey": record.get("previewKey"),
                    "ciId": ci_id,
                    "status": "success",
                    "message": "更新成功" if current_existing_ci else "导入成功",
                }
            )

        for relation in payload.get("relations") or []:
            if not relation.get("selected", True):
                report["skipped"] += 1
                continue
            source_type = resource_type_map.get(str(relation.get("sourceKey")), "")
            target_type = resource_type_map.get(str(relation.get("targetKey")), "")
            relation_type = _clean_text(relation.get("relationType")) or "contain"
            rule_allowed = (source_type, relation_type, target_type) in allowed_relation_rules if allowed_relation_rules else None
            relation_debug_context = _build_relation_debug_context(
                relation=relation,
                source_type=source_type,
                target_type=target_type,
                relation_type=relation_type,
                allowed=rule_allowed,
            )
            if allowed_relation_rules and not rule_allowed:
                LOGGER.warning(
                    "resource-import relation skipped by model rule check: %s",
                    json.dumps(relation_debug_context, ensure_ascii=False, default=str),
                )
                report["skipped"] += 1
                report["relationResults"].append(
                    {
                        "sourceKey": relation.get("sourceKey"),
                        "targetKey": relation.get("targetKey"),
                        "status": "skipped",
                        "message": f"CMDB 未配置关系：{source_type} -> {relation_type} -> {target_type}",
                    }
                )
                continue
            source_ci_id = ci_id_map.get(str(relation.get("sourceKey")))
            target_ci_id = ci_id_map.get(str(relation.get("targetKey")))
            if not source_ci_id or not target_ci_id:
                LOGGER.warning(
                    "resource-import relation skipped because CI ids are missing: %s",
                    json.dumps(
                        _build_relation_debug_context(
                            relation=relation,
                            source_type=source_type,
                            target_type=target_type,
                            relation_type=relation_type,
                            source_ci_id=source_ci_id,
                            target_ci_id=target_ci_id,
                            allowed=rule_allowed,
                        ),
                        ensure_ascii=False,
                        default=str,
                    ),
                )
                report["relationResults"].append(
                    {
                        "sourceKey": relation.get("sourceKey"),
                        "targetKey": relation.get("targetKey"),
                        "status": "skipped",
                        "message": "关联资源未全部成功导入，已跳过关系创建",
                    }
                )
                continue
            try:
                LOGGER.info(
                    "resource-import relation creating: %s",
                    json.dumps(
                        _build_relation_debug_context(
                            relation=relation,
                            source_type=source_type,
                            target_type=target_type,
                            relation_type=relation_type,
                            source_ci_id=source_ci_id,
                            target_ci_id=target_ci_id,
                            allowed=rule_allowed,
                        ),
                        ensure_ascii=False,
                        default=str,
                    ),
                )
                relation_id, _response = client.create_relation(source_ci_id, target_ci_id, relation_type)
                if relation_id is not None:
                    created_relation_ids.append(relation_id)
                report["relationsCreated"] += 1
                report["relationResults"].append(
                    {
                        "sourceKey": relation.get("sourceKey"),
                        "targetKey": relation.get("targetKey"),
                        "status": "success",
                        "message": "关系创建成功",
                    }
                )
            except Exception as exc:  # noqa: BLE001
                LOGGER.error(
                    "resource-import relation create failed: %s | context=%s",
                    exc,
                    json.dumps(
                        _build_relation_debug_context(
                            relation=relation,
                            source_type=source_type,
                            target_type=target_type,
                            relation_type=relation_type,
                            source_ci_id=source_ci_id,
                            target_ci_id=target_ci_id,
                            allowed=rule_allowed,
                        ),
                        ensure_ascii=False,
                        default=str,
                    ),
                )
                report["failed"] += 1
                report["relationResults"].append(
                    {
                        "sourceKey": relation.get("sourceKey"),
                        "targetKey": relation.get("targetKey"),
                        "status": "failed",
                        "message": str(exc),
                    }
                )
        if report["failed"]:
            report["status"] = "partial" if (report["created"] or report["relationsCreated"]) else "failed"
    except Exception as exc:  # noqa: BLE001
        rollback_errors: list[str] = []
        for relation_id in reversed(created_relation_ids):
            try:
                client.delete_relation(relation_id)
                report["rollbackResults"].append(
                    {"kind": "relation", "id": relation_id, "status": "rolled_back", "message": "已回滚本次创建的关系"}
                )
            except Exception as rollback_exc:  # noqa: BLE001
                rollback_errors.append(f"回滚关系 {relation_id} 失败: {rollback_exc}")
        for ci_id in reversed(created_ci_ids):
            try:
                client.delete_ci(ci_id)
                report["rollbackResults"].append(
                    {"kind": "ci", "id": ci_id, "status": "rolled_back", "message": "已回滚本次创建的资源"}
                )
            except Exception as rollback_exc:  # noqa: BLE001
                rollback_errors.append(f"回滚资源 {ci_id} 失败: {rollback_exc}")
        for snapshot in reversed(updated_ci_snapshots):
            try:
                client.update_ci(snapshot.get("ciId"), snapshot.get("ciType") or "", snapshot.get("attributes") or {})
                report["rollbackResults"].append(
                    {"kind": "ci-update", "id": snapshot.get("ciId"), "status": "rolled_back", "message": "已回滚本次更新的资源"}
                )
            except Exception as rollback_exc:  # noqa: BLE001
                rollback_errors.append(f"回滚资源更新 {snapshot.get('ciId')} 失败: {rollback_exc}")
        report["status"] = "failed"
        report["error"] = str(exc)
        if rollback_errors:
            report["error"] += "；回滚存在异常：" + "；".join(rollback_errors)
        elif created_ci_ids or created_relation_ids or updated_ci_snapshots:
            report["error"] += "；已自动回滚本次已写入的数据"
    finally:
        client.close()
    return report
