"""Per-format behaviour.

These assert on *structure* — that a table is a table and a heading kept
its level — rather than on exact strings, so a wording change in a
fixture does not break the suite while a structural regression does.
"""

from __future__ import annotations

import pytest

from papyrus.ir import Table

ALL_FIXTURES = [
    "sample.csv",
    "sample.docx",
    "sample.eml",
    "sample.html",
    "sample.ipynb",
    "sample.json",
    "sample.jsonl",
    "sample.md",
    "sample.pdf",
    "sample.pptx",
    "sample.py",
    "sample.rtf",
    "sample.tsv",
    "sample.txt",
    "sample.xlsx",
    "sample.zip",
]


def _types(doc):
    return [b.type for b in doc.blocks]


def _tables(doc):
    return [b.content for b in doc.blocks if isinstance(b.content, Table)]


@pytest.mark.parametrize("name", ALL_FIXTURES)
def test_every_fixture_converts_to_non_empty_markdown(convert, fixtures, name):
    result = convert(fixtures / name)
    assert result.markdown.strip(), f"{name} produced no Markdown"
    assert result.markdown.endswith("\n")


@pytest.mark.parametrize("name", ALL_FIXTURES)
def test_frontmatter_carries_provenance(convert, fixtures, name):
    result = convert(fixtures / name)
    assert result.markdown.startswith("---\n")
    assert result.document.source.sha256
    assert result.document.source.sha256 in result.markdown


# ── Word ─────────────────────────────────────────────────────────────


def test_docx_keeps_heading_levels_and_inline_emphasis(convert, fixtures):
    result = convert(fixtures / "sample.docx")
    levels = [b.level for b in result.document.blocks if b.type == "heading"]
    assert levels == [1, 2, 2]
    assert "**41%**" in result.markdown
    assert "_conservative_" in result.markdown


def test_docx_table_lands_between_its_neighbours(convert, fixtures):
    """Document order, not `paragraphs` then `tables`."""
    types = _types(convert(fixtures / "sample.docx").document)
    assert types.index("table") < types.index("paragraph", types.index("table") - 1) + 2
    assert types[-1] == "paragraph"  # the closing line follows the table


def test_docx_promotes_the_header_row(convert, fixtures):
    table = _tables(convert(fixtures / "sample.docx").document)[0]
    assert table.header == ["Metric", "2024", "2025"]
    assert table.rows[0][0] == "Revenue"


def test_docx_bullets_become_one_list(convert, fixtures):
    doc = convert(fixtures / "sample.docx").document
    lists = [b for b in doc.blocks if b.type == "list"]
    assert len(lists) == 1
    assert len(lists[0].content) == 3


def test_docx_list_depth_comes_from_the_style_name(convert, fixtures):
    """ "List Bullet 2" is one level in, even with no numbering definition."""
    doc = convert(fixtures / "sample.docx").document
    items = next(b for b in doc.blocks if b.type == "list").content
    assert items[0].children, "sub-bullet was flattened to the top level"
    assert items[0].children[0].text == "Driven by two expansions"
    assert "  - Driven by two expansions" in convert(fixtures / "sample.docx").markdown


# ── PowerPoint ───────────────────────────────────────────────────────


def test_pptx_emits_one_heading_and_page_marker_per_slide(convert, fixtures):
    doc = convert(fixtures / "sample.pptx").document
    assert doc.metadata["slides"] == 3
    assert len([b for b in doc.blocks if b.type == "page_break"]) == 3
    assert [b.metadata.get("page") for b in doc.blocks if b.type == "page_break"] == [1, 2, 3]


def test_pptx_preserves_bullet_nesting(convert, fixtures):
    doc = convert(fixtures / "sample.pptx").document
    lists = [b for b in doc.blocks if b.type == "list"]
    assert any(item.children for block in lists for item in block.content)


def test_pptx_includes_speaker_notes(convert, fixtures):
    assert "Speaker notes" in convert(fixtures / "sample.pptx").markdown


def test_pptx_speaker_notes_can_be_suppressed(convert_bytes, fixtures):
    from papyrus import ConvertOptions

    data = (fixtures / "sample.pptx").read_bytes()
    result = convert_bytes(data, "d.pptx", ConvertOptions(include_speaker_notes=False))
    assert "Speaker notes" not in result.markdown


