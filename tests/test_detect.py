"""Format detection must not trust the filename."""

from __future__ import annotations

import pytest

from papyrus.detect import detect


def test_magic_bytes_beat_a_lying_extension(fixtures):
    """A PDF renamed to .docx is still a PDF."""
    data = (fixtures / "sample.pdf").read_bytes()
    result = detect("invoice.docx", data)
    assert result.format == "pdf"
    assert result.via == "magic"
    assert result.confidence == 1.0


def test_ooxml_containers_are_disambiguated_by_contents(fixtures):
    for name, expected in (("sample.docx", "docx"), ("sample.pptx", "pptx"), ("sample.xlsx", "xlsx")):
        data = (fixtures / name).read_bytes()
        # Strip the extension entirely — only the zip members can decide.
        assert detect("upload", data).format == expected


def test_plain_zip_is_not_mistaken_for_office(fixtures):
    assert detect("bundle.zip", (fixtures / "sample.zip").read_bytes()).format == "zip"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("notes.md", "markdown"),
        ("data.csv", "csv"),
        ("data.tsv", "tsv"),
        ("app.py", "code"),
        ("Dockerfile", "code"),
        ("config.yaml", "code"),
        ("page.html", "html"),
        ("log.txt", "text"),
    ],
)
def test_text_formats_resolve_by_name(name, expected):
    assert detect(name, b"hello world\n").format == expected


def test_content_shape_rescues_an_unknown_extension():
    assert detect("payload.bin", b'{"a": 1}').format == "json"
    assert detect("payload.bin", b"<!DOCTYPE html><html>").format == "html"


def test_binary_is_recognised_as_binary():
    assert detect("mystery.dat", b"\x00\x01\x02\x03" * 40).format == "binary"


def test_legacy_office_is_identified_not_guessed():
    ole2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100
    assert detect("old.doc", ole2).format == "ole2"
