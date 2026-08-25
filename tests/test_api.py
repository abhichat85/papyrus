"""HTTP surface.

The API is thin by design — these check the contract and the guards, not
the conversion logic, which `test_parsers.py` already covers.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from papyrus.api.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def _upload(fixtures, name: str) -> dict:
    return {"file": (name, (fixtures / name).read_bytes(), "application/octet-stream")}


# ── meta ─────────────────────────────────────────────────────────────


def test_healthz(client):
    assert client.get("/healthz").json()["status"] == "ok"


def test_formats_lists_every_parser(client):
    body = client.get("/v1/formats").json()
    assert body["count"] > 15
    assert "pdf" in body["formats"] and "docx" in body["formats"]
    assert body["max_file_bytes"] > 0


def test_openapi_schema_is_served(client):
    assert client.get("/openapi.json").status_code == 200


# ── detect ───────────────────────────────────────────────────────────


def test_detect_identifies_without_converting(client, fixtures):
    body = client.post("/v1/detect", files=_upload(fixtures, "sample.pdf")).json()
    assert body["format"] == "pdf"
    assert body["detected_via"] == "magic"
    assert body["supported"] is True


def test_detect_sees_through_a_lying_extension(client, fixtures):
    data = (fixtures / "sample.pdf").read_bytes()
    body = client.post("/v1/detect", files={"file": ("invoice.docx", data, "x")}).json()
    assert body["format"] == "pdf"


# ── convert ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", ["sample.pdf", "sample.docx", "sample.pptx", "sample.xlsx", "sample.csv"])
def test_convert_returns_markdown_and_provenance(client, fixtures, name):
    response = client.post("/v1/convert", files=_upload(fixtures, name))
    assert response.status_code == 200
    body = response.json()
    assert body["markdown"].strip()
    assert len(body["sha256"]) == 64
    assert body["word_count"] > 0
    assert body["duration_ms"] >= 0


def test_convert_can_return_raw_markdown(client, fixtures):
    response = client.post(
        "/v1/convert", files=_upload(fixtures, "sample.docx"), data={"response_format": "markdown"}
    )
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.text.startswith("---\n")


def test_convert_bundle_is_a_zip_with_everything(client, fixtures):
    response = client.post(
        "/v1/convert",
        files=_upload(fixtures, "sample.pptx"),
        data={"response_format": "bundle", "chunk": "true"},
    )
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
        assert "sample.md" in names
        assert "sample.json" in names
        assert "sample.chunks.jsonl" in names
        assert "manifest.json" in names
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["format"] == "pptx"
        # The IR in the bundle must be parseable, not just present.
        ir = json.loads(archive.read("sample.json"))
        assert ir["blocks"]


def test_convert_honours_rendering_options(client, fixtures):
    response = client.post(
        "/v1/convert",
        files=_upload(fixtures, "sample.pdf"),
        data={"frontmatter": "false", "page_anchors": "false"},
    )
    markdown = response.json()["markdown"]
    assert not markdown.startswith("---\n")
    assert "papyrus:page" not in markdown


def test_convert_rejects_an_unknown_response_format(client, fixtures):
    response = client.post(
        "/v1/convert", files=_upload(fixtures, "sample.csv"), data={"response_format": "xml"}
    )
    assert response.status_code == 400


def test_convert_rejects_an_invalid_image_mode(client, fixtures):
    response = client.post("/v1/convert", files=_upload(fixtures, "sample.csv"), data={"images": "sideways"})
    assert response.status_code == 400


# ── chunk ────────────────────────────────────────────────────────────


def test_chunk_returns_embedding_ready_records(client, fixtures):
    response = client.post("/v1/chunk", files=_upload(fixtures, "sample.pdf"), data={"chunk_size": "300"})
    body = response.json()
    assert body["chunk_count"] >= 1
    assert body["total_tokens"] > 0
    first = body["chunks"][0]
    assert set(first) >= {"id", "text", "heading_path", "pages", "token_estimate"}


# ── errors and guards ────────────────────────────────────────────────


def test_empty_upload_is_a_400(client):
    response = client.post("/v1/convert", files={"file": ("empty.txt", b"", "text/plain")})
    assert response.status_code == 400


def test_unsupported_format_is_a_415(client):
    ole2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 512
    response = client.post("/v1/convert", files={"file": ("old.doc", ole2, "application/msword")})
    assert response.status_code == 415
    assert response.json()["code"] == "unsupported_format"


def test_corrupt_document_is_a_422_not_a_500(client, fixtures):
    data = (fixtures / "sample.docx").read_bytes()[:400]
    response = client.post("/v1/convert", files={"file": ("broken.docx", data, "x")})
    assert response.status_code == 422
    assert response.json()["code"] == "parse_error"


def test_oversized_upload_is_a_413(client, monkeypatch):
    from papyrus.api import main

    monkeypatch.setattr(main._limits, "max_file_bytes", 1024)
    response = client.post("/v1/convert", files={"file": ("big.txt", b"x" * 4096, "text/plain")})
    assert response.status_code == 413


def test_upload_filename_cannot_escape_with_path_traversal(client):
    response = client.post(
        "/v1/convert", files={"file": ("../../etc/passwd.txt", b"root:x:0:0", "text/plain")}
    )
    assert response.status_code == 200
    assert "/" not in response.json()["filename"]
    assert ".." not in response.json()["filename"]
