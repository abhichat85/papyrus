# AGENTS.md

Instructions for AI coding agents working on Papyrus. Read this before
changing anything. `CLAUDE.md` points here; this file is the source of truth.

## What Papyrus is

A universal document ingestion engine. Any file in, agent-ready Markdown
out. It is a deterministic library first, with a CLI, an HTTP API and a
demo web app layered on top.

## The one rule

```
bytes → detect → parser → Document IR → renderer → markdown
                              ↓
                          chunks.jsonl
```

**Parsers never emit Markdown. Renderers never parse files.** Everything
meets at the Document IR (`src/papyrus/ir.py`). If you find yourself
writing a `#` or a `|` inside `src/papyrus/parsers/`, stop — that string
belongs in `src/papyrus/renderers/markdown.py`.

This is what makes a new format a single self-contained file. Breaking it
costs the project its main property, so it is not a stylistic preference.

## Core principles

1. **Degrade, don't crash.** Messy input produces a `Document` with a
   warning appended. Only genuinely unreadable input raises `ParseError`.
   A parser that raises something unexpected is wrapped by `Converter` and
   surfaces as `ParseError` — never a bare traceback.
2. **Never trust a filename.** `detect()` reads magic bytes first. A PDF
   named `invoice.docx` is a PDF.
3. **No LLM in the conversion path.** Conversion is deterministic and
   free. Same bytes in, same Markdown out. An AI cleanup pass may exist
   later, but it is opt-in and it sits *after* the IR, never inside a
   parser.
4. **Use the format's own signal before a heuristic.** Word marks header
   rows with `w:tblHeader`; HTML has `<th>`; PyMuPDF reports the header it
   detected; `csv.Sniffer` exists. Guessing from cell contents is the
   fallback, not the first move — see `split_header(rows, hint)`.
5. **Preserve document order.** python-docx hands you `paragraphs` and
   `tables` as separate collections; python-pptx hands you shapes in
   z-order; PDF text and tables come from two different passes. All three
   are reconstructed. A table rendered under the wrong heading is a
   correctness bug, not a formatting nit.
6. **Every uploaded file is hostile.** Never execute input, never shell
   out, never write it outside a temp directory, always sanitise the
   filename with `safe_name()`. Every ceiling lives in `Limits`.
7. **Preserve provenance.** sha256, source format, page anchors. A
   converted document must be traceable to the bytes it came from.

## Layout

| Path | What lives there |
|---|---|
| `src/papyrus/ir.py` | The Document IR — the contract |
| `src/papyrus/detect.py` | Magic-byte and extension sniffing |
| `src/papyrus/parsers/` | One module per format family |
| `src/papyrus/renderers/markdown.py` | The only place that knows Markdown |
| `src/papyrus/chunking.py` | Heading-aware chunking for retrieval |
| `src/papyrus/converter.py` | Public API: `convert`, `convert_bytes` |
| `src/papyrus/config.py` | `ConvertOptions` and `Limits` |
| `src/papyrus/cli.py` | `papyrus` command |
| `src/papyrus/api/` | FastAPI service |
| `tests/make_fixtures.py` | Builds binary fixtures — do not commit blobs |
| `web/` | Next.js landing page and live demo |

## Commands

```bash
uv pip install -e ".[api,dev]"   # install
pytest                           # tests
ruff check src tests             # lint
ruff format src tests            # format
papyrus serve --port 8787        # API
npm --prefix web run dev         # web (needs the API running)
python tests/make_fixtures.py    # rebuild fixtures
python scripts/make_samples.py   # rebuild demo documents
```

## Adding a parser

1. Add the format to `FORMATS` in `detect.py`, with a magic-byte branch if
   the format has one.
2. Create `src/papyrus/parsers/<format>.py` implementing `BaseParser`.
3. Register it in `default_registry()` in `registry.py`. Order matters —
   `TextParser` must stay last, because it accepts everything.
4. Add a fixture generator to `tests/make_fixtures.py`.
5. Add tests that assert on *structure* (a table is a `Table`, a heading
   kept its level), not on exact output strings.
6. Cover the unhappy paths: empty file, truncated file, malformed input,
   non-UTF-8 bytes, and something larger than the relevant limit.

## Definition of done

A change is complete only when all of these hold:

- `pytest` passes, and the new behaviour has a test that fails without the fix.
- `ruff check src tests` passes.
- Error paths are covered, not just the happy path.
- No unrelated files were modified.
- README or docs updated when observable behaviour changed.
- You ran the thing and looked at the output. "It should work" is not done.

## Do not

- Do not restructure the Document IR without being asked. Everything
  depends on it.
- Do not add an LLM call to a parser or the renderer.
- Do not persist uploaded documents anywhere.
- Do not add a dependency that duplicates something already present.
- Do not commit generated fixtures or sample documents.
- Do not weaken a limit in `Limits` to make a test pass.
- Do not claim a conversion works without having read the Markdown it
  produced.
