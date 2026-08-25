"""The parser contract.

A parser turns bytes into a `Document`. It must not produce Markdown, must
not touch the filesystem, and must not raise for merely *messy* input —
degrade and record a warning instead. Only genuinely unreadable input
raises `ParseError`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from papyrus.config import ConvertOptions
from papyrus.detect import Detection
from papyrus.ir import Document, SourceInfo
from papyrus.utils.files import sha256
from papyrus.utils.text import title_from_filename


class BaseParser(ABC):
    """Base class for every format handler."""

    #: papyrus format ids this parser claims (see `papyrus.detect.FORMATS`)
    formats: tuple[str, ...] = ()
    #: human-readable label, surfaced in `papyrus formats`
    label: str = ""
    #: lower number wins when several parsers claim the same format
    priority: int = 100

    def supports(self, detection: Detection) -> bool:
        return detection.format in self.formats

    @abstractmethod
    def parse(
        self,
        data: bytes,
        filename: str,
        detection: Detection,
        options: ConvertOptions,
    ) -> Document:
        """Parse `data` into a Document. Implementations must not raise on
        recoverable problems — append to `document.warnings` instead."""

    # ── helper for implementations ───────────────────────────────
    @staticmethod
    def new_document(data: bytes, filename: str, detection: Detection) -> Document:
        return Document(
            source=SourceInfo(
                filename=filename,
                media_type=detection.media_type,
                format=detection.format,
                size_bytes=len(data),
                sha256=sha256(data),
            ),
            title=title_from_filename(filename),
        )
