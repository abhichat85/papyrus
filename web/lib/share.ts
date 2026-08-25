/**
 * Share-card payload encoding.
 *
 * A share link carries the excerpt *inside the URL* — gzipped and
 * base64url'd — rather than pointing at a stored record. That is a
 * deliberate choice, not a shortcut: Papyrus's claim is that your
 * documents never leave your control, and a share feature that quietly
 * persisted a copy of everyone's excerpts would undercut it. Links never
 * expire, cost nothing to keep, and there is no database to leak.
 *
 * The cost is a size budget, enforced below.
 */

export type SharePayload = {
  /** filename */
  n: string;
  /** papyrus format id */
  f: string;
  /** document title */
  t?: string;
  /** one-sentence headline */
  h: string;
  /** naive extraction excerpt */
  b: string[];
  /** papyrus markdown excerpt */
  a: string[];
  /** recovered counts: [headings, tables, cells, listItems, pages, headersRemoved] */
  r: number[];
};

export const MAX_TOKEN_LENGTH = 1600;

const BEFORE_LINES = 12;
const AFTER_LINES = 16;
const LINE_WIDTH = 72;

function clip(line: string): string {
  return line.length > LINE_WIDTH ? `${line.slice(0, LINE_WIDTH - 1)}…` : line;
}

function compact(lines: string[], count: number): string[] {
  return lines
    .filter((line, index, all) => line.trim() || (index > 0 && all[index - 1].trim()))
    .slice(0, count)
    .map(clip);
}

/**
 * Pick the part of the document worth showing.
 *
 * The first N lines are almost always a title and an opening paragraph —
 * the part that survives naive extraction perfectly well, and therefore
 * the part that proves nothing. If Papyrus recovered a table, that is the
 * interesting region, so the excerpt starts at the heading above it.
 */
function excerptAfter(markdown: string, count: number): { lines: string[]; anchor: string | null } {
  const all = markdown.split("\n");
  const tableAt = all.findIndex((line) => line.trimStart().startsWith("|"));
  if (tableAt === -1) {
    return { lines: compact(all, count), anchor: null };
  }

  // Walk back to the nearest heading so the table arrives with its context.
  let start = tableAt;
  let anchor: string | null = null;
  for (let index = tableAt - 1; index >= 0 && tableAt - index < 6; index -= 1) {
    if (all[index].trimStart().startsWith("#")) {
      start = index;
      anchor = all[index].replace(/^#+\s*/, "").trim();
      break;
    }
  }
  return { lines: compact(all.slice(start), count), anchor };
}

/**
 * Show the same region of the naive extraction — which is where the loss
 * becomes visible, because the table simply is not there.
 */
function excerptBefore(baseline: string, anchor: string | null, count: number): string[] {
  const all = baseline.split("\n");
  if (anchor) {
    const at = all.findIndex((line) => line.trim().toLowerCase() === anchor.toLowerCase());
    if (at !== -1) return compact(all.slice(at), count);
  }
  return compact(all, count);
}

/** Build the payload from a comparison response. */
export function buildPayload(input: {
  filename: string;
  format: string;
  title?: string | null;
  headline: string;
  baseline: string;
  markdown: string;
  recovered: Record<string, number>;
}): SharePayload {
  // Skip the frontmatter block — it is provenance, not the argument.
  const body = input.markdown.startsWith("---\n")
    ? input.markdown.split("---").slice(2).join("---").trimStart()
    : input.markdown;

  const after = excerptAfter(body, AFTER_LINES);

  return {
    n: input.filename.slice(0, 60),
    f: input.format,
    t: (input.title ?? "").slice(0, 80) || undefined,
    h: input.headline.slice(0, 180),
    b: excerptBefore(input.baseline, after.anchor, BEFORE_LINES),
    a: after.lines,
    r: [
      input.recovered.headings ?? 0,
      input.recovered.tables ?? 0,
      input.recovered.table_cells ?? 0,
      input.recovered.list_items ?? 0,
      input.recovered.pages ?? 0,
      input.recovered.running_headers_removed ?? 0,
    ],
  };
}

export const RECOVERED_LABELS = [
  "headings",
  "tables",
  "cells",
  "list items",
  "pages",
  "headers dropped",
] as const;
