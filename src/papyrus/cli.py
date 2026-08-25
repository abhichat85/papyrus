"""`papyrus` — the command line.

papyrus convert report.pdf                  # markdown to stdout
papyrus convert docs/ -o out/ --recursive   # a whole tree
papyrus convert deck.pptx --chunk           # + chunks.jsonl
papyrus inspect weird.bin                   # what is this, and why
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table as RichTable

from papyrus import __version__
from papyrus.config import ConvertOptions, Limits
from papyrus.converter import ConversionResult, Converter
from papyrus.detect import detect
from papyrus.errors import PapyrusError
from papyrus.utils.files import human_bytes

app = typer.Typer(
    name="papyrus",
    help="Universal document ingestion — any file in, agent-ready Markdown out.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console(stderr=True)
out = Console()

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".next", "dist", "build"}


@app.command()
def convert(
    paths: Annotated[list[Path], typer.Argument(help="Files or directories to convert.")],
    output: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write a bundle here instead of stdout.")
    ] = None,
    recursive: Annotated[bool, typer.Option("--recursive", "-r", help="Descend into directories.")] = False,
    chunk: Annotated[bool, typer.Option("--chunk", help="Also emit heading-aware chunks.jsonl.")] = False,
    chunk_size: Annotated[int, typer.Option("--chunk-size", help="Target characters per chunk.")] = 1200,
    chunk_overlap: Annotated[
        int, typer.Option("--chunk-overlap", help="Characters carried between chunks.")
    ] = 120,
    ir: Annotated[bool, typer.Option("--ir", help="Also write the Document IR as JSON.")] = False,
    frontmatter: Annotated[
        bool, typer.Option("--frontmatter/--no-frontmatter", help="YAML provenance header.")
    ] = True,
    images: Annotated[
        str, typer.Option("--images", help="extract | reference | placeholder | omit")
    ] = "reference",
    page_anchors: Annotated[
        bool, typer.Option("--page-anchors/--no-page-anchors", help="Emit <!-- papyrus:page N -->.")
    ] = True,
    tables: Annotated[str, typer.Option("--tables", help="pipe | html | csv")] = "pipe",
    ocr: Annotated[
        bool, typer.Option("--ocr", help="OCR scanned pages and images (needs Tesseract).")
    ] = False,
    hidden_sheets: Annotated[
        bool, typer.Option("--hidden-sheets", help="Include hidden spreadsheet sheets.")
    ] = False,
    max_mb: Annotated[int, typer.Option("--max-mb", help="Per-file size ceiling.")] = 50,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress the summary.")] = False,
) -> None:
    """Convert files to Markdown."""
    if images not in ("extract", "reference", "placeholder", "omit"):
        raise typer.BadParameter("--images must be extract, reference, placeholder or omit")
    if tables not in ("pipe", "html", "csv"):
        raise typer.BadParameter("--tables must be pipe, html or csv")

    options = ConvertOptions(
        frontmatter=frontmatter,
        page_anchors=page_anchors,
        images=images,  # type: ignore[arg-type]
        table_format=tables,  # type: ignore[arg-type]
        chunk=chunk,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        ocr=ocr,
        include_hidden_sheets=hidden_sheets,
        limits=Limits(max_file_bytes=max_mb * 1024 * 1024),
    )

    targets = _collect(paths, recursive)
    if not targets:
        console.print("[red]No files to convert.[/red]")
        raise typer.Exit(1)
    if output is None and len(targets) > 1:
        console.print("[red]Multiple files need --out; stdout can only carry one document.[/red]")
        raise typer.Exit(2)

    converter = Converter(options=options)
    results: list[tuple[Path, ConversionResult]] = []
    failures: list[tuple[Path, str]] = []
    used: set[str] = set()

    for path in targets:
        try:
            result = converter.convert(path)
        except PapyrusError as exc:
            failures.append((path, str(exc)))
            console.print(f"[red]✗[/red] {path} — {exc}")
            continue
        results.append((path, result))

        if output is None:
            out.file.write(result.markdown)
        else:
            written = result.write(output, stem=_stem(path, paths, used))
            if ir:
                result.write_ir(written["markdown"].with_suffix(".json"))
            if not quiet:
                console.print(f"[green]✓[/green] {path} → {written['markdown']}")

    if not quiet and (output is not None or len(results) > 1):
        _summary(results, failures)
    if failures and not results:
        raise typer.Exit(1)


@app.command()
def inspect(
    path: Annotated[Path, typer.Argument(help="File to identify and profile.")],
    show: Annotated[int, typer.Option("--show", help="Lines of Markdown to preview.")] = 20,
) -> None:
    """Identify a file and report what conversion would produce."""
    if not path.is_file():
        console.print(f"[red]Not a file: {path}[/red]")
        raise typer.Exit(1)

    data = path.read_bytes()
    detection = detect(path.name, data)

    facts = RichTable(show_header=False, box=None, pad_edge=False)
    facts.add_column(style="dim")
    facts.add_column()
    facts.add_row("file", str(path))
    facts.add_row("size", human_bytes(len(data)))
    facts.add_row("format", f"[bold]{detection.format}[/bold]")
    facts.add_row("media type", detection.media_type)
    facts.add_row("detected via", f"{detection.via} (confidence {detection.confidence:.0%})")

    try:
        result = Converter().convert_bytes(data, path.name)
    except PapyrusError as exc:
        facts.add_row("conversion", f"[red]{exc}[/red]")
        console.print(facts)
        raise typer.Exit(1) from exc

    counts: dict[str, int] = {}
    for block in result.document.blocks:
        counts[block.type] = counts.get(block.type, 0) + 1

    facts.add_row("title", result.document.title or "[dim]none[/dim]")
    facts.add_row("blocks", ", ".join(f"{k} x{v}" for k, v in sorted(counts.items())) or "none")
    facts.add_row("words", f"{result.document.word_count:,}")
    facts.add_row("assets", str(len(result.document.assets)))
    facts.add_row("duration", f"{result.duration_ms} ms")
    for key, value in result.document.metadata.items():
        if not key.startswith("_"):
            facts.add_row(f"meta.{key}", str(value)[:90])
    for warning in result.warnings:
        facts.add_row("[yellow]warning[/yellow]", warning)
    console.print(facts)

    if show > 0:
        console.rule("[dim]markdown preview[/dim]")
        body = result.markdown.split("---", 2)[-1].strip().splitlines()
        for line in body[:show]:
            console.print(line, markup=False, highlight=False)
        if len(body) > show:
            console.print(f"[dim]... {len(body) - show} more lines[/dim]")


@app.command()
def formats() -> None:
    """List every supported format."""
    table = RichTable(title="Papyrus supported formats")
    table.add_column("format", style="bold cyan")
    table.add_column("handled by")
    for fmt, label in Converter().supported_formats().items():
        table.add_row(fmt, label)
    console.print(table)


@app.command()
def serve(
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port")] = 8787,
    reload: Annotated[bool, typer.Option("--reload")] = False,
) -> None:
    """Run the HTTP API."""
    try:
        import uvicorn
    except ImportError as exc:
        console.print("[red]Install the API extra: uv pip install 'papyrus-engine[api]'[/red]")
        raise typer.Exit(1) from exc
    uvicorn.run("papyrus.api.main:app", host=host, port=port, reload=reload)


@app.command()
def version() -> None:
    """Print the version."""
    out.print(f"papyrus {__version__}")


# ── helpers ──────────────────────────────────────────────────────────


def _collect(paths: list[Path], recursive: bool) -> list[Path]:
    found: list[Path] = []
    for path in paths:
        if path.is_file():
            found.append(path)
        elif path.is_dir():
            pattern = "**/*" if recursive else "*"
            for child in sorted(path.glob(pattern)):
                if child.is_file() and not any(p in SKIP_DIRS for p in child.parts):
                    found.append(child)
        else:
            console.print(f"[yellow]skipped[/yellow] {path} — not found")
    return found


def _stem(path: Path, roots: list[Path], used: set[str]) -> str:
    """Flatten a source path into a unique output stem.

    `a/b/c.pdf` becomes `a-b-c`. Because the extension is dropped, a
    directory holding `report.pdf` and `report.docx` would collide and one
    conversion would silently overwrite the other — so collisions fall back
    to including the extension, then a counter.
    """
    base = path.stem
    for root in roots:
        if root.is_dir():
            try:
                base = "-".join(path.relative_to(root).with_suffix("").parts)
                break
            except ValueError:
                continue

    candidate = base
    if candidate in used:
        candidate = f"{base}-{path.suffix.lstrip('.')}" if path.suffix else base
    counter = 2
    while candidate in used:
        candidate = f"{base}-{counter}"
        counter += 1
    used.add(candidate)
    return candidate


def _summary(results: list[tuple[Path, ConversionResult]], failures: list[tuple[Path, str]]) -> None:
    if not results and not failures:
        return
    words = sum(r.document.word_count for _, r in results)
    chunks = sum(len(r.chunks) for _, r in results)
    ms = sum(r.duration_ms for _, r in results)
    warnings = sum(len(r.warnings) for _, r in results)

    console.rule()
    parts = [f"[green]{len(results)} converted[/green]", f"{words:,} words"]
    if chunks:
        parts.append(f"{chunks} chunks")
    if warnings:
        parts.append(f"[yellow]{warnings} warnings[/yellow]")
    if failures:
        parts.append(f"[red]{len(failures)} failed[/red]")
    parts.append(f"{ms} ms")
    console.print("  ·  ".join(parts))


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
