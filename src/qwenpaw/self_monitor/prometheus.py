# -*- coding: utf-8 -*-
"""Prometheus text exposition rendered from the SQLite rollup.

Multi-worker correctness (design D7): uvicorn workers share one port,
so rendering "this process's registry" would return a random worker's
view per scrape.  Instead every series is read from the rollup with an
added ``worker`` label — scrapers see all workers consistently and
aggregate with ``sum by (...)`` / ``rate()`` as usual.  The cost is
one rollup interval of staleness, which scraping tolerates by design.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .store import SelfMonitorStore

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def _escape_label_value(value: str) -> str:
    return str(value).replace("\\", r"\\").replace("\n", r"\n").replace('"', r"\"")


def _format_value(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return repr(float(value))


def _series_line(name: str, labels: dict[str, str], value: float) -> str:
    if labels:
        body = ",".join(
            f'{key}="{_escape_label_value(val)}"' for key, val in sorted(labels.items())
        )
        return f"{name}{{{body}}} {_format_value(value)}"
    return f"{name} {_format_value(value)}"


def render_prometheus(store: SelfMonitorStore, *, max_age_s: float = 180.0) -> str:
    """Render the freshest sample of every series as exposition text."""
    rows = store.latest_samples(max_age_s=max_age_s)
    by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_name[row["name"]].append(row)

    lines: list[str] = []
    for name in sorted(by_name):
        series = by_name[name]
        kind = series[0].get("kind") or ""
        # Histogram parts (…_bucket/_sum/_count) are exposition-level
        # counters; plain kinds keep their registry kind.
        prom_type = (
            "counter"
            if kind == "histogram"
            else (kind if kind in ("counter", "gauge") else "untyped")
        )
        lines.append(f"# TYPE {name} {prom_type}")
        for row in series:
            labels = dict(row["labels"])
            worker = row.get("worker_id") or ""
            if worker:
                labels["worker"] = worker
            lines.append(_series_line(name, labels, row["value"]))
    return "\n".join(lines) + ("\n" if lines else "")


__all__ = ["CONTENT_TYPE", "render_prometheus"]
