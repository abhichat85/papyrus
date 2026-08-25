"""Parser registry.

Adding a format is: write a parser, list it here. Nothing else in the
engine changes.
"""

from __future__ import annotations

from papyrus.detect import Detection
from papyrus.errors import UnsupportedFormatError
from papyrus.parsers.base import BaseParser


class ParserRegistry:
    def __init__(self, parsers: list[BaseParser] | None = None) -> None:
        self._parsers: list[BaseParser] = []
        for parser in parsers or []:
            self.register(parser)

    def register(self, parser: BaseParser) -> None:
        self._parsers.append(parser)
        self._parsers.sort(key=lambda p: p.priority)

    @property
    def parsers(self) -> list[BaseParser]:
        return list(self._parsers)

    def get(self, detection: Detection) -> BaseParser:
        for parser in self._parsers:
            if parser.supports(detection):
                return parser
        raise UnsupportedFormatError(
            f"No parser for '{detection.format}' "
            f"(detected via {detection.via}, extension '{detection.extension or 'none'}')"
        )

    def supported_formats(self) -> dict[str, str]:
        """format id → parser label, for `papyrus formats` and GET /v1/formats."""
        out: dict[str, str] = {}
        for parser in reversed(self._parsers):
            for fmt in parser.formats:
                out[fmt] = parser.label or parser.__class__.__name__
        return dict(sorted(out.items()))


def default_registry() -> ParserRegistry:
    """Every parser Papyrus ships with, in resolution order."""
    from papyrus.parsers.archive import ArchiveParser
    from papyrus.parsers.data import CSVParser, JSONLParser, JSONParser
    from papyrus.parsers.email import EmailParser
    from papyrus.parsers.epub import EpubParser
    from papyrus.parsers.html import HTMLParser, XMLParser
    from papyrus.parsers.image import ImageParser
    from papyrus.parsers.legacy import LegacyOfficeParser, RTFParser
    from papyrus.parsers.notebook import NotebookParser
    from papyrus.parsers.office import DocxParser, PptxParser, XlsxParser
    from papyrus.parsers.pdf import PDFParser
    from papyrus.parsers.text import CodeParser, MarkdownParser, TextParser

    return ParserRegistry(
        [
            PDFParser(),
            DocxParser(),
            PptxParser(),
            XlsxParser(),
            EpubParser(),
            NotebookParser(),
            EmailParser(),
            HTMLParser(),
            XMLParser(),
            JSONParser(),
            JSONLParser(),
            CSVParser(),
            MarkdownParser(),
            CodeParser(),
            RTFParser(),
            LegacyOfficeParser(),
            ImageParser(),
            ArchiveParser(),
            TextParser(),  # last: the catch-all
        ]
    )
