"""Table shaping: trimming, header inference, and alignment."""

from __future__ import annotations

import re

_NUMERIC = re.compile(r"^-?[\d,]*\.?\d+\s*%?$|^[($]-?[\d,]*\.?\d+[)]?$")


def trim(rows: list[list[str]]) -> list[list[str]]:
    """Drop fully empty leading/trailing rows and fully empty columns."""
    rows = [[("" if c is None else str(c)).strip() for c in row] for row in rows]
    while rows and not any(rows[0]):
        rows.pop(0)
    while rows and not any(rows[-1]):
        rows.pop()
    if not rows:
        return []

    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    keep = [i for i in range(width) if any(r[i] for r in rows)]
    if len(keep) != width:
        rows = [[r[i] for i in keep] for r in rows]
    return rows


def split_header(rows: list[list[str]], hint: bool | None = None) -> tuple[list[str] | None, list[list[str]]]:
    """Promote row 0 to a header row.

    Telling a header from a data row by content alone is genuinely
    unreliable — `| Metric | 2024 | 2025 |` is a header whose cells are
    numbers. So parsers pass a `hint` derived from the format's own signal
    (`<th>`, Word's `tblHeader`, PowerPoint's `firstRow`, PyMuPDF's
    detected header, `csv.Sniffer`), and the heuristic below is only the
    fallback for sources that carry no signal at all.
    """
    if len(rows) < 2:
        return None, rows
    first, body = rows[0], rows[1:]
    if not any(c.strip() for c in first):
        return None, rows
    if not any(any(c.strip() for c in row) for row in body):
        return None, rows

    if hint is True:
        return first, body
    if hint is False:
        return None, rows

    # No signal: only promote a fully populated, entirely non-numeric row.
    if not all(c.strip() for c in first):
        return None, rows
    if any(_NUMERIC.match(c.strip()) for c in first):
        return None, rows
    return first, body


def alignments(header: list[str] | None, rows: list[list[str]]) -> list[str]:
    """Right-align numeric columns; left-align everything else."""
    width = len(header) if header else (max((len(r) for r in rows), default=0))
    out: list[str] = []
    for i in range(width):
        column = [r[i] for r in rows if i < len(r) and r[i].strip()]
        numeric = column and all(_NUMERIC.match(c.strip()) for c in column)
        out.append("---:" if numeric else "---")
    return out


def is_numeric(value: str) -> bool:
    return bool(_NUMERIC.match(value.strip()))
