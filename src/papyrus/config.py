"""Conversion options and resource guards.

Papyrus accepts arbitrary, untrusted files. Every limit here exists to
stop a hostile or merely enormous document from taking the process down:
zip bombs, million-cell spreadsheets, 10k-page PDFs, deeply nested
archives. Defaults are generous for a laptop and safe for a server.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal

ImageMode = Literal["extract", "reference", "placeholder", "omit"]


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


@dataclass
class Limits:
    """Hard ceilings enforced during parsing."""

    max_file_bytes: int = field(default_factory=lambda: _int_env("PAPYRUS_MAX_FILE_BYTES", 50 * 1024 * 1024))
    max_pdf_pages: int = field(default_factory=lambda: _int_env("PAPYRUS_MAX_PDF_PAGES", 2000))
    max_slides: int = field(default_factory=lambda: _int_env("PAPYRUS_MAX_SLIDES", 1000))
    max_sheet_rows: int = field(default_factory=lambda: _int_env("PAPYRUS_MAX_SHEET_ROWS", 20000))
    max_sheet_cols: int = field(default_factory=lambda: _int_env("PAPYRUS_MAX_SHEET_COLS", 256))
    max_table_cells: int = field(default_factory=lambda: _int_env("PAPYRUS_MAX_TABLE_CELLS", 1_000_000))
    max_csv_rows: int = field(default_factory=lambda: _int_env("PAPYRUS_MAX_CSV_ROWS", 50000))
    max_archive_members: int = field(default_factory=lambda: _int_env("PAPYRUS_MAX_ARCHIVE_MEMBERS", 500))
    max_archive_ratio: int = field(default_factory=lambda: _int_env("PAPYRUS_MAX_ARCHIVE_RATIO", 200))
    max_archive_bytes: int = field(
        default_factory=lambda: _int_env("PAPYRUS_MAX_ARCHIVE_BYTES", 400 * 1024 * 1024)
    )
    max_recursion_depth: int = 3
    max_assets: int = field(default_factory=lambda: _int_env("PAPYRUS_MAX_ASSETS", 500))
    min_asset_bytes: int = 2048  # skip spacer gifs / bullet glyphs


@dataclass
class ConvertOptions:
    """Everything that changes what the Markdown looks like."""

    # ── Markdown shaping ─────────────────────────────────────────
    frontmatter: bool = True
    page_anchors: bool = True  # <!-- page: 3 --> comments for citation
    heading_offset: int = 0
    detect_headings: bool = True  # infer headings in unstructured sources (PDF)
    table_format: Literal["pipe", "html", "csv"] = "pipe"
    keep_page_breaks: bool = True
    wrap_width: int = 0  # 0 = no hard wrapping

    # ── Assets ───────────────────────────────────────────────────
    images: ImageMode = "reference"
    asset_dir: str = "assets"

    # ── Agent-ready extras ───────────────────────────────────────
    chunk: bool = False
    chunk_size: int = 1200  # target characters per chunk
    chunk_overlap: int = 120

    # ── Behaviour ────────────────────────────────────────────────
    ocr: bool = False
    include_hidden_sheets: bool = False
    include_speaker_notes: bool = True
    limits: Limits = field(default_factory=Limits)

    def with_(self, **kwargs: object) -> ConvertOptions:
        from dataclasses import replace

        return replace(self, **kwargs)  # type: ignore[arg-type]
