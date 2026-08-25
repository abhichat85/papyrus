"""Text hygiene shared by every parser."""

from __future__ import annotations

import re
import unicodedata

_LIGATURES = {
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "ﬅ": "st",
    "ﬆ": "st",
}
_SMART = {
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "–": "-",
    "—": "--",
    "…": "...",
    " ": " ",
}
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MULTISPACE = re.compile(r"[ \t]{2,}")
_MULTINEWLINE = re.compile(r"\n{3,}")
# A word split across a PDF line break: "informa-\ntion" -> "information"
_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")

_MD_SPECIALS = re.compile(r"([\\`*_{}\[\]<>|])")


def decode(data: bytes, hint: str | None = None) -> str:
    """Best-effort bytes → str. Tries the hint, UTF-8, chardet, then latin-1."""
    if hint:
        try:
            return data.decode(hint)
        except (UnicodeDecodeError, LookupError):
            pass
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    try:
        import chardet

        guess = chardet.detect(data[:200_000])
        if guess.get("encoding") and (guess.get("confidence") or 0) > 0.5:
            return data.decode(guess["encoding"], errors="replace")
    except Exception:
        pass
    return data.decode("latin-1", errors="replace")


def clean(text: str, *, join_hyphens: bool = False) -> str:
    """Normalise unicode, strip control characters, collapse whitespace."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    for src, dst in {**_LIGATURES, **_SMART}.items():
        text = text.replace(src, dst)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL.sub("", text)
    if join_hyphens:
        text = _HYPHEN_BREAK.sub(r"\1\2", text)
    text = _MULTISPACE.sub(" ", text)
    text = _MULTINEWLINE.sub("\n\n", text)
    return text.strip()


def escape_md(text: str) -> str:
    """Escape characters that would otherwise become Markdown syntax."""
    return _MD_SPECIALS.sub(r"\\\1", text)


def escape_cell(text: str) -> str:
    """Table cells: pipes and newlines must not break the row."""
    return str(text).replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>").strip()


def slugify(text: str, max_length: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[-\s]+", "-", text)
    return text[:max_length].strip("-") or "untitled"


def title_from_filename(filename: str) -> str:
    stem = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    stem = re.sub(r"[_\-]+", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem[:1].upper() + stem[1:] if stem else "Untitled"


def looks_like_heading(text: str, *, max_words: int = 14) -> bool:
    """Heuristic for unstructured sources: short, no terminal period, title-ish."""
    stripped = text.strip()
    if not stripped or len(stripped) > 120:
        return False
    words = stripped.split()
    if len(words) > max_words:
        return False
    if stripped.endswith((".", ",", ";", ":")):
        return False
    if re.match(r"^(\d+(\.\d+)*|[IVXLC]+\.|[A-Z]\.)\s+\S", stripped):
        return True
    letters = [c for c in stripped if c.isalpha()]
    # Mostly-uppercase short lines read as headings ("EXECUTIVE SUMMARY").
    return bool(letters) and sum(c.isupper() for c in letters) / len(letters) > 0.7
