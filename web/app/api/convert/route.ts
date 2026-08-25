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

// Serverless platforms cap request bodies well below what the engine can
// handle — Vercel at 4.5 MB. Locally there is no such cap, so the limit is
// configuration rather than a constant, and the message names the real
// reason so nobody goes hunting in the engine for it.
const MAX_BYTES = Number(process.env.PAPYRUS_MAX_UPLOAD_BYTES ?? 25 * 1024 * 1024);
const LIMIT_LABEL = MAX_BYTES >= 1024 * 1024
  ? `${Math.round(MAX_BYTES / (1024 * 1024))} MB`
  : `${Math.round(MAX_BYTES / 1024)} KB`;

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
      {
        error: `This demo accepts files up to ${LIMIT_LABEL}. Papyrus itself handles 50 MB — run it locally for anything larger.`,
        code: "file_too_large",
      },
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
