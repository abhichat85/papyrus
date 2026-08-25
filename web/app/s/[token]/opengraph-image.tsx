import { ImageResponse } from "next/og";
import { decodeToken } from "@/app/api/share/route";

/**
 * The card that actually spreads.
 *
 * Someone converts a document they were stuck on, screenshots the result,
 * and posts it. This is that screenshot, generated so it looks the same
 * everywhere — the before/after split, with the recovered-structure count
 * as the punchline.
 */

export const runtime = "nodejs";
export const alt = "Before and after: document converted to Markdown by Papyrus";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const VELLUM = "#eff0ea";
const INK = "#171a1d";
const INK_SOFT = "#5d646c";
const CINNABAR = "#be3a24";
const LAPIS = "#1f3fa8";
const RULE = "rgba(23,26,29,0.14)";

export default async function Image({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  const payload = decodeToken(token);

  const before = (payload?.b ?? []).slice(0, 9);
  const after = (payload?.a ?? []).slice(0, 11);
  const headline = payload?.h ?? "Any file in. Markdown out.";
  const name = payload?.n ?? "document";

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          background: VELLUM,
          color: INK,
          fontFamily: "monospace",
        }}
      >
        {/* header */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "26px 44px",
            borderBottom: `1px solid ${RULE}`,
          }}
        >
          <div style={{ display: "flex", alignItems: "baseline", gap: 14 }}>
            <span style={{ fontSize: 32, fontWeight: 700, letterSpacing: "-0.02em" }}>Papyrus</span>
            <span style={{ fontSize: 18, color: INK_SOFT }}>{name}</span>
          </div>
          <span style={{ fontSize: 18, color: INK_SOFT, letterSpacing: "0.12em" }}>
            {(payload?.f ?? "file").toUpperCase()} → MARKDOWN
          </span>
        </div>

        {/* the split */}
        <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              width: "46%",
              padding: "20px 26px 20px 44px",
              borderRight: `1px solid ${RULE}`,
            }}
          >
            <span style={{ fontSize: 15, color: INK_SOFT, letterSpacing: "0.14em", marginBottom: 12 }}>
              TEXT EXTRACTION
            </span>
            <div style={{ display: "flex", flexDirection: "column", color: INK_SOFT }}>
              {before.map((line, index) => (
                <span key={index} style={{ fontSize: 15, lineHeight: 1.55 }}>
                  {line.slice(0, 46) || " "}
                </span>
              ))}
            </div>
          </div>

          <div style={{ display: "flex", flexDirection: "column", flex: 1, padding: "20px 44px 20px 26px" }}>
            <span style={{ fontSize: 15, color: INK_SOFT, letterSpacing: "0.14em", marginBottom: 12 }}>
              PAPYRUS
            </span>
            <div style={{ display: "flex", flexDirection: "column" }}>
              {after.map((line, index) => {
                const heading = line.trimStart().startsWith("#");
                const table = line.trimStart().startsWith("|");
                return (
                  <span
                    key={index}
                    style={{
                      fontSize: 15,
                      lineHeight: 1.55,
                      color: heading ? CINNABAR : table ? LAPIS : INK,
                      fontWeight: heading ? 700 : 400,
                    }}
                  >
                    {line.slice(0, 54) || " "}
                  </span>
                );
              })}
            </div>
          </div>
        </div>

        {/* punchline */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            padding: "22px 44px",
            borderTop: `1px solid ${RULE}`,
            background: "rgba(190,58,36,0.06)",
          }}
        >
          <span style={{ fontSize: 26, fontWeight: 700, letterSpacing: "-0.01em" }}>{headline}</span>
        </div>
      </div>
    ),
    size,
  );
}
