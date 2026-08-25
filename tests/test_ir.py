"""The IR is a contract — it must round-trip and normalise reliably."""

from __future__ import annotations

import json

from papyrus.ir import (
    Document,
    ListItem,
    SourceInfo,
    Table,
    heading,
    list_block,
    paragraph,
    table,
)


def _doc() -> Document:
    return Document(source=SourceInfo(filename="x.txt"), title="X")


def test_heading_level_is_clamped():
    assert heading("a", 0).level == 1
    assert heading("a", 99).level == 6


def test_ragged_tables_are_padded_not_dropped():
    padded = Table(rows=[["a"], ["b", "c", "d"]]).normalized()
    assert [len(r) for r in padded.rows] == [3, 3]


def test_document_serialises_to_json():
    doc = _doc()
    doc.add(heading("Title", 2))
    doc.add(paragraph("Body"))
    doc.add(table([["1", "2"]], header=["a", "b"]))
    doc.add(list_block([ListItem("x", [ListItem("y")])]))

    payload = json.loads(doc.to_json())
    assert [b["type"] for b in payload["blocks"]] == ["heading", "paragraph", "table", "list"]
    assert payload["blocks"][2]["content"]["header"] == ["a", "b"]
    assert payload["blocks"][3]["content"][0]["children"][0]["text"] == "y"


def test_word_count_reaches_into_lists_and_tables():
    doc = _doc()
    doc.add(list_block([ListItem("one two"), ListItem("three")]))
    doc.add(table([["four", "five"]], header=["six"]))
    assert doc.word_count == 6


def test_warnings_are_deduplicated():
    doc = _doc()
    doc.warn("same")
    doc.warn("same")
    assert doc.warnings == ["same"]
