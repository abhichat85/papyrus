"""Properties that must hold for every format, on every fixture.

The per-format tests in `test_parsers.py` check that each parser recovers
what it should. This file checks the things that must be true *regardless*
of format — the contract a downstream consumer relies on. A new parser
gets this whole suite for free the moment its fixture lands in the
directory, which is the point.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from papyrus import Converter, ConvertOptions, MarkdownRenderer, chunk_document
from papyrus.errors import PapyrusError

sys.path.insert(0, str(Path(__file__).parent))
from markdown_checks import check, tables_of

FIXTURES = Path(__file__).parent / "fixtures"
HARD = FIXTURES / "hard"


def _ensure_hard() -> None:
    generator = Path(__file__).parent / "make_hard_fixtures.py"
    marker = HARD / "hard.xlsx"
    if not marker.exists() or marker.stat().st_mtime < generator.stat().st_mtime:
        subprocess.run([sys.executable, str(generator)], check=True, capture_output=True)


_ensure_hard()

EASY = sorted(p for p in FIXTURES.glob("sample.*") if p.is_file())
NASTY = sorted(p for p in HARD.iterdir() if p.is_file())
EVERY = EASY + NASTY

assert len(EASY) >= 16, "clean fixtures missing — run tests/make_fixtures.py"
assert len(NASTY) >= 15, "hard fixtures missing — run tests/make_hard_fixtures.py"


def ids(paths: list[Path]) -> list[str]:
    return [p.parent.name + "/" + p.name if p.parent.name == "hard" else p.name for p in paths]


@pytest.fixture(scope="module")
def converter() -> Converter:
    return Converter()


# ══════════════════════════════════════════════════════════════════════
# Every fixture, every invariant
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("path", EVERY, ids=ids(EVERY))
def test_conversion_never_raises(converter, path):
    """The whole promise: any file in, something useful out."""
    result = converter.convert(path)
    assert isinstance(result.markdown, str)


@pytest.mark.parametrize("path", EVERY, ids=ids(EVERY))
def test_markdown_is_structurally_valid(converter, path):
    """Tables rectangular, fences balanced, headings well-formed."""
    report = check(converter.convert(path).markdown)
    assert report.ok, f"{path.name} produced invalid Markdown:\n{report}"


@pytest.mark.parametrize("path", EVERY, ids=ids(EVERY))
def test_output_has_no_control_characters(converter, path):
    markdown = converter.convert(path).markdown
    assert "\x00" not in markdown
    assert "\r" not in markdown, "CRLF must be normalised"


@pytest.mark.parametrize("path", EVERY, ids=ids(EVERY))
def test_output_ends_with_exactly_one_newline(converter, path):
    markdown = converter.convert(path).markdown
    if markdown:
        assert markdown.endswith("\n")
        assert not markdown.endswith("\n\n")


@pytest.mark.parametrize("path", EVERY, ids=ids(EVERY))
def test_frontmatter_is_valid_yaml_with_provenance(converter, path):
    markdown = converter.convert(path).markdown
    assert markdown.startswith("---\n")
    block = markdown.split("---", 2)[1]
    data = yaml.safe_load(block)
    assert isinstance(data, dict)
    assert len(data["source"]["sha256"]) == 64
    assert data["source"]["filename"] == path.name
    assert data["converted_by"] == "papyrus"


@pytest.mark.parametrize("path", EVERY, ids=ids(EVERY))
def test_conversion_is_deterministic(converter, path):
    """Same bytes in, same Markdown out — modulo the timestamp."""
    options = ConvertOptions(frontmatter=False)
    first = converter.convert(path, options).markdown
    second = converter.convert(path, options).markdown
    assert first == second


@pytest.mark.parametrize("path", EVERY, ids=ids(EVERY))
def test_ir_round_trips_through_json(converter, path):
    """The IR must serialise — it is the debugging and interchange surface."""
    document = converter.convert(path).document
    payload = json.loads(document.to_json())
    assert payload["source"]["filename"] == path.name
    assert isinstance(payload["blocks"], list)
    for block in payload["blocks"]:
        assert block["type"]
        if block["type"] == "table":
            assert isinstance(block["content"]["rows"], list)


@pytest.mark.parametrize("path", EVERY, ids=ids(EVERY))
def test_rendering_the_ir_twice_is_stable(converter, path):
    document = converter.convert(path).document
    renderer = MarkdownRenderer(ConvertOptions(frontmatter=False))
    assert renderer.render(document) == renderer.render(document)


@pytest.mark.parametrize("path", EVERY, ids=ids(EVERY))
def test_tables_are_rectangular_after_parsing_back(converter, path):
    """Re-parse the emitted tables: every row must have the header's width."""
    for table in tables_of(converter.convert(path).markdown):
        widths = {len(row) for row in table}
        assert len(widths) == 1, f"{path.name}: ragged table widths {widths}"


