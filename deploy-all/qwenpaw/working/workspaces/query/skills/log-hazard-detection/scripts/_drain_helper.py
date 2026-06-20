#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared Drain3 helpers for log-hazard-detection.

Wraps drain3.TemplateMiner with:
- in-memory persistence (no disk state across runs)
- aggressive masking (IPv4 / numbers / UUIDs / paths / hex / quoted)
- multi-field line composition (e.g. join app_json + message)
- a serializable template export structure
- baseline / current alignment by normalized template key
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import _n9e_client as nc  # type: ignore[import-not-found]

try:
    from drain3 import TemplateMiner
    from drain3.masking import MaskingInstruction
    from drain3.template_miner_config import TemplateMinerConfig
    HAS_DRAIN3 = True
except ImportError:  # pragma: no cover — surfaced via a friendly error
    HAS_DRAIN3 = False


# ---------------------------------------------------------------------------
# field candidates and helpers
# ---------------------------------------------------------------------------

# Highest-signal message fields, copied from nightingale-log's
# n9e_log_aggregate _MESSAGE_CANDIDATES head — drain3 stabilises faster when
# fed the most semantic field first.
DEFAULT_MESSAGE_FIELDS: List[str] = ["app_json", "message"]

ERROR_TOKENS = re.compile(
    r"\b(error|exception|traceback|failed|failure|panic|fatal|"
    r"refused|timeout|denied|unreachable|crash|abort|critical)\b",
    re.IGNORECASE,
)

_SQUEEZE_WS = re.compile(r"\s+")


def normalize_template(template: str) -> str:
    """Stable key for cross-miner template alignment."""
    return _SQUEEZE_WS.sub(" ", template.strip()).lower()


def _compose_line(source: Dict[str, Any], fields: Sequence[str], max_len: int) -> str:
    parts: List[str] = []
    for field in fields:
        val = nc.deep_get(source, field)
        if val is None or val == "":
            continue
        if isinstance(val, (dict, list)):
            try:
                import json as _json
                val = _json.dumps(val, ensure_ascii=False, separators=(",", ":"))
            except (TypeError, ValueError):
                val = str(val)
        else:
            val = str(val)
        parts.append(val)
    line = " ".join(parts).strip()
    if not line:
        return ""
    line = _SQUEEZE_WS.sub(" ", line)
    if len(line) > max_len:
        line = line[:max_len]
    return line


# ---------------------------------------------------------------------------
# drain3 miner factory
# ---------------------------------------------------------------------------

