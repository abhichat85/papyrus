"""The documents that break converters in the wild.

Each test here names a specific real-world failure mode. The fixtures come
from `make_hard_fixtures.py`, which explains why each one exists.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from papyrus import Converter, ConvertOptions
from papyrus.ir import Table

HARD = Path(__file__).parent / "fixtures" / "hard"


def pytest_generate_tests(metafunc):  # pragma: no cover - collection hook
    pass


@pytest.fixture(scope="module", autouse=True)
def _fixtures():
    generator = Path(__file__).parent / "make_hard_fixtures.py"
    if not (HARD / "hard.xlsx").exists() or (HARD / "hard.xlsx").stat().st_mtime < generator.stat().st_mtime:
        subprocess.run([sys.executable, str(generator)], check=True, capture_output=True)


@pytest.fixture(scope="module")
def convert():
    return Converter().convert


def tables(doc):
    return [b.content for b in doc.blocks if isinstance(b.content, Table)]


# ══════════════════════════════════════════════════════════════════════
# Word
# ══════════════════════════════════════════════════════════════════════


def test_merged_cell_value_appears_once_not_across_the_span(convert):
    """python-docx returns one cell object per merged span.

    Reading it naively repeats the value in every column it covers, so a
    merged total of 190 shows up as two separate numbers.
    """
    table = tables(convert(HARD / "merged-cells.docx").document)[0]
    total = next(row for row in table.rows if row[0] == "Total")
    assert total[1].startswith("190")
    assert total[2] == "", f"merged value duplicated across the span: {total}"


def test_sparse_table_keeps_its_shape(convert):
    table = tables(convert(HARD / "merged-cells.docx").document)[1]
    widths = {len(row) for row in table.rows}
    assert len(widths) == 1


def test_list_nesting_depth_survives(convert):
    """Word's template defines List Bullet 2 and 3; deeper levels fall back."""
    markdown = convert(HARD / "deep-lists.docx").markdown
    assert "- Level 1 bullet" in markdown
    assert "  - Level 2 bullet" in markdown
    assert "    - Level 3 bullet" in markdown
    assert markdown.count("Level 4 bullet") == 1, "paragraph emitted twice"


def test_ordered_and_unordered_lists_do_not_merge(convert):
    doc = convert(HARD / "deep-lists.docx").document
    lists = [b for b in doc.blocks if b.type == "list"]
    kinds = {bool(b.metadata.get("ordered")) for b in lists}
    assert kinds == {True, False}, "ordered and bullet lists collapsed into one"


def test_non_latin_scripts_survive_intact(convert):
    result = convert(HARD / "unicode.docx")
    for token in ("多言語", "العربية", "Ελληνικά", "Кириллица", "🚀"):
        assert token in result.markdown, f"lost {token}"


def test_cjk_table_headers_are_promoted(convert):
    table = tables(convert(HARD / "unicode.docx").document)[0]
    assert table.header == ["列 1", "列 2"]


# ── the injection class ──────────────────────────────────────────────


def test_a_paragraph_of_backticks_cannot_open_a_code_fence(convert):
    """Document text that is itself Markdown must not become structure.

    A paragraph reading ``` would otherwise fence off the entire rest of
    the document.
    """
    body = convert(HARD / "injection.docx").markdown.split("---", 2)[2]
    assert "\\```" in body, "a bare ``` paragraph was left unescaped"
    # Nothing after it may be swallowed into a code block.
    assert "fake | table" in body


def test_a_paragraph_of_dashes_cannot_become_a_rule_or_frontmatter(convert):
    body = convert(HARD / "injection.docx").markdown.split("---", 2)[2]
    assert "\\---" in body


def test_a_paragraph_that_looks_like_a_table_row_is_escaped(convert):
    body = convert(HARD / "injection.docx").markdown.split("---", 2)[2]
    assert "\\| fake | table |" in body


def test_a_pipe_inside_a_real_table_cell_is_escaped(convert):
    markdown = convert(HARD / "injection.docx").markdown
    assert "col \\| with pipe" in markdown


