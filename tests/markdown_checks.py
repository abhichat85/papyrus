"""A structural validator for the Markdown Papyrus emits.

Used by the invariant suite to assert properties that must hold for every
format. This is deliberately strict about the things that break downstream
consumers — ragged tables, unbalanced fences, stray control characters —
and silent about matters of taste.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")
_HEADING = re.compile(r"^(#{1,6})(\s*)(.*)$")
_SEPARATOR = re.compile(r"^\|(\s*:?-{3,}:?\s*\|)+$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass
class Report:
    problems: list[str] = field(default_factory=list)
    tables: int = 0
    headings: int = 0
    fences: int = 0

    @property
    def ok(self) -> bool:
        return not self.problems

    def __str__(self) -> str:  # pragma: no cover - only shown on failure
        return "\n".join(f"  - {p}" for p in self.problems)


def check(markdown: str) -> Report:
    report = Report()
    if not markdown:
        return report

    lines = markdown.split("\n")
    in_fence = False
    fence_marker = ""
    in_frontmatter = lines[0].strip() == "---"
    frontmatter_closed = not in_frontmatter

    table: list[tuple[int, str]] = []

    for number, line in enumerate(lines, start=1):
        # ── frontmatter ──────────────────────────────────────────
        if in_frontmatter and not frontmatter_closed:
            if number > 1 and line.strip() == "---":
                frontmatter_closed = True
            continue

        # ── fences ───────────────────────────────────────────────
        stripped = line.lstrip()
        if not in_fence and (stripped.startswith("```") or stripped.startswith("~~~")):
            in_fence = True
            fence_marker = stripped[:3]
            report.fences += 1
            continue
        if in_fence:
            if stripped.startswith(fence_marker):
                in_fence = False
            continue

        if _CONTROL.search(line):
            report.problems.append(f"line {number}: control character in output")

        if line != line.rstrip():
            report.problems.append(f"line {number}: trailing whitespace")

        # ── headings ─────────────────────────────────────────────
        heading = _HEADING.match(line)
        if heading and not line.startswith("#!"):
            hashes, gap, text = heading.groups()
            report.headings += 1
            if gap != " ":
                report.problems.append(f"line {number}: heading needs one space after {hashes}")
            if not text.strip():
                report.problems.append(f"line {number}: empty heading")
            if "\n" in text:
                report.problems.append(f"line {number}: heading spans lines")

        # ── tables ───────────────────────────────────────────────
        if line.startswith("|"):
            table.append((number, line))
        elif table:
            report.problems.extend(_check_table(table))
            report.tables += 1
            table = []

    if table:
        report.problems.extend(_check_table(table))
        report.tables += 1

    if in_fence:
        report.problems.append("unterminated code fence")
    if in_frontmatter and not frontmatter_closed:
        report.problems.append("unterminated frontmatter")

    return report


def _check_table(rows: list[tuple[int, str]]) -> list[str]:
    problems: list[str] = []
    if len(rows) < 2:
        problems.append(f"line {rows[0][0]}: table with no separator row")
        return problems

    header_line, separator_line = rows[0][1], rows[1][1]
    if not _SEPARATOR.match(separator_line.strip()):
        problems.append(f"line {rows[1][0]}: second table row is not a separator")

    width = len(_UNESCAPED_PIPE.findall(header_line))
    for number, line in rows:
        found = len(_UNESCAPED_PIPE.findall(line))
        if found != width:
            problems.append(
                f"line {number}: table row has {found} unescaped pipes, header has {width}"
            )
    return problems


def tables_of(markdown: str) -> list[list[list[str]]]:
    """Parse pipe tables back out, for round-trip assertions."""
    tables: list[list[list[str]]] = []
    current: list[list[str]] = []
    in_fence = False

    for line in markdown.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if line.startswith("|"):
            cells = [c.strip() for c in _UNESCAPED_PIPE.split(line)[1:-1]]
            if not _SEPARATOR.match(line.strip()):
                current.append(cells)
        elif current:
            tables.append(current)
            current = []
    if current:
        tables.append(current)
    return tables
