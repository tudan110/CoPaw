# -*- coding: utf-8 -*-
"""领域准入守卫 (domain relevance guard).

在导入技能 / MCP 之前，判断其是否属于本系统的领域（网络管理 / 网络运维 / NMS）。
不相关的内容会被拒绝，并向前端返回提示。

判定流程（分层漏斗）::

    L0   可信白名单（内置技能 / 管理员配置的名单）        -> 直接放行，不掏 LLM
    L1   关键词预筛（强正向 / 强负向 / 通用工具灰区）       -> 给 LLM 一个先验信号
    L1.5 命中多个正向词且无负向 / 无通用工具词              -> 直接放行，不掏 LLM
    L2   LLM 主审（用 qwenpaw 默认模型，严格 JSON 输出）   -> relevant / confidence / category / reason
    L3  置信度分档:  通过阈值 -> 放行;  低于阈值(灰区) -> 拒绝（可联系管理员加白名单）
    L4  LLM 不可用 / 超时 / 解析失败  -> 关键词兜底:有正向且无负向则放行,否则拒绝

裁判细则与词库是数据文件（``rubric.zh.md`` / ``lexicon.yaml``），运维管理员可直接编辑，
无需改代码；改动后哈希变化会令旧缓存失效。

配置：基准值放在 ``config.json`` 的 ``security.domain_guard`` 段（随 ``WORKING_DIR``
走，换部署方式不会丢）；下列环境变量在设置时**覆盖**对应字段（``COPAW_`` 为兼容别名）::

    QWENPAW_DOMAIN_GUARD_MODE        block(默认) | warn | off
    QWENPAW_DOMAIN_GUARD_CONFIDENCE  通过阈值，默认 0.7
    QWENPAW_DOMAIN_GUARD_LLM_TIMEOUT 单次 LLM 判定超时秒数，默认 15
    QWENPAW_DOMAIN_GUARD_ALLOWLIST   逗号/换行分隔的技能名或 MCP URL，命中即放行
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import threading
from concurrent import futures
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent
_RUBRIC_PATH = _DATA_DIR / "rubric.zh.md"
_LEXICON_PATH = _DATA_DIR / "lexicon.yaml"

_MAX_CONTENT_CHARS = 4000
_MAX_CACHE_ENTRIES = 128

__all__ = [
    "DomainGuardConfig",
    "DomainVerdict",
    "judge_text",
    "judge_text_async",
    "load_config",
    "register_skill_domain_analyzer",
]


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DomainGuardConfig:
    mode: str = "block"  # block | warn | off
    confidence_threshold: float = 0.7
    llm_timeout_seconds: float = 15.0
    extra_allowlist: tuple[str, ...] = ()


def _split_allowlist(raw: str) -> tuple[str, ...]:
    return tuple(
        x.strip().lower() for x in re.split(r"[,\n;]+", raw or "") if x.strip()
    )


def load_config() -> DomainGuardConfig:
    """Resolve domain-guard settings.

    Base values come from ``config.json`` -> ``security.domain_guard`` (which
    travels with the working dir under every deployment method); the
    ``QWENPAW_DOMAIN_GUARD_*`` env vars override individual fields when set.
    """
    mode = "block"
    thr = 0.7
    timeout = 15.0
    allow: tuple[str, ...] = ()

    # 1. base: config.json (security.domain_guard)
    try:
        from qwenpaw.config import load_config as _load_app_config

        dgc = _load_app_config().security.domain_guard
        cfg_mode = str(getattr(dgc, "mode", "block") or "block").strip().lower()
        if cfg_mode in ("block", "warn", "off"):
            mode = cfg_mode
        thr = float(getattr(dgc, "confidence_threshold", 0.7))
        timeout = float(getattr(dgc, "llm_timeout_seconds", 15.0))
        allow = tuple(
            str(x).strip().lower()
            for x in (getattr(dgc, "allowlist", None) or [])
            if str(x).strip()
        )
    except Exception as exc:  # pragma: no cover - config not ready / no section
        logger.debug(
            "domain_guard: no config.json section, using code defaults: %s", exc
        )

    # 2. env overrides (highest priority)
    try:
        from qwenpaw.constant import EnvVarLoader

        env_mode = (
            EnvVarLoader.get_str("QWENPAW_DOMAIN_GUARD_MODE", "") or ""
        ).strip().lower()
        if env_mode in ("block", "warn", "off"):
            mode = env_mode
        env_thr = (
            EnvVarLoader.get_str("QWENPAW_DOMAIN_GUARD_CONFIDENCE", "") or ""
        ).strip()
        if env_thr:
            try:
                thr = float(env_thr)
            except ValueError:
                pass
        env_timeout = (
            EnvVarLoader.get_str("QWENPAW_DOMAIN_GUARD_LLM_TIMEOUT", "") or ""
        ).strip()
        if env_timeout:
            try:
                timeout = float(env_timeout)
            except ValueError:
                pass
        env_allow = EnvVarLoader.get_str("QWENPAW_DOMAIN_GUARD_ALLOWLIST", "") or ""
        if env_allow.strip():
            allow = _split_allowlist(env_allow)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("domain_guard: env override read failed: %s", exc)

    mode = mode if mode in ("block", "warn", "off") else "block"
    thr = min(1.0, max(0.0, thr))
    timeout = timeout if timeout and timeout > 0 else 15.0
    return DomainGuardConfig(
        mode=mode,
        confidence_threshold=thr,
        llm_timeout_seconds=timeout,
        extra_allowlist=allow,
    )


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------
@dataclass
class DomainVerdict:
    relevant: bool
    confidence: float
    category: str
    reason: str
    decision: str  # "allow" | "reject" | "reject_unavailable"
    source: str  # disabled | builtin | allowlist | llm | error

    @property
    def allowed(self) -> bool:
        return self.decision == "allow"

    def reject_message(self) -> str:
        if self.decision == "reject_unavailable":
            return "技能领域审核失败，请稍后重试或联系管理员。"
        cat = f"（识别为 {self.category}）" if self.category else ""
        why = self.reason or "判断为与网络管理 / 运维无关"
        return (
            "当前系统仅支持导入网络管理 / 运维相关的技能或工具。"
            f"{why}{cat}。如确属网管相关，请联系管理员加入白名单。"
        )

    def to_payload(self, *, kind: str, name: str) -> dict[str, Any]:
        return {
            "type": (
                "domain_rejected"
                if self.decision == "reject"
                else "domain_check_unavailable"
            ),
            "detail": self.reject_message(),
            "kind": kind,
            "name": name,
            "category": self.category,
            "confidence": self.confidence,
            "source": self.source,
        }


# ---------------------------------------------------------------------------
# Lexicon / rubric loaders (mtime-cached)
# ---------------------------------------------------------------------------
_lex_lock = threading.Lock()
_lex_cache: Optional[tuple[Any, dict[str, list[str]]]] = None
_rubric_lock = threading.Lock()
_rubric_cache: Optional[tuple[Any, str]] = None


def _fingerprint(path: Path) -> Any:
    try:
        st = path.stat()
        return (st.st_mtime, st.st_size)
    except OSError:
        return None


_FALLBACK_RUBRIC = (
    "本系统是网络管理 / 网络运维（NMS）平台，仅承载与网络管理、IT 基础设施运维相关的能力："
    "故障/告警、性能、配置、资源/CMDB/拓扑、巡检、运维自动化、监控、ITSM/工单、SLA。"
    "财务/医疗/法律/HR/营销/电商/金融交易/通用内容创作等其它专业方向的能力不予导入。"
    "通用工具（shell/文件/HTTP/数据库/K8s/Grafana/Jira/IM 等）若未声明网管用途则从严拒绝。"
)


def _load_rubric() -> str:
    global _rubric_cache
    fp = _fingerprint(_RUBRIC_PATH)
    with _rubric_lock:
        if _rubric_cache and _rubric_cache[0] == fp and fp is not None:
            return _rubric_cache[1]
        text = _FALLBACK_RUBRIC
        if fp is not None:
            try:
                raw = _RUBRIC_PATH.read_text(encoding="utf-8").strip()
                text = raw or _FALLBACK_RUBRIC
            except OSError as exc:
                logger.warning(
                    "domain_guard: failed to read rubric: %s", exc
                )
        _rubric_cache = (fp, text)
        return text


def _load_lexicon() -> dict[str, list[str]]:
    global _lex_cache
    fp = _fingerprint(_LEXICON_PATH)
    with _lex_lock:
        if _lex_cache and _lex_cache[0] == fp and fp is not None:
            return _lex_cache[1]
        data: dict[str, Any] = {}
        if fp is not None:
            try:
                import yaml

                raw = _LEXICON_PATH.read_text(encoding="utf-8")
                data = yaml.safe_load(raw) or {}
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("domain_guard: failed to load lexicon: %s", exc)
                data = {}

        def _norm(key: str) -> list[str]:
            return [
                str(x).strip().lower()
                for x in (data.get(key) or [])
                if str(x).strip()
            ]

        norm = {
            "positive": _norm("positive"),
            "negative": _norm("negative"),
            "borderline": _norm("borderline"),
        }
        _lex_cache = (fp, norm)
        return norm


def _prefilter(text: str) -> dict[str, list[str]]:
    low = (text or "").lower()
    lex = _load_lexicon()
    return {
        "positive": sorted({t for t in lex["positive"] if t and t in low}),
        "negative": sorted({t for t in lex["negative"] if t and t in low}),
        "borderline": sorted({t for t in lex["borderline"] if t and t in low}),
    }


# ---------------------------------------------------------------------------
# Verdict cache (in-memory, content-hash keyed; only allow/reject are cached)
# ---------------------------------------------------------------------------
_cache_lock = threading.Lock()
_verdict_cache: "dict[str, DomainVerdict]" = {}


def _content_digest(
    kind: str,
    name: str,
    description: str,
    content: str,
    extra: Optional[dict[str, Any]],
) -> str:
    h = hashlib.sha256()
    for part in (
        kind,
        name or "",
        description or "",
        (content or "")[:8000],
        json.dumps(extra or {}, sort_keys=True, ensure_ascii=False),
        json.dumps(_fingerprint(_RUBRIC_PATH)),
        json.dumps(_fingerprint(_LEXICON_PATH)),
    ):
        h.update(str(part).encode("utf-8", "replace"))
        h.update(b"\x00")
    return h.hexdigest()


def _cache_get(digest: str) -> Optional[DomainVerdict]:
    with _cache_lock:
        return _verdict_cache.get(digest)


def _cache_put(digest: str, verdict: DomainVerdict) -> None:
    if verdict.decision not in ("allow", "reject"):
        return
    with _cache_lock:
        _verdict_cache.pop(digest, None)
        _verdict_cache[digest] = verdict
        while len(_verdict_cache) > _MAX_CACHE_ENTRIES:
            del _verdict_cache[next(iter(_verdict_cache))]


def _clear_cache() -> None:  # used by tests
    with _cache_lock:
        _verdict_cache.clear()


# ---------------------------------------------------------------------------
# LLM plumbing
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT_HEAD = (
    "你是一套网络管理 / 网络运维（NMS / 网管）平台的『能力准入审查员』。"
    "下面是该系统的领域裁判细则，请严格据此判断一个待导入的技能或外部工具（MCP）"
    "是否属于本平台的领域。\n\n===== 裁判细则 =====\n"
)
_SYSTEM_PROMPT_TAIL = (
    "\n===== 细则结束 =====\n\n"
    "判断原则：1) 看其主要用途落在 IN-SCOPE 还是 OUT-OF-SCOPE；"
    "2) 通用工具要看是否声明了网管场景，没声明则从严视为不够明确；"
    "3) 拿不准时给较低的 confidence（上层会按从严原则处理）。\n"
    "只输出一个 JSON 对象，不要 markdown 代码块、不要任何额外文字："
    ' {"relevant": true/false, "confidence": 0.0~1.0, '
    '"category": "<最贴切的领域分类，中文短语>", "reason": "<一句话中文理由>"}'
)


def _system_prompt(rubric: str) -> str:
    return _SYSTEM_PROMPT_HEAD + rubric + _SYSTEM_PROMPT_TAIL


def _safe_attr(obj: Any, name: str) -> Any:
    try:
        return getattr(obj, name, None)
    except Exception:  # pragma: no cover - defensive
        return None


def _first_text_in_list(items: list) -> str:
    for item in items or []:
        if isinstance(item, str) and item:
            return item
        if isinstance(item, dict):
            t = item.get("text")
            if isinstance(t, str) and t:
                return t
    return ""


def _extract_text(response: Any) -> str:
    if response is None:
        return ""
    if isinstance(response, str):
        return response
    text = _safe_attr(response, "text")
    if isinstance(text, str) and text:
        return text
    content = _safe_attr(response, "content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return _first_text_in_list(content)
    return ""


async def _consume(model: Any, messages: list) -> str:
    response = await model(messages)
    if hasattr(response, "__aiter__"):
        accumulated = ""
        async for chunk in response:
            text = _extract_text(chunk)
            if text:
                accumulated = text
        return accumulated
    return _extract_text(response)


_JSON_OBJ_RE = re.compile(r"\{.*\}", re.S)


def _parse_verdict_json(raw: str) -> Optional[dict[str, Any]]:
    if not raw:
        return None
    candidate = raw.strip()
    # strip ```json ... ``` fences if present
    if candidate.startswith("```"):
        candidate = candidate.strip("`")
        if candidate.lower().startswith("json"):
            candidate = candidate[4:]
        candidate = candidate.strip()
    try:
        obj = json.loads(candidate)
        if isinstance(obj, dict):
            return obj
    except (ValueError, TypeError):
        pass
    m = _JSON_OBJ_RE.search(raw)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return obj
        except (ValueError, TypeError):
            return None
    return None


# Allow tests to inject a fake LLM without touching the agent stack.
_llm_override = None  # type: ignore[var-annotated]


async def _llm_judge(
    *,
    kind: str,
    name: str,
    description: str,
    content: str,
    extra: dict[str, Any],
    signals: dict[str, list[str]],
    timeout: float,
) -> DomainVerdict:
    rubric = _load_rubric()
    body_excerpt = (content or "")[:_MAX_CONTENT_CHARS]
    extra_lines = "\n".join(
        f"- {k}: {v}" for k, v in (extra or {}).items() if v
    )
    label = "技能" if kind == "skill" else "外部工具(MCP)"
    user_prompt = (
        f"待判定的{label}:\n"
        f"名称: {name}\n"
        f"描述: {description}\n"
        + (f"附加信息:\n{extra_lines}\n" if extra_lines else "")
        + (f"内容节选:\n{body_excerpt}\n" if body_excerpt else "")
        + "\n关键词预筛信号："
        f"正向命中={signals.get('positive')}; "
        f"负向命中={signals.get('negative')}; "
        f"通用工具词命中={signals.get('borderline')}\n"
        '\n现在只输出 JSON: {"relevant": true/false, "confidence": 0.0~1.0,'
        ' "category": "...", "reason": "..."}'
    )
    messages = [
        {"role": "system", "content": _system_prompt(rubric)},
        {"role": "user", "content": user_prompt},
    ]

    if _llm_override is not None:
        raw = await asyncio.wait_for(
            _llm_override(messages), timeout=timeout
        )
        parsed = _parse_verdict_json(raw)
    else:
        from qwenpaw.agents.model_factory import create_model_and_formatter

        model = None
        last_exc: Exception | None = None
        for slot_agent_id in (None, "default"):
            try:
                model, _ = create_model_and_formatter(agent_id=slot_agent_id)
                break
            except Exception as exc:  # noqa: BLE001 - try the next fallback
                last_exc = exc
                model = None
        if model is None:
            raise RuntimeError(f"无可用模型用于领域审核: {last_exc}")

        raw = await asyncio.wait_for(_consume(model, messages), timeout=timeout)
        parsed = _parse_verdict_json(raw)
        if parsed is None:
            # One retry, nudging the model to emit JSON only.
            retry_messages = messages + [
                {
                    "role": "user",
                    "content": (
                        "上面的回答不是合法 JSON。请只输出一个 JSON 对象，"
                        '形如 {"relevant": true, "confidence": 0.9, '
                        '"category": "...", "reason": "..."}，不要任何其它文字。'
                    ),
                },
            ]
            try:
                raw = await asyncio.wait_for(
                    _consume(model, retry_messages), timeout=timeout
                )
                parsed = _parse_verdict_json(raw)
            except Exception:  # noqa: BLE001 - fall through to the error below
                parsed = None

    if parsed is None:
        raise ValueError(f"无法解析模型返回的 JSON: {str(raw)[:200]!r}")
    relevant = bool(parsed.get("relevant"))
    try:
        confidence = float(parsed.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = min(1.0, max(0.0, confidence))
    category = str(parsed.get("category") or "").strip()
    reason = str(parsed.get("reason") or "").strip()
    return DomainVerdict(
        relevant=relevant,
        confidence=confidence,
        category=category,
        reason=reason,
        decision="",
        source="llm",
    )


# ---------------------------------------------------------------------------
# Core layered judge
# ---------------------------------------------------------------------------
def _allow(source: str, category: str = "", reason: str = "") -> DomainVerdict:
    return DomainVerdict(True, 1.0, category, reason, "allow", source)


async def _judge_async_impl(
    *,
    kind: str,
    name: str,
    description: str,
    content: str = "",
    extra: Optional[dict[str, Any]] = None,
    is_builtin: bool = False,
) -> DomainVerdict:
    cfg = load_config()
    extra = extra or {}

    # L0a: globally disabled
    if cfg.mode == "off":
        return _allow("disabled")

    # L0b: trusted builtin
    if is_builtin:
        return _allow("builtin", "内置能力", "随系统发布的内置技能/工具")

    # L0c: admin allowlist (skill name or MCP url substring)
    name_l = (name or "").strip().lower()
    url_l = str(extra.get("url") or "").lower()
    for entry in cfg.extra_allowlist:
        if entry and (entry == name_l or (url_l and entry in url_l)):
            return _allow("allowlist", "", "管理员白名单")

    # cache
    digest = _content_digest(kind, name, description, content, extra)
    cached = _cache_get(digest)
    if cached is not None:
        return cached

    # L1: cheap keyword prefilter (signal only — LLM still decides)
    haystack = " ".join(
        x
        for x in (
            name,
            description,
            (content or "")[:_MAX_CONTENT_CHARS],
            json.dumps(extra, ensure_ascii=False),
        )
        if x
    )
    signals = _prefilter(haystack)

    # L1.5: strong, unambiguous keyword evidence -> allow without an LLM call.
    # Triggers only when there are >=2 network-management terms AND zero
    # off-domain signals AND zero "generic tool" (borderline) signals — so
    # off-domain content and ambiguous generic tools still go to the LLM.
    # This also keeps obviously-on-domain imports working when the model is
    # temporarily unavailable.
    if (
        len(signals["positive"]) >= 2
        and not signals["negative"]
        and not signals["borderline"]
    ):
        verdict = _allow(
            "lexicon",
            "网络管理 / 运维相关",
            "命中多个网管领域关键词，且无任何其它领域 / 通用工具信号",
        )
        _cache_put(digest, verdict)
        return verdict

    # L2: LLM verdict
    try:
        verdict = await _llm_judge(
            kind=kind,
            name=name,
            description=description,
            content=content,
            extra=extra,
            signals=signals,
            timeout=cfg.llm_timeout_seconds,
        )
    except Exception as exc:
        logger.warning(
            "domain_guard: LLM verdict failed for %s '%s': %s", kind, name, exc
        )
        # L4: judge unavailable (timeout / no model / unparseable output).
        # warn mode: pass through with a flag.
        if cfg.mode == "warn":
            return _allow("error", "", "领域审核服务不可用（warn 模式放行）")
        # Graceful degradation: when the judge itself can't run, fall back to
        # the keyword lexicon instead of blocking every import. Strong
        # on-domain evidence (>=1 positive term) with no off-domain signal is
        # enough to admit the skill — otherwise a slow / rate-limited model
        # walls off everything, including clearly network-management skills.
        # Not cached, so a recovered model still gets to re-judge next time.
        if signals["positive"] and not signals["negative"]:
            logger.info(
                "domain_guard: judge unavailable, admitting %s '%s' by "
                "lexicon fallback (positive=%s, no negative signal)",
                kind,
                name,
                signals["positive"],
            )
            return _allow(
                "lexicon-fallback",
                "网络管理 / 运维相关",
                "领域审核服务暂不可用，按关键词命中放行（有正向且无负向信号）",
            )
        return DomainVerdict(
            False, 0.0, "", f"领域审核服务不可用: {exc}", "reject_unavailable", "error"
        )

    # L3: confidence banding
    if verdict.relevant and verdict.confidence >= cfg.confidence_threshold:
        verdict.decision = "allow"
    else:
        # not relevant, OR relevant-but-low-confidence (borderline): reject (strict)
        verdict.decision = "reject"
        if not verdict.relevant:
            if not verdict.reason:
                verdict.reason = "判断为与网络管理 / 运维无关"
        else:
            verdict.reason = (
                (verdict.reason + "；" if verdict.reason else "")
                + "判定置信度不足，按从严原则不予导入"
            )

    if cfg.mode == "warn" and verdict.decision == "reject":
        return DomainVerdict(
            True,
            verdict.confidence,
            verdict.category,
            f"[warn]{verdict.reason}",
            "allow",
            verdict.source,
        )

    _cache_put(digest, verdict)
    return verdict


async def judge_text_async(
    *,
    kind: str,
    name: str,
    description: str,
    content: str = "",
    extra: Optional[dict[str, Any]] = None,
    is_builtin: bool = False,
) -> DomainVerdict:
    """Async entry point — use from FastAPI handlers."""
    return await _judge_async_impl(
        kind=kind,
        name=name,
        description=description,
        content=content,
        extra=extra,
        is_builtin=is_builtin,
    )


def _run_async(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # We are already inside an event loop (rare here) -> offload to a thread.
    with futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(lambda: asyncio.run(coro)).result()


def judge_text(
    *,
    kind: str,
    name: str,
    description: str,
    content: str = "",
    extra: Optional[dict[str, Any]] = None,
    is_builtin: bool = False,
) -> DomainVerdict:
    """Synchronous entry point — safe to call from worker threads."""
    return _run_async(
        _judge_async_impl(
            kind=kind,
            name=name,
            description=description,
            content=content,
            extra=extra,
            is_builtin=is_builtin,
        )
    )


# Re-export the analyzer registration helper (kept in a submodule to avoid a
# hard import of the security package at module-load time).
def register_skill_domain_analyzer() -> bool:
    from .analyzer import register_skill_domain_analyzer as _reg

    return _reg()