def test_inline_emphasis_is_not_over_escaped(convert):
    """Escaping is for line starts only — inline syntax stays readable."""
    markdown = convert(HARD / "injection.docx").markdown
    assert "and *stars*." in markdown


# ══════════════════════════════════════════════════════════════════════
# Excel
# ══════════════════════════════════════════════════════════════════════


def test_dates_render_as_dates_not_serial_numbers(convert):
    markdown = convert(HARD / "hard.xlsx").markdown
    assert "2026-01-15" in markdown
    assert "45000" not in markdown  # the Excel serial for that date


def test_a_datetime_keeps_its_time_component(convert):
    assert "2026-02-20T14:30:00" in convert(HARD / "hard.xlsx").markdown


def test_currency_and_percent_formats_are_honoured(convert):
    markdown = convert(HARD / "hard.xlsx").markdown
    assert "$1234.50" in markdown or "$1234.5" in markdown
    assert "7.5%" in markdown
    assert "-$890" in markdown


def test_blank_rows_split_a_sheet_into_separate_tables(convert):
    doc = convert(HARD / "hard.xlsx").document
    mixed = [b for b in doc.blocks if isinstance(b.content, Table)]
    assert len(mixed) >= 3, "regions separated by blank rows were merged"


def test_uncached_formula_results_are_explained_not_silently_dropped(convert):
    """A workbook written by a script has no cached values at all."""
    warnings = convert(HARD / "hard.xlsx").warnings
    assert any("Formula results are missing" in w for w in warnings)
    assert any("Formulas" in w for w in warnings)


def test_a_clean_workbook_does_not_get_the_formula_warning(convert):
    warnings = convert(Path(__file__).parent / "fixtures" / "sample.xlsx").warnings
    assert not any("Formula results" in w for w in warnings)


def test_a_wide_sheet_stays_rectangular(convert):
    wide = next(
        t for t in tables(convert(HARD / "hard.xlsx").document) if (t.header or [""])[0] == "col1"
    )
    assert len(wide.header) == 39
    assert all(len(row) == 39 for row in wide.rows)


# ══════════════════════════════════════════════════════════════════════
# PowerPoint
# ══════════════════════════════════════════════════════════════════════


def test_shapes_are_read_top_to_bottom_not_in_insertion_order(convert):
    """The bottom box was added to the slide first."""
    markdown = convert(HARD / "hard.pptx").markdown
    top = markdown.index("sits at the top")
    bottom = markdown.index("sits at the bottom")
    assert top < bottom


def test_side_by_side_boxes_read_left_then_right(convert):
    markdown = convert(HARD / "hard.pptx").markdown
    assert markdown.index("Left column") < markdown.index("Right column")


def test_an_empty_slide_still_gets_a_page_marker(convert):
    doc = convert(HARD / "hard.pptx").document
    assert len([b for b in doc.blocks if b.type == "page_break"]) == 4


# ══════════════════════════════════════════════════════════════════════
# PDF
# ══════════════════════════════════════════════════════════════════════


def test_two_columns_are_not_interleaved_line_by_line(convert):
    """The failure mode is 'The first column begins here and / The second
    column continues the' — alternating between columns every line."""
    doc = convert(HARD / "two-column.pdf").document
    paragraphs = [str(b.content) for b in doc.blocks if b.type == "paragraph"]
    left = next((p for p in paragraphs if "first column" in p), "")
    assert "continues for several lines" in left
    assert "second column" not in left


def test_a_rotated_page_still_yields_its_text(convert):
    markdown = convert(HARD / "two-column.pdf").markdown
    assert "Rotated content heading" in markdown
    assert "Body text on a rotated page" in markdown


def test_a_scanned_pdf_says_so_instead_of_returning_nothing(convert):
    result = convert(HARD / "scanned.pdf")
    assert any("scanned" in w.lower() for w in result.warnings)
    assert any("OCR" in w for w in result.warnings)


