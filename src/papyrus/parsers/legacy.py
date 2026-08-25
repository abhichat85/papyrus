"""Legacy formats: RTF, and a clear failure for OLE2 (.doc/.xls/.ppt).

RTF is de-controlled with a small state machine rather than a dependency —
enough to recover the text and paragraph breaks, which is all RTF usually
carries. OLE2 is refused with instructions instead of a mystery error,
because a wrong answer is worse than a good failure message.
"""

from __future__ import annotations

import re

from papyrus.config import ConvertOptions
from papyrus.detect import Detection
from papyrus.errors import UnsupportedFormatError
from papyrus.ir import Document
from papyrus.parsers.base import BaseParser
from papyrus.parsers.text import text_to_blocks
from papyrus.utils.text import clean, decode

_RTF_ESCAPE = re.compile(r"\\'([0-9a-fA-F]{2})")
_RTF_UNICODE = re.compile(r"\\u(-?\d+)\s?\??")
_RTF_CONTROL = re.compile(r"\\([a-zA-Z]+)(-?\d+)?[ ]?")
_SKIP_GROUPS = ("fonttbl", "colortbl", "stylesheet", "info", "pict", "generator", "themedata")


class RTFParser(BaseParser):
    formats = ("rtf",)
    label = "Rich Text (.rtf)"
    priority = 50

    def parse(self, data: bytes, filename: str, detection: Detection, options: ConvertOptions) -> Document:
        doc = self.new_document(data, filename, detection)
        text = _dertf(decode(data, "latin-1"))
        text = clean(text)
        if not text:
            doc.warn("RTF document contained no extractable text.")
            return doc
        doc.extend(text_to_blocks(text, detect_headings=options.detect_headings))
        doc.warn("RTF formatting is approximate — only text and paragraph breaks are recovered.")
        return doc


class LegacyOfficeParser(BaseParser):
    """Detects OLE2 binaries and refuses them with a usable next step."""

    formats = ("ole2",)
    label = "Legacy Office (unsupported)"
    priority = 55

    def parse(self, data: bytes, filename: str, detection: Detection, options: ConvertOptions) -> Document:
        raise UnsupportedFormatError(
            "Legacy binary Office format (.doc/.xls/.ppt). Convert it to the "
            "OOXML equivalent (.docx/.xlsx/.pptx) first — "
            "`soffice --headless --convert-to docx <file>` does this locally."
        )


def _dertf(text: str) -> str:
    """Strip RTF control words, keeping text, paragraph breaks and emphasis.

    RTF is a brace-delimited stream of control words. Groups such as the
    font and colour tables carry no document text, so they are skipped
    wholesale; `\\b` / `\\i` toggles are tracked so bold and italic runs
    survive into Markdown.
    """
    out: list[str] = []
    pending: list[str] = []
    bold = italic = False
    depth = 0
    skip_depth: int | None = None
    i, n = 0, len(text)

    def flush() -> None:
        nonlocal pending
        if not pending:
            return
        run = "".join(pending)
        pending = []
        stripped = run.strip()
        if not stripped:
            out.append(run)
            return
        lead = run[: len(run) - len(run.lstrip())]
        trail = run[len(run.rstrip()) :]
        if bold and italic:
            stripped = f"***{stripped}***"
        elif bold:
            stripped = f"**{stripped}**"
        elif italic:
            stripped = f"_{stripped}_"
        out.append(lead + stripped + trail)

    def emit(char: str) -> None:
        if skip_depth is None:
            pending.append(char)

    while i < n:
        char = text[i]

        if char == "{":
            depth += 1
            i += 1
            continue
        if char == "}":
            depth -= 1
            if skip_depth is not None and depth < skip_depth:
                skip_depth = None
            i += 1
            continue

        if char == "\\":
            hex_match = _RTF_ESCAPE.match(text, i)
            if hex_match:
                emit(bytes([int(hex_match.group(1), 16)]).decode("cp1252", "replace"))
                i = hex_match.end()
                continue
            uni_match = _RTF_UNICODE.match(text, i)
            if uni_match:
                point = int(uni_match.group(1))
                emit(chr(point if point >= 0 else point + 65536))
                i = uni_match.end()
                continue
            control = _RTF_CONTROL.match(text, i)
            if control:
                word, arg = control.group(1), control.group(2)
                if word in _SKIP_GROUPS:
                    if skip_depth is None:
                        skip_depth = depth
                elif skip_depth is None:
                    if word in ("par", "sect"):
                        flush()
                        out.append("\n\n")  # paragraph break
                    elif word == "line":
                        flush()
                        out.append("\n")
                    elif word == "tab":
                        emit("\t")
                    elif word in ("b", "i"):
                        on = arg not in ("0",)
                        flush()
                        if word == "b":
                            bold = on
                        else:
                            italic = on
                    elif word in ("pard", "plain"):
                        flush()
                        bold = italic = False
                i = control.end()
                continue
            # An escaped literal: \{ \} \\
            i += 2
            if i - 1 < n:
                emit(text[i - 1])
            continue

        emit(char)
        i += 1

    flush()
    return re.sub(r"\n{3,}", "\n\n", "".join(out))
