"""EPUB — a zipped set of XHTML chapters plus an OPF manifest.

Chapters are emitted in *spine* order (the reading order the author
declared), not zip order, and each chapter is run through the same HTML
walker the web parser uses.
"""

from __future__ import annotations

import zipfile
from io import BytesIO
from posixpath import dirname, join, normpath

from papyrus.config import ConvertOptions
from papyrus.detect import Detection
from papyrus.errors import ParseError
from papyrus.ir import Document, heading, page_break
from papyrus.parsers.base import BaseParser
from papyrus.parsers.html import _walk
from papyrus.utils.text import clean, decode


class EpubParser(BaseParser):
    formats = ("epub",)
    label = "EPUB"
    priority = 15

    def parse(self, data: bytes, filename: str, detection: Detection, options: ConvertOptions) -> Document:
        from bs4 import BeautifulSoup

        doc = self.new_document(data, filename, detection)
        try:
            archive = zipfile.ZipFile(BytesIO(data))
        except Exception as exc:
            raise ParseError(f"Could not open EPUB: {exc}") from exc

        with archive:
            opf_path = _find_opf(archive)
            if not opf_path:
                raise ParseError("EPUB has no OPF package document.")

            opf = BeautifulSoup(decode(archive.read(opf_path)), "xml")
            doc.metadata.update(_dublin_core(opf))
            if doc.metadata.get("title"):
                doc.title = doc.metadata["title"]

            base = dirname(opf_path)
            manifest = {
                item.get("id"): item.get("href")
                for item in opf.find_all("item")
                if item.get("id") and item.get("href")
            }
            spine = [
                manifest.get(ref.get("idref"))
                for ref in opf.find_all("itemref")
                if manifest.get(ref.get("idref"))
            ]
            if not spine:
                spine = [h for h in manifest.values() if h.lower().endswith((".xhtml", ".html"))]

            doc.metadata["chapters"] = len(spine)
            names = set(archive.namelist())

            for index, href in enumerate(spine, 1):
                path = normpath(join(base, href.split("#")[0])) if base else href.split("#")[0]
                if path not in names:
                    continue
                try:
                    raw = archive.read(path)
                except Exception:
                    doc.warn(f"Could not read chapter '{href}'.")
                    continue

                soup = BeautifulSoup(decode(raw), "lxml")
                for tag in soup.find_all(["script", "style", "svg"]):
                    tag.decompose()
                body = soup.body or soup
                blocks = _walk(body, options)
                if not blocks:
                    continue

                doc.add(page_break(index))
                if blocks[0].type != "heading":
                    title = _chapter_title(soup) or f"Chapter {index}"
                    doc.add(heading(title, 2, page=index))
                doc.extend(blocks)

        if not doc.blocks:
            doc.warn("EPUB contained no readable chapters.")
        return doc


def _find_opf(archive: zipfile.ZipFile) -> str | None:
    try:
        from bs4 import BeautifulSoup

        container = BeautifulSoup(decode(archive.read("META-INF/container.xml")), "xml")
        rootfile = container.find("rootfile")
        if rootfile and rootfile.get("full-path"):
            return rootfile["full-path"]
    except Exception:
        pass
    for name in archive.namelist():
        if name.lower().endswith(".opf"):
            return name
    return None


def _dublin_core(opf) -> dict[str, str]:
    fields = ("title", "creator", "publisher", "language", "date", "description", "identifier")
    out: dict[str, str] = {}
    for field in fields:
        tag = opf.find(field)
        if tag and tag.get_text(strip=True):
            key = "author" if field == "creator" else field
            out[key] = clean(tag.get_text())
    return out


def _chapter_title(soup) -> str | None:
    for selector in ("h1", "h2", "title"):
        tag = soup.find(selector)
        if tag and tag.get_text(strip=True):
            return clean(tag.get_text())
    return None
