"""HTML and XML.

HTML maps onto the IR almost one-to-one, so this is a genuine DOM walk
rather than a text scrape: headings keep their level, lists keep their
nesting, tables keep their header row, and links survive as Markdown
inline links.
"""

from __future__ import annotations

import re
from typing import Any

from papyrus.config import ConvertOptions
from papyrus.detect import Detection
from papyrus.ir import (
    Block,
    Document,
    ListItem,
    code,
    heading,
    image,
    list_block,
    paragraph,
    quote,
    rule,
    table,
)
from papyrus.parsers.base import BaseParser
from papyrus.utils.tables import split_header, trim
from papyrus.utils.text import clean, decode

# Stripped before walking: chrome that is never document content.
_DROP = {
    "script",
    "style",
    "noscript",
    "template",
    "svg",
    "canvas",
    "iframe",
    "nav",
    "header",
    "footer",
    "aside",
    "form",
    "button",
    "select",
}
# Preferred content roots, most specific first.
_MAIN = ["main", "article", '[role="main"]', "#content", "#main", ".content", ".post-body"]

_INLINE_MARKS = {"strong": "**", "b": "**", "em": "_", "i": "_", "code": "`", "del": "~~", "s": "~~"}


class HTMLParser(BaseParser):
    formats = ("html",)
    label = "HTML"
    priority = 30

    def parse(self, data: bytes, filename: str, detection: Detection, options: ConvertOptions) -> Document:
        from bs4 import BeautifulSoup

        doc = self.new_document(data, filename, detection)
        soup = BeautifulSoup(decode(data), "lxml")

        if soup.title and soup.title.string:
            doc.title = clean(str(soup.title.string))
        doc.metadata.update(_meta_tags(soup))

        from bs4 import Comment

        for tag in soup.find_all(list(_DROP)):
            tag.decompose()
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()

        root = None
        for selector in _MAIN:
            found = soup.select_one(selector)
            if found and len(found.get_text(strip=True)) > 200:
                root = found
                doc.metadata["extracted_from"] = selector
                break
        root = root or soup.body or soup

        blocks = _walk(root, options)
        if not blocks:
            doc.warn("No content found in HTML document.")
        doc.extend(blocks)

        # A leading H1 is the page title; keeping both duplicates it.
        opens_with_h1 = doc.blocks and doc.blocks[0].type == "heading" and doc.blocks[0].level == 1
        if opens_with_h1 and (not doc.title or doc.title == str(doc.blocks[0].content)):
            doc.title = str(doc.blocks[0].content)
            doc.blocks.pop(0)
        return doc


class XMLParser(BaseParser):
    """Generic XML: elements become headings, attributes and leaves become
    key/value pairs. Enough structure for a model to reason over."""

    formats = ("xml",)
    label = "XML"
    priority = 45

    def parse(self, data: bytes, filename: str, detection: Detection, options: ConvertOptions) -> Document:
        from bs4 import BeautifulSoup

        doc = self.new_document(data, filename, detection)
        soup = BeautifulSoup(decode(data), "xml")
        root = soup.find()
        if root is None:
            doc.warn("XML document had no root element — emitted verbatim.")
            doc.add(code(decode(data), "xml"))
            return doc

        doc.metadata["root_element"] = root.name
        doc.extend(_walk_xml(root, level=1, depth=0))
        return doc


# ── HTML walking ─────────────────────────────────────────────────────


def _walk(node: Any, options: ConvertOptions, depth: int = 0) -> list[Block]:
    blocks: list[Block] = []
    if depth > 40:  # pathological nesting guard
        return blocks

    for child in getattr(node, "children", []):
        name = getattr(child, "name", None)
        if name is None:
            text = clean(str(child))
            if text:
                blocks.append(paragraph(text))
            continue
        if name in _DROP:
            continue

        if re.fullmatch(r"h[1-6]", name):
            text = _inline(child)
            if text:
                blocks.append(heading(text, int(name[1])))
        elif name == "p":
            text = _inline(child)
            if text:
                blocks.append(paragraph(text))
        elif name in ("ul", "ol"):
            items = _list_items(child)
            if items:
                blocks.append(list_block(items, ordered=(name == "ol")))
        elif name == "table":
            block = _table(child)
            if block:
                blocks.append(block)
        elif name == "pre":
            body = child.get_text()
            if body.strip():
                blocks.append(code(body, _code_lang(child)))
        elif name == "blockquote":
            text = _inline(child)
            if text:
                blocks.append(quote(text))
        elif name == "hr":
            blocks.append(rule())
        elif name == "img":
            src = child.get("src") or ""
            if src:
                blocks.append(image(clean(child.get("alt") or ""), src))
        elif name == "figure":
            inner = _walk(child, options, depth + 1)
            caption = child.find("figcaption")
            blocks.extend(inner)
            if caption:
                text = _inline(caption)
                if text:
                    blocks.append(paragraph(f"*{text}*"))
        elif name in ("br", "wbr", "input", "meta", "link"):
            continue
        else:
            blocks.extend(_walk(child, options, depth + 1))

    return blocks


