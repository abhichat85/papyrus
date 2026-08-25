"""Vercel serverless entry point for the Papyrus engine.

Vercel's Python runtime serves any module-level `app` that is an ASGI
application, so this is a thin shim: put `src/` on the path and re-export
the FastAPI app that `papyrus serve` and Docker also run. There is exactly
one implementation of the API, and this is not a second copy of it.

Serverless changes two things about the deployment, both handled here:

* Request bodies are capped at 4.5 MB by the platform, well below the
  engine's own 50 MB ceiling, so the limit is lowered to match and the
  error message says which limit was hit.
* Functions are cold-started per request, so the registry is built at
  import time rather than on first use.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Match the platform's body limit so an oversized upload fails with our
# message rather than a bare platform 413.
os.environ.setdefault("PAPYRUS_MAX_FILE_BYTES", str(4 * 1024 * 1024))
# Cold starts make a huge archive a poor fit for the hosted demo.
os.environ.setdefault("PAPYRUS_MAX_ARCHIVE_MEMBERS", "100")

from papyrus.api.main import app

__all__ = ["app"]
