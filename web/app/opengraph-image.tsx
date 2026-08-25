import { ImageResponse } from "next/og";

/** The link preview for the site itself: the thesis, stated once. */

export const runtime = "nodejs";
export const alt = "Papyrus — any file in, agent-ready Markdown out";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const VELLUM = "#eff0ea";
const INK = "#171a1d";
const INK_SOFT = "#5d646c";
const CINNABAR = "#be3a24";
const LAPIS = "#1f3fa8";
const RULE = "rgba(23,26,29,0.14)";

const FORMATS = [
  "pdf", "docx", "pptx", "xlsx", "html", "epub", "eml",
  "ipynb", "csv", "json", "xml", "rtf", "zip", "images", "code",
];

export default function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: VELLUM,
          color: INK,
          fontFamily: "monospace",
          padding: "60px 64px",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column" }}>
          <span style={{ fontSize: 26, color: INK_SOFT, letterSpacing: "0.16em" }}>PAPYRUS</span>
          <span style={{ fontSize: 86, fontWeight: 700, letterSpacing: "-0.035em", marginTop: 26 }}>
            Any file in.
          </span>
          <span style={{ fontSize: 86, fontWeight: 700, letterSpacing: "-0.035em", color: LAPIS }}>
            Markdown out.
          </span>
        </div>

        <div style={{ display: "flex", flexWrap: "wrap", gap: 10, maxWidth: 900 }}>
          {FORMATS.map((format) => (
            <span
              key={format}
              style={{
                fontSize: 20,
                color: INK_SOFT,
                border: `1px solid ${RULE}`,
                padding: "5px 12px",
              }}
            >
              {format}
            </span>
          ))}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 30, fontSize: 22, color: INK }}>
          <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ width: 9, height: 9, background: CINNABAR }} />
            Structure preserved
          </span>
          <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ width: 9, height: 9, background: CINNABAR }} />
            No LLM in the path
          </span>
          <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ width: 9, height: 9, background: CINNABAR }} />
            Runs on your machine
          </span>
        </div>
      </div>
    ),
    size,
  );
}
