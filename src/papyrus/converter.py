"""The engine's front door.

    from papyrus import convert
    result = convert("report.pdf")
    print(result.markdown)

Everything above this line is machinery; this is the whole public API.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from papyrus.chunking import Chunk, chunk_document, to_jsonl
from papyrus.config import ConvertOptions
from papyrus.detect import Detection, detect
from papyrus.errors import FileTooLargeError, PapyrusError, ParseError
from papyrus.ir import Document
from papyrus.registry import ParserRegistry, default_registry
from papyrus.renderers.markdown import MarkdownRenderer
from papyrus.utils.files import safe_name


@dataclass
class ConversionResult:
    """Everything one conversion produced."""

    markdown: str
    document: Document
    detection: Detection
    chunks: list[Chunk] = field(default_factory=list)
    duration_ms: int = 0

    # ── convenience ──────────────────────────────────────────────
    @property
    def title(self) -> str | None:
        return self.document.title

    @property
    def warnings(self) -> list[str]:
        return self.document.warnings

    @property
    def format(self) -> str:
        return self.detection.format

    def summary(self) -> dict[str, Any]:
        return {
            "filename": self.document.source.filename,
            "format": self.detection.format,
            "detected_via": self.detection.via,
            "title": self.document.title,
            "blocks": len(self.document.blocks),
            "words": self.document.word_count,
            "characters": len(self.markdown),
            "assets": len(self.document.assets),
            "chunks": len(self.chunks),
            "warnings": self.document.warnings,
            "duration_ms": self.duration_ms,
        }

    def write(self, out_dir: str | Path, stem: str | None = None) -> dict[str, Path]:
        """Write the bundle: Markdown, IR, chunks and extracted assets."""
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = stem or Path(safe_name(self.document.source.filename, "document")).stem or "document"

        written: dict[str, Path] = {}
        md_path = out_dir / f"{stem}.md"
        md_path.write_text(self.markdown, encoding="utf-8")
        written["markdown"] = md_path

        if self.chunks:
            chunks_path = out_dir / f"{stem}.chunks.jsonl"
            chunks_path.write_text(to_jsonl(self.chunks), encoding="utf-8")
            written["chunks"] = chunks_path

        assets = [a for a in self.document.assets if a.data]
        if assets:
            asset_dir = out_dir / "assets"
            asset_dir.mkdir(exist_ok=True)
            for asset in assets:
                (asset_dir / safe_name(asset.filename, asset.asset_id)).write_bytes(asset.data)
            written["assets"] = asset_dir
        return written

    def write_ir(self, path: str | Path) -> Path:
        path = Path(path)
        path.write_text(self.document.to_json(), encoding="utf-8")
        return path


class Converter:
    """Detect → parse → render. Reusable and thread-safe once constructed."""

    def __init__(
        self,
        registry: ParserRegistry | None = None,
        options: ConvertOptions | None = None,
    ) -> None:
        self.registry = registry or default_registry()
        self.options = options or ConvertOptions()

    # ── entry points ─────────────────────────────────────────────
    def convert_bytes(
        self,
        data: bytes,
        filename: str = "document",
        options: ConvertOptions | None = None,
    ) -> ConversionResult:
        options = options or self.options
        started = time.perf_counter()

        limit = options.limits.max_file_bytes
        if len(data) > limit:
            raise FileTooLargeError(
                f"File is {len(data):,} bytes; the limit is {limit:,} "
                "(raise PAPYRUS_MAX_FILE_BYTES to change it)."
            )
        if not data:
            raise ParseError("File is empty.")

        detection = detect(filename, data)
        parser = self.registry.get(detection)

        try:
            document = parser.parse(data, filename, detection, options)
        except PapyrusError:
            raise
        except Exception as exc:  # a parser bug must not look like a user error
            raise ParseError(
                f"{parser.label or type(parser).__name__} failed on '{filename}': {type(exc).__name__}: {exc}"
            ) from exc

        markdown = MarkdownRenderer(options).render(document)
        chunks = chunk_document(document, options) if options.chunk else []

        return ConversionResult(
            markdown=markdown,
            document=document,
            detection=detection,
            chunks=chunks,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    def convert(self, path: str | Path, options: ConvertOptions | None = None) -> ConversionResult:
        path = Path(path)
        if not path.is_file():
            raise ParseError(f"Not a file: {path}")
        return self.convert_bytes(path.read_bytes(), path.name, options)

    # ── introspection ────────────────────────────────────────────
    def supported_formats(self) -> dict[str, str]:
        return self.registry.supported_formats()


# ── module-level shortcuts ───────────────────────────────────────────

_default: Converter | None = None


def _shared() -> Converter:
    global _default
    if _default is None:
        _default = Converter()
    return _default


def convert(path: str | Path, options: ConvertOptions | None = None) -> ConversionResult:
    """Convert a file on disk."""
    return _shared().convert(path, options)


def convert_bytes(
    data: bytes, filename: str = "document", options: ConvertOptions | None = None
) -> ConversionResult:
    """Convert an in-memory file."""
    return _shared().convert_bytes(data, filename, options)


def to_markdown(path: str | Path, **kwargs: Any) -> str:
    """One-liner: file path in, Markdown string out."""
    options = ConvertOptions(**kwargs) if kwargs else None
    return convert(path, options).markdown
