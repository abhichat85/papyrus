"""Tabular and structured data: CSV, TSV, JSON, JSON Lines."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from papyrus.config import ConvertOptions
from papyrus.detect import Detection
from papyrus.errors import ParseError
from papyrus.ir import Block, Document, ListItem, code, heading, list_block, paragraph, table
from papyrus.parsers.base import BaseParser
from papyrus.utils.tables import split_header, trim
from papyrus.utils.text import decode


class CSVParser(BaseParser):
    """Delimited text. The delimiter is sniffed, not assumed."""

    formats = ("csv", "tsv")
    label = "CSV / TSV"
    priority = 40

    def parse(self, data: bytes, filename: str, detection: Detection, options: ConvertOptions) -> Document:
        doc = self.new_document(data, filename, detection)
        text = decode(data)
        if not text.strip():
            doc.warn("Delimited file was empty.")
            return doc

        delimiter = "\t" if detection.format == "tsv" else _sniff_delimiter(text)
        doc.metadata["delimiter"] = "tab" if delimiter == "\t" else delimiter

        limit = options.limits.max_csv_rows
        rows: list[list[str]] = []
        truncated = False
        try:
            reader = csv.reader(io.StringIO(text), delimiter=delimiter)
            for row in reader:
                if len(rows) >= limit:
                    truncated = True
                    break
                rows.append([("" if c is None else str(c)) for c in row])
        except csv.Error as exc:
            raise ParseError(f"Malformed delimited data: {exc}") from exc

        rows = trim(rows)
        if not rows:
            doc.warn("Delimited file contained no data rows.")
            return doc

        if truncated:
            doc.warn(f"Truncated at {limit} rows (PAPYRUS_MAX_CSV_ROWS).")

        header, body = split_header(rows, _has_header(text, delimiter))
        doc.metadata["rows"] = len(body)
        doc.metadata["columns"] = len(header) if header else (len(body[0]) if body else 0)
        doc.add(table(body, header=header))
        return doc


class JSONParser(BaseParser):
    """JSON becomes readable structure, not a wall of braces.

    An array of flat objects renders as a Markdown table — that is what an
    API dump or an export usually is, and a table is what a model reads
    best. Anything else becomes nested headings and key/value lists.
    """

    formats = ("json",)
    label = "JSON"
    priority = 40

    def parse(self, data: bytes, filename: str, detection: Detection, options: ConvertOptions) -> Document:
        doc = self.new_document(data, filename, detection)
        text = decode(data).strip()
        if not text:
            doc.warn("JSON file was empty.")
            return doc

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            doc.warn(f"Invalid JSON ({exc.msg} at line {exc.lineno}) — emitted verbatim.")
            doc.add(code(text, "json"))
            return doc

        doc.metadata["json_root"] = type(parsed).__name__
        doc.extend(_render_value(parsed, level=1, limits=options.limits))
        return doc


class JSONLParser(BaseParser):
    """JSON Lines: one record per line, rendered as a table when uniform."""

    formats = ("jsonl",)
    label = "JSON Lines"
    priority = 40

    def parse(self, data: bytes, filename: str, detection: Detection, options: ConvertOptions) -> Document:
        doc = self.new_document(data, filename, detection)
        records: list[Any] = []
        bad = 0
        for line in decode(data).splitlines():
            line = line.strip()
            if not line:
                continue
            if len(records) >= options.limits.max_csv_rows:
                doc.warn(f"Truncated at {options.limits.max_csv_rows} records.")
                break
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                bad += 1

        if bad:
            doc.warn(f"Skipped {bad} malformed line(s).")
        if not records:
            doc.warn("No valid JSON records found.")
            return doc

        doc.metadata["records"] = len(records)
        doc.extend(_render_value(records, level=1, limits=options.limits))
        return doc


# ── value rendering ──────────────────────────────────────────────────


def _render_value(value: Any, level: int, limits: Any, key: str | None = None) -> list[Block]:
    blocks: list[Block] = []

    if isinstance(value, list):
        if _is_table_like(value):
            columns = _columns(value)
            rows = [[_scalar(item.get(c)) for c in columns] for item in value]
            if key:
                blocks.append(heading(key, level))
            blocks.append(table(rows, header=columns))
            return blocks
        if value and all(_is_scalar(v) for v in value):
            if key:
                blocks.append(heading(key, level))
            blocks.append(list_block([ListItem(_scalar(v)) for v in value]))
            return blocks
        if key:
            blocks.append(heading(key, level))
        for index, item in enumerate(value, 1):
            blocks.extend(_render_value(item, min(level + 1, 6), limits, key=f"[{index}]"))
        return blocks

    if isinstance(value, dict):
        scalars = {k: _scalar(v) for k, v in value.items() if _is_scalar(v)}
        nested = {k: v for k, v in value.items() if not _is_scalar(v)}
        if key:
            blocks.append(heading(key, level))
        if scalars:
            blocks.append(Block("key_values", scalars))
        for k, v in nested.items():
            blocks.extend(_render_value(v, min(level + 1, 6), limits, key=k))
        return blocks

    text = _scalar(value)
    blocks.append(paragraph(f"**{key}:** {text}" if key else text))
    return blocks


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, str | int | float | bool)


def _scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str | int | float):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


def _is_table_like(value: list[Any], min_rows: int = 2) -> bool:
    """True when every element is a flat object sharing most of its keys."""
    if len(value) < min_rows or not all(isinstance(v, dict) for v in value):
        return False
    if not all(all(_is_scalar(x) for x in v.values()) for v in value):
        return False
    first = set(value[0].keys())
    if not first:
        return False
    overlap = sum(len(first & set(v.keys())) / max(len(first | set(v.keys())), 1) for v in value)
    return overlap / len(value) > 0.7


def _columns(value: list[dict]) -> list[str]:
    columns: list[str] = []
    for item in value:
        for k in item:
            if k not in columns:
                columns.append(k)
    return columns


def _has_header(text: str, delimiter: str) -> bool | None:
    """`csv.Sniffer` compares row 0's types against the rows below it."""
    sample = "\n".join(text.splitlines()[:30])
    try:
        return csv.Sniffer().has_header(sample)
    except csv.Error:
        return None


def _sniff_delimiter(text: str) -> str:
    sample = "\n".join(text.splitlines()[:20])
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        counts = {d: sample.count(d) for d in (",", ";", "\t", "|")}
        best = max(counts, key=counts.get)
        return best if counts[best] else ","
