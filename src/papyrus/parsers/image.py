"""Images.

Without OCR an image yields metadata and a placeholder — honest, and it
keeps the document's position in a batch. With `--ocr` (and Tesseract
installed) the recognised text is run through the same structure pass as
plain text.
"""

from __future__ import annotations

from papyrus.config import ConvertOptions
from papyrus.detect import Detection
from papyrus.ir import Asset, Document, heading, image, key_values
from papyrus.parsers.base import BaseParser
from papyrus.parsers.text import text_to_blocks
from papyrus.utils.files import human_bytes, safe_name
from papyrus.utils.text import clean, title_from_filename


class ImageParser(BaseParser):
    formats = ("image",)
    label = "Images (OCR optional)"
    priority = 60

    def parse(self, data: bytes, filename: str, detection: Detection, options: ConvertOptions) -> Document:
        doc = self.new_document(data, filename, detection)
        doc.title = title_from_filename(filename)

        facts: dict[str, str] = {
            "Format": detection.media_type,
            "Size": human_bytes(len(data)),
        }
        width = height = None
        try:
            from PIL import Image as PILImage

            with PILImage.open(_buffer(data)) as img:
                width, height = img.size
                facts["Dimensions"] = f"{width} x {height} px"
                facts["Mode"] = img.mode
        except Exception:
            pass

        name = safe_name(filename, "image")
        asset_id = "img-001"
        if options.images != "omit":
            doc.assets.append(
                Asset(asset_id, f"{asset_id}-{name}", detection.media_type, data, width, height)
            )
            doc.add(image(doc.title, f"{options.asset_dir}/{asset_id}-{name}", asset_id))

        doc.add(key_values(facts))
        doc.metadata.update({"width": width, "height": height})

        if options.ocr:
            text = self._ocr(data, doc)
            if text:
                doc.add(heading("Recognised text", 2))
                doc.extend(text_to_blocks(text))
                doc.metadata["ocr"] = True
        else:
            doc.warn("Image has no text layer — re-run with OCR to transcribe it.")
        return doc

    def _ocr(self, data: bytes, doc: Document) -> str:
        try:
            import pytesseract
            from PIL import Image as PILImage
        except ImportError:
            doc.warn("OCR requested but `papyrus-engine[ocr]` is not installed.")
            return ""
        try:
            with PILImage.open(_buffer(data)) as img:
                return clean(pytesseract.image_to_string(img))
        except Exception as exc:
            doc.warn(f"OCR failed: {exc}")
            return ""


def _buffer(data: bytes):
    from io import BytesIO

    return BytesIO(data)