@pytest.mark.parametrize("path", EVERY, ids=ids(EVERY))
def test_chunks_cover_the_document_without_empties(converter, path):
    result = converter.convert(path, ConvertOptions(chunk=True, chunk_size=600))
    for chunk in result.chunks:
        assert chunk.text.strip(), "empty chunk emitted"
        assert chunk.token_estimate > 0
        assert chunk.id
    ids_seen = [c.id for c in result.chunks]
    assert len(set(ids_seen)) == len(ids_seen), "duplicate chunk ids"


@pytest.mark.parametrize("path", EVERY, ids=ids(EVERY))
def test_chunk_text_is_structurally_valid_markdown(converter, path):
    """A chunk is fed to a model on its own, so it must stand alone."""
    result = converter.convert(path, ConvertOptions(chunk=True, chunk_size=600))
    for chunk in result.chunks:
        report = check(chunk.text)
        assert report.ok, f"{path.name} chunk {chunk.index} invalid:\n{report}"


@pytest.mark.parametrize("path", EVERY, ids=ids(EVERY))
def test_options_never_break_the_output(converter, path):
    """Every rendering option must still produce valid Markdown."""
    for options in (
        ConvertOptions(frontmatter=False),
        ConvertOptions(page_anchors=False),
        ConvertOptions(table_format="html"),
        ConvertOptions(table_format="csv"),
        ConvertOptions(images="omit"),
        ConvertOptions(images="placeholder"),
        ConvertOptions(heading_offset=2),
        ConvertOptions(wrap_width=72),
    ):
        markdown = converter.convert(path, options).markdown
        if options.table_format == "pipe":
            assert check(markdown).ok, f"{path.name} broke with {options}"


@pytest.mark.parametrize("path", EVERY, ids=ids(EVERY))
def test_no_frontmatter_option_removes_it_entirely(converter, path):
    markdown = converter.convert(path, ConvertOptions(frontmatter=False)).markdown
    assert not markdown.startswith("---\ntitle:")


@pytest.mark.parametrize("path", EVERY, ids=ids(EVERY))
def test_heading_offset_never_exceeds_six(converter, path):
    markdown = converter.convert(path, ConvertOptions(heading_offset=5)).markdown
    for line in markdown.split("\n"):
        if line.startswith("#"):
            assert len(line) - len(line.lstrip("#")) <= 6


# ══════════════════════════════════════════════════════════════════════
# Round trip: our own output must survive re-ingestion
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("path", EVERY, ids=ids(EVERY))
def test_output_survives_being_converted_again(converter, path):
    """Feed Papyrus its own Markdown back. It must come out unchanged.

    A converter whose output it cannot itself read is a converter that
    produces something other than Markdown.
    """
    options = ConvertOptions(frontmatter=False)
    once = converter.convert(path, options).markdown
    if not once.strip():
        pytest.skip("nothing to re-ingest")
    twice = converter.convert_bytes(once.encode(), "round-trip.md", options).markdown
    assert twice.strip() == once.strip()


# ══════════════════════════════════════════════════════════════════════
# Truncation fuzzing: every prefix of every file
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("path", EVERY, ids=ids(EVERY))
def test_truncated_files_fail_cleanly_at_every_prefix(converter, path):
    """Cut each file at ten points. Every one is a PapyrusError or a result.

    Never an IndexError, never a UnicodeDecodeError, never a hang.
    """
    data = path.read_bytes()
    for fraction in range(1, 11):
        prefix = data[: len(data) * fraction // 11]
        if not prefix:
            continue
        try:
            result = converter.convert_bytes(prefix, path.name)
        except PapyrusError:
            continue
        assert isinstance(result.markdown, str)
        if result.document.metadata.get("passthrough"):
            # Markdown in, Markdown out is verbatim by design. Half a
            # Markdown file is half a table, and repairing the user's own
            # content would be a worse answer than passing it through.
            continue
        assert check(result.markdown).ok, f"{path.name} at {fraction}/11 produced bad Markdown"


@pytest.mark.parametrize("path", EASY, ids=ids(EASY))
def test_byte_flips_never_crash_the_engine(converter, path):
    """Corrupt one byte at a time in the header region."""
    data = bytearray(path.read_bytes())
    for offset in range(0, min(len(data), 64), 7):
        mutated = bytearray(data)
        mutated[offset] ^= 0xFF
        try:
            result = converter.convert_bytes(bytes(mutated), path.name)
        except PapyrusError:
            continue
        assert isinstance(result.markdown, str)


# ══════════════════════════════════════════════════════════════════════
# Chunking properties, independent of format
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("size", [250, 600, 1500, 4000])
@pytest.mark.parametrize("path", EASY, ids=ids(EASY))
def test_chunking_holds_at_every_size(converter, path, size):
    document = converter.convert(path).document
    chunks = chunk_document(document, ConvertOptions(chunk_size=size, chunk_overlap=size // 10))
    for chunk in chunks:
        assert check(chunk.text).ok
        assert chunk.heading_path == [] or all(isinstance(h, str) for h in chunk.heading_path)
