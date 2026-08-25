"""Heading-aware chunking.

The reason Papyrus exists is that a converted document is an input to a
model, not an output for a human. So the last mile is chunking — and a
chunker that splits on character count alone destroys the structure the
parsers just worked to recover.

This one walks the IR, not the rendered string:

* it never splits a table row or a code fence away from its fence;
* every chunk carries the heading path it sits under ("Report › Q3 ›
  Revenue"), so a retrieved fragment still says where it came from;
* every chunk carries its source page, so an agent can cite "page 14".

Output is JSON Lines — one chunk per line, ready for an embedding job.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from papyrus.config import ConvertOptions
from papyrus.ir import Block, Document
from papyrus.renderers.markdown import MarkdownRenderer
from papyrus.utils.text import slugify


@dataclass
class Chunk:
    id: str
    index: int
    text: str
    heading_path: list[str] = field(default_factory=list)
    pages: list[int] = field(default_factory=list)
    char_count: int = 0
    token_estimate: int = 0
    source: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _Unit:
    """One rendered block plus the context in force where it sits."""

    text: str
    path: list[str]
    page: int | None
    is_heading: bool
    kind: str  # "prose" | "table" | "code"


def chunk_document(doc: Document, options: ConvertOptions | None = None) -> list[Chunk]:
    options = options or ConvertOptions()
    renderer = MarkdownRenderer(options.with_(frontmatter=False))
    target = max(200, options.chunk_size)
    overlap = max(0, min(options.chunk_overlap, target // 2))

    groups = _group(_units(doc, renderer), target)
    return _materialize(groups, doc, overlap)


def _group(units: list[_Unit], target: int) -> list[list[_Unit]]:
    """Pack units into groups of roughly `target` characters.

    Groups break at headings where possible, and a single unit larger than
    the target is split into groups of its own — never merged with
    neighbours, so a table fragment can keep its header row and a code
    fragment can keep its fence.
    """
    groups: list[list[_Unit]] = []
    current: list[_Unit] = []
    size = 0

    def close() -> None:
        nonlocal current, size
        if current:
            groups.append(current)
            current, size = [], 0

    for unit in units:
        if len(unit.text) > target * 1.5:
            close()
            for piece in _split_oversized(unit.text, target, unit.kind):
                groups.append([_Unit(piece, unit.path, unit.page, False, unit.kind)])
            continue
        # A heading should open a chunk, not close one.
        if (unit.is_heading and size > target * 0.35) or (size and size + len(unit.text) > target):
            close()
        current.append(unit)
        size += len(unit.text) + 2

    close()
    return groups


def _materialize(groups: list[list[_Unit]], doc: Document, overlap: int) -> list[Chunk]:
    chunks: list[Chunk] = []
    stem = slugify(doc.source.filename or "doc", 40)

    for index, group in enumerate(groups):
        text = "\n\n".join(u.text for u in group).strip()
        if not text:
            continue

        # Overlap is prose-only. Prefixing the tail of a table onto the next
        # chunk would produce orphan rows with no header, and half a code
        # fence — the exact structure the parsers just worked to preserve.
        prefix = ""
        if overlap and index and _prose(group) and _prose(groups[index - 1]):
            previous = "\n\n".join(u.text for u in groups[index - 1]).strip()
            prefix = _tail(previous, overlap)

        full = f"{prefix}\n\n{text}" if prefix else text
        # The path is that of the first real unit, never the carried tail.
        path = group[0].path
        pages = sorted({u.page for u in group if u.page is not None})

        chunks.append(
            Chunk(
                id=f"{stem}-{len(chunks):04d}",
                index=len(chunks),
                text=full,
                heading_path=list(path),
                pages=pages,
                char_count=len(full),
                token_estimate=estimate_tokens(full),
                source={
                    "filename": doc.source.filename,
                    "sha256": doc.source.sha256,
                    "format": doc.source.format,
                },
            )
        )
    return chunks


def _prose(group: list[_Unit]) -> bool:
    return all(u.kind == "prose" for u in group)


def _tail(text: str, overlap: int) -> str:
    """The last `overlap` characters, snapped to a word boundary."""
    if len(text) <= overlap:
        return text
    tail = text[-overlap:]
    cut = tail.find(" ")
    return tail[cut + 1 :] if cut != -1 else tail


def _units(doc: Document, renderer: MarkdownRenderer) -> list[_Unit]:
    """Rendered blocks paired with the heading path in force at that point."""
    out: list[_Unit] = []
    path: list[str] = [doc.title] if doc.title else []
    depth_map: dict[int, str] = {0: doc.title} if doc.title else {}
    page: int | None = None

    for block in doc.blocks:
        if block.type == "page_break":
            page = block.metadata.get("page", page)
            continue
        if block.type == "heading":
            level = block.level or 1
            depth_map = {k: v for k, v in depth_map.items() if k < level}
            depth_map[level] = str(block.content)
            path = [depth_map[k] for k in sorted(depth_map)]
        if block.page is not None:
            page = block.page

        text = renderer.block(block)
        if text.strip():
            out.append(_Unit(text, list(path), page, block.type == "heading", _kind(block)))
    return out


def _kind(block: Block) -> str:
    if block.type == "table":
        return "table"
    if block.type == "code":
        return "code"
    return "prose"


def _split_oversized(text: str, target: int, kind: str) -> list[str]:
    """Split a too-large unit without breaking a table or a fence."""
    lines = text.split("\n")

    # A table repeats its header and separator on every piece.
    header: list[str] = []
    if kind == "table" and len(lines) > 2 and lines[0].startswith("|"):
        header = lines[:2]

    # A code block is unwrapped, split, then re-fenced piece by piece.
    fence = ""
    if kind == "code" and lines and lines[0].lstrip().startswith("```"):
        fence = lines[0]
        lines = lines[1:-1] if lines[-1].strip().startswith("```") else lines[1:]

    pieces: list[str] = []
    current: list[str] = list(header)
    for line in lines[len(header) :]:
        if len(current) > len(header) and sum(len(x) + 1 for x in current) + len(line) > target:
            pieces.append("\n".join(current))
            current = list(header)
        current.append(line)
    if len(current) > len(header):
        pieces.append("\n".join(current))

    if fence:
        closing = "`" * (len(fence) - len(fence.lstrip("`")))
        pieces = [f"{fence}\n{p}\n{closing}" for p in pieces]
    return pieces or [text]


def estimate_tokens(text: str) -> int:
    """Rough token count: ~4 characters per token for English prose.

    Deliberately dependency-free — an exact count needs the target model's
    tokeniser, and callers who need exactness should re-count downstream.
    """
    return max(1, len(text) // 4)


def to_jsonl(chunks: list[Chunk]) -> str:
    return "\n".join(json.dumps(c.to_dict(), ensure_ascii=False) for c in chunks) + ("\n" if chunks else "")
