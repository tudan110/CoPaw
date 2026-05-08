#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Nightingale (n9e) log query — metadata helper.

Sub-commands (via `--mode`):
- datasources : list configured data sources (filtered to ES where possible)
- indices     : list indices visible to a datasource (via _cat/indices)
- mapping     : dump _mapping for an index pattern
- fields      : flatten _mapping into a (path, type) field list, optionally
                marking fields commonly used for log queries

Usage:
    uv run scripts/n9e_log_meta.py --mode datasources [--output json|markdown]
    uv run scripts/n9e_log_meta.py --mode indices    [--datasource <id>] [--output ...]
    uv run scripts/n9e_log_meta.py --mode mapping    [--index <pattern>]
    uv run scripts/n9e_log_meta.py --mode fields     [--index <pattern>] [--output ...]
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Dict, List, Optional, Tuple

import _n9e_client as nc  # type: ignore[import-not-found]


# ---------------------------------------------------------------------------
# datasources
# ---------------------------------------------------------------------------

def _cmd_datasources(args: argparse.Namespace) -> int:
    res = nc.list_datasources()
    if nc.is_error(res):
        nc.stdout_json(res)
        return 1

    rows = _normalize_datasources(res.get("data") or {})
    if args.output == "json":
        nc.stdout_json(nc.make_ok({"total": len(rows), "rows": rows}))
        return 0

    md = ["# 智观日志数据源", ""]
    if not rows:
        md.append("_未找到任何数据源（可能账号无权限或日志服务未配置数据源）_")
    else:
        es_rows = [r for r in rows if (r.get("plugin_type") or "").lower() == "elasticsearch"]
        md.append(
            f"共 {len(rows)} 个数据源；其中 elasticsearch 类型 {len(es_rows)} 个，"
            "本技能仅支持 elasticsearch（其它类型先标记，后续可扩展）。"
        )
        md.append("")
        md.append("| ID | 名称 | 类型 | 状态 | 本技能支持 |")
        md.append("|---:|------|------|------|:---------:|")
        for r in rows:
            ptype = (r.get("plugin_type") or "").lower()
            supported = "✓" if ptype == "elasticsearch" else "—"
            md.append(
                f"| {r.get('id', '')} | {r.get('name', '')} | "
                f"{r.get('plugin_type') or ''} | {r.get('status') or ''} | {supported} |"
            )
    sys.stdout.write("\n".join(md) + "\n")
    return 0


