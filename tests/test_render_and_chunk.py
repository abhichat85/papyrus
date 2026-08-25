"""Rendering and chunking — the half that makes the output agent-ready."""

from __future__ import annotations

import json

import pytest

from papyrus import ConvertOptions, MarkdownRenderer
from papyrus.chunking import chunk_document, to_jsonl
from papyrus.ir import (
    Document,
    ListItem,
    SourceInfo,
    code,
    heading,
    list_block,
    page_break,
    paragraph,
    table,
)


def _doc(*blocks, title="Doc") -> Document:
    doc = Document(source=SourceInfo(filename="d.txt", format="text"), title=title)
    doc.extend(list(blocks))
    return doc


def render(doc, **kwargs) -> str:
    return MarkdownRenderer(ConvertOptions(frontmatter=False, **kwargs)).render(doc)


# ── rendering ────────────────────────────────────────────────────────


def test_headings_render_at_their_level():
    out = render(_doc(heading("A", 1), heading("B", 3)))
    assert "# A" in out and "### B" in out


def test_heading_offset_shifts_the_whole_document():
    out = render(_doc(heading("A", 1)), heading_offset=2)
    assert "### A" in out


def test_nested_lists_indent_by_two_spaces():
    items = [ListItem("top", [ListItem("child", [ListItem("grandchild")])])]
    out = render(_doc(list_block(items)))
    assert "- top" in out
    assert "  - child" in out
    assert "    - grandchild" in out


def test_ordered_lists_number_sequentially():
    out = render(_doc(list_block([ListItem("a"), ListItem("b")], ordered=True)))
    assert "1. a" in out and "2. b" in out


def test_task_items_render_as_checkboxes():
    items = [ListItem("done", checked=True), ListItem("todo", checked=False)]
    out = render(_doc(list_block(items)))
    assert "- [x] done" in out and "- [ ] todo" in out


def test_numeric_columns_are_right_aligned():
    out = render(_doc(table([["a", "1"], ["b", "2"]], header=["name", "count"])))
    assert "| --- | ---: |" in out


def test_ragged_rows_are_padded_so_the_table_stays_valid():
    out = render(_doc(table([["a"], ["b", "c"]], header=["x", "y"])))
    rows = [ln for ln in out.splitlines() if ln.startswith("|")]
    assert all(ln.count("|") == 3 for ln in rows)


@pytest.mark.parametrize(
    ("fmt", "needle"),
    [("pipe", "| a |"), ("html", "<table>"), ("csv", "```csv")],
)
def test_table_format_option(fmt, needle):
    out = render(_doc(table([["1"]], header=["a"])), table_format=fmt)
    assert needle in out


def test_code_fence_widens_past_inner_backticks():
    out = render(_doc(code("a\n```\nb", "python")))
    assert out.count("````") == 2


def test_page_anchors_are_html_comments_so_they_are_invisible():
    out = render(_doc(page_break(7), paragraph("x")))
    assert "<!-- papyrus:page 7 -->" in out


def test_page_anchors_can_be_turned_off():
    out = render(_doc(page_break(7), paragraph("x")), page_anchors=False)
    assert "papyrus:page" not in out
    assert "---" in out


@pytest.mark.parametrize(
    ("mode", "expected", "absent"),
    [
        ("reference", "![alt](assets/a.png)", None),
        ("placeholder", "`[image: alt]`", "!["),
        ("omit", None, "alt"),
    ],
)
def test_image_modes(mode, expected, absent):
    from papyrus.ir import image

    out = render(_doc(image("alt", "assets/a.png")), images=mode)
    if expected:
        assert expected in out
    if absent:
        assert absent not in out


def test_wrap_width_hard_wraps_paragraphs():
    out = render(_doc(paragraph("word " * 60)), wrap_width=40)
    assert max(len(ln) for ln in out.splitlines()) <= 40


