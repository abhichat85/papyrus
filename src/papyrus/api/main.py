"""Papyrus HTTP API.

Stateless by construction: a request carries a file in, a conversion goes
out, and nothing is written to disk. That is a security property, not an
omission — Papyrus is meant to run inside someone else's network on
documents they will not send anywhere.
"""

from __future__ import annotations

import io
import json
import logging
import zipfile
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from papyrus import __version__
from papyrus.api.schemas import (
    ChunkResponse,
    ConvertResponse,
    DetectResponse,
    ErrorResponse,
    FormatsResponse,
)
from papyrus.chunking import to_jsonl
from papyrus.config import ConvertOptions, Limits
from papyrus.converter import ConversionResult, Converter
from papyrus.detect import detect
from papyrus.errors import PapyrusError, UnsupportedFormatError
from papyrus.registry import default_registry
from papyrus.utils.files import safe_name

logger = logging.getLogger("papyrus.api")

app = FastAPI(
    title="Papyrus",
    version=__version__,
    summary="Universal document ingestion — any file in, agent-ready Markdown out.",
    docs_url="/docs",
)

# The API holds no secrets and no session state, so an open CORS policy is
# safe here and lets the demo UI call it from anywhere. Narrow this if you
# put it behind auth.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)

_registry = default_registry()
_converter = Converter(registry=_registry)
_limits = Limits()


@app.exception_handler(PapyrusError)
async def papyrus_error_handler(request: Request, exc: PapyrusError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content=ErrorResponse(error=str(exc), code=exc.code).model_dump(),
    )


# ── endpoints ────────────────────────────────────────────────────────


@app.get("/", tags=["meta"])
async def index() -> dict[str, Any]:
    """What this service is, for anyone who opens the port in a browser.

    Without this, hitting the root gives a bare 404 and the service looks
    dead when it is running perfectly well.
    """
    return {
        "service": "papyrus",
        "version": __version__,
        "description": "Universal document ingestion — any file in, agent-ready Markdown out.",
        "docs": "/docs",
        "endpoints": {
            "POST /v1/convert": "Convert one document (json | markdown | bundle)",
            "POST /v1/chunk": "Convert and split into embedding-ready chunks",
            "POST /v1/detect": "Identify a file without converting it",
            "GET /v1/formats": "Every supported format",
            "GET /healthz": "Liveness",
        },
        "formats": len(_registry.supported_formats()),
        "example": "curl -F file=@report.pdf http://localhost:8787/v1/convert",
    }


@app.get("/healthz", tags=["meta"])
async def healthz() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/v1/formats", response_model=FormatsResponse, tags=["meta"])
async def formats() -> FormatsResponse:
    supported = _registry.supported_formats()
    return FormatsResponse(
        count=len(supported),
        formats=supported,
        max_file_bytes=_limits.max_file_bytes,
        version=__version__,
    )


@app.post("/v1/detect", response_model=DetectResponse, tags=["convert"])
async def detect_endpoint(file: Annotated[UploadFile, File()]) -> DetectResponse:
    """Identify a file without converting it."""
    data = await _read(file)
    filename = safe_name(file.filename or "upload")
    detection = detect(filename, data)
    try:
        parser = _registry.get(detection)
        handled_by, supported = parser.label, True
    except UnsupportedFormatError:
        handled_by, supported = None, False
    return DetectResponse(
        filename=filename,
        format=detection.format,
        media_type=detection.media_type,
        extension=detection.extension,
        confidence=detection.confidence,
        detected_via=detection.via,
        size_bytes=len(data),
        supported=supported,
        handled_by=handled_by,
    )


