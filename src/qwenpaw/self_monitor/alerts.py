# -*- coding: utf-8 -*-
"""Alert rule engine (design P1) — threshold rules over the rollup.

Rules are evaluated once per rollup tick against the SQLite store (so
every worker sees the same cross-worker truth).  A rule that breaches
for ``for_s`` seconds transitions to *firing*: one row in the
``alerts`` table, one ``alert.fired`` event, and — when a notifier is
wired — one channel push.  When the condition clears the alert
resolves in place.

Built-in rules cover the incident catalogue the self-monitor exists
for (degrade, 429 storm, worker loss, disk, governance timeouts, log
errors, probe/datasource down, daily cost budget).  Operators may
extend/override via ``<working-dir>/self_monitor_rules.json``:

    {"rules": [{"id": "...", "metric": "...", "op": ">", ...}],
     "disable": ["builtin-rule-id"]}

Known limitation (documented in the design): a single-worker deploy
cannot self-report its own total death — that is what the external
``/metrics`` scrape is for.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping

from ..constant import WORKING_DIR, EnvVarLoader
from .events import emit_event
from .registry import get_registry
from .store import SelfMonitorStore

logger = logging.getLogger(__name__)

RULES_FILENAME = "self_monitor_rules.json"

Notifier = Callable[[str], Awaitable[None]]


@dataclass(frozen=True)
class AlertRule:
    id: str
    name: str
    layer: str
    severity: str  # warn | critical
    kind: str  # counter_delta | gauge_sum | gauge_min | cost_daily
    metric: str = ""
    label_filter: Mapping[str, str] | None = None
    op: str = ">"  # > | < | >= | <=
    threshold: float = 0.0
    window_s: float = 300.0
    for_s: float = 0.0
    message: str = ""


def _expected_workers() -> float:
    return float(EnvVarLoader.get_int("QWENPAW_APP_WORKERS", 1, min_value=1))


def default_rules() -> list[AlertRule]:
    return [
        AlertRule(
            id="degrade-events",
            name="组件降级",
            layer="l3",
            severity="critical",
            kind="counter_delta",
            metric="qwenpaw_degrade_events_total",
            op=">",
            threshold=0,
            window_s=300,
            message="5 分钟内出现 {value:.0f} 起降级(阈值 >{threshold:.0f})",
        ),
        AlertRule(
            id="llm-429-storm",
            name="LLM 429 风暴",
            layer="l3",
            severity="warn",
            kind="counter_delta",
            metric="qwenpaw_llm_requests_total",
            label_filter={"status": "429"},
            op=">",
            threshold=20,
            window_s=300,
            message="5 分钟内 429 计 {value:.0f} 次(阈值 >{threshold:.0f})",
        ),
        AlertRule(
            id="worker-down",
            name="Worker 掉线",
            layer="l4",
            severity="critical",
            kind="gauge_sum",
            metric="qwenpaw_worker_up",
            op="<",
            threshold=_expected_workers(),
            for_s=60,
            message="存活 worker {value:.0f} < 期望 {threshold:.0f}",
        ),
        AlertRule(
            id="disk-high",
            name="磁盘水位",
            layer="l4",
            severity="warn",
            kind="gauge_min",
            metric="qwenpaw_disk_usage_percent",
            op=">=",
            threshold=90,
            for_s=60,
            message="working 卷使用率 {value:.0f}%(阈值 ≥{threshold:.0f}%)",
        ),
        AlertRule(
            id="governance-timeout",
            name="治理审批超时",
            layer="l2",
            severity="warn",
            kind="counter_delta",
            metric="qwenpaw_governance_decisions_total",
            label_filter={"decision": "timeout"},
            op=">",
            threshold=0,
            window_s=900,
            message="15 分钟内治理超时 {value:.0f} 次",
        ),
        AlertRule(
            id="log-errors",
            name="日志 ERROR 激增",
            layer="l4",
            severity="warn",
            kind="counter_delta",
            metric="qwenpaw_log_errors_total",
            op=">",
            threshold=50,
            window_s=900,
            message="15 分钟内 ERROR 日志 {value:.0f} 条(阈值 >{threshold:.0f})",
        ),
        AlertRule(
            id="probe-down",
            name="拨测失败",
            layer="l1",
            severity="critical",
            kind="gauge_min",
            metric="qwenpaw_probe_up",
            op="<",
            threshold=1,
            for_s=120,
            message="至少一个拨测目标持续不可达",
        ),
        AlertRule(
            id="datasource-down",
            name="数据源断连",
            layer="l3",
            severity="warn",
            kind="gauge_min",
            metric="qwenpaw_datasource_up",
            op="<",
            threshold=1,
            for_s=600,
            message="至少一个外部数据源持续不可用",
        ),
        AlertRule(
            id="cost-budget",
            name="LLM 日成本超预算",
            layer="l3",
            severity="warn",
            kind="cost_daily",
            op=">",
            threshold=0,  # replaced by the configured budget at eval time
            message="今日 LLM 成本 {value:.2f} 超出预算 {threshold:.2f}",
        ),
    ]


def load_rules(path=None) -> list[AlertRule]:
    """Built-in rules + operator overrides from the JSON file."""
    rules = {rule.id: rule for rule in default_rules()}
    config_path = path or (WORKING_DIR / RULES_FILENAME)
    try:
        if config_path.exists():
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            for rule_id in raw.get("disable") or []:
                rules.pop(str(rule_id), None)
            for spec in raw.get("rules") or []:
                try:
                    rule = AlertRule(
                        id=str(spec["id"]),
                        name=str(spec.get("name") or spec["id"]),
                        layer=str(spec.get("layer") or "l4"),
                        severity=str(spec.get("severity") or "warn"),
                        kind=str(spec.get("kind") or "counter_delta"),
                        metric=str(spec.get("metric") or ""),
                        label_filter=spec.get("labelFilter"),
                        op=str(spec.get("op") or ">"),
                        threshold=float(spec.get("threshold") or 0),
                        window_s=float(spec.get("windowS") or 300),
                        for_s=float(spec.get("forS") or 0),
                        message=str(spec.get("message") or ""),
                    )
                    rules[rule.id] = rule
                except Exception:
                    logger.warning(
                        "self_monitor: bad alert rule spec skipped: %r",
                        spec,
                    )
    except Exception:
        logger.warning("self_monitor: rules config unreadable", exc_info=True)
    return list(rules.values())


_OPS = {
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
}


@dataclass
class _RuleState:
    breach_since: float | None = None
    alert_row_id: int | None = None


class AlertEngine:
    """Evaluates rules each tick; owns firing state (recovered from the
    alerts table on start so restarts do not double-fire)."""

    def __init__(
        self,
        store: SelfMonitorStore,
        rules: list[AlertRule] | None = None,
        notifier: Notifier | None = None,
    ) -> None:
        self.store = store
        self.rules = rules if rules is not None else load_rules()
        self.notifier = notifier
        self._state: dict[str, _RuleState] = {}
        self._recovered = False

    def set_notifier(self, notifier: Notifier | None) -> None:
        self.notifier = notifier

    # ── evaluation ───────────────────────────────────────────────

    async def evaluate(self, now: float | None = None) -> None:
        """One evaluation pass. Never raises."""
        try:
            now = now if now is not None else time.time()
            if not self._recovered:
                self._recover_active()
            firing_by_severity: dict[str, int] = {}
            for rule in self.rules:
                try:
                    await self._evaluate_rule(rule, now)
                except Exception:
                    logger.debug(
                        "self_monitor rule %s evaluation failed",
                        rule.id,
                        exc_info=True,
                    )
                state = self._state.get(rule.id)
                if state and state.alert_row_id is not None:
                    firing_by_severity[rule.severity] = (
                        firing_by_severity.get(rule.severity, 0) + 1
                    )
            gauge = get_registry().gauge("qwenpaw_alerts_firing")
            for severity in ("warn", "critical"):
                gauge.set(
                    {"severity": severity},
                    float(firing_by_severity.get(severity, 0)),
                )
        except Exception:  # pragma: no cover - engine is fail-open
            logger.warning("self_monitor alert evaluation failed", exc_info=True)

    def _recover_active(self) -> None:
        for row in self.store.active_alerts():
            state = self._state.setdefault(str(row["ruleId"]), _RuleState())
            state.alert_row_id = int(row["id"])
            state.breach_since = float(row["startedAt"])
        self._recovered = True

    async def _evaluate_rule(self, rule: AlertRule, now: float) -> None:
        value, threshold = self._rule_value(rule, now)
        state = self._state.setdefault(rule.id, _RuleState())
        if value is None:  # no data → neither fire nor resolve
            return
        breach = _OPS.get(rule.op, _OPS[">"])(value, threshold)
        if breach:
            if state.breach_since is None:
                state.breach_since = now
            if state.alert_row_id is None and now - state.breach_since >= rule.for_s:
                await self._fire(rule, value, threshold, now)
            elif state.alert_row_id is not None:
                self.store.touch_alert(state.alert_row_id, value)
        else:
            state.breach_since = None
            if state.alert_row_id is not None:
                await self._resolve(rule, value, now)

    def _rule_value(self, rule: AlertRule, now: float) -> tuple[float | None, float]:
        if rule.kind == "counter_delta":
            return (
                self.store.counter_delta(
                    rule.metric,
                    since=now - rule.window_s,
                    label_filter=rule.label_filter,
                ),
                rule.threshold,
            )
        if rule.kind == "gauge_sum":
            return (
                self.store.gauge_agg(
                    rule.metric, agg="sum", label_filter=rule.label_filter
                ),
                rule.threshold,
            )
        if rule.kind == "gauge_min":
            return (
                self.store.gauge_agg(
                    rule.metric, agg="min", label_filter=rule.label_filter
                ),
                rule.threshold,
            )
        if rule.kind == "cost_daily":
            from .costs import cost_summary, day_start

            summary = cost_summary(self.store, since=day_start(now))
            budget = summary.get("budgetDaily")
            total = summary.get("total")
            if budget is None or total is None:
                return None, rule.threshold  # unpriced → rule dormant
            return float(total), float(budget)
        return None, rule.threshold

    async def _fire(
        self, rule: AlertRule, value: float, threshold: float, now: float
    ) -> None:
        # Multi-worker guard: another worker may have fired this rule
        # between our ticks — adopt its row instead of double-firing.
        # (A tiny check-then-insert race remains; ticks are jittered by
        # scheduling so in practice one worker wins.)
        existing = [
            row for row in self.store.active_alerts() if row["ruleId"] == rule.id
        ]
        if existing:
            self._state[rule.id].alert_row_id = int(existing[0]["id"])
            return
        message = _render(rule.message, value, threshold) or rule.name
        row_id = self.store.insert_alert(
            rule_id=rule.id,
            name=rule.name,
            layer=rule.layer,
            severity=rule.severity,
            value=value,
            threshold=threshold,
            message=message,
            started_at=now,
        )
        self._state[rule.id].alert_row_id = row_id
        emit_event(
            "alert.fired",
            severity="critical" if rule.severity == "critical" else "warn",
            layer=rule.layer,
            source=rule.id,
            message=f"[{rule.name}] {message}",
            dedup_key=f"alert.fired|{rule.id}",
        )
        await self._notify(f"🔴 [智观AI 自监控] {rule.name}\n{message}")

    async def _resolve(self, rule: AlertRule, value: float, now: float) -> None:
        row_id = self._state[rule.id].alert_row_id
        self._state[rule.id].alert_row_id = None
        changed = (
            self.store.resolve_alert(row_id, resolved_at=now, value=value)
            if row_id is not None
            else False
        )
        if not changed:  # another worker already resolved + notified
            return
        emit_event(
            "alert.resolved",
            severity="info",
            layer=rule.layer,
            source=rule.id,
            message=f"[{rule.name}] 已恢复",
            dedup_key=f"alert.resolved|{rule.id}",
        )
        await self._notify(f"🟢 [智观AI 自监控] {rule.name} 已恢复")

    async def _notify(self, text: str) -> None:
        if self.notifier is None:
            return
        try:
            await self.notifier(text)
        except Exception:
            logger.warning("self_monitor alert notify failed", exc_info=True)


def _render(template: str, value: float, threshold: float) -> str:
    try:
        return template.format(value=value, threshold=threshold)
    except Exception:
        return template


__all__ = [
    "AlertEngine",
    "AlertRule",
    "RULES_FILENAME",
    "default_rules",
    "load_rules",
]
