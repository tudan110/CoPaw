"""Token-aware recursive text chunker with Markdown-hierarchy awareness.

Two-level output: parent chunks (~1500 tokens, returned to LLM as context)
each containing child chunks (~300 tokens, the retrieval grain).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

try:
    import tiktoken  # type: ignore
    _ENCODER = tiktoken.get_encoding("cl100k_base")
except Exception:  # pragma: no cover
    _ENCODER = None


PARENT_TARGET_TOKENS = 1500
CHILD_TARGET_TOKENS = 300
CHILD_OVERLAP_TOKENS = 50

# Separators in priority order. Earlier ones produce more semantic boundaries.
SEPARATORS: list[str] = [
    "\n\n",
    "\n",
    "。",
    "！",
    "？",
    "；",
    ".",
    "!",
    "?",
    ";",
    "，",
    ",",
    " ",
    "",
]

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass
class ChildPiece:
    chunk_index: int
    content: str
    token_count: int


@dataclass
class ParentPiece:
    chunk_index: int
    section_path: str
    locator: str
    content: str
    token_count: int
    children: list[ChildPiece] = field(default_factory=list)


def count_tokens(text: str) -> int:
    """Token count via tiktoken. Falls back to char count when unavailable."""
    if not text:
        return 0
    if _ENCODER is None:
        return len(text)
    return len(_ENCODER.encode(text, disallowed_special=()))


def _take_tail_tokens(text: str, n_tokens: int) -> str:
    if not text or n_tokens <= 0:
        return ""
    if _ENCODER is None:
        return text[-n_tokens:]
    tokens = _ENCODER.encode(text, disallowed_special=())
    if len(tokens) <= n_tokens:
        return text
    return _ENCODER.decode(tokens[-n_tokens:])


def _split_by_separators(text: str, max_tokens: int, seps: list[str]) -> list[str]:
    """Recursively split until every piece fits within max_tokens, or we run
    out of separators (then fall back to character chopping)."""
    if count_tokens(text) <= max_tokens:
        return [text] if text else []

    if not seps:
        return _char_chop(text, max_tokens)

    sep, rest = seps[0], seps[1:]
    if sep == "":
        return _char_chop(text, max_tokens)
    if sep not in text:
        return _split_by_separators(text, max_tokens, rest)

    parts = text.split(sep)
    out: list[str] = []
    for i, raw in enumerate(parts):
        # Re-attach the separator (except for the final fragment) so the joined
        # output is round-trip-equivalent to the input.
        piece = raw + (sep if i < len(parts) - 1 else "")
        if not piece:
            continue
        if count_tokens(piece) <= max_tokens:
            out.append(piece)
        else:
            out.extend(_split_by_separators(piece, max_tokens, rest))
    return out


def _char_chop(text: str, max_tokens: int) -> list[str]:
    """Last-resort character-level chop when no separator helps."""
    if _ENCODER is None:
        # max_tokens treated as character count when tiktoken is missing
        size = max_tokens
        return [text[i:i + size] for i in range(0, len(text), size)]
    tokens = _ENCODER.encode(text, disallowed_special=())
    out: list[str] = []
    for i in range(0, len(tokens), max_tokens):
        out.append(_ENCODER.decode(tokens[i:i + max_tokens]))
    return out


def _pack_with_overlap(
    pieces: list[str],
    target_tokens: int,
    overlap_tokens: int,
) -> list[str]:
    """Greedy-pack adjacent small pieces into chunks of ~target_tokens, each
    new chunk seeded with the trailing overlap_tokens of the previous one."""
    if not pieces:
        return []

    chunks: list[str] = []
    buf: list[str] = []
    buf_tokens = 0

    for p in pieces:
        p_tokens = count_tokens(p)
        if buf_tokens + p_tokens > target_tokens and buf:
            chunks.append("".join(buf))
            if overlap_tokens > 0:
                tail = _take_tail_tokens(chunks[-1], overlap_tokens)
                buf = [tail] if tail else []
                buf_tokens = count_tokens(tail) if tail else 0
            else:
                buf = []
                buf_tokens = 0
        buf.append(p)
        buf_tokens += p_tokens

    if buf:
        chunks.append("".join(buf))

    return [c for c in chunks if c.strip()]


def recursive_split(
    text: str,
    target_tokens: int,
    *,
    overlap_tokens: int = 0,
) -> list[str]:
    """Public API: split text into chunks of approximately target_tokens, with
    optional sliding-window overlap. Output content sums to slightly more than
    the input due to overlap when overlap_tokens > 0."""
    if not text or not text.strip():
        return []
    pieces = _split_by_separators(text, target_tokens, SEPARATORS)
    return _pack_with_overlap(pieces, target_tokens, overlap_tokens)


@dataclass
class _MarkdownSection:
    section_path: list[str]
    content: str


def _parse_markdown_sections(text: str) -> list[_MarkdownSection]:
    """Walk the document line by line, tracking heading lineage. Each non-heading
    block becomes a section labeled with its enclosing heading stack."""
    sections: list[_MarkdownSection] = []
    heading_stack: list[tuple[int, str]] = []
    body: list[str] = []

    def flush() -> None:
        nonlocal body
        joined = "\n".join(body).strip()
        body = []
        if joined:
            path = [t for _, t in heading_stack]
            sections.append(_MarkdownSection(section_path=path, content=joined))

    for line in text.split("\n"):
        m = _HEADING_RE.match(line)
        if m:
            flush()
            level = len(m.group(1))
            title = m.group(2).strip()
            heading_stack = [(lv, t) for lv, t in heading_stack if lv < level]
            heading_stack.append((level, title))
        else:
            body.append(line)

    flush()

    if not sections:
        sections.append(_MarkdownSection(section_path=[], content=text.strip()))
    return sections


def chunk_document(
    text: str,
    *,
    source_format: str = "plain",
    parent_target: int = PARENT_TARGET_TOKENS,
    child_target: int = CHILD_TARGET_TOKENS,
    child_overlap: int = CHILD_OVERLAP_TOKENS,
    locator_prefix: str = "",
) -> list[ParentPiece]:
    """Chunk a single text body into parent + child pieces.

    For PDFs and other paginated sources, call this function once per page and
    pass `locator_prefix` (e.g. "第 3 页") so each parent inherits page locator.
    """
    if not text or not text.strip():
        return []

    if source_format == "markdown":
        sections = _parse_markdown_sections(text)
    else:
        sections = [_MarkdownSection(section_path=[], content=text.strip())]

    parents: list[ParentPiece] = []
    parent_idx = 0

    for section in sections:
        section_parents = recursive_split(section.content, parent_target)
        for parent_body in section_parents:
            parent_body = parent_body.strip()
            if not parent_body:
                continue

            child_texts = recursive_split(
                parent_body, child_target, overlap_tokens=child_overlap
            )
            children: list[ChildPiece] = []
            for ci, ctext in enumerate(child_texts):
                ctext = ctext.strip()
                if not ctext:
                    continue
                children.append(
                    ChildPiece(
                        chunk_index=ci,
                        content=ctext,
                        token_count=count_tokens(ctext),
                    )
                )

            if not children:
                continue

            section_path_str = " > ".join(section.section_path)
            parents.append(
                ParentPiece(
                    chunk_index=parent_idx,
                    section_path=section_path_str,
                    locator=locator_prefix,
                    content=parent_body,
                    token_count=count_tokens(parent_body),
                    children=children,
                )
            )
            parent_idx += 1

    return parents
