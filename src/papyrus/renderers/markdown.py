"""Document IR → Markdown.

The renderer is the only place in Papyrus that knows what Markdown looks
like. It is deliberately dumb: no inference, no cleanup, no heuristics —
if the output is wrong, the bug is in a parser.

Output targets CommonMark plus GFM tables, which is what every LLM
tokeniser and every RAG pipeline in practice expects.
"""

from __future__ import annotations

import textwrap
from datetime import UTC, datetime
from typing import Any

from papyrus.config import ConvertOptions
from papyrus.ir import Block, Document, ListItem, Table
from papyrus.utils.tables import alignments
from papyrus.utils.text import escape_block_start, escape_cell


class MarkdownRenderer:
    def __init__(self, options: ConvertOptions | None = None) -> None:
        self.options = options or ConvertOptions()

    # ── entry point ──────────────────────────────────────────────
    def render(self, doc: Document) -> str:
        parts: list[str] = []
        if self.options.frontmatter:
            parts.append(self.frontmatter(doc))
        # `passthrough` sources (Markdown in, Markdown out) already carry
        # their own heading structure — adding a title would duplicate it.
        # So does a document whose first heading already says the title,
        # which happens whenever the title was inferred from the filename.
        if doc.title and not doc.metadata.get("passthrough") and not _title_is_repeated(doc):
            parts.append(f"# {_inline_safe(doc.title)}")

        for block in doc.blocks:
            chunk = self.block(block)
            if chunk:
                parts.append(chunk)

        body = "\n\n".join(p for p in parts if p).strip()
        return body + "\n" if body else ""

    # ── frontmatter ──────────────────────────────────────────────
    def frontmatter(self, doc: Document) -> str:
        import yaml

        data: dict[str, Any] = {
            "title": doc.title,
            "source": {
                "filename": doc.source.filename,
                "format": doc.source.format,
                "media_type": doc.source.media_type,
                "bytes": doc.source.size_bytes,
                "sha256": doc.source.sha256,
            },
            "converted_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "converted_by": "papyrus",
            "word_count": doc.word_count,
        }
        extra = {k: v for k, v in doc.metadata.items() if not k.startswith("_") and v not in (None, "", [])}
        if extra:
            data["document"] = extra
        if doc.assets:
            data["assets"] = [a.filename for a in doc.assets]
        if doc.warnings:
            data["warnings"] = doc.warnings

        dumped = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100).strip()
        return f"---\n{dumped}\n---"

    # ── block dispatch ───────────────────────────────────────────
    def block(self, block: Block) -> str:
        handler = getattr(self, f"_{block.type}", None)
        if handler is None:
            return ""
        return handler(block)

    # ── block renderers ──────────────────────────────────────────
    def _heading(self, block: Block) -> str:
        level = max(1, min(6, (block.level or 1) + self.options.heading_offset))
        return f"{'#' * level} {_inline_safe(str(block.content))}"

    def _paragraph(self, block: Block) -> str:
        text = str(block.content).strip()
        if not text:
            return ""
        width = self.options.wrap_width
        if width and len(text) > width:
            text = "\n".join(
                textwrap.wrap(text, width, break_long_words=False, break_on_hyphens=False)
            )
        return escape_block_start(text)

    def _quote(self, block: Block) -> str:
        lines = escape_block_start(str(block.content).strip()).split("\n")
        return "\n".join(f"> {line}" if line else ">" for line in lines)

    def _code(self, block: Block) -> str:
        body = str(block.content)
        lang = block.metadata.get("lang", "")
        fence = "`" * max(3, _longest_backtick_run(body) + 1)
        return f"{fence}{lang}\n{body}\n{fence}"

    def _rule(self, block: Block) -> str:
        return "---"

    def _raw(self, block: Block) -> str:
        return str(block.content).strip()

    def _image(self, block: Block) -> str:
        mode = self.options.images
        if mode == "omit":
            return ""
        alt = str(block.content or "").replace("]", "\\]")
        src = block.metadata.get("src", "")
        if mode == "placeholder":
            return f"`[image: {alt or src}]`"
        return f"![{alt}]({src})"

    def _page_break(self, block: Block) -> str:
        if not self.options.keep_page_breaks:
            return ""
        page = block.metadata.get("page")
        label = block.metadata.get("label")
        if not self.options.page_anchors:
            return "---"
        marker = f"<!-- papyrus:page {page} -->" if page else "<!-- papyrus:page -->"
        return f"{marker}\n\n**{label}**" if label else marker

    def _key_values(self, block: Block) -> str:
        pairs = block.content or {}
        if not isinstance(pairs, dict) or not pairs:
            return ""
        return "\n".join(f"- **{_inline_safe(str(k))}:** {_inline_safe(str(v))}" for k, v in pairs.items())

    def _list(self, block: Block) -> str:
        items = block.content or []
        ordered = bool(block.metadata.get("ordered"))
        return "\n".join(_render_items(items, ordered, 0))

    def _table(self, block: Block) -> str:
        source = block.content
        if not isinstance(source, Table):
            return ""
        source = source.normalized()
        if self.options.table_format == "csv":
            return _table_as_csv(source)
        if self.options.table_format == "html":
            return _table_as_html(source)
        return _table_as_pipe(source, block)


