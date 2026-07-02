# -*- coding: utf-8 -*-
"""LLM cost accounting (design P2 成本关联 + 预算).

Token counts are already mirrored into ``qwenpaw_llm_tokens_total``;
cost = windowed token increase × operator-configured unit prices.  No
prices are invented: unpriced models are reported as such and the
total stays ``None`` until at least one price matches — the budget
alert rule stays dormant likewise.

``<working-dir>/self_monitor_costs.json``:

    {"currency": "CNY",
     "budgetDaily": 200,
     "prices": {
       "ctyun:glm-*": {"promptPer1k": 0.005, "completionPer1k": 0.015},
       "dashscope:qwen-max": {"promptPer1k": 0.02, "completionPer1k": 0.06}
     }}
"""

from __future__ import annotations

import fnmatch
import json
import logging
import time
from typing import Any

from ..constant import WORKING_DIR
from .store import SelfMonitorStore

logger = logging.getLogger(__name__)

COSTS_FILENAME = "self_monitor_costs.json"


def load_cost_config(path=None) -> dict[str, Any]:
    config_path = path or (WORKING_DIR / COSTS_FILENAME)
    try:
        if config_path.exists():
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
    except Exception:
        logger.warning("self_monitor: cost config unreadable", exc_info=True)
    return {}


def day_start(now: float | None = None) -> float:
    lt = time.localtime(now if now is not None else time.time())
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))


def _match_price(
    prices: dict[str, Any], provider: str, model: str
) -> dict[str, float] | None:
    key = f"{provider}:{model}" if provider else model
    spec = prices.get(key)
    if spec is None:
        for pattern, candidate in prices.items():
            if fnmatch.fnmatch(key, pattern):
                spec = candidate
                break
    if not isinstance(spec, dict):
        return None
    try:
        return {
            "prompt": float(spec.get("promptPer1k") or 0.0),
            "completion": float(spec.get("completionPer1k") or 0.0),
        }
    except (TypeError, ValueError):
        return None


def cost_summary(
    store: SelfMonitorStore,
    *,
    since: float,
    until: float | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Windowed cost from token increases × configured prices."""
    cfg = config if config is not None else load_cost_config()
    prices = cfg.get("prices") or {}
    deltas = store.counter_deltas("qwenpaw_llm_tokens_total", since=since, until=until)
    by_model: dict[str, dict[str, float]] = {}
    for row in deltas:
        labels = row["labels"]
        model_key = (
            f"{labels.get('provider', '')}:{labels.get('model', '')}".strip(":")
            or "unknown"
        )
        entry = by_model.setdefault(model_key, {"prompt": 0.0, "completion": 0.0})
        kind = labels.get("kind") or "prompt"
        if kind in entry:
            entry[kind] += row["delta"]

    priced: dict[str, float] = {}
    unpriced: list[str] = []
    total: float | None = None
    for model_key, tokens in sorted(by_model.items()):
        provider, _, model = model_key.partition(":")
        price = _match_price(prices, provider, model)
        if price is None:
            unpriced.append(model_key)
            continue
        cost = (
            tokens["prompt"] / 1000.0 * price["prompt"]
            + tokens["completion"] / 1000.0 * price["completion"]
        )
        priced[model_key] = round(cost, 4)
        total = (total or 0.0) + cost

    budget = cfg.get("budgetDaily")
    return {
        "total": round(total, 4) if total is not None else None,
        "currency": str(cfg.get("currency") or "CNY"),
        "byModel": priced,
        "unpricedModels": unpriced,
        "tokensByModel": {
            key: {k: int(v) for k, v in tokens.items()}
            for key, tokens in by_model.items()
        },
        "budgetDaily": float(budget) if budget is not None else None,
        "configured": bool(prices),
    }


__all__ = ["COSTS_FILENAME", "cost_summary", "day_start", "load_cost_config"]