@app.post("/v1/convert", tags=["convert"])
async def convert_endpoint(
    file: Annotated[UploadFile, File(description="The document to convert.")],
    response_format: Annotated[str, Form(description="json | markdown | bundle")] = "json",
    frontmatter: Annotated[bool, Form()] = True,
    page_anchors: Annotated[bool, Form()] = True,
    images: Annotated[str, Form(description="extract | reference | placeholder | omit")] = "reference",
    tables: Annotated[str, Form(description="pipe | html | csv")] = "pipe",
    chunk: Annotated[bool, Form()] = False,
    chunk_size: Annotated[int, Form()] = 1200,
    ocr: Annotated[bool, Form()] = False,
) -> Response:
    """Convert one document.

    `response_format=bundle` returns a zip containing the Markdown, the IR,
    any extracted assets and — when requested — `chunks.jsonl`.
    """
    options = _options(frontmatter, page_anchors, images, tables, chunk, chunk_size, ocr)
    data = await _read(file)
    filename = safe_name(file.filename or "upload")
    result = _converter.convert_bytes(data, filename, options)

    if response_format == "markdown":
        return PlainTextResponse(result.markdown, media_type="text/markdown; charset=utf-8")
    if response_format == "bundle":
        return _bundle(result, filename)
    if response_format != "json":
        raise HTTPException(400, "response_format must be json, markdown or bundle")

    payload = ConvertResponse(
        markdown=result.markdown,
        title=result.document.title,
        format=result.detection.format,
        detected_via=result.detection.via,
        filename=filename,
        sha256=result.document.source.sha256,
        word_count=result.document.word_count,
        block_count=len(result.document.blocks),
        assets=[a.to_dict() for a in result.document.assets],
        warnings=result.warnings,
        duration_ms=result.duration_ms,
    )
    return JSONResponse(payload.model_dump())


@app.post("/v1/chunk", response_model=ChunkResponse, tags=["convert"])
async def chunk_endpoint(
    file: Annotated[UploadFile, File()],
    chunk_size: Annotated[int, Form()] = 1200,
    chunk_overlap: Annotated[int, Form()] = 120,
    frontmatter: Annotated[bool, Form()] = False,
) -> ChunkResponse:
    """Convert and split into embedding-ready chunks in one call."""
    options = ConvertOptions(
        frontmatter=frontmatter,
        chunk=True,
        chunk_size=max(200, min(chunk_size, 8000)),
        chunk_overlap=max(0, min(chunk_overlap, 2000)),
        limits=_limits,
    )
    data = await _read(file)
    filename = safe_name(file.filename or "upload")
    result = _converter.convert_bytes(data, filename, options)

    return ChunkResponse(
        filename=filename,
        format=result.detection.format,
        title=result.document.title,
        chunk_count=len(result.chunks),
        total_tokens=sum(c.token_estimate for c in result.chunks),
        chunks=[c.to_dict() for c in result.chunks],  # type: ignore[arg-type]
        warnings=result.warnings,
        duration_ms=result.duration_ms,
    )


# ── helpers ──────────────────────────────────────────────────────────


async def _read(file: UploadFile) -> bytes:
    """Read an upload, refusing anything past the size ceiling.

    Read in chunks and stop at the limit so an oversized upload cannot be
    used to exhaust memory before the check runs.
    """
    limit = _limits.max_file_bytes
    buffer = bytearray()
    while True:
        piece = await file.read(1024 * 1024)
        if not piece:
            break
        buffer.extend(piece)
        if len(buffer) > limit:
            raise HTTPException(413, f"File exceeds the {limit:,}-byte limit.")
    if not buffer:
        raise HTTPException(400, "Empty upload.")
    return bytes(buffer)


def _options(
    frontmatter: bool,
    page_anchors: bool,
    images: str,
    tables: str,
    chunk: bool,
    chunk_size: int,
    ocr: bool,
) -> ConvertOptions:
    if images not in ("extract", "reference", "placeholder", "omit"):
        raise HTTPException(400, "images must be extract, reference, placeholder or omit")
    if tables not in ("pipe", "html", "csv"):
        raise HTTPException(400, "tables must be pipe, html or csv")
    return ConvertOptions(
        frontmatter=frontmatter,
        page_anchors=page_anchors,
        images=images,  # type: ignore[arg-type]
        table_format=tables,  # type: ignore[arg-type]
        chunk=chunk,
        chunk_size=max(200, min(chunk_size, 8000)),
        ocr=ocr,
        limits=_limits,
    )


def _bundle(result: ConversionResult, filename: str) -> Response:
    stem = filename.rsplit(".", 1)[0] or "document"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{stem}.md", result.markdown)
        archive.writestr(f"{stem}.json", result.document.to_json())
        if result.chunks:
            archive.writestr(f"{stem}.chunks.jsonl", to_jsonl(result.chunks))
        for asset in result.document.assets:
            if asset.data:
                archive.writestr(f"assets/{safe_name(asset.filename, asset.asset_id)}", asset.data)
        archive.writestr(
            "manifest.json",
            json.dumps(result.summary(), indent=2, ensure_ascii=False),
        )
    return Response(
        buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{stem}-papyrus.zip"'},
    )
