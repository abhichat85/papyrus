"""Papyrus error taxonomy.

Every failure the engine raises is one of these, so callers (CLI, API)
can map them to exit codes / HTTP statuses without string matching.
"""

from __future__ import annotations


class PapyrusError(Exception):
    """Base class for every Papyrus failure."""

    code = "papyrus_error"
    http_status = 500


class UnsupportedFormatError(PapyrusError):
    """No registered parser claims this file."""

    code = "unsupported_format"
    http_status = 415


class ParseError(PapyrusError):
    """The file matched a parser but could not be read."""

    code = "parse_error"
    http_status = 422


class FileTooLargeError(PapyrusError):
    """Input exceeded the configured byte ceiling."""

    code = "file_too_large"
    http_status = 413


class LimitExceededError(PapyrusError):
    """A resource guard tripped (pages, cells, archive members, depth...)."""

    code = "limit_exceeded"
    http_status = 422


class MissingDependencyError(PapyrusError):
    """An optional extra (OCR, for example) is not installed."""

    code = "missing_dependency"
    http_status = 501