# ── Excel ────────────────────────────────────────────────────────────


def test_xlsx_renders_each_sheet_under_its_own_heading(convert, fixtures):
    result = convert(fixtures / "sample.xlsx")
    assert "## Sheet: Revenue" in result.markdown
    assert "## Sheet: Expenses" in result.markdown


def test_xlsx_hidden_sheet_is_skipped_and_reported(convert, fixtures):
    """The contents stay out, but the frontmatter still admits it exists."""
    result = convert(fixtures / "sample.xlsx")
    assert "## Sheet: Scratch" not in result.markdown
    assert "do not read" not in result.markdown
    assert any("hidden" in w for w in result.warnings)


def test_xlsx_hidden_sheet_can_be_opted_into(convert_bytes, fixtures):
    from papyrus import ConvertOptions

    data = (fixtures / "sample.xlsx").read_bytes()
    result = convert_bytes(data, "b.xlsx", ConvertOptions(include_hidden_sheets=True))
    assert "Scratch" in result.markdown


def test_xlsx_respects_number_formats(convert, fixtures):
    """0.05 formatted as a percentage must not render as 0.05."""
    markdown = convert(fixtures / "sample.xlsx").markdown
    assert "5%" in markdown and "0.05" not in markdown
    assert "$100000" in markdown


def test_xlsx_puts_the_minus_outside_the_currency_symbol(convert, fixtures):
    markdown = convert(fixtures / "sample.xlsx").markdown
    assert "-$120000" in markdown
    assert "$-120000" not in markdown


def test_xlsx_splits_regions_on_blank_rows(convert, fixtures):
    doc = convert(fixtures / "sample.xlsx").document
    assert any(b.type == "paragraph" and "unaudited" in str(b.content) for b in doc.blocks)


# ── PDF ──────────────────────────────────────────────────────────────


def test_pdf_infers_headings_from_font_size(convert, fixtures):
    doc = convert(fixtures / "sample.pdf").document
    headings = [(b.level, b.content) for b in doc.blocks if b.type == "heading"]
    assert "Annual Report" in [h[1] for h in headings]
    assert min(h[0] for h in headings) < max(h[0] for h in headings)


def test_pdf_drops_running_headers_and_page_numbers(convert, fixtures):
    result = convert(fixtures / "sample.pdf")
    assert "Confidential" not in result.markdown
    assert result.document.metadata["removed_running_text"]


def test_pdf_emits_page_anchors_for_citation(convert, fixtures):
    markdown = convert(fixtures / "sample.pdf").markdown
    assert "<!-- papyrus:page 1 -->" in markdown
    assert "<!-- papyrus:page 2 -->" in markdown


def test_pdf_reflows_wrapped_lines_into_paragraphs(convert, fixtures):
    doc = convert(fixtures / "sample.pdf").document
    paragraphs = [str(b.content) for b in doc.blocks if b.type == "paragraph"]
    assert any("year over year, ahead of the conservative plan" in p for p in paragraphs)


def test_pdf_table_lands_inside_its_own_section(convert, fixtures):
    """Text and tables are extracted separately; they must still interleave.

    The table belongs under "Financials" and above "Notes". Appending it at
    the end of the page would silently file it under the wrong heading.
    """
    blocks = convert(fixtures / "sample.pdf").document.blocks

    def index_of(kind: str, text: str | None = None) -> int:
        return next(i for i, b in enumerate(blocks) if b.type == kind and (text is None or b.content == text))

    assert index_of("heading", "Financials") < index_of("table") < index_of("heading", "Notes")


def test_pdf_recognises_bullets(convert, fixtures):
    doc = convert(fixtures / "sample.pdf").document
    lists = [b for b in doc.blocks if b.type == "list"]
    assert lists and len(lists[0].content) == 3


# ── HTML ─────────────────────────────────────────────────────────────


def test_html_drops_chrome_and_keeps_main(convert, fixtures):
    markdown = convert(fixtures / "sample.html").markdown
    assert "skip me" not in markdown
    assert "Intro with" in markdown


