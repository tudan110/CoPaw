# -*- coding: utf-8 -*-
"""出口脱敏引擎 (outgoing-message redactor).

对即将发往聊天渠道的文本做敏感信息打码：

* 内置凭证类 pattern（API key / token / 密码 / 私钥 / JWT / DB 连接串）；
* 用户自维护的业务词库 ``lexicon.yaml``（字面词 + 正则，mtime 热加载）。

设计要点：

* **打码幂等**：打码后的文本不会再命中任何 pattern（掩码字符 ``*`` 不在
  各 pattern 的字符类里，partial 打码保留前后缀且长度不变），因此同一段
  文本被多层包装重复脱敏是无害的。
* **只记 id 不记值**：`redact` 返回命中的 pattern id 列表供日志使用，
  绝不返回 / 记录原始敏感值；词库命中以序号代替词条本身。
* **fail-open**：词库文件损坏 / 正则非法时记日志跳过，内置 pattern
  照常生效。
"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent
_DEFAULT_LEXICON_PATH = _DATA_DIR / "lexicon.yaml"

_MASK_CHAR = "*"

__all__ = [
    "OutputGuardSettings",
    "clear_caches",
    "mask_value",
    "redact",
]


# ---------------------------------------------------------------------------
# Settings (resolved by output_guard.load_config; defaults used standalone)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class OutputGuardSettings:
    enabled: bool = True
    mode: str = "mask"  # mask | off
    lexicon_path: str = ""  # empty -> bundled lexicon.yaml
    disabled_patterns: Tuple[str, ...] = ()
    mask_streaming: bool = True

    @property
    def active(self) -> bool:
        return self.enabled and self.mode == "mask"


# ---------------------------------------------------------------------------
# Masking helpers
# ---------------------------------------------------------------------------
def mask_value(
    s: str,
    keep_prefix: int = 4,
    keep_suffix: int = 2,
    min_mask: int = 4,
) -> str:
    """Mask ``s`` keeping a short prefix/suffix hint.

    Length-preserving for strings longer than ``min_mask`` (which makes
    repeated masking idempotent); short strings collapse to stars.
    """
    n = len(s)
    keep_prefix = max(0, keep_prefix)
    keep_suffix = max(0, keep_suffix)
    if n <= min_mask:
        return _MASK_CHAR * n
    while keep_prefix + keep_suffix + min_mask > n and keep_suffix > 0:
        keep_suffix -= 1
    while keep_prefix + keep_suffix + min_mask > n and keep_prefix > 0:
        keep_prefix -= 1
    masked = _MASK_CHAR * (n - keep_prefix - keep_suffix)
    suffix = s[n - keep_suffix :] if keep_suffix else ""
    return s[:keep_prefix] + masked + suffix


def _mask_full(s: str) -> str:
    """Fully mask a value with a short, bounded run of stars."""
    return _MASK_CHAR * min(max(len(s), 4), 8)


# ---------------------------------------------------------------------------
# Built-in credential patterns (order matters: most specific first)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _Pattern:
    id: str
    regex: "re.Pattern[str]"
    group: int = 0  # which group to mask (0 = whole match)
    style: str = "partial"  # partial | full | fixed
    keep_prefix: int = 4
    keep_suffix: int = 2
    replacement: str = ""  # for style == "fixed"

    def mask(self, value: str) -> str:
        if self.style == "fixed":
            return self.replacement
        if self.style == "full":
            return _mask_full(value)
        return mask_value(value, self.keep_prefix, self.keep_suffix)


_BUILTIN_PATTERNS: Tuple[_Pattern, ...] = (
    _Pattern(
        id="pem_private_key",
        regex=re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----"
            r"[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----",
        ),
        style="fixed",
        replacement="[REDACTED PRIVATE KEY]",
    ),
    _Pattern(
        id="anthropic_key",
        regex=re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}"),
        keep_prefix=9,  # "sk-ant-" + 2
        keep_suffix=2,
    ),
    _Pattern(
        id="openai_dashscope_key",
        regex=re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
        keep_prefix=6,  # "sk-" + 3
        keep_suffix=2,
    ),
    _Pattern(
        id="aliyun_ak_id",
        regex=re.compile(r"\bLTAI[A-Za-z0-9]{12,24}\b"),
        keep_prefix=6,
        keep_suffix=2,
    ),
    _Pattern(
        id="aws_ak_id",
        regex=re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        keep_prefix=6,
        keep_suffix=2,
    ),
    _Pattern(
        id="github_token",
        regex=re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
        keep_prefix=6,
        keep_suffix=2,
    ),
    _Pattern(
        id="jwt",
        regex=re.compile(
            r"\beyJ[A-Za-z0-9_-]{10,}"
            r"\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{10,}\b",
        ),
        style="fixed",
        replacement="eyJ***.[REDACTED-JWT]",
    ),
    _Pattern(
        id="db_uri_password",
        regex=re.compile(
            r"\b(?:mysql|postgres(?:ql)?|mongodb(?:\+srv)?|redis"
            r"|amqp|mssql|jdbc:[a-z]+)://[^\s:@/]+:([^\s@/]+)@",
            re.IGNORECASE,
        ),
        group=1,
        style="full",
    ),
    _Pattern(
        id="bearer_token",
        regex=re.compile(
            r"\bBearer\s+([A-Za-z0-9._~+/=-]{16,})",
            re.IGNORECASE,
        ),
        group=1,
        keep_prefix=4,
        keep_suffix=2,
    ),
    _Pattern(
        id="kv_secret_assignment",
        regex=re.compile(
            r"\b(?:password|passwd|pwd|secret|token|api[_-]?key"
            r"|access[_-]?key[_-]?secret|client[_-]?secret)\b"
            r"\s*[:=]\s*[\"']?([^\s\"',;*]{6,})",
            re.IGNORECASE,
        ),
        group=1,
        keep_prefix=4,
        keep_suffix=2,
    ),
    _Pattern(
        id="cn_mobile",
        regex=re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
        keep_prefix=3,
        keep_suffix=4,
    ),
)


# ---------------------------------------------------------------------------
# Streaming tail guard: mask an unfinished high-confidence credential
# fragment at the end of accumulated streaming text (delta updates only).
# ---------------------------------------------------------------------------
_TAIL_GUARD_RE = re.compile(
    r"(?:\bsk-[A-Za-z0-9_-]*"
    r"|\bAKIA[0-9A-Z]*"
    r"|\bLTAI[A-Za-z0-9]*"
    r"|\bgh[pousr]_[A-Za-z0-9]*"
    r"|\beyJ[A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]*){0,2}"
    r"|-----BEGIN[A-Z ]*[\s\S]*"
    r"|\b(?:[Pp]assword|[Pp]asswd|[Pp]wd|[Ss]ecret|[Tt]oken"
    r"|[Aa]pi[_-]?[Kk]ey)\s*[:=]\s*\S*)\Z",
)


# ---------------------------------------------------------------------------
# Lexicon (user-maintained YAML, mtime hot-reloaded; domain_guard mechanics)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _LexiconEntry:
    regex: "re.Pattern[str]"
    style: str  # partial | full | fixed
    keep_prefix: int = 0
    keep_suffix: int = 0
    replacement: str = ""

    def mask(self, value: str) -> str:
        if self.style == "fixed":
            return self.replacement
        if self.style == "partial":
            return mask_value(value, self.keep_prefix, self.keep_suffix)
        return _mask_full(value)


_lex_lock = threading.Lock()
_lex_cache: Optional[Tuple[str, Any, Tuple[_LexiconEntry, ...]]] = None


def _fingerprint(path: Path) -> Any:
    try:
        st = path.stat()
        return (st.st_mtime, st.st_size)
    except OSError:
        return None


def _compile_word_entry(item: Any) -> Optional[_LexiconEntry]:
    if isinstance(item, dict):
        text = str(item.get("text") or "").strip()
        mask = str(item.get("mask") or "").strip()
    else:
        text, mask = str(item).strip(), ""
    if not text:
        return None
    rx = re.compile(re.escape(text), re.IGNORECASE)
    if mask:
        return _LexiconEntry(regex=rx, style="fixed", replacement=mask)
    return _LexiconEntry(regex=rx, style="full")


def _compile_regex_entry(item: Any) -> Optional[_LexiconEntry]:
    if not isinstance(item, dict):
        return None
    pattern = str(item.get("pattern") or "")
    if not pattern:
        return None
    style = str(item.get("style") or "full").strip().lower()
    if style not in ("partial", "full", "fixed"):
        style = "full"
    return _LexiconEntry(
        regex=re.compile(pattern),
        style=style,
        keep_prefix=int(item.get("keep_prefix") or 0),
        keep_suffix=int(item.get("keep_suffix") or 0),
        replacement=str(item.get("replacement") or "[已脱敏]"),
    )


def _compile_lexicon(data: Any) -> Tuple[_LexiconEntry, ...]:
    entries: List[_LexiconEntry] = []
    if not isinstance(data, dict):
        return ()
    for kind, compiler in (
        ("words", _compile_word_entry),
        ("regexes", _compile_regex_entry),
    ):
        for item in data.get(kind) or []:
            try:
                entry = compiler(item)
                if entry is not None:
                    entries.append(entry)
            except Exception as exc:
                logger.warning(
                    "output_guard: invalid lexicon %s entry skipped: %s",
                    kind,
                    exc,
                )
    return tuple(entries)


def _load_lexicon(lexicon_path: str = "") -> Tuple[_LexiconEntry, ...]:
    global _lex_cache
    path = Path(lexicon_path) if lexicon_path else _DEFAULT_LEXICON_PATH
    key = str(path)
    fp = _fingerprint(path)
    with _lex_lock:
        if (
            _lex_cache
            and _lex_cache[0] == key
            and _lex_cache[1] == fp
            and fp is not None
        ):
            return _lex_cache[2]
        entries: Tuple[_LexiconEntry, ...] = ()
        if fp is not None:
            try:
                import yaml

                raw = path.read_text(encoding="utf-8")
                entries = _compile_lexicon(yaml.safe_load(raw) or {})
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "output_guard: failed to load lexicon %s: %s",
                    key,
                    exc,
                )
                entries = ()
        _lex_cache = (key, fp, entries)
        return entries


def clear_caches() -> None:
    """Reset the lexicon cache (used by tests)."""
    global _lex_cache
    with _lex_lock:
        _lex_cache = None


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------
def _apply(
    regex: "re.Pattern[str]",
    group: int,
    mask_fn: Callable[[str], str],
    text: str,
) -> Tuple[str, bool]:
    changed = False

    def _repl(m: "re.Match[str]") -> str:
        nonlocal changed
        target = m.group(group) if group else m.group(0)
        if target is None:
            return m.group(0)
        masked = mask_fn(target)
        if masked == target:
            return m.group(0)
        changed = True
        if not group:
            return masked
        whole = m.group(0)
        start = m.start(group) - m.start(0)
        end = m.end(group) - m.start(0)
        return whole[:start] + masked + whole[end:]

    return regex.sub(_repl, text), changed


def redact(
    text: str,
    *,
    cfg: Optional[OutputGuardSettings] = None,
    streaming_tail_guard: bool = False,
) -> Tuple[str, List[str]]:
    """Mask sensitive fragments in ``text``.

    Returns ``(masked_text, hit_pattern_ids)``. Pattern ids are safe to
    log; the original sensitive values are never returned.
    """
    cfg = cfg or OutputGuardSettings()
    if not text or not cfg.active:
        return text, []

    hits: List[str] = []
    disabled = set(cfg.disabled_patterns)

    for pat in _BUILTIN_PATTERNS:
        if pat.id in disabled:
            continue
        text, changed = _apply(pat.regex, pat.group, pat.mask, text)
        if changed:
            hits.append(pat.id)

    for idx, entry in enumerate(_load_lexicon(cfg.lexicon_path)):
        text, changed = _apply(entry.regex, 0, entry.mask, text)
        if changed:
            hits.append(f"lexicon:{idx}")

    if streaming_tail_guard:
        m = _TAIL_GUARD_RE.search(text)
        if m and m.group(0):
            tail = m.group(0)
            masked = mask_value(tail, keep_prefix=3, keep_suffix=0)
            if masked != tail:
                text = text[: m.start()] + masked
                hits.append("streaming_tail_guard")

    return text, hits
