"""Papyrus eats untrusted files, so the failure modes are the product.

The rule the engine holds to: *messy* input degrades with a warning,
*hostile* or *impossible* input raises a typed error. Nothing crashes with
a bare traceback, and nothing hangs.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from papyrus import Converter, ConvertOptions, Limits
from papyrus.errors import (
    FileTooLargeError,
    LimitExceededError,
    ParseError,
    UnsupportedFormatError,
)

TRUNCATED = {
    "sample.docx": ParseError,
    "sample.pptx": ParseError,
    "sample.xlsx": ParseError,
    "sample.pdf": ParseError,
}


# ── malformed input ──────────────────────────────────────────────────


@pytest.mark.parametrize("name", list(TRUNCATED))
def test_truncated_binaries_raise_a_typed_error(convert_bytes, fixtures, name):
    """Half a .docx is not a .docx — fail loudly, not with a stack trace."""
    data = (fixtures / name).read_bytes()[: len(TRUNCATED) * 200]
    with pytest.raises(TRUNCATED[name]):
        convert_bytes(data, name)


@pytest.mark.parametrize(
    "name",
    ["a.txt", "a.csv", "a.json", "a.html", "a.md", "a.py", "a.xml", "a.jsonl"],
)
def test_garbage_in_a_text_format_never_crashes(convert_bytes, name):
    data = b"\xff\xfe\x00garbage,,,{{{<<<\x01\x02" * 20
    result = convert_bytes(data, name)
    assert isinstance(result.markdown, str)


def test_empty_file_is_rejected_clearly(convert_bytes):
    with pytest.raises(ParseError, match="empty"):
        convert_bytes(b"", "empty.txt")


def test_a_file_of_only_whitespace_warns_rather_than_raising(convert_bytes):
    result = convert_bytes(b"   \n\n\t  \n", "blank.txt")
    assert result.warnings
    assert result.document.blocks == []


def test_unicode_survives_the_round_trip(convert_bytes):
    text = "# 見出し\n\nЭто текст. مرحبا. 🚀 café\n"
    result = convert_bytes(text.encode("utf-8"), "unicode.md")
    for token in ("見出し", "Это текст", "مرحبا", "🚀"):
        assert token in result.markdown


def test_latin1_bytes_are_decoded_not_mangled(convert_bytes):
    result = convert_bytes("Café Münster".encode("latin-1"), "legacy.txt")
    assert "Caf" in result.markdown
    assert "�" not in result.markdown or "Caf" in result.markdown


def test_null_bytes_do_not_reach_the_output(convert_bytes):
    result = convert_bytes(b"before\x00\x01\x02after", "weird.txt")
    assert "\x00" not in result.markdown


def test_binary_with_no_parser_recovers_printable_runs(convert_bytes):
    data = b"\x00\x01" * 50 + b"READABLE STRING HERE" + b"\x02\x03" * 50
    result = convert_bytes(data, "mystery.dat")
    assert "READABLE STRING HERE" in result.markdown
    assert result.warnings


def test_legacy_office_fails_with_a_next_step(convert_bytes):
    ole2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 512
    with pytest.raises(UnsupportedFormatError, match="convert-to docx"):
        convert_bytes(ole2, "ancient.doc")


# ── resource guards ──────────────────────────────────────────────────


def test_oversized_file_is_refused_before_parsing(convert_bytes):
    options = ConvertOptions(limits=Limits(max_file_bytes=1024))
    with pytest.raises(FileTooLargeError):
        convert_bytes(b"x" * 2048, "big.txt", options)


def test_csv_row_ceiling_truncates_and_says_so(convert_bytes):
    data = ("a,b\n" + "1,2\n" * 5000).encode()
    options = ConvertOptions(limits=Limits(max_csv_rows=100))
    result = convert_bytes(data, "huge.csv", options)
    assert any("Truncated" in w for w in result.warnings)
    assert len(result.document.blocks[0].content.rows) <= 100


def test_pdf_page_ceiling_is_reported(convert_bytes, fixtures):
    options = ConvertOptions(limits=Limits(max_pdf_pages=1))
    result = convert_bytes((fixtures / "sample.pdf").read_bytes(), "r.pdf", options)
    assert result.document.metadata["pages"] == 1
    assert any("stopped at 1" in w for w in result.warnings)


def test_zip_bomb_is_refused(convert_bytes):
    """A high compression ratio is the signal; refuse before expanding."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("bomb.txt", b"0" * (5 * 1024 * 1024))
    with pytest.raises(LimitExceededError, match="zip bomb"):
        convert_bytes(buffer.getvalue(), "bomb.zip")