def test_html_preserves_links_emphasis_and_code_language(convert, fixtures):
    markdown = convert(fixtures / "sample.html").markdown
    assert "[a link](https://example.com)" in markdown
    assert "**bold**" in markdown
    assert "```python" in markdown


def test_html_keeps_nested_list_structure(convert, fixtures):
    doc = convert(fixtures / "sample.html").document
    lists = [b for b in doc.blocks if b.type == "list"]
    assert lists[0].content[0].children[0].text == "nested"


def test_html_th_becomes_the_table_header(convert, fixtures):
    assert _tables(convert(fixtures / "sample.html").document)[0].header == ["K", "V"]


# ── data formats ─────────────────────────────────────────────────────


def test_csv_becomes_a_table_with_a_header(convert, fixtures):
    table = _tables(convert(fixtures / "sample.csv").document)[0]
    assert table.header == ["Month", "Revenue", "Growth"]
    assert len(table.rows) == 3


def test_tsv_delimiter_is_detected(convert, fixtures):
    assert convert(fixtures / "sample.tsv").document.metadata["delimiter"] == "tab"


def test_json_array_of_objects_becomes_a_table(convert, fixtures):
    tables = _tables(convert(fixtures / "sample.json").document)
    assert tables and tables[0].header == ["file", "ms", "pages"]


def test_json_scalars_become_key_values(convert, fixtures):
    doc = convert(fixtures / "sample.json").document
    kv = [b for b in doc.blocks if b.type == "key_values"]
    assert kv and kv[0].content["product"] == "Papyrus"


def test_invalid_json_degrades_to_a_code_block(convert_bytes):
    result = convert_bytes(b'{"broken": ', "bad.json")
    assert result.document.blocks[0].type == "code"
    assert any("Invalid JSON" in w for w in result.warnings)


def test_jsonl_records_become_a_table(convert, fixtures):
    assert _tables(convert(fixtures / "sample.jsonl").document)[0].header == ["id", "name"]


# ── text-ish ─────────────────────────────────────────────────────────


def test_markdown_passes_through_without_a_duplicate_title(convert, fixtures):
    result = convert(fixtures / "sample.md")
    assert result.markdown.count("# Title") == 1
    assert result.document.title == "Title"


def test_code_is_fenced_with_its_language(convert, fixtures):
    result = convert(fixtures / "sample.py")
    assert "```python" in result.markdown
    assert result.document.metadata["language"] == "python"


def test_plain_text_gains_structure(convert, fixtures):
    doc = convert(fixtures / "sample.txt").document
    assert doc.title == "PROJECT BRIEF"
    assert any(b.type == "list" for b in doc.blocks)


def test_rtf_recovers_text_and_emphasis(convert, fixtures):
    markdown = convert(fixtures / "sample.rtf").markdown
    assert "**bold**" in markdown
    assert "Second paragraph" in markdown
    assert "\\rtf" not in markdown


def test_eml_keeps_headers_and_body(convert, fixtures):
    result = convert(fixtures / "sample.eml")
    assert result.document.title == "Launch plan"
    assert "alice@example.com" in result.markdown
    assert "ship Monday" in result.markdown


def test_notebook_renders_code_and_output(convert, fixtures):
    result = convert(fixtures / "sample.ipynb")
    assert "```python" in result.markdown
    assert "print('hello')" in result.markdown
    assert result.document.metadata["language"] == "python"


# ── archives ─────────────────────────────────────────────────────────


def test_zip_converts_every_member(convert, fixtures):
    result = convert(fixtures / "sample.zip")
    assert result.document.metadata["converted"] == 2
    assert "Inside the archive" in result.markdown
    assert "| a | b |" in result.markdown


def test_zip_ignores_platform_junk(convert, fixtures):
    assert "__MACOSX" not in convert(fixtures / "sample.zip").markdown


def test_zip_demotes_member_headings(convert, fixtures):
    """A member's H1 must not compete with the archive's own structure."""
    markdown = convert(fixtures / "sample.zip").markdown
    assert "### Notes" in markdown
    assert "\n# Notes" not in markdown
