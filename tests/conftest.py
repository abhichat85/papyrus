from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def pytest_sessionstart(session) -> None:
    """Build the binary fixtures if they are missing or stale."""
    generator = Path(__file__).parent / "make_fixtures.py"
    sample = FIXTURES / "sample.docx"
    if not sample.exists() or sample.stat().st_mtime < generator.stat().st_mtime:
        subprocess.run([sys.executable, str(generator)], check=True, capture_output=True)


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES


@pytest.fixture
def convert():
    from papyrus import Converter

    return Converter().convert


@pytest.fixture
def convert_bytes():
    from papyrus import Converter

    return Converter().convert_bytes
