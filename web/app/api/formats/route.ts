import { NextResponse } from "next/server";

const API = process.env.PAPYRUS_API_URL ?? "http://127.0.0.1:8787";

export const runtime = "nodejs";
export const revalidate = 60;

export async function GET() {
  try {
    const response = await fetch(`${API}/v1/formats`, { next: { revalidate: 60 } });
    if (!response.ok) throw new Error("bad status");
    return NextResponse.json(await response.json());
  } catch {
    return NextResponse.json({ error: "Engine unreachable", code: "engine_unreachable" }, { status: 503 });
  }
}
