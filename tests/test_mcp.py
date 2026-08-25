"""The MCP server, driven through the real client/server session.

These call the tools the way an agent does — over a stdio transport with a
real handshake — rather than calling the Python functions directly. That is
the only way to catch a schema the SDK rejects or a return value it cannot
serialise.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def session():
    """A live MCP session against `papyrus-mcp` over stdio.

    The session runs on a dedicated thread that owns its event loop, so the
    async context managers are entered and exited by the same task. Driving
    them from the test thread instead trips anyio's cancel-scope check at
    teardown.
    """
    import asyncio
    import threading

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    loop = asyncio.new_event_loop()
    ready = threading.Event()
    state: dict[str, object] = {}

    async def serve():
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "papyrus.mcp.server"], env=None
        )
        stop = asyncio.Event()
        state["stop"] = stop
        try:
            async with (
                stdio_client(params) as (read, write),
                ClientSession(read, write) as client,
            ):
                await client.initialize()
                state["client"] = client
                ready.set()
                await stop.wait()
        finally:
            ready.set()

    def run() -> None:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(serve())

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    ready.wait(timeout=30)
    client = state.get("client")
    if client is None:
        pytest.fail("MCP server did not start")

    def submit(coro):
        return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=60)

    class Bridge:
        def call(self, name: str, **arguments) -> str:
            result = submit(client.call_tool(name, arguments))
            return "\n".join(
                block.text for block in result.content if getattr(block, "text", None)
            )

        def tools(self) -> list[str]:
            return [tool.name for tool in submit(client.list_tools()).tools]

    yield Bridge()

    loop.call_soon_threadsafe(state["stop"].set)
    thread.join(timeout=10)
    loop.close()


def test_server_advertises_its_tools(session):
    names = session.tools()
    assert {
        "inspect_document",
        "convert_document",
        "convert_to_file",
        "convert_to_chunks",
        "list_supported_formats",
    } <= set(names)


def test_list_formats_reports_the_whole_registry(session):
    output = session.call("list_supported_formats")
    assert "pdf" in output and "docx" in output and "xlsx" in output
    assert "formats" in output


def test_inspect_reports_cost_before_spending_it(session):
    """An agent should be able to decide whether reading is worth it."""
    import json

    payload = json.loads(session.call("inspect_document", path=str(FIXTURES / "sample.pdf")))
    assert payload["format"] == "pdf"
    assert payload["detected_via"] == "magic"
    assert payload["convertible"] is True
    assert payload["approx_tokens"] > 0
    assert payload["reads_in_one_call"] is True
    assert "heading" in payload["structure"]


def test_inspect_sees_through_a_lying_extension(session):
    import json
    import shutil
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        fake = Path(tmp) / "invoice.docx"
        shutil.copy(FIXTURES / "sample.pdf", fake)
        payload = json.loads(session.call("inspect_document", path=str(fake)))
    assert payload["format"] == "pdf"


def test_convert_returns_markdown_an_agent_can_read(session):
    output = session.call("convert_document", path=str(FIXTURES / "sample.docx"))
    assert "## Highlights" in output
    assert "| Metric | 2024 | 2025 |" in output
    assert not output.startswith("---\ntitle:"), "frontmatter is off by default for agents"


def test_convert_paginates_and_says_how_to_continue(session):
    """The footer must contain the literal next call, not a vague hint."""
    path = str(FIXTURES / "hard" / "server.log")
    first = session.call("convert_document", path=path, max_chars=1000)
    assert "offset=" in first
    assert "convert_document" in first

    offset = int(first.split("offset=")[1].split(")")[0])
    second = session.call("convert_document", path=path, offset=offset, max_chars=1000)
    assert second.strip()
    assert second[:200] not in first


def test_convert_surfaces_warnings_to_the_agent(session):
    output = session.call("convert_document", path=str(FIXTURES / "hard" / "scanned.pdf"))
    assert "Papyrus notes" in output
    assert "scanned" in output.lower()


def test_convert_to_file_costs_almost_no_context(session, tmp_path):
    receipt = session.call(
        "convert_to_file", path=str(FIXTURES / "sample.pptx"), output_dir=str(tmp_path)
    )
    assert "Wrote 1 file" in receipt
    assert (tmp_path / "sample.md").exists()
    assert len(receipt) < 400, "receipt should be short by design"


def test_convert_to_file_handles_a_whole_folder(session, tmp_path):
    receipt = session.call(
        "convert_to_file", path=str(FIXTURES), output_dir=str(tmp_path), recursive=False
    )
    written = list(tmp_path.glob("*.md"))
    assert len(written) >= 16
    assert len({p.name for p in written}) == len(written), "outputs collided"
    assert "Wrote" in receipt


def test_chunks_carry_citations(session):
    import json

    output = session.call(
        "convert_to_chunks", path=str(FIXTURES / "sample.pdf"), chunk_size=400
    )
    assert "chunks" in output
    body = output.split("\n\n", 1)[1]
    first = json.loads(body.splitlines()[0])
    assert first["heading_path"]
    assert "sha256" in first["source"]


def test_chunks_can_be_written_to_disk(session, tmp_path):
    out = tmp_path / "chunks.jsonl"
    receipt = session.call(
        "convert_to_chunks", path=str(FIXTURES / "sample.pdf"), save_to=str(out)
    )
    assert out.exists()
    assert "Wrote" in receipt
    assert out.read_text().strip()


def test_a_missing_file_is_a_message_not_a_crash(session):
    output = session.call("convert_document", path="/nonexistent/nope.pdf")
    assert "Not a file" in output


def test_an_unconvertible_file_explains_itself(session, tmp_path):
    import json

    legacy = tmp_path / "ancient.doc"
    legacy.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 512)
    payload = json.loads(session.call("inspect_document", path=str(legacy)))
    assert payload["convertible"] is False
    assert "docx" in payload["error"]
