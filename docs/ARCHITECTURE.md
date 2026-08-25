# Architecture

## The shape of the thing

```
             ┌──────────┐
  bytes ────▶│  detect  │  magic bytes first, filename only to break ties
             └────┬─────┘
                  ▼
             ┌──────────┐
             │  parser  │  one per format; never writes Markdown
             └────┬─────┘
                  ▼
        ╔═══════════════════╗
        ║   Document IR     ║  headings · lists · tables · code · images
        ║   (ir.py)         ║  page anchors · assets · warnings · provenance
        ╚════════┬══════════╝
                 │
     ┌───────────┼───────────┐
     ▼           ▼           ▼
 markdown    document.json  chunks.jsonl
```

Everything below follows from one decision: **the IR sits in the middle,
and nothing crosses it.**

## Why an IR

The obvious design is a function per format that returns a Markdown
string. It is shorter to write and it fails in three predictable ways.

1. **Markdown correctness gets re-implemented per format.** Escaping a
   pipe inside a table cell, widening a code fence past inner backticks,
   padding a ragged row — every parser has to get all of it right, and
   they never all do. With an IR, `renderers/markdown.py` gets it right
   once and every format inherits it.
2. **Options stop composing.** `--tables html`, `--no-frontmatter`,
   `--images placeholder` would each need handling in every parser.
   They're handled once, in the renderer.
3. **The output target gets welded on.** Chunking, a JSON dump for
   debugging, and any future target all read the IR. None of them could
   exist if the parsers had already flattened everything to text.

The cost is one indirection. It is worth it, and it is the rule in
[AGENTS.md](../AGENTS.md) that matters most.

## Detection

`detect.py` returns a `Detection` describing what a file is and how
confident it is.

Magic bytes decide first. `%PDF-` is a PDF whatever the extension says.
DOCX, XLSX, PPTX and EPUB are all ZIP containers, so those are
disambiguated by looking for `word/document.xml`, `xl/workbook.xml`,
`ppt/slides/`, or an OPF. Only when the content is genuinely ambiguous —
which is the normal case for text formats — does the extension get a vote.
An unknown extension falls back to content shape: a leading `{` is JSON, a
`<!DOCTYPE html>` is HTML, a null byte means binary.

Legacy OLE2 (`.doc`, `.xls`, `.ppt`) is *recognised* so it can be refused
with instructions, rather than half-parsed into garbage.

## Parsers

Each implements `BaseParser.parse(data, filename, detection, options) ->
Document`. They are independent — no parser imports another except where
one format genuinely embeds another (EPUB and email both reuse the HTML
walker, the archive parser recurses through the registry).

The three recurring problems, and how each is handled:

**Document order.** python-docx exposes `paragraphs` and `tables` as
separate collections, so `_iter_body()` walks the XML body directly.
python-pptx returns shapes in z-order, so `_reading_order()` sorts by
position. PDF text and tables come from two different passes, so tables
carry their `bbox` top and are interleaved by y-coordinate. In all three
cases the naive approach silently files content under the wrong heading.

**Header rows.** Telling a header from a data row by content alone is
unreliable — `| Metric | 2024 | 2025 |` is a header whose cells are
numbers. So `split_header(rows, hint)` takes a hint derived from the
format's own signal: `w:tblHeader`, `<th>`, PowerPoint's `firstRow`,
PyMuPDF's detected header, `csv.Sniffer().has_header()`. The content
heuristic is only the fallback.

**Displayed value vs stored value.** A spreadsheet stores 0.05 and
displays "5%". Dropping the number format turns a percentage into a
fraction — quiet corruption that nothing downstream can detect. The Excel
parser reads `number_format` and renders what the sheet shows.

### PDF specifically

PDF has no headings, paragraphs or lists — only glyphs at coordinates.
Everything structural is inferred, in descending order of trust:

1. the embedded outline (TOC), when the author left one;
2. font size, ranked relative to the document's most common size;
3. line shape — numbering, casing, length.

Tables are located geometrically first and their regions excluded from the
text pass, so cells never also appear as loose paragraphs. Lines that
repeat near the top or bottom of most pages are detected as running
headers and dropped — page furniture repeated once per page is the single
largest source of noise when a model reads a converted PDF. What was
removed is recorded in the frontmatter, so the removal is auditable.

## Rendering

`MarkdownRenderer` is deliberately dumb: it dispatches on block type and
formats. No inference, no cleanup. If the Markdown is wrong, the bug is in
a parser — that is the point of keeping the renderer stupid.

Output targets CommonMark plus GFM tables. Frontmatter carries provenance:
filename, format, byte count, sha256, word count, source metadata and any
warnings.

## Chunking

Chunking walks the **IR**, not the rendered string, which is what lets it
hold three guarantees a character-count splitter cannot:

- a table is never split away from its header row;
- a code block never loses its fence;
- every chunk carries the heading path in force where it starts
  (`Report › Q3 › Revenue`) and the page it came from, so a retrieved
  fragment can still cite its source.

Overlap is prose-only. Carrying the tail of a table into the next chunk
would produce orphan rows with no header — the exact structure the parsers
just worked to preserve.

## Safety

Papyrus is designed to eat untrusted files. It never executes input, never
shells out, and holds everything in memory. Every ceiling is in `Limits`
and every one is an environment variable:

| Guard | Default | Env |
|---|---|---|
| File size | 50 MB | `PAPYRUS_MAX_FILE_BYTES` |
| PDF pages | 2,000 | `PAPYRUS_MAX_PDF_PAGES` |
| Slides | 1,000 | `PAPYRUS_MAX_SLIDES` |
| Sheet rows | 20,000 | `PAPYRUS_MAX_SHEET_ROWS` |
| Table cells | 1,000,000 | `PAPYRUS_MAX_TABLE_CELLS` |
| CSV rows | 50,000 | `PAPYRUS_MAX_CSV_ROWS` |
| Archive members | 500 | `PAPYRUS_MAX_ARCHIVE_MEMBERS` |
| Compression ratio | 200:1 | `PAPYRUS_MAX_ARCHIVE_RATIO` |
| Archive expansion | 400 MB | `PAPYRUS_MAX_ARCHIVE_BYTES` |
| Archive nesting | 3 | — |
| Extracted assets | 500 | `PAPYRUS_MAX_ASSETS` |

Archive members with absolute paths or `..` segments are dropped before
they are read. Uploaded filenames go through `safe_name()` before touching
disk.

## What is deliberately absent

- **No LLM in the conversion path.** Cost stays predictable and output
  stays reproducible. An optional cleanup pass belongs after the IR.
- **No database, no queue, no auth.** The API is stateless; a request goes
  in and Markdown comes out. Anything that needs persistence should wrap
  Papyrus rather than live inside it.
- **No OCR by default.** It is an extra (`[ocr]`) because it needs
  Tesseract on the host and changes conversion from deterministic to
  approximate.
