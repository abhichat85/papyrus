"""Command-line behaviour, including the things that quietly lose data."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from papyrus.cli import app

runner = CliRunner()


def test_formats_lists_parsers():
    result = runner.invoke(app, ["formats"])
    assert result.exit_code == 0
    assert "pdf" in result.output and "docx" in result.output


def test_version():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "papyrus" in result.output


def test_convert_writes_markdown_to_stdout(fixtures):
    result = runner.invoke(app, ["convert", str(fixtures / "sample.csv")])
    assert result.exit_code == 0
    assert "| Month | Revenue | Growth |" in result.output


def test_convert_writes_a_bundle(tmp_path, fixtures):
    result = runner.invoke(
        app, ["convert", str(fixtures / "sample.pptx"), "-o", str(tmp_path), "--chunk", "--ir"]
    )
    assert result.exit_code == 0
    assert (tmp_path / "sample.md").exists()
    assert (tmp_path / "sample.chunks.jsonl").exists()
    ir = json.loads((tmp_path / "sample.json").read_text())
    assert ir["blocks"]


def test_batch_conversion_never_overwrites_between_files(tmp_path, fixtures):
    """Sixteen files all named `sample.*` must produce sixteen outputs."""
    result = runner.invoke(app, ["convert", str(fixtures), "-o", str(tmp_path), "-q"])
    assert result.exit_code == 0
    written = sorted(p.name for p in tmp_path.glob("*.md"))
    assert len(written) == len(list(fixtures.glob("sample.*")))
    assert len(set(written)) == len(written)


def test_directory_needs_out_when_it_holds_many_files(fixtures):
    result = runner.invoke(app, ["convert", str(fixtures)])
    assert result.exit_code == 2
    assert "stdout can only carry one document" in result.output


def test_no_frontmatter_flag(fixtures):
    result = runner.invoke(app, ["convert", str(fixtures / "sample.md"), "--no-frontmatter"])
    assert result.exit_code == 0
    assert not result.output.startswith("---")


def test_inspect_reports_detection_and_structure(fixtures):
    result = runner.invoke(app, ["inspect", str(fixtures / "sample.docx")])
    assert result.exit_code == 0
    assert "docx" in result.output
    assert "magic" in result.output


def test_inspect_on_a_missing_file_exits_nonzero(tmp_path):
    result = runner.invoke(app, ["inspect", str(tmp_path / "nope.pdf")])
    assert result.exit_code == 1


def test_a_failing_file_does_not_abort_the_batch(tmp_path, fixtures):
    broken = tmp_path / "broken.docx"
    broken.write_bytes((fixtures / "sample.docx").read_bytes()[:300])
    good = tmp_path / "good.md"
    good.write_text("# Fine\n\nBody.\n")
    out = tmp_path / "out"

    result = runner.invoke(app, ["convert", str(broken), str(good), "-o", str(out)])
    assert result.exit_code == 0
    assert (out / "good.md").exists()
    assert "✗" in result.output


def test_bad_option_values_are_rejected(fixtures):
    result = runner.invoke(app, ["convert", str(fixtures / "sample.md"), "--images", "sideways"])
    assert result.exit_code != 0
