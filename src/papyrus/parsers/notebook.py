"""Jupyter notebooks.

Markdown cells pass through verbatim; code cells become fenced blocks in
the notebook's language; outputs are included (text and stream output as
code, errors as quotes, images as assets) because for a model reading a
notebook the output *is* half the meaning.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from papyrus.config import ConvertOptions
from papyrus.detect import Detection
from papyrus.errors import ParseError
from papyrus.ir import Asset, Document, code, heading, image, quote, raw
from papyrus.parsers.base import BaseParser
from papyrus.utils.text import clean


class NotebookParser(BaseParser):
    formats = ("ipynb",)
    label = "Jupyter notebook"
    priority = 20

    def parse(self, data: bytes, filename: str, detection: Detection, options: ConvertOptions) -> Document:
        doc = self.new_document(data, filename, detection)
        try:
            notebook = json.loads(data.decode("utf-8"))
        except Exception as exc:
            raise ParseError(f"Could not read notebook: {exc}") from exc

        meta = notebook.get("metadata", {})
        lang = (
            meta.get("kernelspec", {}).get("language")
            or meta.get("language_info", {}).get("name")
            or "python"
        )
        doc.metadata["language"] = lang
        doc.metadata["kernel"] = meta.get("kernelspec", {}).get("display_name", "")
        doc.metadata["nbformat"] = notebook.get("nbformat")

        cells = notebook.get("cells", [])
        doc.metadata["cells"] = len(cells)
        counter = 0

        for cell in cells:
            kind = cell.get("cell_type")
            source = _source(cell)
            if kind == "markdown":
                body = source.strip()
                if not body:
                    continue
                # A notebook that opens with an H1 is telling us its title;
                # keeping both that and the filename-derived one duplicates it.
                if not doc.blocks and body.startswith("# "):
                    first, _, rest = body.partition("\n")
                    doc.title = first[2:].strip()
                    body = rest.strip()
                if body:
                    doc.add(raw(body))
            elif kind == "code":
                counter += 1
                if source.strip():
                    doc.add(code(source, lang, cell=counter))
                self._emit_outputs(cell.get("outputs", []), doc, counter, options)
            elif kind == "raw" and source.strip():
                doc.add(code(source, "text", cell=counter))

        if not doc.blocks:
            doc.warn("Notebook contained no cells.")
        return doc

    def _emit_outputs(
        self, outputs: list[dict[str, Any]], doc: Document, cell: int, options: ConvertOptions
    ) -> None:
        for output in outputs:
            kind = output.get("output_type")
            if kind == "stream":
                text = clean(_join(output.get("text", "")))
                if text:
                    doc.add(code(text, "text", cell=cell, output=True))
            elif kind == "error":
                message = f"{output.get('ename', 'Error')}: {output.get('evalue', '')}"
                doc.add(quote(f"**{clean(message)}**", cell=cell, output=True))
            elif kind in ("execute_result", "display_data"):
                self._emit_rich(output.get("data", {}), doc, cell, options)

    def _emit_rich(self, data: dict[str, Any], doc: Document, cell: int, options: ConvertOptions) -> None:
        if "text/markdown" in data:
            doc.add(raw(_join(data["text/markdown"])))
            return
        if "image/png" in data and options.images != "omit":
            if len(doc.assets) < options.limits.max_assets:
                blob = base64.b64decode(_join(data["image/png"]))
                asset_id = f"img-{len(doc.assets) + 1:03d}"
                filename = f"{asset_id}-cell{cell}.png"
                doc.assets.append(Asset(asset_id, filename, "image/png", blob))
                doc.add(
                    image(f"Output of cell {cell}", f"{options.asset_dir}/{filename}", asset_id, cell=cell)
                )
            return
        if "text/html" in data:
            doc.add(heading(f"Output {cell}", 6, cell=cell))
            doc.add(raw(_join(data["text/html"]).strip()))
            return
        if "text/plain" in data:
            text = clean(_join(data["text/plain"]))
            if text:
                doc.add(code(text, "text", cell=cell, output=True))


def _source(cell: dict[str, Any]) -> str:
    return _join(cell.get("source", ""))


def _join(value: Any) -> str:
    if isinstance(value, list):
        return "".join(str(v) for v in value)
    return str(value or "")