def _normalize_datasources(payload: Any) -> List[Dict[str, Any]]:
    """Pull a list of datasource records out of n9e's response.

    n9e variants return one of:
    - {"data": [...]}                            (POST /datasource/list)
    - {"dat": [...], "err": ""}                  (GET /datasource/brief)
    - {"dat": {"list": [...]}, "err": ""}        (older builds)
    - bare list
    """
    if isinstance(payload, dict):
        # try "data" first (current v8 POST shape), then "dat", else the whole dict
        if "data" in payload:
            dat = payload.get("data")
        elif "dat" in payload:
            dat = payload.get("dat")
        else:
            dat = payload
    else:
        dat = payload
    if isinstance(dat, dict):
        items = dat.get("list") or dat.get("items") or []
    elif isinstance(dat, list):
        items = dat
    else:
        items = []
    out: List[Dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        out.append(
            {
                "id": it.get("id"),
                "name": it.get("name"),
                "plugin_type": it.get("plugin_type") or it.get("type") or it.get("typ"),
                "status": it.get("status"),
                "description": it.get("description") or it.get("desc"),
            }
        )
    return out


# ---------------------------------------------------------------------------
# indices
# ---------------------------------------------------------------------------

def _cmd_indices(args: argparse.Namespace) -> int:
    ds_id = _resolve_ds_id(args)
    if ds_id is None:
        nc.stdout_json(_no_ds_error())
        return 1

    res = nc.es_get(ds_id, "/_cat/indices?format=json&bytes=b")
    if nc.is_error(res):
        nc.stdout_json(res)
        return 1
    items = res.get("data") or []
    if not isinstance(items, list):
        items = []

    if args.pattern:
        import fnmatch

        items = [it for it in items if fnmatch.fnmatch(str(it.get("index", "")), args.pattern)]

    items.sort(key=lambda x: str(x.get("index", "")))

    if args.output == "json":
        nc.stdout_json(nc.make_ok({"total": len(items), "rows": items}))
        return 0

    md = [f"# 数据源 {ds_id} 的索引列表", ""]
    if not items:
        md.append("_未找到任何索引_")
    else:
        md.append(f"共 {len(items)} 个索引：")
        md.append("")
        md.append("| 索引 | health | status | docs.count | store.size |")
        md.append("|------|--------|--------|-----------:|-----------:|")
        for it in items[: args.limit]:
            md.append(
                f"| {it.get('index', '')} | {it.get('health', '')} | "
                f"{it.get('status', '')} | {it.get('docs.count', '')} | "
                f"{it.get('store.size', '')} |"
            )
        if len(items) > args.limit:
            md.append(f"\n_仅展示前 {args.limit} 个，剩余 {len(items) - args.limit} 个未列出_")
    sys.stdout.write("\n".join(md) + "\n")
    return 0


# ---------------------------------------------------------------------------
# mapping
# ---------------------------------------------------------------------------

def _cmd_mapping(args: argparse.Namespace) -> int:
    ds_id = _resolve_ds_id(args)
    if ds_id is None:
        nc.stdout_json(_no_ds_error())
        return 1
    index = args.index or nc.get_default_index()
    res = nc.es_get(ds_id, f"/{index}/_mapping")
    if nc.is_error(res):
        nc.stdout_json(res)
        return 1
    if args.output == "json":
        nc.stdout_json(res)
        return 0
    sys.stdout.write(
        f"# 数据源 {ds_id} 索引 `{index}` 的 mapping\n\n"
        "```json\n"
        + nc_json_dumps(res.get("data"))
        + "\n```\n"
    )
    return 0


def nc_json_dumps(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


# ---------------------------------------------------------------------------
# fields
# ---------------------------------------------------------------------------

_COMMON_LOG_FIELDS = {
    "@timestamp", "timestamp", "time", "level", "log.level", "severity",
    "message", "msg", "log.message", "host.name", "hostname", "agent.hostname",
    "service.name", "service", "app", "container.name",
    "kubernetes.pod.name", "kubernetes.namespace_name", "kubernetes.container_name",
    "trace.id", "span.id", "request_id", "client.ip", "url.path", "http.response.status_code",
}


def _cmd_fields(args: argparse.Namespace) -> int:
    ds_id = _resolve_ds_id(args)
    if ds_id is None:
        nc.stdout_json(_no_ds_error())
        return 1
    index = args.index or nc.get_default_index()
    res = nc.es_get(ds_id, f"/{index}/_mapping")
    if nc.is_error(res):
        nc.stdout_json(res)
        return 1
    flat = _flatten_mapping(res.get("data") or {})
    if args.output == "json":
        nc.stdout_json(nc.make_ok({"total": len(flat), "rows": flat}))
        return 0

    md = [f"# 数据源 {ds_id} 索引 `{index}` 字段列表（精简）", ""]
    if not flat:
        md.append("_mapping 为空或解析失败_")
        sys.stdout.write("\n".join(md) + "\n")
        return 0
    md.append(f"共 {len(flat)} 个字段（去重后）：")
    md.append("")
    md.append("| 字段 | 类型 | 常用 |")
    md.append("|------|------|:---:|")
    for f in flat[: args.limit]:
        common = "✓" if f["path"] in _COMMON_LOG_FIELDS else ""
        md.append(f"| `{f['path']}` | {f['type']} | {common} |")
    if len(flat) > args.limit:
        md.append(f"\n_仅展示前 {args.limit} 个，剩余 {len(flat) - args.limit} 个未列出_")
    sys.stdout.write("\n".join(md) + "\n")
    return 0


def _flatten_mapping(mapping_resp: Any) -> List[Dict[str, str]]:
    """Flatten ES `_mapping` response into [{path, type}, ...].

    Handles both classic (with type-name layer) and v7+ (no type) shapes.
    Deduplicates across multiple matching indices.
    """
    seen: Dict[str, str] = {}

    def walk(props: Dict[str, Any], prefix: str) -> None:
        if not isinstance(props, dict):
            return
        for name, defn in props.items():
            if not isinstance(defn, dict):
                continue
            path = f"{prefix}.{name}" if prefix else name
            if "properties" in defn:
                walk(defn["properties"], path)
                continue
            t = defn.get("type") or "object"
            seen.setdefault(path, str(t))
            sub = defn.get("fields") or {}
            for sub_name, sub_def in sub.items():
                if isinstance(sub_def, dict):
                    seen.setdefault(f"{path}.{sub_name}", str(sub_def.get("type") or t))

    if not isinstance(mapping_resp, dict):
        return []
    for _idx, idx_obj in mapping_resp.items():
        if not isinstance(idx_obj, dict):
            continue
        m = idx_obj.get("mappings") or {}
        if not isinstance(m, dict):
            continue
        if "properties" in m:
            walk(m["properties"], "")
        else:
            for type_obj in m.values():
                if isinstance(type_obj, dict):
                    walk(type_obj.get("properties") or {}, "")
    out = [{"path": k, "type": v} for k, v in seen.items()]
    out.sort(key=lambda x: (x["path"] not in _COMMON_LOG_FIELDS, x["path"]))
    return out


# ---------------------------------------------------------------------------
# arg parsing helpers
# ---------------------------------------------------------------------------

def _resolve_ds_id(args: argparse.Namespace) -> Optional[int]:
    if getattr(args, "datasource", None):
        try:
            return int(args.datasource)
        except (ValueError, TypeError):
            return None
    return nc.get_default_datasource_id()


def _no_ds_error() -> Dict[str, Any]:
    return nc.make_error(
        400,
        "未指定日志数据源 ID。请通过 --datasource <id> 传入，"
        "或在 .env 里设置 N9E_LOG_DATASOURCE_ID。"
        "可先运行 `n9e_log_meta.py --mode datasources` 查询可用数据源。",
    )


def main() -> int:
    p = argparse.ArgumentParser(description="Nightingale log metadata helper")
    p.add_argument(
        "--mode",
        required=True,
        choices=["datasources", "indices", "mapping", "fields"],
    )
    p.add_argument("--datasource", help="数据源 ID（覆盖 .env 默认）")
    p.add_argument("--index", help="索引或索引模式（覆盖 .env 默认）")
    p.add_argument("--pattern", help="(indices) 索引名通配过滤")
    p.add_argument("--limit", type=int, default=50, help="展示行数上限")
    p.add_argument("--output", choices=["json", "markdown"], default="markdown")
    args = p.parse_args()

    handlers = {
        "datasources": _cmd_datasources,
        "indices": _cmd_indices,
        "mapping": _cmd_mapping,
        "fields": _cmd_fields,
    }
    return handlers[args.mode](args)


if __name__ == "__main__":
    raise SystemExit(main())
