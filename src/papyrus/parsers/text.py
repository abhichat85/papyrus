"""Plain text, Markdown and source code."""

from __future__ import annotations

import re

from papyrus.config import ConvertOptions
from papyrus.detect import CODE_LANGS, Detection
from papyrus.ir import Block, Document, ListItem, code, heading, list_block, paragraph, raw
from papyrus.parsers.base import BaseParser
from papyrus.utils.text import clean, decode, looks_like_heading

_BULLET = re.compile(r"^\s*[-*•·‣▪◦]\s+(.*)$")
_ORDERED = re.compile(r"^\s*(\d+)[.)]\s+(.*)$")
_SETEXT = re.compile(r"^\s*(=|-){3,}\s*$")


def text_to_blocks(text: str, *, detect_headings: bool = True) -> list[Block]:
    """Turn a wall of plain text into structured blocks.

    Shared by the text parser, the PDF fallback path and OCR output, so
    unstructured sources all get the same treatment.
    """
    blocks: list[Block] = []
    paragraphs = re.split(r"\n\s*\n", text)

    for chunk in paragraphs:
        lines = [line.rstrip() for line in chunk.split("\n") if line.strip()]
        if not lines:
            continue

        # A run of bullets becomes one list block.
        if all(_BULLET.match(line) for line in lines):
            items = [ListItem(_BULLET.match(line).group(1).strip()) for line in lines]
            blocks.append(list_block(items, ordered=False))
            continue
        if all(_ORDERED.match(line) for line in lines):
            items = [ListItem(_ORDERED.match(line).group(2).strip()) for line in lines]
            blocks.append(list_block(items, ordered=True))
            continue

        # Setext-style underlined title.
        if len(lines) == 2 and _SETEXT.match(lines[1]):
            level = 1 if lines[1].strip().startswith("=") else 2
            blocks.append(heading(lines[0], level))
            continue

        if detect_headings and len(lines) == 1 and looks_like_heading(lines[0]):
            blocks.append(heading(lines[0], 2))
            continue

        blocks.append(paragraph(" ".join(lines)))

    return blocks


class TextParser(BaseParser):
    """Catch-all: plain text, logs, subtitles, unknown text-ish files."""

    formats = ("text", "binary", "unknown")
    label = "Plain text"
    priority = 900

    def supports(self, detection: Detection) -> bool:
        # The registry places this last, so it accepts whatever is left.
        return True

    def parse(self, data: bytes, filename: str, detection: Detection, options: ConvertOptions) -> Document:
        doc = self.new_document(data, filename, detection)

        if detection.format == "binary":
            doc.warn("Binary file with no matching parser — only printable text was recovered.")
            text = clean(_printable_strings(data))
        else:
            text = clean(decode(data))

        if not text:
            doc.warn("File contained no extractable text.")
            return doc

        doc.extend(text_to_blocks(text, detect_headings=options.detect_headings))
        _lift_title(doc)
        return doc


class MarkdownParser(BaseParser):
    """Markdown in, Markdown out — passed through verbatim.

    Re-parsing Markdown into the IR and re-rendering it would silently drop
    anything the IR does not model (footnotes, HTML, MDX components). For a
    format that is already the target, verbatim is the correct answer.
    """

    formats = ("markdown",)
    label = "Markdown"
    priority = 20

    def parse(self, data: bytes, filename: str, detection: Detection, options: ConvertOptions) -> Document:
        doc = self.new_document(data, filename, detection)
        text = decode(data).replace("\r\n", "\n").strip()

        body, front = _split_frontmatter(text)
        if front:
            doc.metadata["source_frontmatter"] = front

        # The title is recorded as metadata only. `passthrough` tells the
        # renderer not to re-emit it as a heading — the body already has
        # whatever headings the author wrote.
        if isinstance(front.get("title"), str):
            doc.title = front["title"]
        else:
            heading_match = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
            if heading_match:
                doc.title = heading_match.group(1).strip()

        doc.metadata["passthrough"] = True
        if body:
            doc.add(raw(body))
        else:
            doc.warn("Markdown file was empty.")
        return doc


class CodeParser(BaseParser):
    """Source and config files become a single fenced block with a language."""

    formats = ("code",)
    label = "Source code"
    priority = 30

    def parse(self, data: bytes, filename: str, detection: Detection, options: ConvertOptions) -> Document:
        doc = self.new_document(data, filename, detection)
        text = decode(data).replace("\r\n", "\n")
        lang = detection.lang or CODE_LANGS.get(detection.extension, "")

        doc.metadata["language"] = lang or "text"
        doc.metadata["lines"] = text.count("\n") + 1 if text else 0
        doc.title = filename.rsplit("/", 1)[-1]

        if text.strip():
            doc.add(code(text, lang))
        else:
            doc.warn("Source file was empty.")
        return doc


# ── helpers ──────────────────────────────────────────────────────────


def _split_frontmatter(text: str) -> tuple[str, dict]:
    if not text.startswith("---\n"):
        return text, {}
    end = text.find("\n---", 4)
    if end == -1:
        return text, {}
    block, body = text[4:end], text[end + 4 :].lstrip("\n")
    try:
        import yaml

        parsed = yaml.safe_load(block)
        return body, parsed if isinstance(parsed, dict) else {}
    except Exception:
        return body, {}


def _lift_title(doc: Document) -> None:
    """If the document opens with a heading, that is the real title."""
    if doc.blocks and doc.blocks[0].type == "heading":
        doc.title = str(doc.blocks[0].content)
        doc.blocks.pop(0)


def _printable_strings(data: bytes, min_run: int = 6) -> str:
    """Recover readable runs from a binary blob (the `strings(1)` trick)."""
    out: list[str] = []
    current: list[str] = []
    for byte in data[:2_000_000]:
        if 32 <= byte < 127 or byte in (9, 10, 13):
            current.append(chr(byte))
        else:
            if len(current) >= min_run:
                out.append("".join(current))
            current = []
    if len(current) >= min_run:
        out.append("".join(current))
    return "\n".join(out)
