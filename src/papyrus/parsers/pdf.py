"""PDF via PyMuPDF.

PDF has no notion of a heading, a paragraph or a list — it has glyphs at
coordinates. Everything structural in the output of this parser is
inferred, in this order:

1. the embedded outline (TOC), when the author left one — always trusted;
2. font size relative to the document's body size, ranked into levels;
3. line shape (numbering, casing, length) as a last resort.

Tables are located geometrically first and their regions are then excluded
from the text pass, so a table's cells never also appear as loose
paragraphs. Running headers and footers that repeat across most pages are
detected and dropped — they are page furniture, and repeating them once
per page is the single biggest source of noise when a model reads a
converted PDF.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from papyrus.config import ConvertOptions
from papyrus.detect import Detection
from papyrus.errors import ParseError
from papyrus.ir import (
    Asset,
    Block,
    Document,
    ListItem,
    heading,
    image,
    list_block,
    page_break,
    paragraph,
    table,
)
from papyrus.parsers.base import BaseParser
from papyrus.utils.tables import split_header, trim
from papyrus.utils.text import clean, looks_like_heading

_BULLET_LINE = re.compile(r"^\s*[-*•·‣▪◦●○]\s+(.+)$")
_NUMBER_LINE = re.compile(r"^\s*(\d{1,2})[.)]\s+(.+)$")
_PAGE_NUMBER = re.compile(r"^\s*(page\s+)?\d+\s*(/\s*\d+)?\s*$", re.IGNORECASE)


class PDFParser(BaseParser):
    formats = ("pdf",)
    label = "PDF"
    priority = 10

    def parse(self, data: bytes, filename: str, detection: Detection, options: ConvertOptions) -> Document:
        import pymupdf

        _quiet_pymupdf(pymupdf)
        doc = self.new_document(data, filename, detection)
        try:
            pdf = pymupdf.open(stream=data, filetype="pdf")
        except Exception as exc:
            raise ParseError(f"Could not open PDF: {exc}") from exc

        try:
            if pdf.needs_pass:
                raise ParseError("PDF is password-protected.")

            doc.metadata.update(_metadata(pdf))
            if doc.metadata.get("title"):
                doc.title = doc.metadata["title"]

            limits = options.limits
            total = pdf.page_count
            pages = min(total, limits.max_pdf_pages)
            if pages < total:
                doc.warn(f"PDF has {total} pages; stopped at {pages}.")
            doc.metadata["pages"] = pages

            outline = _outline_index(pdf)
            page_data = [_read_page(pdf[i], i + 1, options, doc) for i in range(pages)]

            furniture = _repeated_furniture(page_data, pages)
            # Bare page numbers generalise to "#" and are dropped anyway;
            # listing them as removed running text is noise.
            reported = sorted(f for f in furniture if f.strip("# ").strip())
            if reported:
                doc.metadata["removed_running_text"] = reported

            body_size = _body_font_size(page_data)
            size_levels = _heading_levels(page_data, body_size)
            empty_pages = 0

            for page in page_data:
                lines = [ln for ln in page["lines"] if _keep(ln, furniture)]
                if not lines and not page["tables"]:
                    empty_pages += 1

                if options.keep_page_breaks:
                    doc.add(page_break(page["number"]))

                doc.extend(
                    _blocks_for_page(
                        lines,
                        page["tables"],
                        page["number"],
                        outline,
                        size_levels,
                        body_size,
                        options,
                    )
                )
                for asset in page["assets"]:
                    doc.assets.append(asset)
                    doc.add(
                        image(
                            f"Page {page['number']} image",
                            f"{options.asset_dir}/{asset.filename}",
                            asset.asset_id,
                            page=page["number"],
                        )
                    )

            if empty_pages and empty_pages >= max(1, pages // 2):
                doc.warn(
                    f"{empty_pages} of {pages} pages had no extractable text — "
                    "this looks like a scanned PDF. Re-run with OCR enabled."
                )
        finally:
            pdf.close()

        if not any(b.type not in ("page_break",) for b in doc.blocks):
            doc.warn("PDF contained no extractable text.")
        return doc


_quieted = False


def _quiet_pymupdf(pymupdf: Any) -> None:
    """Route MuPDF's chatter into logging instead of stdout.

    `find_tables` prints an advisory on every call. Papyrus writes Markdown
    to stdout, so library chatter there would corrupt piped output.
    """
    global _quieted
    if _quieted:
        return
    import logging
    from contextlib import suppress

    with suppress(Exception):
        pymupdf.set_messages(
            pylogging=True,
            pylogging_name="papyrus.pymupdf",
            pylogging_level=logging.DEBUG,
        )
    with suppress(Exception):
        # `find_tables` prints a layout-package advisory straight to stdout,
        # bypassing the message system above.
        pymupdf.no_recommend_layout()
    _quieted = True


# ── page reading ─────────────────────────────────────────────────────


def _read_page(page: Any, number: int, options: ConvertOptions, doc: Document) -> dict[str, Any]:
    tables, table_boxes = _extract_tables(page, doc)
    lines = _extract_lines(page, number, table_boxes)
    assets = _extract_images(page, number, options, doc) if options.images != "omit" else []
    if not lines and not tables and options.ocr:
        text = _ocr_page(page, doc)
        if text:
            lines = [
                {"text": t, "size": 0.0, "bold": False, "y": i, "x": 0.0, "page": number}
                for i, t in enumerate(text.splitlines())
                if t.strip()
            ]
    return {"number": number, "lines": lines, "tables": tables, "assets": assets}


def _extract_tables(page: Any, doc: Document) -> tuple[list[tuple[float, Block]], list[Any]]:
    """Return (top_y, block) pairs so tables can be placed in reading order."""
    blocks: list[tuple[float, Block]] = []
    boxes: list[Any] = []
    try:
        found = page.find_tables()
    except Exception as exc:  # table finding is best-effort
        doc.warn(f"Table detection unavailable on page {page.number + 1}: {exc}")
        return blocks, boxes

    for candidate in getattr(found, "tables", []):
        try:
            rows = [[clean(c or "") for c in row] for row in candidate.extract()]
        except Exception:
            continue
        rows = trim(rows)
        # Two cells in a line is a layout artefact, not a table.
        if len(rows) < 2 or len(rows[0]) < 2:
            continue
        header, body = split_header(rows, _pdf_header_hint(candidate, rows))
        blocks.append((float(candidate.bbox[1]), table(body, header=header, page=page.number + 1)))
        boxes.append(candidate.bbox)
    return blocks, boxes


def _pdf_header_hint(candidate: Any, rows: list[list[str]]) -> bool | None:
    """PyMuPDF's table finder reports the header row it detected."""
    try:
        header = candidate.header
        names = [clean(n or "") for n in (header.names or [])]
        if names and not header.external:
            # `external` means the header sits outside the table body, in
            # which case row 0 is real data.
            return [n.strip() for n in names] == [c.strip() for c in rows[0]]
        if header.external:
            return False
    except Exception:
        pass
    return None


