"""The before/after comparison.

The baseline must be a fair fight: the same bytes, read the way a one-line
script reads them, with no help from the parsers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from papyrus import Converter
from papyrus.compare import baseline_text, compare, measure
from papyrus.detect import detect

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def convert():
    return Converter().convert_bytes


def _comparison(name: str, convert):
    data = (FIXTURES / name).read_bytes()
    return compare(data, convert(data, name))


def test_the_word_baseline_loses_every_table(convert):
    """`"\\n".join(p.text for p in doc.paragraphs)` omits tables entirely.

    This is the single most common document-ingestion bug in the wild and
    the reason the comparison is worth showing.
    """
    result = _comparison("sample.docx", convert)
    assert "Metric" not in result.baseline
    assert "| Metric | 2024 | 2025 |" in result.markdown
    assert result.recovered.tables == 1


def test_the_pdf_baseline_keeps_the_running_header(convert):
    result = _comparison("sample.pdf", convert)
    assert "Confidential" in result.baseline
    assert "Confidential" not in result.markdown


def test_the_pdf_baseline_keeps_bare_page_numbers(convert):
    result = _comparison("sample.pdf", convert)
    assert result.recovered.running_headers_removed > 0


def test_headings_are_counted_as_recovered(convert):
    result = _comparison("sample.docx", convert)
    assert result.recovered.headings >= 3
    assert "#" not in result.baseline


def test_the_headline_reads_like_a_sentence(convert):
    headline = _comparison("sample.docx", convert).recovered.headline
    assert headline.startswith("Recovered ")
    assert headline.endswith(".")
    assert "table" in headline


def test_table_cells_are_counted_including_the_header(convert):
    result = _comparison("sample.csv", convert)
    # 3 columns, 3 body rows + 1 header row
    assert result.recovered.table_cells == 12


def test_a_baseline_that_fails_returns_empty_not_an_exception():
    """Some formats give a one-liner nothing. That is a fair result."""
    detection = detect("broken.pdf", b"%PDF-1.4 not really a pdf")
    assert baseline_text(b"%PDF-1.4 not really a pdf", detection) == ""


def test_comparison_serialises_for_the_api(convert):
    payload = _comparison("sample.pptx", convert).to_dict()
    assert set(payload) >= {"filename", "format", "baseline", "markdown", "recovered", "headline"}
    assert isinstance(payload["recovered"]["tables"], int)


def test_measure_counts_nested_list_items(convert):
    data = (FIXTURES / "hard" / "deep-lists.docx").read_bytes()
    found = measure(convert(data, "deep-lists.docx").document)
    assert found.list_items >= 5


def test_every_fixture_produces_a_comparison(convert):
    """The card must render for any file someone drops, not just the demos."""
    for path in sorted(FIXTURES.glob("sample.*")):
        data = path.read_bytes()
        result = compare(data, convert(data, path.name))
        assert isinstance(result.baseline, str)
        assert result.markdown
        assert result.recovered.headline
