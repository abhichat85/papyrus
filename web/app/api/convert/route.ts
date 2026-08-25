import { NextRequest, NextResponse } from "next/server";

/**
 * Proxy to the Papyrus engine.
 *
 * The web app never parses documents itself — there is exactly one
 * implementation of the pipeline, in Python, and this route hands the
 * upload to it. Keeping the engine behind the proxy also means the browser
 * never talks to it directly, so it can stay bound to localhost.
 */

const API = process.env.PAPYRUS_API_URL ?? "http://127.0.0.1:8787";
const MAX_BYTES = 25 * 1024 * 1024;

export const runtime = "nodejs";
export const maxDuration = 60;

export async function POST(request: NextRequest) {
  let incoming: FormData;
  try {
    incoming = await request.formData();
  } catch {
    return NextResponse.json({ error: "Send the file as multipart/form-data.", code: "bad_request" }, { status: 400 });
  }

  const file = incoming.get("file");
  if (!(file instanceof File)) {
    return NextResponse.json({ error: "No file in the request.", code: "bad_request" }, { status: 400 });
  }
  if (file.size === 0) {
    return NextResponse.json({ error: "That file is empty.", code: "bad_request" }, { status: 400 });
  }
  if (file.size > MAX_BYTES) {
    return NextResponse.json(
      { error: `The demo accepts files up to 25 MB. Run Papyrus locally for anything larger.`, code: "file_too_large" },
      { status: 413 },
    );
  }

  const outgoing = new FormData();
  outgoing.append("file", file, file.name);
  outgoing.append("chunk", "true");
  outgoing.append("chunk_size", String(incoming.get("chunk_size") ?? 1200));
  outgoing.append("images", "placeholder");
  outgoing.append("frontmatter", String(incoming.get("frontmatter") ?? "true"));

  try {
    const response = await fetch(`${API}/v1/convert`, { method: "POST", body: outgoing });
    const payload = await response.json();
    if (!response.ok) {
      return NextResponse.json(
        { error: payload.error ?? "Conversion failed.", code: payload.code ?? "error" },
        { status: response.status },
      );
    }

    // Chunks come from the dedicated endpoint so the demo can show both
    // views from one drop without the user converting twice.
    let chunks: unknown[] = [];
    try {
      const chunkForm = new FormData();
      chunkForm.append("file", file, file.name);
      chunkForm.append("chunk_size", String(incoming.get("chunk_size") ?? 1200));
      const chunkResponse = await fetch(`${API}/v1/chunk`, { method: "POST", body: chunkForm });
      if (chunkResponse.ok) chunks = (await chunkResponse.json()).chunks ?? [];
    } catch {
      // Chunks are a bonus view; a failure here must not lose the Markdown.
    }

    return NextResponse.json({ ...payload, chunks });
  } catch {
    return NextResponse.json(
      {
        error: "The Papyrus engine is not reachable. Start it with `papyrus serve`.",
        code: "engine_unreachable",
      },
      { status: 503 },
    );
  }
}
