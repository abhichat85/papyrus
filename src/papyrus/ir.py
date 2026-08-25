"""Papyrus Document IR — the single contract every parser writes to.

Parsers NEVER emit Markdown. They emit a `Document`: an ordered list of
typed `Block`s plus provenance metadata. Renderers turn a `Document` into
Markdown, JSON, or chunks. That separation is what lets a new file format
be added without touching a single line of rendering logic.

The IR is intentionally small and JSON-serialisable. If you find yourself
wanting a new block type, first check whether `metadata` on an existing
block would do.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

BlockType = Literal[
    "heading",  # content: str                     level: 1-6
    "paragraph",  # content: str
    "list",  # content: list[ListItem]
    "table",  # content: Table
    "code",  # content: str                     metadata: {"lang": str}
    "quote",  # content: str
    "image",  # content: str (alt text)         metadata: {"src", "asset_id"}
    "rule",  # content: None
    "page_break",  # content: None                    metadata: {"page": int}
    "key_values",  # content: dict[str, str]
    "raw",  # content: str  (verbatim markdown, escape hatch)
]

__all__ = [
    "Asset",
    "Block",
    "BlockType",
    "Document",
    "ListItem",
    "SourceInfo",
    "Table",
    "code",
    "heading",
    "image",
    "key_values",
    "list_block",
    "page_break",
    "paragraph",
    "quote",
    "raw",
    "rule",
    "table",
]


@dataclass
class ListItem:
    """One bullet. `children` gives arbitrary nesting depth."""

    text: str
    children: list[ListItem] = field(default_factory=list)
    checked: bool | None = None  # None = not a task item

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"text": self.text}
        if self.checked is not None:
            out["checked"] = self.checked
        if self.children:
            out["children"] = [c.to_dict() for c in self.children]
        return out


@dataclass
class Table:
    """A rectangular table. `header` may be None for headerless data."""

    rows: list[list[str]]
    header: list[str] | None = None
    caption: str | None = None

    @property
    def width(self) -> int:
        widths = [len(r) for r in self.rows]
        if self.header:
            widths.append(len(self.header))
        return max(widths) if widths else 0

    def normalized(self) -> Table:
        """Pad every row to the table width so rendering can't go ragged."""
        w = self.width
        return Table(
            rows=[list(r) + [""] * (w - len(r)) for r in self.rows],
            header=(list(self.header) + [""] * (w - len(self.header))) if self.header else None,
            caption=self.caption,
        )

    def to_dict(self) -> dict[str, Any]:
        return {"rows": self.rows, "header": self.header, "caption": self.caption}


@dataclass
class Asset:
    """A binary extracted from the source document (usually an image)."""

    asset_id: str
    filename: str
    media_type: str
    data: bytes = b""
    width: int | None = None
    height: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "filename": self.filename,
            "media_type": self.media_type,
            "bytes": len(self.data),
            "width": self.width,
            "height": self.height,
        }


@dataclass
class Block:
    """One structural unit of a document."""

    type: BlockType
    content: Any = None
    level: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def page(self) -> int | None:
        value = self.metadata.get("page")
        return value if isinstance(value, int) else None

    def to_dict(self) -> dict[str, Any]:
        content: Any = self.content
        if self.type == "table" and isinstance(content, Table):
            content = content.to_dict()
        elif self.type == "list" and isinstance(content, list):
            content = [i.to_dict() if isinstance(i, ListItem) else i for i in content]
        out: dict[str, Any] = {"type": self.type, "content": content}
        if self.level is not None:
            out["level"] = self.level
        if self.metadata:
            out["metadata"] = self.metadata
        return out


@dataclass
class SourceInfo:
    """Where this document came from. Travels into the Markdown frontmatter."""

    filename: str
    media_type: str = "application/octet-stream"
    format: str = "unknown"  # papyrus format id, e.g. "pdf", "docx"
    size_bytes: int = 0
    sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Document:
    """A parsed document, ready to render."""

    source: SourceInfo
    blocks: list[Block] = field(default_factory=list)
    title: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    assets: list[Asset] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # ── convenience ──────────────────────────────────────────────
    def add(self, block: Block | None) -> None:
        if block is not None:
            self.blocks.append(block)

    def extend(self, blocks: list[Block]) -> None:
        self.blocks.extend(b for b in blocks if b is not None)

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    @property
    def text(self) -> str:
        """Rough plain-text projection — used for word counts and previews."""
        parts: list[str] = []
        for b in self.blocks:
            if isinstance(b.content, str):
                parts.append(b.content)
            elif b.type == "list" and isinstance(b.content, list):
                parts.extend(_flatten_items(b.content))
            elif b.type == "table" and isinstance(b.content, Table):
                for row in ([b.content.header] if b.content.header else []) + b.content.rows:
                    parts.append(" ".join(str(c) for c in row))
        return "\n".join(parts)

    @property
    def word_count(self) -> int:
        return len(self.text.split())

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "source": self.source.to_dict(),
            "metadata": self.metadata,
            "blocks": [b.to_dict() for b in self.blocks],
            "assets": [a.to_dict() for a in self.assets],
            "warnings": self.warnings,
        }

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


def _flatten_items(items: list[ListItem]) -> list[str]:
    out: list[str] = []
    for item in items:
        out.append(item.text)
        out.extend(_flatten_items(item.children))
    return out


# ── Block constructors ───────────────────────────────────────────────
# Parsers use these instead of building Block(...) by hand, so the
# type/level/metadata invariants live in exactly one place.


def heading(text: str, level: int = 1, **meta: Any) -> Block:
    return Block("heading", text.strip(), level=max(1, min(6, level)), metadata=_clean(meta))


def paragraph(text: str, **meta: Any) -> Block:
    return Block("paragraph", text.strip(), metadata=_clean(meta))


def list_block(items: list[ListItem], ordered: bool = False, **meta: Any) -> Block:
    meta = _clean(meta)
    meta["ordered"] = ordered
    return Block("list", items, metadata=meta)


def table(
    rows: list[list[str]],
    header: list[str] | None = None,
    caption: str | None = None,
    **meta: Any,
) -> Block:
    return Block("table", Table(rows, header, caption), metadata=_clean(meta))


def code(text: str, lang: str = "", **meta: Any) -> Block:
    meta = _clean(meta)
    meta["lang"] = lang
    return Block("code", text.rstrip(), metadata=meta)


def quote(text: str, **meta: Any) -> Block:
    return Block("quote", text.strip(), metadata=_clean(meta))


def image(alt: str, src: str, asset_id: str | None = None, **meta: Any) -> Block:
    meta = _clean(meta)
    meta["src"] = src
    if asset_id:
        meta["asset_id"] = asset_id
    return Block("image", alt, metadata=meta)


def rule(**meta: Any) -> Block:
    return Block("rule", None, metadata=_clean(meta))


def page_break(page: int, label: str | None = None, **meta: Any) -> Block:
    meta = _clean(meta)
    meta["page"] = page
    if label:
        meta["label"] = label
    return Block("page_break", None, metadata=meta)


def key_values(pairs: dict[str, str], **meta: Any) -> Block:
    return Block("key_values", pairs, metadata=_clean(meta))


def raw(markdown: str, **meta: Any) -> Block:
    return Block("raw", markdown, metadata=_clean(meta))


def _clean(meta: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in meta.items() if v is not None}
