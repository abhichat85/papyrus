"""Request and response models for the HTTP API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ConvertResponse(BaseModel):
    markdown: str = Field(description="The converted document.")
    title: str | None = None
    format: str
    detected_via: str
    filename: str
    sha256: str
    word_count: int
    block_count: int
    assets: list[dict[str, Any]] = []
    warnings: list[str] = []
    duration_ms: int


class ChunkModel(BaseModel):
    id: str
    index: int
    text: str
    heading_path: list[str]
    pages: list[int]
    char_count: int
    token_estimate: int
    source: dict[str, Any]


class ChunkResponse(BaseModel):
    filename: str
    format: str
    title: str | None = None
    chunk_count: int
    total_tokens: int
    chunks: list[ChunkModel]
    warnings: list[str] = []
    duration_ms: int


class CompareResponse(BaseModel):
    filename: str
    format: str
    title: str | None = None
    baseline: str = Field(description="What a one-line text extraction returns.")
    markdown: str = Field(description="What Papyrus returns.")
    recovered: dict[str, int]
    headline: str
    warnings: list[str] = []
    duration_ms: int


class DetectResponse(BaseModel):
    filename: str
    format: str
    media_type: str
    extension: str
    confidence: float
    detected_via: str
    size_bytes: int
    supported: bool
    handled_by: str | None = None


class FormatsResponse(BaseModel):
    count: int
    formats: dict[str, str]
    max_file_bytes: int
    version: str


class ErrorResponse(BaseModel):
    error: str
    code: str
    detail: str | None = None


ResponseFormat = Literal["json", "markdown", "bundle"]