def _inline(node: Any) -> str:
    """Flatten an element to Markdown-inline text, keeping emphasis and links."""
    parts: list[str] = []
    for child in getattr(node, "children", []):
        name = getattr(child, "name", None)
        if name is None:
            parts.append(str(child))
            continue
        if name in _DROP:
            continue
        if name == "br":
            parts.append("\n")
            continue
        if name == "a":
            href = (child.get("href") or "").strip()
            label = _inline(child).strip()
            if label and href and not href.startswith("javascript:"):
                parts.append(f"[{label}]({href})")
            elif label:
                parts.append(label)
            continue
        if name == "img":
            src = (child.get("src") or "").strip()
            if src:
                parts.append(f"![{clean(child.get('alt') or '')}]({src})")
            continue
        mark = _INLINE_MARKS.get(name)
        inner = _inline(child)
        if mark and inner.strip():
            parts.append(f"{mark}{inner.strip()}{mark}")
        else:
            parts.append(inner)
    return clean("".join(parts))


def _list_items(node: Any, depth: int = 0) -> list[ListItem]:
    items: list[ListItem] = []
    if depth > 8:
        return items
    for li in node.find_all("li", recursive=False):
        nested: list[ListItem] = []
        for sub in li.find_all(["ul", "ol"], recursive=False):
            nested.extend(_list_items(sub, depth + 1))
            sub.extract()
        text = _inline(li)
        checked = _task_state(li)
        if text or nested:
            items.append(ListItem(text, nested, checked))
    return items


def _task_state(li: Any) -> bool | None:
    box = li.find("input", attrs={"type": "checkbox"})
    if box is None:
        return None
    return box.has_attr("checked")


def _table(node: Any) -> Block | None:
    header: list[str] | None = None
    rows: list[list[str]] = []

    head = node.find("thead")
    if head:
        head_rows = head.find_all("tr")
        if head_rows:
            header = [_inline(c) for c in head_rows[0].find_all(["th", "td"])]

    body = node.find("tbody") or node
    for tr in body.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if not cells:
            continue
        values = [_inline(c) for c in cells]
        if header is None and all(c.name == "th" for c in cells):
            header = values
            continue
        rows.append(values)

    rows = trim(rows)
    if not rows and not header:
        return None
    if header is None:
        header, rows = split_header(rows, None)

    caption = node.find("caption")
    return table(rows, header=header, caption=_inline(caption) if caption else None)


def _code_lang(node: Any) -> str:
    target = node.find("code") or node
    for cls in target.get("class", []) or []:
        if cls.startswith(("language-", "lang-")):
            return cls.split("-", 1)[1]
    return ""


def _meta_tags(soup: Any) -> dict[str, str]:
    wanted = {
        "description": ("name", "description"),
        "author": ("name", "author"),
        "keywords": ("name", "keywords"),
        "og_title": ("property", "og:title"),
        "og_site": ("property", "og:site_name"),
        "canonical_url": ("property", "og:url"),
        "published": ("property", "article:published_time"),
    }
    out: dict[str, str] = {}
    for key, (attr, value) in wanted.items():
        tag = soup.find("meta", attrs={attr: value})
        content = (tag.get("content") if tag else "") or ""
        if content.strip():
            out[key] = clean(content)
    return out


# ── XML walking ──────────────────────────────────────────────────────


def _walk_xml(node: Any, level: int, depth: int) -> list[Block]:
    blocks: list[Block] = []
    if depth > 12:
        return blocks

    children = [c for c in node.children if getattr(c, "name", None)]
    own_text = clean("".join(str(c) for c in node.children if not getattr(c, "name", None)))

    attrs = {k: str(v) for k, v in (node.attrs or {}).items()}
    if children:
        blocks.append(heading(node.name, min(level, 6)))
        if attrs:
            blocks.append(Block("key_values", attrs))
        if own_text:
            blocks.append(paragraph(own_text))
        for child in children:
            blocks.extend(_walk_xml(child, level + 1, depth + 1))
    else:
        pairs = dict(attrs)
        if own_text:
            pairs[node.name] = own_text
        if pairs:
            blocks.append(Block("key_values", pairs))
    return blocks