# ── list rendering ───────────────────────────────────────────────────


def _render_items(items: list[ListItem], ordered: bool, depth: int) -> list[str]:
    lines: list[str] = []
    indent = "  " * depth
    for index, item in enumerate(items, 1):
        if not isinstance(item, ListItem):
            item = ListItem(str(item))
        marker = f"{index}." if ordered else "-"
        box = "" if item.checked is None else ("[x] " if item.checked else "[ ] ")
        text = item.text.replace("\n", " ").strip()
        lines.append(f"{indent}{marker} {box}{text}".rstrip())
        if item.children:
            lines.extend(_render_items(item.children, ordered=False, depth=depth + 1))
    return lines


# ── table rendering ──────────────────────────────────────────────────


def _table_as_pipe(source: Table, block: Block) -> str:
    header = source.header or [""] * source.width
    rows = source.rows
    if not header and not rows:
        return ""

    align = alignments(source.header, rows)
    lines = [
        "| " + " | ".join(escape_cell(c) for c in header) + " |",
        "| " + " | ".join(align) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(escape_cell(c) for c in row) + " |")

    out = "\n".join(lines)
    if source.caption:
        out = f"**{source.caption}**\n\n{out}"
    return out


def _table_as_csv(source: Table) -> str:
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    if source.header:
        writer.writerow(source.header)
    writer.writerows(source.rows)
    return f"```csv\n{buffer.getvalue().strip()}\n```"


def _table_as_html(source: Table) -> str:
    parts = ["<table>"]
    if source.header:
        parts.append("<thead><tr>" + "".join(f"<th>{_html(c)}</th>" for c in source.header) + "</tr></thead>")
    parts.append("<tbody>")
    for row in source.rows:
        parts.append("<tr>" + "".join(f"<td>{_html(c)}</td>" for c in row) + "</tr>")
    parts.append("</tbody></table>")
    return "\n".join(parts)


def _html(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── helpers ──────────────────────────────────────────────────────────


def _title_is_repeated(doc: Document) -> bool:
    """True when the document opens with a heading that says the title."""
    for block in doc.blocks:
        if block.type == "page_break":
            continue
        if block.type != "heading":
            return False
        return _inline_safe(str(block.content)).casefold() == _inline_safe(doc.title or "").casefold()
    return False


def _inline_safe(text: str) -> str:
    """Headings and key names must not contain newlines."""
    return " ".join(str(text).split())


def _longest_backtick_run(text: str) -> int:
    longest = current = 0
    for char in text:
        current = current + 1 if char == "`" else 0
        longest = max(longest, current)
    return longest
