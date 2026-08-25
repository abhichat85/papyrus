"""Papyrus — the universal document ingestion engine.

Any file in, agent-ready Markdown out.

    from papyrus import convert
    print(convert("report.pdf").markdown)
"""

from __future__ import annotations

from papyrus.chunking import Chunk, chunk_document, to_jsonl
from papyrus.config import ConvertOptions, Limits
from papyrus.converter import ConversionResult, Converter, convert, convert_bytes, to_markdown
from papyrus.detect import detect
from papyrus.errors import (
    FileTooLargeError,
    LimitExceededError,
    MissingDependencyError,
    PapyrusError,
    ParseError,
    UnsupportedFormatError,
)
from papyrus.ir import Block, Document, ListItem, SourceInfo, Table
from papyrus.registry import ParserRegistry, default_registry
from papyrus.renderers.markdown import MarkdownRenderer

__version__ = "0.1.0"

__all__ = [
    "Block",
    "Chunk",
    "ConversionResult",
    "ConvertOptions",
    "Converter",
    "Document",
    "FileTooLargeError",
    "LimitExceededError",
    "Limits",
    "ListItem",
    "MarkdownRenderer",
    "MissingDependencyError",
    "PapyrusError",
    "ParseError",
    "ParserRegistry",
    "SourceInfo",
    "Table",
    "UnsupportedFormatError",
    "__version__",
    "chunk_document",
    "convert",
    "convert_bytes",
    "default_registry",
    "detect",
    "to_jsonl",
    "to_markdown",
]
