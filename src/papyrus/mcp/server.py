"""Papyrus as an MCP server.

An agent with a filesystem can already read `.txt` and `.md`. It cannot
read a PDF, a deck, or a spreadsheet — those are opaque binaries, and the
usual workaround is a brittle shell pipeline the model has to reinvent
every session. This server closes that gap with one command:

    claude mcp add papyrus -- papyrus-mcp

The design constraint that shapes everything here is **context budget**. A
48-page report is ~60,000 characters; returning it whole would consume a
large fraction of the model's window and crowd out the actual task. So:

* every tool that returns document text takes `max_chars` and reports
  exactly how to fetch the next slice;
* `inspect_document` exists so an agent can find out what a file *is*, and
  how big the answer would be, before spending the tokens;
* `convert_to_file` writes Markdown to disk and returns only a receipt,
  which is the right move for anything large or for batch work.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from papyrus import __version__
from papyrus.chunking import to_jsonl
from papyrus.config import ConvertOptions, Limits
from papyrus.converter import Converter
from papyrus.detect import detect
from papyrus.errors import PapyrusError
from papyrus.utils.files import human_bytes

#: Roughly 5k tokens — a large but not ruinous slice of an agent's window.
DEFAULT_MAX_CHARS = 20_000
#: Directory listings can be enormous; cap what one call will walk.
MAX_BATCH_FILES = 200

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".next", "dist", "build"}


@dataclass
class _Slice:
    text: str
    truncated: bool
    total: int
    end: int


def _cut(text: str, offset: int, max_chars: int) -> _Slice:
    """Take a window of text, preferring to break at a line boundary."""
    total = len(text)
    if offset >= total:
        return _Slice("", False, total, total)
    end = min(offset + max_chars, total)
    if end < total:
        # Back up to the last blank line so a slice starts at a block.
        boundary = text.rfind("\n\n", offset + max_chars // 2, end)
        if boundary != -1:
            end = boundary
    return _Slice(text[offset:end], end < total, total, end)


def _resolve(path: str) -> Path:
    resolved = Path(path).expanduser()
    if not resolved.is_absolute():
        resolved = Path.cwd() / resolved
    return resolved.resolve()


def build_server(converter: Converter | None = None) -> Any:
    """Construct the MCP server. Separated from `main` so tests can drive it."""
    from mcp.server.mcpserver import MCPServer

    engine = converter or Converter()

    server = MCPServer(
        name="papyrus",
        title="Papyrus — universal document ingestion",
        version=__version__,
        instructions=(
            "Converts any document into clean Markdown so you can read it.\n\n"
            "Handles PDF, Word, PowerPoint, Excel, HTML, EPUB, email, Jupyter "
            "notebooks, CSV/JSON, RTF, images and ZIP archives.\n\n"
            "Start with `inspect_document` when you do not know what a file is "
            "or how large it is — it is cheap and tells you whether reading the "
            "whole thing is worth the context. Use `convert_document` to read a "
            "file directly, `convert_to_file` for anything large or for batches, "
            "and `convert_to_chunks` when you are building a retrieval index."
        ),
    )

    # ── inspect ──────────────────────────────────────────────────
    @server.tool(
        title="Inspect a document",
        description=(
            "Identify a file and report what converting it would cost, without "
            "returning its text. Use this first when a file's type or size is "
            "unknown. Returns the detected format (from magic bytes, not the "
            "file extension), page/sheet/slide counts, word count, the size of "
            "the Markdown that conversion would produce, and any warnings."
        ),
    )
    def inspect_document(path: str) -> str:
        """Identify a document and estimate the cost of reading it."""
        target = _resolve(path)
        if not target.is_file():
            return f"Not a file: {target}"

        data = target.read_bytes()
        detection = detect(target.name, data)
        try:
            result = engine.convert_bytes(data, target.name)
        except PapyrusError as exc:
            return json.dumps(
                {
                    "path": str(target),
                    "format": detection.format,
                    "size": human_bytes(len(data)),
                    "convertible": False,
                    "error": str(exc),
                },
                indent=2,
            )

        counts: dict[str, int] = {}
        for block in result.document.blocks:
            counts[block.type] = counts.get(block.type, 0) + 1

        payload = {
            "path": str(target),
            "format": detection.format,
            "detected_via": detection.via,
            "size": human_bytes(len(data)),
            "title": result.document.title,
            "convertible": True,
            "markdown_characters": len(result.markdown),
            "approx_tokens": len(result.markdown) // 4,
            "words": result.document.word_count,
            "structure": counts,
            "metadata": {
                k: v for k, v in result.document.metadata.items() if not k.startswith("_")
            },
            "warnings": result.warnings,
            "reads_in_one_call": len(result.markdown) <= DEFAULT_MAX_CHARS,
        }
        return json.dumps(payload, indent=2, default=str)

    # ── convert ──────────────────────────────────────────────────
    @server.tool(
        title="Convert a document to Markdown",
        description=(
            "Read any document as Markdown. Structure is preserved: headings, "
            "tables, lists, code blocks, and page markers you can cite. "
            "Long documents are returned in slices — the footer tells you the "
            "exact call to make for the next one. For very large files prefer "
            "`convert_to_file`."
        ),
    )
    def convert_document(
        path: str,
        offset: int = 0,
        max_chars: int = DEFAULT_MAX_CHARS,
        include_frontmatter: bool = False,
        include_page_markers: bool = True,
    ) -> str:
        """Convert one document and return a slice of its Markdown."""
        target = _resolve(path)
        if not target.is_file():
            return f"Not a file: {target}"

        options = ConvertOptions(
            frontmatter=include_frontmatter,
            page_anchors=include_page_markers,
            images="placeholder",
        )
        try:
            result = engine.convert(target, options)
        except PapyrusError as exc:
            return f"Could not convert {target.name}: {exc}"

        window = _cut(result.markdown, max(0, offset), max(1000, max_chars))
        parts = [window.text]

        if window.truncated:
            parts.append(
                f"\n\n---\n[Papyrus: showing characters {offset}-{window.end} of "
                f"{window.total}. Continue with "
                f'convert_document(path="{path}", offset={window.end}), or use '
                f"convert_to_file to write the whole document to disk.]"
            )
        if result.warnings:
            parts.append("\n[Papyrus notes: " + "; ".join(result.warnings) + "]")
        return "".join(parts)

    # ── convert to file ──────────────────────────────────────────
    @server.tool(
        title="Convert documents to Markdown files",
        description=(
            "Convert a file, or every file in a folder, and write the Markdown "
            "to disk instead of returning it. Returns a short receipt listing "
            "what was written. This is the right tool for large documents and "
            "for batches — it costs almost no context, and you can then read "
            "only the parts you need."
        ),
    )
    def convert_to_file(
        path: str,
        output_dir: str,
        recursive: bool = False,
        include_chunks: bool = False,
    ) -> str:
        """Convert a file or folder to Markdown on disk."""
        source = _resolve(path)
        destination = _resolve(output_dir)

        if source.is_file():
            targets = [source]
        elif source.is_dir():
            pattern = "**/*" if recursive else "*"
            targets = [
                p
                for p in sorted(source.glob(pattern))
                if p.is_file() and not any(part in SKIP_DIRS for part in p.parts)
            ][:MAX_BATCH_FILES]
        else:
            return f"Not found: {source}"

        if not targets:
            return f"No files to convert in {source}"

        options = ConvertOptions(chunk=include_chunks, images="placeholder")
        written: list[str] = []
        failed: list[str] = []
        used: set[str] = set()

        for target in targets:
            try:
                result = engine.convert(target, options)
            except PapyrusError as exc:
                failed.append(f"{target.name}: {exc}")
                continue

            stem = target.stem
            if stem in used:
                stem = f"{target.stem}-{target.suffix.lstrip('.')}"
            counter = 2
            while stem in used:
                stem = f"{target.stem}-{counter}"
                counter += 1
            used.add(stem)

            paths = result.write(destination, stem=stem)
            written.append(f"{target.name} -> {paths['markdown'].name} ({result.document.word_count} words)")

        lines = [f"Wrote {len(written)} file(s) to {destination}"]
        lines.extend(f"  {entry}" for entry in written[:50])
        if len(written) > 50:
            lines.append(f"  ... and {len(written) - 50} more")
        if failed:
            lines.append(f"Failed ({len(failed)}):")
            lines.extend(f"  {entry}" for entry in failed[:20])
        return "\n".join(lines)

    # ── chunks ───────────────────────────────────────────────────
    @server.tool(
        title="Convert a document to retrieval chunks",
        description=(
            "Split a document into embedding-ready chunks. Each chunk carries "
            "the heading path it sits under and the page it came from, so a "
            "retrieved fragment can still cite its source. Tables are never "
            "split from their header row and code blocks keep their fences. "
            "Returns JSON Lines; write it to disk with `save_to` for large "
            "documents."
        ),
    )
    def convert_to_chunks(
        path: str,
        chunk_size: int = 1200,
        chunk_overlap: int = 120,
        save_to: str = "",
        max_chars: int = DEFAULT_MAX_CHARS,
    ) -> str:
        """Convert a document into chunks suitable for a vector index."""
        target = _resolve(path)
        if not target.is_file():
            return f"Not a file: {target}"

        options = ConvertOptions(
            frontmatter=False,
            chunk=True,
            chunk_size=max(200, chunk_size),
            chunk_overlap=max(0, chunk_overlap),
        )
        try:
            result = engine.convert(target, options)
        except PapyrusError as exc:
            return f"Could not convert {target.name}: {exc}"

        payload = to_jsonl(result.chunks)
        tokens = sum(c.token_estimate for c in result.chunks)

        if save_to:
            out = _resolve(save_to)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(payload, encoding="utf-8")
            return (
                f"Wrote {len(result.chunks)} chunks (~{tokens:,} tokens) to {out}"
            )

        window = _cut(payload, 0, max(1000, max_chars))
        header = f"{len(result.chunks)} chunks, ~{tokens:,} tokens total\n\n"
        if window.truncated:
            return (
                header
                + window.text
                + f"\n\n[Papyrus: truncated at {window.end} of {window.total} characters. "
                f'Call again with save_to="chunks.jsonl" to write them all to disk.]'
            )
        return header + window.text

    # ── formats ──────────────────────────────────────────────────
    @server.tool(
        title="List supported formats",
        description="Every file format Papyrus can convert, and what it recovers from each.",
    )
    def list_supported_formats() -> str:
        """List the formats this server can read."""
        supported = engine.supported_formats()
        lines = [f"Papyrus {__version__} — {len(supported)} formats", ""]
        lines.extend(f"  {fmt:<10} {label}" for fmt, label in supported.items())
        lines.append("")
        lines.append(f"Maximum file size: {human_bytes(Limits().max_file_bytes)}")
        return "\n".join(lines)

    return server


def main() -> None:
    """Console entry point: `papyrus-mcp`."""
    build_server().run(transport="stdio")


if __name__ == "__main__":
    main()