# ══════════════════════════════════════════════════════════════════════
# Text-shaped formats
# ══════════════════════════════════════════════════════════════════════


def test_bom_crlf_and_semicolons_are_all_handled(convert):
    result = convert(HARD / "bom-crlf.csv")
    table = tables(result.document)[0]
    assert (table.header or [])[:3] == ["name", "note", "amount"]
    assert "﻿" not in result.markdown, "byte-order mark leaked into the output"


def test_an_overlong_row_keeps_its_extra_field(convert):
    """One row has a fourth value. Dropping it would be quiet data loss, so
    the table widens and the header gains an empty cell instead."""
    table = tables(convert(HARD / "bom-crlf.csv").document)[0]
    assert any("extra" in cell for row in table.rows for cell in row)


def test_a_quoted_newline_stays_inside_its_cell(convert):
    markdown = convert(HARD / "bom-crlf.csv").markdown
    assert "line one<br>line two" in markdown


def test_ragged_rows_do_not_break_the_table(convert):
    table = tables(convert(HARD / "bom-crlf.csv").document)[0]
    widths = {len(row) for row in table.rows}
    assert len(widths) == 1


def test_latin1_bytes_decode_without_replacement_characters(convert):
    markdown = convert(HARD / "latin1.csv").markdown
    assert "Zürich" in markdown
    assert "René" in markdown
    assert "�" not in markdown


def test_a_single_column_csv_is_still_a_table(convert):
    doc = convert(HARD / "single-column.csv").document
    assert any(isinstance(b.content, Table) for b in doc.blocks)


def test_deeply_nested_json_becomes_nested_headings(convert):
    markdown = convert(HARD / "deep.json").markdown
    assert "レベル1" in markdown
    assert "bottom" in markdown
    assert "###" in markdown


def test_a_mixed_json_array_does_not_become_a_broken_table(convert):
    """[{a:1}, {b:2}, "string", 42, null, true] is not tabular."""
    markdown = convert(HARD / "deep.json").markdown
    assert "42" in markdown


def test_malformed_html_still_yields_its_content(convert):
    markdown = convert(HARD / "messy.html").markdown
    assert "Second paragraph" in markdown
    assert "Trailing text" in markdown
    assert "&amp;" not in markdown, "entities should be decoded"


def test_nested_html_tables_do_not_produce_a_ragged_table(convert):
    for table in tables(convert(HARD / "messy.html").document):
        widths = {len(row) for row in table.rows}
        assert len(widths) <= 1


def test_html_definition_lists_survive(convert):
    markdown = convert(HARD / "messy.html").markdown
    assert "Term" in markdown and "Definition" in markdown


def test_existing_frontmatter_is_recorded_not_duplicated(convert):
    result = convert(HARD / "with-frontmatter.md")
    assert result.document.metadata["source_frontmatter"]["title"] == "Existing Doc"
    assert result.markdown.count("# Existing Doc") == 1


def test_a_repetitive_log_converts_without_blowing_up(convert):
    result = convert(HARD / "server.log")
    assert result.document.word_count > 100


def test_whitespace_only_file_warns_rather_than_raising(convert):
    result = convert(HARD / "whitespace.txt")
    assert result.warnings
    assert result.document.blocks == []


def test_a_mixed_archive_converts_every_readable_member(convert):
    result = convert(HARD / "mixed.zip", ConvertOptions(chunk=False))
    markdown = result.markdown
    assert "Top level readme" in markdown
    assert "alpha" in markdown
    assert "def main()" in markdown
    assert "Quarterly Web Page" in markdown
    assert "Body text of the page" in markdown


def test_a_nested_archive_is_converted_not_skipped(convert):
    assert "One level down" in convert(HARD / "mixed.zip").markdown


def test_a_binary_member_is_reported_not_dumped(convert):
    markdown = convert(HARD / "mixed.zip").markdown
    assert "binary.dat" in markdown
    assert "\x00" not in markdown