def _extract_lines(page: Any, number: int, table_boxes: list[Any]) -> list[dict[str, Any]]:
    """Text lines with the font metrics we need for heading inference."""
    try:
        data = page.get_text("dict", sort=True)
    except TypeError:  # older PyMuPDF without `sort`
        data = page.get_text("dict")
    except Exception:
        return []

    lines: list[dict[str, Any]] = []
    for block in data.get("blocks", []):
        if block.get("type") != 0:  # 0 = text
            continue
        if _inside(block.get("bbox"), table_boxes):
            continue
        for line in block.get("lines", []):
            spans = [s for s in line.get("spans", []) if (s.get("text") or "").strip()]
            if not spans:
                continue
            text = clean("".join(s["text"] for s in spans))
            if not text:
                continue
            sizes = [float(s.get("size", 0)) for s in spans]
            bbox = line.get("bbox", (0, 0, 0, 0))
            lines.append(
                {
                    "text": text,
                    "size": round(max(sizes), 1),
                    "bold": any(_is_bold(s) for s in spans),
                    "y": round(float(bbox[1]), 1),
                    "x": round(float(bbox[0]), 1),
                    "page": number,
                    "height": float(bbox[3]) - float(bbox[1]),
                }
            )
    return lines


def _is_bold(span: dict[str, Any]) -> bool:
    bold_flag = 2**4  # PyMuPDF span flag for a bold face
    return bool(int(span.get("flags", 0)) & bold_flag) or "bold" in (span.get("font") or "").lower()


