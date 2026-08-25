import { gzipSync, gunzipSync } from "node:zlib";
import { NextRequest, NextResponse } from "next/server";
import { MAX_TOKEN_LENGTH, type SharePayload } from "@/lib/share";

/**
 * Turn a comparison into a share token, and back.
 *
 * The token *is* the data — gzipped JSON in base64url. Nothing is stored,
 * so there is no record of anyone's document on our side, and a link keeps
 * working forever without a database behind it.
 */

export const runtime = "nodejs";

export function encodeToken(payload: SharePayload): string {
  return gzipSync(Buffer.from(JSON.stringify(payload), "utf8")).toString("base64url");
}

export function decodeToken(token: string): SharePayload | null {
  try {
    if (token.length > MAX_TOKEN_LENGTH * 2) return null;
    const json = gunzipSync(Buffer.from(token, "base64url")).toString("utf8");
    const parsed = JSON.parse(json);
    if (!parsed || typeof parsed.n !== "string" || !Array.isArray(parsed.a)) return null;
    return parsed as SharePayload;
  } catch {
    return null;
  }
}

export async function POST(request: NextRequest) {
  let payload: SharePayload;
  try {
    payload = (await request.json()) as SharePayload;
  } catch {
    return NextResponse.json({ error: "Send the card payload as JSON." }, { status: 400 });
  }

  if (!payload?.n || !Array.isArray(payload.a)) {
    return NextResponse.json({ error: "That payload is missing its document." }, { status: 400 });
  }

  const token = encodeToken(payload);
  if (token.length > MAX_TOKEN_LENGTH) {
    // Shouldn't happen — buildPayload caps the excerpts — but a link that
    // some clients silently truncate is worse than a clear refusal.
    return NextResponse.json(
      { error: "That excerpt is too large to fit in a link." },
      { status: 413 },
    );
  }

  return NextResponse.json({ token, path: `/s/${token}` });
}