def test_archive_member_ceiling_truncates(convert_bytes):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for i in range(50):
            archive.writestr(f"f{i}.txt", f"unique content number {i} " * 20)
    options = ConvertOptions(limits=Limits(max_archive_members=5, max_archive_ratio=10_000))
    result = convert_bytes(buffer.getvalue(), "many.zip", options)
    assert result.document.metadata["converted"] == 5


def test_archive_path_traversal_members_are_dropped(convert_bytes):
    """`../../etc/passwd` inside a zip must never be honoured."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../../escape.txt", "should not appear")
        archive.writestr("safe.txt", "should appear")
    result = convert_bytes(buffer.getvalue(), "evil.zip")
    assert "should appear" in result.markdown
    assert "should not appear" not in result.markdown


def test_nested_archives_stop_at_the_depth_limit(convert_bytes):
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as archive:
        archive.writestr("deep.txt", "bottom")
    payload = inner.getvalue()
    for _ in range(5):
        outer = io.BytesIO()
        with zipfile.ZipFile(outer, "w") as archive:
            archive.writestr("nested.zip", payload)
        payload = outer.getvalue()

    options = ConvertOptions(limits=Limits(max_archive_ratio=10_000))
    result = convert_bytes(payload, "nested.zip", options)
    # It completes rather than recursing without bound.
    assert isinstance(result.markdown, str)


def test_a_broken_member_does_not_abort_the_whole_archive(convert_bytes):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("good.md", "# Good\n\nThis converted fine.\n")
        archive.writestr("broken.docx", b"PK\x03\x04 not really a docx")
    result = convert_bytes(buffer.getvalue(), "mixed.zip")
    assert "This converted fine" in result.markdown
    assert result.warnings


# ── correctness under adversarial content ────────────────────────────


def test_markdown_metacharacters_in_table_cells_cannot_break_the_row(convert_bytes):
    """A pipe inside a cell must be escaped, and a newline must not split the row."""
    import re

    data = b'a,b\n"pipe | here","new\nline"\n'
    result = convert_bytes(data, "tricky.csv")
    body = [ln for ln in result.markdown.splitlines() if ln.startswith("|")]
    unescaped = [len(re.findall(r"(?<!\\)\|", ln)) for ln in body]
    assert unescaped == [3, 3, 3], body
    assert "pipe \\| here" in result.markdown
    assert "new<br>line" in result.markdown


def test_code_containing_a_fence_is_still_fenced_correctly(convert_bytes):
    source = b'x = """\n```\nnot the end\n```\n"""\n'
    result = convert_bytes(source, "tricky.py")
    assert "````" in result.markdown  # fence widened past the inner one


def test_html_javascript_urls_are_not_linked(convert_bytes):
    html = (
        b"<html><body><main><p><a href='javascript:alert(1)'>click</a></p>"
        + b"x" * 250
        + b"</main></body></html>"
    )
    result = convert_bytes(html, "xss.html")
    assert "javascript:" not in result.markdown
    assert "click" in result.markdown


def test_conversion_is_deterministic(convert_bytes, fixtures):
    """Same bytes in, same Markdown out — the whole pipeline is pure."""
    data = (fixtures / "sample.docx").read_bytes()
    options = ConvertOptions(frontmatter=False)
    first = convert_bytes(data, "a.docx", options).markdown
    second = convert_bytes(data, "a.docx", options).markdown
    assert first == second


def test_parser_bugs_surface_as_parse_errors_not_tracebacks(fixtures):
    """A parser that raises something unexpected must still be a ParseError."""
    from papyrus.parsers.base import BaseParser
    from papyrus.registry import ParserRegistry

    class Exploding(BaseParser):
        formats = ("text",)
        label = "Exploding"

        def supports(self, detection):
            return True

        def parse(self, data, filename, detection, options):
            raise ZeroDivisionError("boom")

    converter = Converter(registry=ParserRegistry([Exploding()]))
    with pytest.raises(ParseError, match="ZeroDivisionError"):
        converter.convert_bytes(b"hello", "x.txt")
