"""ZIP archives — converted member by member, recursively.

This is where "universal" gets tested: an archive is untrusted input that
expands. Every guard in `Limits` applies here — member count, uncompressed
total, compression ratio (the zip-bomb signal), path traversal, and
recursion depth.
"""

from __future__ import annotations

import zipfile
from io import BytesIO

from papyrus.config import ConvertOptions
from papyrus.detect import Detection, detect
from papyrus.errors import LimitExceededError, PapyrusError, ParseError
from papyrus.ir import Asset, Document, heading, key_values, paragraph, rule
from papyrus.parsers.base import BaseParser
from papyrus.utils.files import human_bytes
from papyrus.utils.text import title_from_filename

_IGNORE_PREFIXES = ("__MACOSX/", ".git/", "node_modules/", ".venv/")
_IGNORE_NAMES = (".DS_Store", "Thumbs.db", ".gitignore")


class ArchiveParser(BaseParser):
    formats = ("zip",)
    label = "ZIP archive"
    priority = 70

    def parse(self, data: bytes, filename: str, detection: Detection, options: ConvertOptions) -> Document:
        doc = self.new_document(data, filename, detection)
        doc.title = title_from_filename(filename)

        try:
            archive = zipfile.ZipFile(BytesIO(data))
        except Exception as exc:
            raise ParseError(f"Could not open archive: {exc}") from exc

        limits = options.limits
        depth = int(doc.metadata.get("_depth", 0))
        if depth >= limits.max_recursion_depth:
            raise LimitExceededError(f"Archive nesting deeper than {limits.max_recursion_depth}.")

        with archive:
            members = [m for m in archive.infolist() if _wanted(m)]
            total_uncompressed = sum(m.file_size for m in members)
            compressed = sum(m.compress_size for m in members) or 1

            if total_uncompressed > limits.max_archive_bytes:
                raise LimitExceededError(
                    f"Archive expands to {human_bytes(total_uncompressed)}, over the "
                    f"{human_bytes(limits.max_archive_bytes)} ceiling."
                )
            if total_uncompressed / compressed > limits.max_archive_ratio:
                raise LimitExceededError(
                    f"Compression ratio {total_uncompressed // compressed}:1 exceeds the "
                    f"{limits.max_archive_ratio}:1 limit — refusing a likely zip bomb."
                )
            if len(members) > limits.max_archive_members:
                doc.warn(
                    f"Archive has {len(members)} files; converting the first {limits.max_archive_members}."
                )
                members = members[: limits.max_archive_members]

            doc.add(
                key_values(
                    {
                        "Files": str(len(members)),
                        "Uncompressed": human_bytes(total_uncompressed),
                    }
                )
            )
            doc.metadata["members"] = len(members)

            from papyrus.registry import default_registry

            registry = default_registry()
            converted = 0

            for member in members:
                name = member.filename
                try:
                    payload = archive.read(member)
                except Exception as exc:
                    doc.warn(f"Could not read '{name}': {exc}")
                    continue

                doc.add(rule())
                doc.add(heading(name, 2, member=name))

                child_detection = detect(name, payload)
                if child_detection.format in ("binary", "image") and not options.ocr:
                    doc.add(
                        paragraph(
                            f"*Binary member — {child_detection.media_type}, "
                            f"{human_bytes(len(payload))}. Not converted.*"
                        )
                    )
                    continue
                try:
                    parser = registry.get(child_detection)
                    child = parser.parse(payload, name, child_detection, options)
                except PapyrusError as exc:
                    doc.add(paragraph(f"*Skipped: {exc}*"))
                    doc.warn(f"'{name}': {exc}")
                    continue
                except Exception as exc:
                    doc.add(paragraph(f"*Skipped: unexpected error — {exc}*"))
                    doc.warn(f"'{name}': {exc}")
                    continue

                converted += 1
                doc.extend(_demote(child, name, by=2))
                for warning in child.warnings:
                    doc.warn(f"'{name}': {warning}")
                doc.assets.extend(_rename_assets(child.assets, len(doc.assets)))

            doc.metadata["converted"] = converted
            if not converted:
                doc.warn("No archive member could be converted.")
        return doc


def _wanted(member: zipfile.ZipInfo) -> bool:
    name = member.filename
    if member.is_dir():
        return False
    if name.startswith("/") or ".." in name.split("/"):
        return False  # path traversal
    if any(name.startswith(p) for p in _IGNORE_PREFIXES):
        return False
    return name.rsplit("/", 1)[-1] not in _IGNORE_NAMES


def _demote(child: Document, member: str, by: int) -> list:
    """Push a member's headings below the archive's own heading for it.

    The member's filename is already a heading, so a title derived from
    that same filename is dropped rather than repeated.
    """
    blocks = []
    derived = title_from_filename(member)
    if child.title and child.title != derived and not child.metadata.get("passthrough"):
        blocks.append(heading(child.title, min(6, 1 + by)))
    for block in child.blocks:
        if block.type == "heading" and block.level is not None:
            block.level = min(6, block.level + by)
        elif block.type == "raw":
            block.content = _demote_markdown(str(block.content), by)
        blocks.append(block)
    return blocks


def _demote_markdown(text: str, by: int) -> str:
    """Add `by` levels to every ATX heading outside a fenced code block."""
    out: list[str] = []
    in_fence = False
    for line in text.split("\n"):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
        elif not in_fence and stripped.startswith("#"):
            hashes = len(stripped) - len(stripped.lstrip("#"))
            if 1 <= hashes <= 6 and stripped[hashes : hashes + 1] in (" ", ""):
                line = "#" * min(6, hashes + by) + stripped[hashes:]
        out.append(line)
    return "\n".join(out)


def _rename_assets(assets: list[Asset], offset: int) -> list[Asset]:
    out: list[Asset] = []
    for index, asset in enumerate(assets, offset + 1):
        asset_id = f"img-{index:03d}"
        out.append(Asset(asset_id, f"{asset_id}-{asset.filename}", asset.media_type, asset.data))
    return out