_MASKING_PATTERNS = [
    (r"(\d+\.){3}\d+", "IP"),
    (r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b", "UUID"),
    (r"(?:[A-Za-z]:)?[/\\][\w./\\-]{2,}", "PATH"),
    (r"\b0x[0-9a-fA-F]+\b", "HEX"),
    (r"\b\d+\b", "NUM"),
    (r'"(?:[^"\\]|\\.)*"', "STR"),
]


def _build_config(max_clusters: int, sim_th: float) -> "TemplateMinerConfig":
    cfg = TemplateMinerConfig()
    cfg.profiling_enabled = False
    cfg.drain_extra_delimiters = ["_"]
    cfg.drain_max_clusters = max_clusters
    cfg.drain_sim_th = sim_th
    cfg.drain_depth = 4
    cfg.drain_max_children = 100
    cfg.snapshot_interval_minutes = 0  # never auto-snapshot
    cfg.snapshot_compress_state = False
    cfg.masking_instructions = [
        MaskingInstruction(pattern, mask_with) for pattern, mask_with in _MASKING_PATTERNS
    ]
    return cfg


def make_miner(*, max_clusters: int = 2000, sim_th: float = 0.4) -> "TemplateMiner":
    if not HAS_DRAIN3:
        raise RuntimeError(
            "drain3 未安装。请在系统 Python 里 `pip install 'drain3>=0.9.11'`"
            "（镜像已随本技能 requirements.txt 烘焙，正常不应缺）。"
        )
    cfg = _build_config(max_clusters=max_clusters, sim_th=sim_th)
    return TemplateMiner(persistence_handler=None, config=cfg)


# ---------------------------------------------------------------------------
# core: hits → templates
# ---------------------------------------------------------------------------

def fit_hits(
    hits: Iterable[Dict[str, Any]],
    *,
    message_fields: Sequence[str] = tuple(DEFAULT_MESSAGE_FIELDS),
    line_max_len: int = 4000,
    max_clusters: int = 2000,
    sim_th: float = 0.4,
    host_field_candidates: Optional[Sequence[str]] = None,
    service_field_candidates: Optional[Sequence[str]] = None,
    timestamp_field: Optional[str] = None,
) -> Dict[str, Any]:
    """Fit drain3 over ES hits and return template stats.

    Returns:
        {
          "templates": [{...}, ...],
          "fit_count": int,
          "skipped_count": int,
          "fields_used": list[str],   # which message fields actually contributed
        }
    """
    miner = make_miner(max_clusters=max_clusters, sim_th=sim_th)
    cluster_state: Dict[int, Dict[str, Any]] = {}
    fit_count = 0
    skipped = 0
    field_hits: Counter = Counter()
    ts_field = timestamp_field or nc.get_timestamp_field()
    host_pool = list(host_field_candidates or _DEFAULT_HOST_FIELDS)
    svc_pool = list(service_field_candidates or _DEFAULT_SERVICE_FIELDS)

    for hit in hits:
        src = (hit.get("_source") or {}) if isinstance(hit, dict) else {}
        if not src:
            skipped += 1
            continue
        for fld in message_fields:
            if nc.deep_get(src, fld) not in (None, ""):
                field_hits[fld] += 1
        line = _compose_line(src, message_fields, line_max_len)
        if not line:
            skipped += 1
            continue
        result = miner.add_log_message(line)
        if not result:
            skipped += 1
            continue
        cluster_id = int(result.get("cluster_id") or -1)
        if cluster_id < 0:
            skipped += 1
            continue
        fit_count += 1
        ts_ms = _coerce_ts(src.get(ts_field) or src.get("@timestamp"))
        host = _first_present(src, host_pool) or ""
        service = _first_present(src, svc_pool) or ""
        index = (hit.get("_index") or "") if isinstance(hit, dict) else ""

        bucket = cluster_state.get(cluster_id)
        if bucket is None:
            bucket = {
                "id": cluster_id,
                "count": 0,
                "first_ts_ms": ts_ms,
                "last_ts_ms": ts_ms,
                "sample": nc.truncate(line, 200),
                "hosts": Counter(),
                "services": Counter(),
                "indices": Counter(),
            }
            cluster_state[cluster_id] = bucket
        bucket["count"] += 1
        if ts_ms is not None:
            if bucket["first_ts_ms"] is None or ts_ms < bucket["first_ts_ms"]:
                bucket["first_ts_ms"] = ts_ms
            if bucket["last_ts_ms"] is None or ts_ms > bucket["last_ts_ms"]:
                bucket["last_ts_ms"] = ts_ms
        if host:
            bucket["hosts"][host] += 1
        if service:
            bucket["services"][service] += 1
        if index:
            bucket["indices"][index] += 1

    templates: List[Dict[str, Any]] = []
    for cluster in miner.drain.clusters:
        cid = int(cluster.cluster_id)
        if cid not in cluster_state:
            continue
        bucket = cluster_state[cid]
        template = cluster.get_template()
        templates.append(
            {
                "id": cid,
                "template": template,
                "template_key": normalize_template(template),
                "count": bucket["count"],
                "first_ts_ms": bucket["first_ts_ms"],
                "last_ts_ms": bucket["last_ts_ms"],
                "sample": bucket["sample"],
                "hosts": _counter_top(bucket["hosts"], 5),
                "services": _counter_top(bucket["services"], 5),
                "indices": _counter_top(bucket["indices"], 5),
                "error_score": _error_score(template),
            }
        )

    templates.sort(key=lambda t: t["count"], reverse=True)
    return {
        "templates": templates,
        "fit_count": fit_count,
        "skipped_count": skipped,
        "fields_used": [f for f, _ in field_hits.most_common()],
    }


# ---------------------------------------------------------------------------
# baseline / current alignment
# ---------------------------------------------------------------------------

def diff_templates(
    *,
    current: List[Dict[str, Any]],
    baseline: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """Compare two template sets keyed by normalized template string.

    Returns three buckets: surged / new / vanished. Each entry includes both
    counts when applicable.
    """
    base_by_key: Dict[str, Dict[str, Any]] = {t["template_key"]: t for t in baseline}
    cur_by_key: Dict[str, Dict[str, Any]] = {t["template_key"]: t for t in current}

    cur_total = sum(t["count"] for t in current) or 1
    base_total = sum(t["count"] for t in baseline) or 1

    new_items: List[Dict[str, Any]] = []
    surged_items: List[Dict[str, Any]] = []
    vanished_items: List[Dict[str, Any]] = []

    for key, cur in cur_by_key.items():
        base = base_by_key.get(key)
        cur_pct = cur["count"] / cur_total
        if base is None:
            new_items.append(
                {
                    **cur,
                    "current_count": cur["count"],
                    "baseline_count": 0,
                    "current_pct": cur_pct,
                    "baseline_pct": 0.0,
                    "delta": cur["count"],
                    "ratio": float("inf"),
                }
            )
            continue
        base_pct = base["count"] / base_total
        delta = cur["count"] - base["count"]
        ratio = (cur["count"] + 1) / (base["count"] + 1)
        # Surge: at least 2x (ratio) AND at least +5 absolute, OR pct doubled.
        if (ratio >= 2.0 and delta >= 5) or (cur_pct >= 0.005 and cur_pct >= 2 * base_pct):
            surged_items.append(
                {
                    **cur,
                    "current_count": cur["count"],
                    "baseline_count": base["count"],
                    "current_pct": cur_pct,
                    "baseline_pct": base_pct,
                    "delta": delta,
                    "ratio": ratio,
                }
            )

    for key, base in base_by_key.items():
        if key in cur_by_key:
            continue
        if base["count"] < 5:
            continue  # ignore long-tail noise that just rotated out
        vanished_items.append(
            {
                **base,
                "current_count": 0,
                "baseline_count": base["count"],
                "current_pct": 0.0,
                "baseline_pct": base["count"] / base_total,
                "delta": -base["count"],
                "ratio": 0.0,
            }
        )

    new_items.sort(key=lambda t: t["current_count"], reverse=True)
    surged_items.sort(key=lambda t: t["delta"], reverse=True)
    vanished_items.sort(key=lambda t: t["baseline_count"], reverse=True)
    return {"new": new_items, "surged": surged_items, "vanished": vanished_items}


def find_rare(
    templates: List[Dict[str, Any]],
    *,
    pct_max: float = 0.001,
    count_range: Tuple[int, int] = (2, 10),
) -> List[Dict[str, Any]]:
    """Templates with very small footprint but seen at least a couple of times."""
    total = sum(t["count"] for t in templates) or 1
    out: List[Dict[str, Any]] = []
    for t in templates:
        pct = t["count"] / total
        if pct >= pct_max:
            continue
        if not (count_range[0] <= t["count"] <= count_range[1]):
            continue
        out.append({**t, "pct": pct})
    out.sort(key=lambda t: t["count"])
    return out


def find_error_dense(
    templates: List[Dict[str, Any]],
    *,
    score_min: float = 0.02,
) -> List[Dict[str, Any]]:
    out = [t for t in templates if t["error_score"] >= score_min]
    out.sort(key=lambda t: (t["error_score"], t["count"]), reverse=True)
    return out


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

_DEFAULT_HOST_FIELDS = (
    "agent_hostname",
    "host.name",
    "hostname",
    "agent.hostname",
    "syslog_hostname",
)
_DEFAULT_SERVICE_FIELDS = (
    "fcservice",
    "service.name",
    "service",
    "app",
    "syslog_program",
)


def _first_present(src: Dict[str, Any], fields: Sequence[str]) -> Optional[str]:
    for fld in fields:
        v = nc.deep_get(src, fld)
        if v not in (None, "", [], {}):
            return str(v)
    return None


def _coerce_ts(v: Any) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        # heuristic: epoch ms already if 13-digit-ish, else seconds
        iv = int(v)
        if iv > 10_000_000_000:
            return iv
        return iv * 1000
    s = str(v).strip()
    if not s:
        return None
    try:
        return nc.parse_time(s)
    except ValueError:
        return None


def _counter_top(c: Counter, n: int) -> List[Dict[str, Any]]:
    return [{"key": k, "count": v} for k, v in c.most_common(n)]


def _error_score(template: str) -> float:
    if not template:
        return 0.0
    matches = ERROR_TOKENS.findall(template)
    if not matches:
        return 0.0
    return min(1.0, len(matches) / max(1, len(template) // 30))
