import { NextResponse } from "next/server";

const API = process.env.PAPYRUS_API_URL ?? "http://127.0.0.1:8787";

export const runtime = "nodejs";
export const revalidate = 60;

const MAX_BYTES = Number(process.env.PAPYRUS_MAX_UPLOAD_BYTES ?? 25 * 1024 * 1024);

export async function GET() {
  const uploadLimit = {
    upload_limit_bytes: MAX_BYTES,
    upload_limit_label:
      MAX_BYTES >= 1024 * 1024
        ? `${Math.round(MAX_BYTES / (1024 * 1024))} MB`
        : `${Math.round(MAX_BYTES / 1024)} KB`,
  };
  try {
    const response = await fetch(`${API}/v1/formats`, { next: { revalidate: 60 } });
    if (!response.ok) throw new Error("bad status");
    return NextResponse.json({ ...(await response.json()), ...uploadLimit });
  } catch {
    return NextResponse.json(
      { error: "Engine unreachable", code: "engine_unreachable", ...uploadLimit },
      { status: 503 },
    );
  }
}
