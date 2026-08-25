import { describe, expect, it } from "vitest";
import { gunzipSync, gzipSync } from "node:zlib";
import { buildPayload, MAX_TOKEN_LENGTH, type SharePayload } from "./share";

// The route module pulls in next/server, which is awkward under vitest, so
// the codec is exercised through the same two calls the route makes.
const encode = (p: SharePayload) =>
  gzipSync(Buffer.from(JSON.stringify(p), "utf8")).toString("base64url");
const decode = (t: string) =>
  JSON.parse(gunzipSync(Buffer.from(t, "base64url")).toString("utf8")) as SharePayload;

const MARKDOWN = `---
title: Quarterly Review
source:
  sha256: abc123
---

# Quarterly Review

Opening paragraph that survives naive extraction perfectly well.

## The numbers

| Metric | FY 2024 | FY 2025 |
| --- | ---: | ---: |
| Revenue | 10,040,000 | 14,120,000 |
| EBITDA | 905,000 | 2,140,000 |

## Decisions needed

Something after the table.
`;

const BASELINE = `Quarterly Review
Opening paragraph that survives naive extraction perfectly well.
The numbers
Decisions needed
Something after the table.`;

function build(overrides: Partial<Parameters<typeof buildPayload>[0]> = {}) {
  return buildPayload({
    filename: "quarterly-review.docx",
    format: "docx",
    title: "Quarterly Review",
    headline: "Recovered 1 table (24 cells), 4 headings.",
    baseline: BASELINE,
    markdown: MARKDOWN,
    recovered: { headings: 4, tables: 1, table_cells: 24, list_items: 9, pages: 0, running_headers_removed: 0 },
    ...overrides,
  });
}

describe("buildPayload", () => {
  it("drops the frontmatter without truncating at a table separator", () => {
    // `markdown.split("---")` also splits on `| --- | ---: |`, so a naive
    // slice loses the entire table.
    const payload = build();
    expect(payload.a.join("\n")).toContain("| Revenue | 10,040,000 | 14,120,000 |");
    expect(payload.a.join("\n")).not.toContain("sha256");
  });

  it("centres the excerpt on the recovered table, not the opening prose", () => {
    const payload = build();
    expect(payload.a[0]).toBe("## The numbers");
    expect(payload.a.join("\n")).not.toContain("Opening paragraph");
  });

  it("aligns the baseline to the same heading so the loss is visible", () => {
    const payload = build();
    expect(payload.b[0]).toBe("The numbers");
    expect(payload.b[1]).toBe("Decisions needed");
    expect(payload.b.join("\n")).not.toContain("Revenue");
  });

  it("falls back to the start when there is no table", () => {
    const payload = build({ markdown: "# Title\n\nJust prose here.\n" });
    expect(payload.a[0]).toBe("# Title");
  });

  it("clips long lines rather than letting the card overflow", () => {
    const long = `# H\n\n| ${"x".repeat(400)} |\n| --- |\n`;
    const payload = build({ markdown: long });
    expect(Math.max(...payload.a.map((l) => l.length))).toBeLessThanOrEqual(72);
  });

  it("keeps the recovered counts in a fixed order", () => {
    expect(build().r).toEqual([4, 1, 24, 9, 0, 0]);
  });

  it("survives a document with no baseline at all", () => {
    const payload = build({ baseline: "" });
    expect(payload.b).toEqual([]);
    expect(payload.a.length).toBeGreaterThan(0);
  });
});

describe("token codec", () => {
  it("round-trips a payload exactly", () => {
    const payload = build();
    expect(decode(encode(payload))).toEqual(payload);
  });

  it("produces a URL-safe token", () => {
    expect(encode(build())).toMatch(/^[A-Za-z0-9_-]+$/);
  });

  it("stays inside the link budget for a realistic document", () => {
    expect(encode(build()).length).toBeLessThan(MAX_TOKEN_LENGTH);
  });

  it("stays inside the budget even at maximum excerpt size", () => {
    const dense = ["# Heading", "", ...Array.from({ length: 40 }, (_, i) => `| cell ${i} | ${"v".repeat(60)} |`)].join("\n");
    const payload = build({ markdown: dense, baseline: "line\n".repeat(60) });
    expect(encode(payload).length).toBeLessThan(MAX_TOKEN_LENGTH);
  });

  it("round-trips non-Latin content", () => {
    const payload = build({ markdown: "# 多言語\n\n| 列 | 値 |\n| --- | --- |\n| مرحبا | 🚀 |\n", title: "多言語" });
    expect(decode(encode(payload)).a.join("\n")).toContain("مرحبا");
  });
});