def _inside(bbox: Any, boxes: list[Any]) -> bool:
    if not bbox or not boxes:
        return False
    x0, y0, x1, y1 = bbox
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return any(box[0] - 2 <= cx <= box[2] + 2 and box[1] - 2 <= cy <= box[3] + 2 for box in boxes)


def _extract_images(page: Any, number: int, options: ConvertOptions, doc: Document) -> list[Asset]:

    limits = options.limits
    assets: list[Asset] = []
    try:
        entries = page.get_images(full=True)
    except Exception:
        return assets

    for xref, *_ in entries:
        if len(doc.assets) + len(assets) >= limits.max_assets:
            break
        try:
            raw = page.parent.extract_image(xref)
        except Exception:
            continue
        # Skip spacer and bullet glyphs — they carry no document content.
        if (raw.get("width") or 0) < 32 or (raw.get("height") or 0) < 32:
            continue
        blob = raw.get("image") or b""
        if len(blob) < limits.min_asset_bytes:
            continue
        ext = raw.get("ext", "png")
        asset_id = f"img-{len(doc.assets) + len(assets) + 1:03d}"
        assets.append(
            Asset(
                asset_id,
                f"{asset_id}-page{number}.{ext}",
                f"image/{'jpeg' if ext == 'jpg' else ext}",
                blob,
                raw.get("width"),
                raw.get("height"),
            )
        )
    return assets


def _ocr_page(page: Any, doc: Document) -> str:
    """OCR a page image. Requires Tesseract; degrades to a warning."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        doc.warn("OCR requested but `papyrus-engine[ocr]` is not installed.")
        return ""
    try:
        import io as _io

        import pytesseract

        pix = page.get_pixmap(dpi=200)
        img = Image.open(_io.BytesIO(pix.tobytes("png")))
        return clean(pytesseract.image_to_string(img))
    except Exception as exc:
        doc.warn(f"OCR failed on page {page.number + 1}: {exc}")
        return ""


# ── structure inference ──────────────────────────────────────────────


def _metadata(pdf: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    raw = pdf.metadata or {}
    for key in ("title", "author", "subject", "keywords", "creator", "producer"):
        value = (raw.get(key) or "").strip()
        if value:
            out[key] = clean(value)
    for key, target in (("creationDate", "created"), ("modDate", "modified")):
        value = (raw.get(key) or "").strip()
        if value:
            out[target] = _pdf_date(value)
    return out


def _pdf_date(value: str) -> str:
    match = re.match(r"D:(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?(\d{2})?", value)
    if not match:
        return value
    y, m, d, hh, mm, ss = (match.group(i) or "00" for i in range(1, 7))
    return f"{y}-{m}-{d}T{hh}:{mm}:{ss}"


def _outline_index(pdf: Any) -> dict[tuple[int, str], int]:
    """(page, normalised title) → heading level, from the PDF's own TOC."""
    index: dict[tuple[int, str], int] = {}
    try:
        toc = pdf.get_toc()
    except Exception:
        return index
    for level, title, page in toc or []:
        key = (int(page), _norm(title))
        if key[1]:
            index[key] = max(1, min(6, int(level)))
    return index


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", clean(text)).strip().lower()


def _body_font_size(pages: list[dict[str, Any]]) -> float:
    """The most common font size, weighted by characters — the body text."""
    counter: Counter[float] = Counter()
    for page in pages:
        for line in page["lines"]:
            counter[line["size"]] += max(1, len(line["text"]))
    return counter.most_common(1)[0][0] if counter else 0.0