def test_frontmatter_is_valid_yaml_and_carries_provenance(convert, fixtures):
    import yaml

    markdown = convert(fixtures / "sample.docx").markdown
    block = markdown.split("---", 2)[1]
    data = yaml.safe_load(block)
    assert data["source"]["format"] == "docx"
    assert len(data["source"]["sha256"]) == 64
    assert data["converted_by"] == "papyrus"
    assert data["word_count"] > 0


def test_output_always_ends_with_a_single_newline(convert, fixtures):
    markdown = convert(fixtures / "sample.txt").markdown
    assert markdown.endswith("\n") and not markdown.endswith("\n\n")


# ── chunking ─────────────────────────────────────────────────────────


def _big_doc() -> Document:
    doc = Document(source=SourceInfo(filename="big.pdf", format="pdf"), title="Report")
    for section in range(4):
        doc.add(page_break(section + 1))
        doc.add(heading(f"Section {section}", 2))
        doc.add(heading(f"Detail {section}", 3))
        for _ in range(6):
            doc.add(paragraph("Sentence about the section. " * 12))
    return doc


def test_chunks_stay_near_the_target_size():
    chunks = chunk_document(_big_doc(), ConvertOptions(chunk_size=800, chunk_overlap=0))
    assert len(chunks) > 4
    assert all(c.char_count <= 800 * 1.6 for c in chunks)


def test_every_chunk_knows_its_heading_path():
    chunks = chunk_document(_big_doc(), ConvertOptions(chunk_size=800))
    assert all(c.heading_path for c in chunks)
    assert any("Section 2" in c.heading_path for c in chunks)
    assert all(c.heading_path[0] == "Report" for c in chunks)


def test_every_chunk_knows_its_page_for_citation():
    chunks = chunk_document(_big_doc(), ConvertOptions(chunk_size=800))
    assert all(c.pages for c in chunks)
    assert max(max(c.pages) for c in chunks) == 4


def test_chunk_ids_are_unique_and_stable():
    options = ConvertOptions(chunk_size=800)
    first = [c.id for c in chunk_document(_big_doc(), options)]
    second = [c.id for c in chunk_document(_big_doc(), options)]
    assert first == second
    assert len(set(first)) == len(first)


def test_overlap_carries_context_between_chunks():
    no_overlap = chunk_document(_big_doc(), ConvertOptions(chunk_size=600, chunk_overlap=0))
    with_overlap = chunk_document(_big_doc(), ConvertOptions(chunk_size=600, chunk_overlap=200))
    assert sum(c.char_count for c in with_overlap) > sum(c.char_count for c in no_overlap)


def test_a_table_is_not_split_away_from_its_header_row():
    doc = Document(source=SourceInfo(filename="t.csv"), title="T")
    doc.add(table([[f"row{i}", str(i)] for i in range(200)], header=["name", "n"]))
    chunks = chunk_document(doc, ConvertOptions(chunk_size=400))
    assert len(chunks) > 1
    for chunk in chunks:
        if "|" in chunk.text:
            assert chunk.text.strip().startswith("| name | n |")


def test_a_split_code_block_stays_fenced():
    doc = Document(source=SourceInfo(filename="c.py"), title="C")
    doc.add(code("\n".join(f"line_{i} = {i}" for i in range(300)), "python"))
    chunks = chunk_document(doc, ConvertOptions(chunk_size=400))
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.text.count("```") % 2 == 0


def test_chunks_serialise_to_jsonl():
    chunks = chunk_document(_big_doc(), ConvertOptions(chunk_size=800))
    lines = to_jsonl(chunks).strip().split("\n")
    assert len(lines) == len(chunks)
    first = json.loads(lines[0])
    assert set(first) >= {"id", "text", "heading_path", "pages", "token_estimate", "source"}
    assert first["source"]["format"] == "pdf"


def test_chunking_is_off_by_default(convert, fixtures):
    assert convert(fixtures / "sample.docx").chunks == []
