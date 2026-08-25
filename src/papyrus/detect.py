"""Format detection.

A filename is a hint, never evidence. Papyrus sniffs magic bytes first and
only falls back to the extension when the content is ambiguous (which is
the normal case for text formats). OOXML and EPUB are all ZIP containers,
so those are disambiguated by looking at the member names.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath

# ── format id → (media type, extensions) ─────────────────────────────
FORMATS: dict[str, tuple[str, tuple[str, ...]]] = {
    "pdf": ("application/pdf", (".pdf",)),
    "docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        (".docx", ".docm"),
    ),
    "pptx": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        (".pptx", ".pptm"),
    ),
    "xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        (".xlsx", ".xlsm"),
    ),
    "epub": ("application/epub+zip", (".epub",)),
    "zip": ("application/zip", (".zip",)),
    "html": ("text/html", (".html", ".htm", ".xhtml")),
    "xml": ("application/xml", (".xml", ".rss", ".atom", ".svg")),
    "json": ("application/json", (".json",)),
    "jsonl": ("application/x-ndjson", (".jsonl", ".ndjson")),
    "csv": ("text/csv", (".csv",)),
    "tsv": ("text/tab-separated-values", (".tsv", ".tab")),
    "ipynb": ("application/x-ipynb+json", (".ipynb",)),
    "eml": ("message/rfc822", (".eml",)),
    "rtf": ("application/rtf", (".rtf",)),
    "markdown": ("text/markdown", (".md", ".markdown", ".mdx")),
    "image": (
        "image/*",
        (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp"),
    ),
    "code": ("text/plain", ()),  # extensions come from CODE_LANGS
    "text": ("text/plain", (".txt", ".text", ".log", ".rst", ".srt", ".vtt")),
}

# extension → fenced-code language label
CODE_LANGS: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "jsx",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".java": "java",
    ".kt": "kotlin",
    ".swift": "swift",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".fish": "fish",
    ".ps1": "powershell",
    ".sql": "sql",
    ".r": "r",
    ".jl": "julia",
    ".lua": "lua",
    ".pl": "perl",
    ".scala": "scala",
    ".dart": "dart",
    ".ex": "elixir",
    ".exs": "elixir",
    ".erl": "erlang",
    ".hs": "haskell",
    ".clj": "clojure",
    ".vim": "vim",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
    ".env": "dotenv",
    ".dockerfile": "dockerfile",
    ".tf": "hcl",
    ".hcl": "hcl",
    ".graphql": "graphql",
    ".gql": "graphql",
    ".proto": "protobuf",
    ".css": "css",
    ".scss": "scss",
    ".less": "less",
    ".vue": "vue",
    ".svelte": "svelte",
    ".make": "makefile",
    ".gradle": "groovy",
}

IMAGE_MEDIA: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".webp": "image/webp",
}

# Filenames with no extension that we still recognise as code/config
BARE_FILENAMES: dict[str, str] = {
    "dockerfile": "dockerfile",
    "makefile": "makefile",
    "justfile": "just",
    "procfile": "yaml",
    "gemfile": "ruby",
    "rakefile": "ruby",
    "brewfile": "ruby",
    "cmakelists.txt": "cmake",
}


@dataclass
class Detection:
    format: str
    media_type: str
    extension: str
    lang: str = ""
    confidence: float = 0.5
    via: str = "extension"

    @property
    def is_text(self) -> bool:
        return self.format in {"text", "code", "markdown", "csv", "tsv", "json", "jsonl", "xml", "html"}


def detect(filename: str, data: bytes) -> Detection:
    """Identify a file from its bytes, using the name only to break ties."""
    ext = _ext(filename)
    magic = _by_magic(data, ext)
    if magic is not None:
        return magic
    return _by_name(filename, ext, data)


# ── magic-byte layer ─────────────────────────────────────────────────


def _by_magic(data: bytes, ext: str) -> Detection | None:
    head = data[:16]

    if head.startswith(b"%PDF-"):
        return Detection("pdf", FORMATS["pdf"][0], ".pdf", confidence=1.0, via="magic")
    if head.startswith(b"{\\rtf"):
        return Detection("rtf", FORMATS["rtf"][0], ".rtf", confidence=1.0, via="magic")

    for sig, extension in (
        (b"\x89PNG\r\n\x1a\n", ".png"),
        (b"\xff\xd8\xff", ".jpg"),
        (b"GIF87a", ".gif"),
        (b"GIF89a", ".gif"),
        (b"BM", ".bmp"),
    ):
        if head.startswith(sig):
            return Detection("image", IMAGE_MEDIA[extension], extension, confidence=1.0, via="magic")
    if head[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return Detection("image", "image/webp", ".webp", confidence=1.0, via="magic")
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return Detection("image", "image/tiff", ".tiff", confidence=1.0, via="magic")

    # Legacy OLE2 (.doc/.xls/.ppt) — recognised so we can fail with a
    # useful message rather than a mystery.
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return Detection("ole2", "application/x-ole-storage", ext or ".doc", confidence=1.0, via="magic")

    if head.startswith(b"PK\x03\x04") or head.startswith(b"PK\x05\x06"):
        return _sniff_zip(data, ext)

    return None


def _sniff_zip(data: bytes, ext: str) -> Detection:
    """OOXML, EPUB and plain ZIP all start with PK. Look inside to decide."""
    try:
        with zipfile.ZipFile(BytesIO(data)) as zf:
            names = set(zf.namelist()[:400])
    except Exception:
        return Detection("zip", FORMATS["zip"][0], ".zip", confidence=0.4, via="magic")

    if "word/document.xml" in names:
        return Detection("docx", FORMATS["docx"][0], ".docx", confidence=1.0, via="magic")
    if any(n.startswith("ppt/slides/") for n in names) or "ppt/presentation.xml" in names:
        return Detection("pptx", FORMATS["pptx"][0], ".pptx", confidence=1.0, via="magic")
    if "xl/workbook.xml" in names:
        return Detection("xlsx", FORMATS["xlsx"][0], ".xlsx", confidence=1.0, via="magic")
    if "mimetype" in names or any(n.endswith(".opf") for n in names):
        return Detection("epub", FORMATS["epub"][0], ".epub", confidence=0.95, via="magic")
    return Detection("zip", FORMATS["zip"][0], ".zip", confidence=0.9, via="magic")


# ── name + content-shape layer ───────────────────────────────────────


def _by_name(filename: str, ext: str, data: bytes) -> Detection:
    base = PurePosixPath(filename).name.lower()

    if ext in CODE_LANGS:
        return Detection("code", "text/plain", ext, lang=CODE_LANGS[ext], confidence=0.9)
    if base in BARE_FILENAMES:
        return Detection("code", "text/plain", ext or "", lang=BARE_FILENAMES[base], confidence=0.9)

    for fmt, (media, exts) in FORMATS.items():
        if ext and ext in exts:
            lang = CODE_LANGS.get(ext, "")
            media = IMAGE_MEDIA.get(ext, media)
            return Detection(fmt, media, ext, lang=lang, confidence=0.85)

    # Unknown extension: guess from the content shape.
    sample = data[:4096]
    if b"\x00" in sample:
        return Detection("binary", "application/octet-stream", ext, confidence=0.3)

    stripped = sample.lstrip()
    if stripped[:1] in (b"{", b"["):
        return Detection("json", FORMATS["json"][0], ext or ".json", confidence=0.5, via="content")
    lowered = stripped[:512].lower()
    if lowered.startswith(b"<!doctype html") or lowered.startswith(b"<html"):
        return Detection("html", FORMATS["html"][0], ext or ".html", confidence=0.8, via="content")
    if stripped.startswith(b"<?xml"):
        return Detection("xml", FORMATS["xml"][0], ext or ".xml", confidence=0.7, via="content")

    return Detection("text", "text/plain", ext, confidence=0.3, via="fallback")


def _ext(filename: str) -> str:
    suffix = PurePosixPath(filename).suffix.lower()
    return suffix if suffix else ""
