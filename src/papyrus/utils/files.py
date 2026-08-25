"""Filesystem and byte helpers."""

from __future__ import annotations

import hashlib
import re

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_name(name: str, fallback: str = "file") -> str:
    """Strip directory traversal and anything that isn't filename-safe.

    Uploaded names are attacker-controlled: `../../etc/passwd` must never
    survive this function.
    """
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = _UNSAFE.sub("_", name).lstrip(".")
    name = name[:120]
    return name or fallback


def human_bytes(n: int) -> str:
    step = 1024.0
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if value < step or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= step
    return f"{value:.1f} GB"
