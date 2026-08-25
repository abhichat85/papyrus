# Papyrus engine + API.
#
# Multi-stage so the runtime image carries no build toolchain. The result
# runs as a non-root user and writes nothing to disk — conversion happens
# entirely in memory.

FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install ".[api]"

# ── runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim

# Optional OCR support: uncomment to enable `--ocr` for scanned PDFs.
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     tesseract-ocr && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 papyrus
COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER papyrus
WORKDIR /home/papyrus

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/healthz')"

CMD ["uvicorn", "papyrus.api.main:app", "--host", "0.0.0.0", "--port", "8787"]
