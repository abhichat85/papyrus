<div align="center">

# Papyrus

**The universal document ingestion engine.**
Any file in — clean, structured, agent-ready Markdown out.

`pdf` `docx` `pptx` `xlsx` `csv` `json` `html` `epub` `eml` `ipynb` `rtf` `zip` `images` `code` `text`

</div>

---

Every AI agent, RAG index and eval harness starts with the same unglamorous
problem: the knowledge is locked in files, and models read text. Papyrus is
the layer that turns *anything* into Markdown a model can actually use —
deterministically, locally, and without an LLM call in the hot path.

```bash
papyrus convert report.pdf
```

```markdown
---
title: Annual Report 2025
source: {filename: report.pdf, format: pdf, sha256: 9f2a...}
converted_at: '2026-08-21T10:04:11+00:00'
document: {pages: 48, author: Finance}
word_count: 11482
---

# Annual Report 2025

<!-- papyrus:page 1 -->

## Executive Summary

Revenue grew 41% year over year...

| Metric | 2024 | 2025 |
| --- | ---: | ---: |
| Revenue | $10.0M | $14.1M |
```

## Why not just extract text?

Text extraction throws away the structure a model needs to reason.

| | Naive extraction | Papyrus |
|---|---|---|
| Headings | lost | recovered from the PDF outline, font ranking, or style names |
| Tables | flattened into prose | GFM tables with inferred headers and numeric alignment |
| Reading order | z-order / stream order | geometric reading order, tables excluded from the text pass |
| Running headers | repeated on every page | detected across pages and dropped |
| Provenance | none | sha256, source format, page anchors in the output |
| Retrieval | your problem | heading-aware `chunks.jsonl`, ready to embed |

## Install

```bash
uv pip install -e ".[api]"
```

Optional extras: `[ocr]` for scanned PDFs and images (needs Tesseract on the
host), `[dev]` for the test suite.

## Use it

**CLI**

```bash
papyrus convert deck.pptx -o out/            # markdown + assets
papyrus convert report.pdf --chunk           # + chunks.jsonl for RAG
papyrus convert docs/ -o out/ --recursive    # whole directory
papyrus inspect contract.docx                # what did it detect, and why
papyrus formats                              # everything supported
```

**Python**

```python
from papyrus import convert, ConvertOptions

result = convert("report.pdf", ConvertOptions(chunk=True, images="extract"))

result.markdown          # str
result.document.blocks   # the IR — headings, tables, lists, code
result.chunks            # heading-aware chunks with page citations
result.write("out/")     # .md + .chunks.jsonl + assets/
```

**HTTP**

```bash
uvicorn papyrus.api.main:app --port 8787
curl -F file=@report.pdf http://localhost:8787/v1/convert
```

**MCP — give your agent eyes on any file**

```bash
claude mcp add papyrus -- papyrus-mcp
```

Your agent can already read `.txt` and `.md`. This lets it read the PDF, the
deck and the spreadsheet too. Five tools: `inspect_document` (what is this,
and what would reading it cost?), `convert_document`, `convert_to_file`,
`convert_to_chunks`, `list_supported_formats`. Long documents paginate with
the exact next call in the footer, so a 300-page report never blows the
context window.

| Endpoint | Purpose |
|---|---|
| `POST /v1/convert` | one file → Markdown (JSON, raw Markdown, or a zip bundle) |
| `POST /v1/chunk` | one file → chunks ready for an embedding job |
| `POST /v1/detect` | identify a file without converting it |
| `GET /v1/formats` | supported formats |
| `GET /healthz` | liveness |

**The demo site**

The landing page at `web/` is a live converter, not a mockup — drop a file
and it calls the same engine.

```bash
papyrus serve --port 8787        # terminal one
npm --prefix web run dev         # terminal two → http://localhost:3473
```

## Architecture

```
bytes ──▶ detect ──▶ parser ──▶ Document IR ──▶ renderer ──▶ markdown
             │          │            │              └─────▶ chunks.jsonl
          magic     one per      headings,          └─────▶ document.json
          bytes,    format       tables, lists,
          not the                code, images,
          filename               page anchors
```

The **Document IR** is the contract. Parsers never emit Markdown; renderers
never parse files. That is what makes a new format a self-contained ~150-line
file instead of a change to the whole pipeline — and it is why the same
engine can emit Markdown today and a different target tomorrow.

See [`AGENTS.md`](AGENTS.md) for the rules, and
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the detail.

## Safety

Papyrus is built to eat untrusted files. It never executes input, never
shells out, and holds everything in memory or a per-request temp dir that is
deleted on the way out. Enforced ceilings cover file size, PDF pages,
spreadsheet cells, CSV rows, archive members, compression ratio (zip bombs),
recursion depth and extracted assets. Uploaded filenames are sanitised
against path traversal before they touch disk.

## Live

| | |
|---|---|
| Demo | https://papyrus-web.vercel.app |
| Engine API | https://papyrus-engine.vercel.app |

The hosted demo caps uploads at **4 MB** — that is the serverless request-body
limit, not Papyrus's. Run it locally and the ceiling is 50 MB.

## Run it locally, entirely

```bash
docker compose up
```

Engine on `:8787`, web on `:3473`. No document leaves the machine. There is
no LLM call in the conversion path, so cost is deterministic and output is
reproducible: the same bytes in produce the same Markdown out.

## Develop

```bash
make install    # venv + dependencies
make test       # 181 tests
make lint
make serve      # API on :8787
make web        # landing page on :3473
```

Binary test fixtures and demo documents are **built, not committed** — a
`.docx` in git is an opaque blob nobody can review. `make fixtures` and
`make samples` regenerate them from `tests/make_fixtures.py` and
`scripts/make_samples.py`.

---

Built by [Einstein Labs](https://einsteinlabs.ai). Apache-2.0.
