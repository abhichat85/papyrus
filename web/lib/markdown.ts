/**
 * Minimal Markdown tokenizer for the preview pane.
 *
 * This is not a renderer — the output pane deliberately shows the raw
 * Markdown, because the raw Markdown is the product. It only marks up
 * enough to rubricate: headings in cinnabar, tables and fences in lapis,
 * frontmatter and page anchors dimmed.
 */

export type Line = { text: string; kind: "h" | "fm" | "tbl" | "fence" | "anchor" | "text"; depth?: number };

export function tokenize(markdown: string): Line[] {
  const out: Line[] = [];
  let inFrontmatter = false;
  let inFence = false;

  markdown.split("\n").forEach((text, index) => {
    if (index === 0 && text.trim() === "---") {
      inFrontmatter = true;
      out.push({ text, kind: "fm" });
      return;
    }
    if (inFrontmatter) {
      if (text.trim() === "---") inFrontmatter = false;
      out.push({ text, kind: "fm" });
      return;
    }
    if (text.trimStart().startsWith("```")) {
      inFence = !inFence;
      out.push({ text, kind: "fence" });
      return;
    }
    if (inFence) {
      out.push({ text, kind: "text" });
      return;
    }
    const heading = /^(#{1,6})\s+/.exec(text);
    if (heading) {
      out.push({ text, kind: "h", depth: heading[1].length });
      return;
    }
    if (text.startsWith("<!-- papyrus:page")) {
      out.push({ text, kind: "anchor" });
      return;
    }
    if (text.startsWith("|")) {
      out.push({ text, kind: "tbl" });
      return;
    }
    out.push({ text, kind: "text" });
  });

  return out;
}

/** Structure marks for the seam: where headings and tables landed. */
export function structureMarks(lines: Line[]): { at: number; depth: number; table: boolean }[] {
  const total = Math.max(lines.length, 1);
  const marks: { at: number; depth: number; table: boolean }[] = [];
  let lastTable = -10;

  lines.forEach((line, index) => {
    if (line.kind === "h") {
      marks.push({ at: index / total, depth: line.depth ?? 1, table: false });
    } else if (line.kind === "tbl" && index - lastTable > 3) {
      // One mark per table, not one per row.
      lastTable = index;
      marks.push({ at: index / total, depth: 4, table: true });
    }
  });

  return marks;
}

export function hexdump(bytes: Uint8Array, rows = 14): string[] {
  const out: string[] = [];
  for (let offset = 0; offset < rows * 16 && offset < bytes.length; offset += 16) {
    const slice = Array.from(bytes.slice(offset, offset + 16));
    const hex = slice.map((b) => b.toString(16).padStart(2, "0")).join(" ").padEnd(47, " ");
    const ascii = slice.map((b) => (b >= 32 && b < 127 ? String.fromCharCode(b) : "·")).join("");
    out.push(`${offset.toString(16).padStart(8, "0")}  ${hex}  ${ascii}`);
  }
  return out;
}

export function humanBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