def _heading_levels(pages: list[dict[str, Any]], body: float) -> dict[float, int]:
    """Rank the font sizes above body text into heading levels 1..4."""
    if not body:
        return {}
    counter: Counter[float] = Counter()
    for page in pages:
        for line in page["lines"]:
            if line["size"] > body * 1.12:
                counter[line["size"]] += 1
    # Ignore sizes used once or twice — usually a stray pull-quote.
    sizes = sorted((s for s, n in counter.items() if n >= 1), reverse=True)
    return {size: min(level, 4) for level, size in enumerate(sizes[:4], start=1)}


def _repeated_furniture(pages: list[dict[str, Any]], total: int) -> set[str]:
    """Lines appearing near the top or bottom of most pages = header/footer."""
    if total < 2:
        return set()
    counter: Counter[str] = Counter()
    for page in pages:
        lines = page["lines"]
        if not lines:
            continue
        candidates = lines[:2] + lines[-2:]
        for line in candidates:
            key = _norm(line["text"])
            if key and len(key) < 120:
                counter[_generalise(key)] += 1
    # On a short document the line has to appear on every page; on a long
    # one, most pages is enough (front matter often lacks the header).
    threshold = total if total < 4 else max(3, int(total * 0.6))
    return {text for text, count in counter.items() if count >= threshold}


def _generalise(text: str) -> str:
    """Collapse page numbers so 'Report | 3' and 'Report | 4' match."""
    return re.sub(r"\d+", "#", text)


def _keep(line: dict[str, Any], furniture: set[str]) -> bool:
    text = line["text"].strip()
    if not text:
        return False
    if _PAGE_NUMBER.match(text):
        return False
    return _generalise(_norm(text)) not in furniture


def _blocks_for_page(
    lines: list[dict[str, Any]],
    tables: list[tuple[float, Block]],
    number: int,
    outline: dict[tuple[int, str], int],
    size_levels: dict[float, int],
    body_size: float,
    options: ConvertOptions,
) -> list[Block]:
    blocks: list[Block] = []
    buffer: list[str] = []
    bullets: list[ListItem] = []
    ordered = False
    pending_tables = sorted(tables, key=lambda pair: pair[0])

    def flush_text() -> None:
        if buffer:
            blocks.append(paragraph(" ".join(buffer), page=number))
            buffer.clear()

    def flush_list() -> None:
        nonlocal bullets
        if bullets:
            blocks.append(list_block(bullets, ordered=ordered, page=number))
            bullets = []

    def emit_tables_above(y: float) -> None:
        """Place any table that sits above this line before the line itself.

        Text and tables are extracted in two separate passes, so without
        this the table would be appended after the whole page — landing
        under the section that follows it rather than inside its own.
        """
        while pending_tables and pending_tables[0][0] <= y:
            flush_text()
            flush_list()
            blocks.append(pending_tables.pop(0)[1])

    for line in lines:
        text = line["text"]
        emit_tables_above(line["y"])

        bullet = _BULLET_LINE.match(text)
        number_match = _NUMBER_LINE.match(text)
        if bullet or (number_match and not looks_like_heading(text)):
            flush_text()
            is_ordered = bullet is None
            if bullets and is_ordered != ordered:
                flush_list()
            ordered = is_ordered
            bullets.append(ListItem((bullet or number_match).group((bullet and 1) or 2).strip()))
            continue

        level = _level_for(line, number, outline, size_levels, body_size, options)
        if level is not None:
            flush_text()
            flush_list()
            blocks.append(heading(text, level, page=number))
            continue

        flush_list()
        # A line ending mid-sentence continues the same paragraph.
        buffer.append(text)
        if text.endswith((".", "!", "?", ":", ";", '"', "”")):
            flush_text()

    flush_text()
    flush_list()
    blocks.extend(block for _, block in pending_tables)
    return blocks


def _level_for(
    line: dict[str, Any],
    number: int,
    outline: dict[tuple[int, str], int],
    size_levels: dict[float, int],
    body_size: float,
    options: ConvertOptions,
) -> int | None:
    key = (number, _norm(line["text"]))
    if key in outline:
        return outline[key]
    if not options.detect_headings:
        return None
    size = line["size"]
    if size in size_levels and size > body_size * 1.12:
        return size_levels[size]
    if line["bold"] and size >= body_size and looks_like_heading(line["text"], max_words=10):
        return 3
    return None
