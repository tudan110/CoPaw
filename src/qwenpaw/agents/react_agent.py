# -*- coding: utf-8 -*-
"""QwenPaw Agent - Main agent implementation.

This module provides the main QwenPawAgent class built on ReActAgent,
with integrated tools, skills, and memory management.

Agent construction is fully delegated to :class:`AgentBuilder` — the
agent accepts all dependencies (model, prompt, toolkit, middlewares)
as constructor parameters and does not build them internally.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal, Optional, TYPE_CHECKING

from agentscope.agent import Agent, ReActConfig
from agentscope.message import Msg, TextBlock
from agentscope.state import AgentState
from agentscope.tool import Toolkit

from .skill_system import get_workspace_skills_dir
from ..modes.coding import CodingModeMixin
from ..constant import (
    AUTO_CONTINUE_MESSAGE_TAG,
    FASTFAIL_CONVERGE_MESSAGE_TAG,
    MEDIA_UNSUPPORTED_PLACEHOLDER,
    QWENPAW_MESSAGE_TAG_KEY,
    WORKING_DIR,
)
from ..providers.model_capability_cache import get_capability_cache

if TYPE_CHECKING:
    from ..agents.memory import BaseMemoryManager
    from ..config.config import AgentProfileConfig

logger = logging.getLogger(__name__)


class QwenPawAgent(CodingModeMixin, Agent):
    """QwenPaw Agent with integrated tools, skills, and memory management.

    This agent extends agentscope 2.0 ``Agent`` with:
    - Built-in tools (shell, file operations, browser, etc.)
    - Dynamic skill loading from working directory
    - Memory management with auto-compaction
    - Bootstrap guidance for first-time setup
    - Tool-guard security (via ``PolicyGuardedTool.check_permissions``)
    - Coding Mode features: Inline Diff (via CodingModeMixin)
    """

    def __init__(
        self,
        *,
        name: str,
        model: Any,
        system_prompt: str,
        toolkit: Toolkit,
        react_config: ReActConfig,
        middlewares: list,
        agent_config: "AgentProfileConfig",
        workspace_dir: Path | None = None,
        request_context: Optional[dict[str, str]] = None,
        memory_manager: "BaseMemoryManager | None" = None,
        offloader: Any = None,
        context_config: Any = None,
        context_manager: Any = None,
        effective_skills: Optional[list[str]] = None,
        governor: Any = None,
    ):
        """Initialize QwenPawAgent.

        All construction dependencies (model, prompt, toolkit, middlewares)
        are provided externally by :class:`AgentBuilder`. The agent does
        not build any of these internally.
        """
        self._agent_config = agent_config
        self._request_context = dict(request_context or {})
        self._workspace_dir = workspace_dir
        self._language = agent_config.language
        # Optional context-management strategy. When None, the agent keeps its
        # native AgentScope compression (see compress_context /
        # _save_to_context).
        self._context_manager = context_manager

        # Register skills metadata on toolkit
        self._register_skills(toolkit, effective_skills=effective_skills or [])

        self._governor = governor

        self.memory_manager = memory_manager

        # Register memory tools into toolkit
        if self.memory_manager is not None:
            memory_tools = self.memory_manager.list_memory_tools()
            basic_group = toolkit.tool_groups[0]
            for tool_fn in memory_tools:
                from ..governance import PolicyGuardedTool

                basic_group.tools.append(
                    PolicyGuardedTool(
                        tool_fn,
                        governor=self._governor,
                        request_context=self._request_context,
                    ),
                )
            logger.debug(
                "Registered memory tools: %s",
                [fn.__name__ for fn in memory_tools],
            )

        init_kwargs: dict[str, Any] = {
            "name": name,
            "model": model,
            "system_prompt": system_prompt,
            "toolkit": toolkit,
            "react_config": react_config,
            "middlewares": middlewares,
            "offloader": offloader,
        }
        if context_config is not None:
            init_kwargs["context_config"] = context_config
        super().__init__(**init_kwargs)

        # Bypass agentscope's built-in permission engine — qwenpaw uses
        # its own PolicyGuardedTool.check_permissions for tool-guard.
        from agentscope.permission import PermissionMode

        self.state.permission_context.mode = PermissionMode.BYPASS

        # Tombstone for legacy ``getattr(agent, "memory", None)`` callers
        self.memory = None  # type: ignore[assignment]

        self._register_tool_call_hooks()

    async def compress_context(
        self,
        context_config: Any = None,
    ) -> None:
        """Delegate to the context manager, else native compression.

        With a ``context_manager`` injected (e.g. the scroll strategy), it owns
        compression. Otherwise fall back to AgentScope's native path, gated on
        ``context_compact_config.enabled``.
        """
        if self._context_manager is not None:
            await self._context_manager.compress(self, context_config)
            return
        try:
            lcc = self._agent_config.running.light_context_config
            if not lcc.context_compact_config.enabled:
                return
        except Exception:
            pass
        await super().compress_context(context_config)

    def _save_to_context(self, blocks: Any, usage: Any = None) -> None:
        """Append blocks, then let the context manager write them through."""
        super()._save_to_context(blocks, usage)
        if self._context_manager is not None:
            self._context_manager.on_save(self, blocks)

    # Session persistence calls state_dict/load_state_dict on the agent;
    # these round-trip through self.state (AgentState pydantic model).
    def state_dict(self) -> dict:
        """Serialize the agent's 2.0 ``AgentState`` to a JSON-safe dict."""
        state = getattr(self, "state", None)
        if state is None:
            return {}
        out = {"state": state.model_dump(mode="json")}
        # Persist the scroll manager's dedup bookkeeping + eviction index so a
        # resumed session doesn't re-append its restored window to history.db.
        cm = getattr(self, "_context_manager", None)
        if cm is not None and hasattr(cm, "to_dict"):
            out["scroll"] = cm.to_dict()
        return out

    def load_state_dict(self, state_dict: dict, strict: bool = True) -> None:
        """Restore ``self.state`` from a dict produced by :meth:`state_dict`.

        Handles two formats:
        - **2.0**: ``{"state": {AgentState dump}}``
        - **1.x legacy**: ``{"memory": {"content": [[msg, marks], ...],
          "_compressed_summary": "..."}}`` — converted on-the-fly so
          existing sessions survive the upgrade.
        """
        if not isinstance(state_dict, dict):
            if strict:
                raise KeyError("state_dict is not a dict")
            return

        # --- 2.0 format (preferred) ---
        raw = state_dict.get("state")
        if raw is not None:
            try:
                self.state = AgentState.model_validate(raw)
            except Exception as exc:
                raise KeyError(
                    f"Could not load AgentState from snapshot: {exc}",
                ) from exc
            # Rehydrate the scroll manager's bookkeeping so the restored window
            # is recognized as already durable (no re-append on resume).
            cm = getattr(self, "_context_manager", None)
            scroll = state_dict.get("scroll")
            if (
                cm is not None
                and scroll is not None
                and hasattr(cm, "load_state")
            ):
                cm.load_state(scroll)
            return

        # --- 1.x legacy format: migrate ``memory`` → ``state`` ---
        memory_raw = state_dict.get("memory")
        if isinstance(memory_raw, dict):
            from qwenpaw.app.chats.utils import parse_legacy_memory_state

            msgs, summary = parse_legacy_memory_state(memory_raw)
            self.state = AgentState()
            self.state.context.extend(msgs)
            self.state.summary = summary
            logger.info(
                "Migrated 1.x session: %d messages + summary(%d chars)",
                len(msgs),
                len(self.state.summary),
            )
            return

        if strict:
            raise KeyError(
                "state_dict has neither 'state' nor 'memory' key",
            )

    async def close(self) -> None:
        """Shut down governor, release the history store, and clean up expired
        tool-result files."""
        gov = getattr(self, "_governor", None)
        if gov is not None:
            try:
                gov.stop()
            except Exception:
                logger.debug("governor stop failed", exc_info=True)

        # Scroll history: apply the retention window (if any) while the
        # connection is still open, then release it (db + -wal + -shm fds —
        # otherwise they accumulate across requests on a long-lived server).
        cm = getattr(self, "_context_manager", None)
        if cm is not None:
            if hasattr(cm, "purge_old"):
                try:
                    lcc = self._agent_config.running.light_context_config
                    cm.purge_old(lcc.scroll_config.history_retention_days)
                except Exception:
                    logger.debug(
                        "history retention purge failed",
                        exc_info=True,
                    )
            if hasattr(cm, "close"):
                try:
                    cm.close()
                except Exception:
                    logger.debug(
                        "context manager close failed",
                        exc_info=True,
                    )

        offloader = getattr(self, "offloader", None)
        if offloader is not None and hasattr(
            offloader,
            "cleanup_expired",
        ):
            try:
                lcc = self._agent_config.running.light_context_config
                trc = lcc.tool_result_pruning_config
                offloader.cleanup_expired(
                    retention_days=trc.offload_retention_days,
                )
            except Exception:
                logger.debug("offloader cleanup failed", exc_info=True)

    def _register_skills(
        self,
        toolkit: Toolkit,
        effective_skills: list[str],
    ) -> None:
        """Load and register skills from workspace directory.

        Skills are stored in ``toolkit._qp_skills`` (a dict) for downstream
        consumption (e.g. ``/skill_name`` slash commands in the runner).
        """
        if not hasattr(toolkit, "_qp_skills"):
            toolkit._qp_skills = {}  # pylint: disable=protected-access
        workspace_dir = self._workspace_dir or WORKING_DIR
        working_skills_dir = get_workspace_skills_dir(Path(workspace_dir))

        for skill_name in effective_skills:
            skill_dir = working_skills_dir / skill_name
            if skill_dir.exists():
                try:
                    # pylint: disable=protected-access
                    toolkit._qp_skills[skill_name] = {
                        "dir": str(skill_dir),
                    }
                    logger.debug("Registered skill: %s", skill_name)
                except Exception as e:
                    logger.error(
                        "Failed to register skill '%s': %s",
                        skill_name,
                        e,
                    )

    # ------------------------------------------------------------------
    # Media-block fallback: strip unsupported media blocks (image, audio,
    # video, file) from memory and retry when the model rejects them.
    # Unlike ``model_factory._fixup_media_list`` (which converts file
    # blocks to text placeholders so the user-facing message history
    # stays readable), this fallback strips them entirely — its purpose
    # is to make a previously-rejected request retryable, so leaving
    # residue would defeat the point.
    # ------------------------------------------------------------------

    _MEDIA_BLOCK_TYPES = {"image", "audio", "video", "file"}
    _MEDIA_MIME_PREFIXES = ("image/", "audio/", "video/")

    _AUTO_CONTINUE_MAX_EXTRA = 2
    _AUTO_CONTINUE_TAIL_CHARS = 600

    _AUTO_CONTINUE_HINT_EN = (
        "<system-hint>"
        "Your previous assistant turn had text only (no tool calls). "
        "Use the trailing excerpt in <previous-assistant-tail> (if present) "
        "plus the conversation to decide in this **reasoning** step: if the "
        "user's task still needs tools, emit tool_use now; if it is fully "
        "done, reply with a short text only (no tools). "
        "Do not stop with plans or code fences alone when tools are still "
        "needed."
        "</system-hint>"
    )
    _AUTO_CONTINUE_HINT_ZH = (
        "<system-hint>"
        "上轮助手仅文字、未调工具。请结合上下文与 <previous-assistant-tail> "
        "（若有）在本轮推理中判断：仍需执行则立刻 tool；已完结则简短收尾。"
        "需要操作时勿只输出计划或代码块。"
        "</system-hint>"
    )

    def _auto_continue_system_hint(self) -> str:
        """Pick hint by agent language (zh vs others)."""
        raw_lang = getattr(self._agent_config, "language", None)
        lang = (raw_lang or "").strip().lower()
        if lang == "zh":
            return self._AUTO_CONTINUE_HINT_ZH
        return self._AUTO_CONTINUE_HINT_EN

    @staticmethod
    def _auto_continue_tail_context(msg: Msg, max_chars: int) -> str:
        """Assistant text suffix for hint (fixed cut, not sentence NLP)."""
        raw = msg.get_text_content() if msg is not None else ""
        text = (raw or "").strip()
        if not text:
            return ""
        if len(text) <= max_chars:
            return text
        return text[-max_chars:].lstrip()

    # _auto_continue_if_text_only — replaced by inline logic in _reasoning()
    # which leverages the 2.0 outer react loop instead of a manual while-loop.

    def _get_model_key(self) -> str | None:
        """Return the capability-cache key for the active model."""
        model = getattr(self, "model", None)
        return getattr(model, "model_key", None)

    def _model_rejects_media(self) -> bool:
        """Check the capability cache for a learned ``rejects_media`` flag."""
        key = self._get_model_key()
        if key is None:
            return False
        return get_capability_cache().get(key, "rejects_media", False)

    def _proactive_strip_media_blocks(self) -> int:
        """Proactively strip media blocks from memory before model call.

        Only called when the active model does not support multimodal.
        Returns the number of blocks stripped.
        """
        return self._strip_media_blocks_from_memory()

    def _uses_request_time_media_normalization(self) -> bool:
        """Return True when request-time normalization can handle media."""
        return getattr(self, "formatter", None) is not None

    def _set_formatter_media_strip(self, enabled: bool) -> None:
        """Toggle request-time media stripping on the active formatter."""
        formatter = getattr(self, "formatter", None)
        if formatter is None:
            return
        setattr(formatter, "_qwenpaw_force_strip_media", enabled)

    # pylint: disable=too-many-branches,too-many-statements
    async def _reasoning(
        self,
        tool_choice: Literal["auto", "none", "required"] | None = None,
    ):
        """Forward 2.0 ``_reasoning`` events with proactive media
        stripping, passive bad-request retry, and auto-continue on
        text-only responses."""

        # ── Fast-fail: break tool-call storms before model call ──
        self._maybe_inject_convergence_hint()

        # ── Proactive media stripping ──
        from .model_factory import _supports_multimodal_for_current_model

        should_strip = (
            not _supports_multimodal_for_current_model()
            or self._model_rejects_media()
        )
        if should_strip:
            if self._uses_request_time_media_normalization():
                self._set_formatter_media_strip(True)
            else:
                n = self._proactive_strip_media_blocks()
                if n > 0:
                    logger.warning(
                        "Proactively stripped %d media block(s) before "
                        "_reasoning (model lacks multimodal support).",
                        n,
                    )

        # ── Model call with passive retry on media error ──
        final_msg: Msg | None = None
        try:
            async for evt in super()._reasoning(tool_choice=tool_choice):
                if isinstance(evt, Msg):
                    final_msg = evt
                else:
                    yield evt
        except Exception as e:
            if not self._is_bad_request_or_media_error(e):
                raise

            model_key = self._get_model_key()
            if model_key:
                get_capability_cache().learn(
                    model_key,
                    "rejects_media",
                    True,
                )
            logger.warning(
                "_reasoning failed with media error (%s); "
                "stripping media and retrying.",
                e,
            )
            if self._uses_request_time_media_normalization():
                self._set_formatter_media_strip(True)
            else:
                self._strip_media_blocks_from_memory()

            try:
                async for evt in super()._reasoning(
                    tool_choice=tool_choice,
                ):
                    if isinstance(evt, Msg):
                        final_msg = evt
                    else:
                        yield evt
            finally:
                if self._uses_request_time_media_normalization():
                    self._set_formatter_media_strip(False)
        else:
            if should_strip and self._uses_request_time_media_normalization():
                self._set_formatter_media_strip(False)

        if final_msg is None:
            return

        # ── Auto-continue: text-only → inject hint, let outer loop retry ──
        if self._should_auto_continue(final_msg, tool_choice):
            hint_body = self._auto_continue_system_hint()
            tail = self._auto_continue_tail_context(
                final_msg,
                self._AUTO_CONTINUE_TAIL_CHARS,
            )
            if tail:
                hint_body += (
                    "\n\n<previous-assistant-tail>\n"
                    f"{tail}\n"
                    "</previous-assistant-tail>"
                )
            logger.info(
                "Auto-continue: text-only response; injecting hint "
                "(tool_choice=%r)",
                tool_choice,
            )
            self.state.context.append(
                Msg(
                    name="user",
                    role="user",
                    content=[TextBlock(type="text", text=hint_body)],
                    metadata={
                        QWENPAW_MESSAGE_TAG_KEY: AUTO_CONTINUE_MESSAGE_TAG,
                    },
                ),
            )
            return  # outer loop continues → _check_next_action → reasoning

        yield final_msg

    def _should_auto_continue(
        self,
        msg: Msg,
        tool_choice: Literal["auto", "none", "required"] | None,
    ) -> bool:
        """Check if auto-continue should be triggered."""
        running = getattr(self, "_agent_config", None)
        running = getattr(running, "running", None)
        if running is None or not getattr(
            running,
            "auto_continue_on_text_only",
            False,
        ):
            return False

        if msg is None or msg.has_content_blocks("tool_call"):
            return False

        if tool_choice == "none":
            return False

        if self.state.cur_iter >= self.react_config.max_iters - 1:
            return False

        return True

    # ------------------------------------------------------------------
    # Fast-fail: detect tool-call storms (repeated identical calls or a
    # run of empty/error tool results) and nudge the model to converge
    # instead of flailing until max_iters / timeout. Safe to run on every
    # agent: it only fires on pathological loops, so legitimate deep
    # reasoning (coding, multi-step ops) is untouched.
    # ------------------------------------------------------------------

    # Same (tool, args) seen this many times within the scan window → storm.
    _FASTFAIL_DUP_THRESHOLD = 3
    # This many trailing empty/error results in a row → data unavailable.
    _FASTFAIL_EMPTY_STREAK = 4
    # How many recent tool calls/results to look back over.
    _FASTFAIL_SCAN_WINDOW = 12
    # Iterations to wait before re-injecting after a trigger (anti-spam).
    _FASTFAIL_COOLDOWN = 1
    # Max chars of a prior tool result to echo back in the reuse hint.
    _FASTFAIL_RESULT_SNIPPET_CHARS = 1500

    # Substrings that mark an "empty / not-found" tool result. Matched
    # case-insensitively against the result's flattened text.
    _FASTFAIL_EMPTY_MARKERS = (
        "暂无数据",
        "接口返回空",
        "返回空",
        "结果为空",
        "未查询到",
        "未找到",
        "查无",
        "无数据",
        "查询为空",
        "共返回 0 条",
        "no result",
        "not found",
        "no data",
        "no rows",
        "empty result",
        '"data":null',
        '"data": null',
        '"count":0',
        '"count": 0',
        '"total":0',
        '"total": 0',
    )

    # Soft-cache hint: the same (tool, args) was called repeatedly AND a
    # usable prior result exists — echo it back so the model reuses it
    # instead of re-running. Safe for shell / mutating tools: the call is
    # never silently suppressed, we only remind the model it already has
    # the answer.
    _FASTFAIL_DUP_REUSE_ZH = (
        "<system-hint>"
        "你已 {count} 次用完全相同的参数调用工具 `{tool}`。它上一次的返回"
        "如下，**请直接复用这个结果、不要再用相同参数重复调用**；若该结果"
        "不满足需求，请换用不同的方法/参数，或据此直接给出结论：\n"
        "<上次调用结果>\n{result}\n</上次调用结果>"
        "</system-hint>"
    )
    _FASTFAIL_DUP_REUSE_EN = (
        "<system-hint>"
        "You have called tool `{tool}` {count} times with identical "
        "arguments. Its previous result is below — **reuse this result and "
        "do not call it again with the same arguments**; if it does not "
        "meet the need, try a different method/arguments, or answer "
        "directly from it:\n"
        "<previous-tool-result>\n{result}\n</previous-tool-result>"
        "</system-hint>"
    )

    # No usable data (empty/error streak, or repeated calls that all came
    # back empty) — nothing to reuse, so stop and report unavailability.
    _FASTFAIL_EMPTY_HINT_ZH = (
        "<system-hint>"
        "检测到你{reason}。请**立即停止重试**：基于已经掌握的信息直接给出"
        "结论；若数据确实查不到，明确告知用户「未查询到该数据 / 数据源暂不"
        "可用」并简述你已尝试的途径与可能原因，**不要再调用工具**。"
        "</system-hint>"
    )
    _FASTFAIL_EMPTY_HINT_EN = (
        "<system-hint>"
        "Detected that you {reason}. **Stop retrying now**: answer directly "
        "from what you already have; if the data is genuinely unavailable, "
        "tell the user plainly that it could not be found / the data source "
        "is unavailable, briefly note what you tried, and **do not call any "
        "more tools**."
        "</system-hint>"
    )

    @staticmethod
    def _block_field(block: Any, key: str, default: Any = None) -> Any:
        """Read *key* from a content block in dict or pydantic form."""
        if isinstance(block, dict):
            return block.get(key, default)
        return getattr(block, key, default)

    def _block_type(self, block: Any) -> Any:
        return self._block_field(block, "type")

    def _result_text(self, output: Any) -> str:
        """Flatten a ToolResultBlock ``output`` into searchable text."""
        if output is None:
            return ""
        if isinstance(output, str):
            return output
        if isinstance(output, list):
            parts: list[str] = []
            for item in output:
                btype = self._block_type(item)
                if btype == "text":
                    parts.append(str(self._block_field(item, "text", "") or ""))
                elif btype in (None, "data"):
                    parts.append(str(self._block_field(item, "data", "") or ""))
            return "\n".join(p for p in parts if p)
        return str(output)

    def _result_snippet(self, text: str) -> str:
        """Truncate a prior tool result for echoing back in the reuse hint."""
        text = (text or "").strip()
        limit = self._FASTFAIL_RESULT_SNIPPET_CHARS
        if len(text) <= limit:
            return text
        suffix = (
            "\n…（结果过长已截断）"
            if (self._language or "").strip().lower() == "zh"
            else "\n…(result truncated)"
        )
        return text[:limit].rstrip() + suffix

    def _is_empty_or_error_result(self, block: Any) -> bool:
        """Heuristic: did this tool result carry no usable data?"""
        state = self._block_field(block, "state")
        state_str = str(state).upper() if state is not None else ""
        if any(s in state_str for s in ("ERROR", "DENIED", "INTERRUPTED")):
            return True

        text = self._result_text(self._block_field(block, "output")).strip()
        if not text:
            return True

        low = text.lower()
        for marker in self._FASTFAIL_EMPTY_MARKERS:
            if marker.lower() in low:
                return True

        # Best-effort: a well-formed JSON envelope with a failure code or
        # an empty ``data`` payload counts as empty.
        import json

        try:
            payload = json.loads(text)
        except Exception:
            payload = None
        if isinstance(payload, dict):
            code = payload.get("code")
            if code is not None and str(code) not in ("200", "0", "True"):
                return True
            if "data" in payload and payload.get("data") in (None, [], {}, ""):
                return True
        return False

    @staticmethod
    def _normalize_tool_input(raw: Any) -> str:
        """Canonicalize tool-call args so trivially-different reorderings of
        the same call compare equal."""
        if raw is None:
            return ""
        if isinstance(raw, str):
            text = raw.strip()
            import json

            try:
                parsed = json.loads(text)
            except Exception:
                return text
        else:
            parsed = raw
        try:
            import json

            return json.dumps(parsed, sort_keys=True, ensure_ascii=False)
        except Exception:
            return str(parsed)

    def _detect_non_convergence(self) -> str | None:
        """Scan the recent context tail; return a convergence hint (or None).

        Triggers when, within the last ``_FASTFAIL_SCAN_WINDOW`` tool calls,
        either the same ``(name, args)`` repeats ``_FASTFAIL_DUP_THRESHOLD``+
        times, or the last ``_FASTFAIL_EMPTY_STREAK``+ tool results in a row
        were empty/error. For the duplicate case, if a usable prior result
        exists it is echoed back so the model reuses it (soft cache).
        """
        context = getattr(self.state, "context", None)
        if not context:
            return None

        calls: list[tuple[str, str, str]] = []  # (id, name, args)
        result_by_id: dict[str, tuple[bool, str]] = {}  # id -> (empty, text)
        results_seq: list[bool] = []  # empties in chronological order
        for msg in context:
            content = getattr(msg, "content", None)
            if not isinstance(content, list):
                continue
            for block in content:
                btype = self._block_type(block)
                if btype == "tool_call":
                    cid = str(self._block_field(block, "id", "") or "")
                    name = str(self._block_field(block, "name", "") or "")
                    args = self._normalize_tool_input(
                        self._block_field(block, "input"),
                    )
                    calls.append((cid, name, args))
                elif btype == "tool_result":
                    rid = str(self._block_field(block, "id", "") or "")
                    is_empty = self._is_empty_or_error_result(block)
                    text = self._result_text(
                        self._block_field(block, "output"),
                    )
                    if rid:
                        result_by_id[rid] = (is_empty, text)
                    results_seq.append(is_empty)

        if not calls:
            return None

        is_zh = (self._language or "").strip().lower() == "zh"
        recent = calls[-self._FASTFAIL_SCAN_WINDOW:]

        # --- Duplicate-call storm within the recent window. ---
        from collections import Counter

        key_counts = Counter((name, args) for _cid, name, args in recent)
        dup_key, dup_count = key_counts.most_common(1)[0]
        if dup_count >= self._FASTFAIL_DUP_THRESHOLD:
            dup_name = dup_key[0]
            # Most recent non-empty result for this duplicated call, if any.
            prior_text = ""
            for cid, name, args in recent:
                if (name, args) != dup_key:
                    continue
                info = result_by_id.get(cid)
                if info is None:
                    continue
                is_empty, text = info
                if not is_empty and text.strip():
                    prior_text = text
            if prior_text.strip():
                tmpl = (
                    self._FASTFAIL_DUP_REUSE_ZH
                    if is_zh
                    else self._FASTFAIL_DUP_REUSE_EN
                )
                return tmpl.format(
                    tool=dup_name,
                    count=dup_count,
                    result=self._result_snippet(prior_text),
                )
            # Repeated but every result was empty/error → unavailable.
            reason = (
                f"已 {dup_count} 次用相同参数调用工具 `{dup_name}`，"
                "且每次都没拿到有效数据"
                if is_zh
                else (
                    f"have called `{dup_name}` {dup_count} times with the "
                    "same arguments and never got usable data"
                )
            )
            tmpl = (
                self._FASTFAIL_EMPTY_HINT_ZH
                if is_zh
                else self._FASTFAIL_EMPTY_HINT_EN
            )
            return tmpl.format(reason=reason)

        # --- Trailing run of empty/error results. ---
        empty_streak = 0
        for is_empty in reversed(results_seq[-self._FASTFAIL_SCAN_WINDOW:]):
            if is_empty:
                empty_streak += 1
            else:
                break
        if empty_streak >= self._FASTFAIL_EMPTY_STREAK:
            reason = (
                f"已连续 {empty_streak} 次得到空 / 错误的工具结果"
                if is_zh
                else (
                    f"have gotten {empty_streak} empty/error tool results "
                    "in a row"
                )
            )
            tmpl = (
                self._FASTFAIL_EMPTY_HINT_ZH
                if is_zh
                else self._FASTFAIL_EMPTY_HINT_EN
            )
            return tmpl.format(reason=reason)

        return None

    def _maybe_inject_convergence_hint(self) -> None:
        """Inject a fast-fail convergence hint if a tool-call storm is
        detected (with a short cooldown to avoid spamming)."""
        try:
            guidance = self._detect_non_convergence()
        except Exception:
            logger.debug("fast-fail detection failed", exc_info=True)
            return
        if not guidance:
            return

        cur_iter = getattr(self.state, "cur_iter", 0)
        last_iter = getattr(self, "_fastfail_last_trigger_iter", -10)
        if cur_iter <= last_iter + self._FASTFAIL_COOLDOWN:
            return
        self._fastfail_last_trigger_iter = cur_iter

        self.state.context.append(
            Msg(
                name="user",
                role="user",
                content=[TextBlock(type="text", text=guidance)],
                metadata={
                    QWENPAW_MESSAGE_TAG_KEY: FASTFAIL_CONVERGE_MESSAGE_TAG,
                },
            ),
        )
        logger.info(
            "Fast-fail: injected convergence hint at iter=%s", cur_iter,
        )

    @staticmethod
    def _is_content_safety_error(exc: Exception) -> bool:
        """Return True for provider-side content safety rejections."""
        error_str = str(exc).lower()
        safety_markers = (
            "new_sensitive",
            "image is sensitive",
            "content policy",
            "content_policy",
            "moderation",
            "content_safety",
            "safety_filter",
            "(1026)",
        )
        return any(marker in error_str for marker in safety_markers)

    @staticmethod
    def _is_bad_request_or_media_error(exc: Exception) -> bool:
        """Return True only for errors that genuinely look media-related.

        A bare 400 is no longer sufficient — provider gateways return
        400 for many unrelated reasons (request too large, malformed
        block fields, exceeded context length) and treating them all as
        "media rejected" poisons the capability cache, causing
        subsequent requests to silently drop user-uploaded images.
        """
        error_str = str(exc).lower()

        # Veto: content safety/moderation rejections are about a
        # particular input, not about whether the model supports media.
        if QwenPawAgent._is_content_safety_error(exc):
            return False

        # Veto: errors clearly about request size / context length are
        # never about media support — stripping media may incidentally
        # make the next request fit, but it's a coincidence, not a
        # learned capability.
        size_signals = (
            "too large",
            "toolarge",
            "max bytes",
            "request body",
            "context length",
            "context_length",
            "maximum context",
            "max_tokens",
        )
        if any(sig in error_str for sig in size_signals):
            return False

        # Match only when the error message itself names a media modality.
        media_keywords = (
            "image",
            "audio",
            "video",
            "vision",
            "multimodal",
            "image_url",
        )
        return any(kw in error_str for kw in media_keywords)

    def _is_media_block(self, block: Any) -> bool:
        """Return True if *block* carries image/audio/video data."""
        if isinstance(block, dict):
            return block.get("type") in self._MEDIA_BLOCK_TYPES
        btype = getattr(block, "type", None)
        if btype in self._MEDIA_BLOCK_TYPES:
            return True
        if btype == "data":
            source = getattr(block, "source", None)
            mt = getattr(source, "media_type", "") or ""
            return mt.startswith(self._MEDIA_MIME_PREFIXES)
        return False

    # ------------------------------------------------------------------
    # Tool call enhancement: hint injection + hook registration
    # ------------------------------------------------------------------

    def _get_tool_coordinator(self) -> Any:
        """Return the ToolCoordinator from request_context, or None."""
        return (self._request_context or {}).get("tool_coordinator")

    async def _inject_pending_hints(self) -> None:
        """Pop background-tool hints and append them to agent context."""
        mgr = self._get_tool_coordinator()
        if mgr is None:
            return
        session_id = (self._request_context or {}).get("session_id", "")
        if not session_id:
            return
        hints = await mgr.pop_pending_hints(session_id)
        for hint in hints:
            self.state.context.append(hint)

    async def _reply(self, **kwargs: Any) -> Any:
        """Override to inject pending background-tool hints before reply."""
        await self._inject_pending_hints()
        async for evt in super()._reply(**kwargs):
            yield evt

    def _register_tool_call_hooks(self) -> None:
        """Register per-tool default timeouts on the ToolCoordinator."""
        mgr = self._get_tool_coordinator()
        if mgr is None:
            return

        mgr.hooks.register(
            "execute_shell_command",
            default_timeout_secs=60.0,
        )
        mgr.hooks.register("chat_with_agent", default_timeout_secs=300.0)
        mgr.hooks.register("check_agent_task", default_timeout_secs=30.0)
        mgr.hooks.register("grep_search", default_timeout_secs=30.0)
        mgr.hooks.register("glob_search", default_timeout_secs=15.0)
        mgr.hooks.register("ast_search", default_timeout_secs=35.0)
        mgr.hooks.register(
            "desktop_screenshot",
            default_timeout_secs=30.0,
        )
        for name in (
            "lsp_definition",
            "lsp_references",
            "lsp_rename",
            "lsp_hover",
            "lsp_diagnostics",
        ):
            mgr.hooks.register(name, default_timeout_secs=20.0)
        mgr.hooks.register(
            "browser_use",
            max_internal_timeout_secs=3600.0,
        )

        agent_id = (self._request_context or {}).get(
            "agent_id",
            self.name,
        )
        mgr.clear_agent_tool_timeouts(agent_id)
        builtin_tools = (
            getattr(
                getattr(self._agent_config, "tools", None),
                "builtin_tools",
                None,
            )
            or {}
        )
        for tool_name, cfg in builtin_tools.items():
            t = getattr(cfg, "timeout_seconds", None)
            if t is not None and t > 0:
                mgr.set_agent_tool_timeout(
                    agent_id,
                    tool_name,
                    float(t),
                )

    # pylint: disable=too-many-nested-blocks
    def _strip_media_blocks_from_memory(self) -> int:
        """Remove media blocks (image/audio/video/DataBlock) from all messages.

        Also strips media blocks nested inside ToolResultBlock outputs.
        Inserts placeholder text when stripping leaves content empty to
        avoid malformed API requests.

        Returns:
            Total number of media blocks removed.
        """
        total_stripped = 0

        for msg in self.state.context:
            if not isinstance(msg.content, list):
                continue

            new_content = []
            stripped_this_message = 0
            for block in msg.content:
                if self._is_media_block(block):
                    total_stripped += 1
                    stripped_this_message += 1
                    continue

                btype = (
                    block.get("type")
                    if isinstance(block, dict)
                    else getattr(block, "type", None)
                )
                if btype == "tool_result":
                    output = (
                        block.get("output")
                        if isinstance(block, dict)
                        else getattr(block, "output", None)
                    )
                    if isinstance(output, list):
                        filtered = [
                            item
                            for item in output
                            if not self._is_media_block(item)
                        ]
                        stripped_count = len(output) - len(filtered)
                        total_stripped += stripped_count
                        stripped_this_message += stripped_count
                        if stripped_count > 0:
                            if isinstance(block, dict):
                                block["output"] = (
                                    filtered or MEDIA_UNSUPPORTED_PLACEHOLDER
                                )
                            else:
                                block.output = (
                                    filtered or MEDIA_UNSUPPORTED_PLACEHOLDER
                                )

                new_content.append(block)

            if not new_content and stripped_this_message > 0:
                new_content.append(
                    TextBlock(type="text", text=MEDIA_UNSUPPORTED_PLACEHOLDER),
                )

            msg.content = new_content

        return total_stripped
