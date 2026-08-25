"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { hexdump, humanBytes, structureMarks, tokenize } from "@/lib/markdown";
import { buildPayload } from "@/lib/share";

type Chunk = {
  id: string;
  index: number;
  text: string;
  heading_path: string[];
  pages: number[];
  token_estimate: number;
};

type Result = {
  markdown: string;
  title: string | null;
  format: string;
  detected_via: string;
  filename: string;
  sha256: string;
  word_count: number;
  block_count: number;
  warnings: string[];
  duration_ms: number;
  chunks: Chunk[];
  baseline?: string;
  headline?: string;
  recovered?: Record<string, number>;
};

type View = "markdown" | "chunks" | "before";

const SAMPLES = [
  { label: "annual-report.pdf", path: "/samples/annual-report.pdf" },
  { label: "quarterly-review.docx", path: "/samples/quarterly-review.docx" },
  { label: "launch-deck.pptx", path: "/samples/launch-deck.pptx" },
  { label: "revenue-model.xlsx", path: "/samples/revenue-model.xlsx" },
];

export default function Converter() {
  const [file, setFile] = useState<{ name: string; size: number; bytes: Uint8Array } | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const [view, setView] = useState<View>("markdown");
  const [limitLabel, setLimitLabel] = useState("Nothing is stored — files are converted and discarded.");
  const [shareUrl, setShareUrl] = useState<string | null>(null);
  const [sharing, setSharing] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // The upload ceiling is set by wherever this is deployed, so ask rather
  // than hard-coding a number the page might be wrong about.
  useEffect(() => {
    fetch("/api/formats")
      .then((response) => (response.ok ? response.json() : null))
      .then((body) => {
        if (body?.upload_limit_label) {
          setLimitLabel(`Up to ${body.upload_limit_label} · nothing is stored`);
        }
      })
      .catch(() => undefined);
  }, []);

  const run = useCallback(async (payload: File) => {
    setBusy(true);
    setError(null);
    setResult(null);
    setShareUrl(null);
    setView("markdown");

    const buffer = await payload.arrayBuffer();
    setFile({ name: payload.name, size: payload.size, bytes: new Uint8Array(buffer.slice(0, 512)) });

    const form = new FormData();
    form.append("file", payload, payload.name);

    try {
      const response = await fetch("/api/convert", { method: "POST", body: form });
      const body = await response.json();
      if (!response.ok) {
        setError(body.error ?? "Conversion failed.");
      } else {
        setResult(body as Result);
      }
    } catch {
      setError("Could not reach the converter. Check that the engine is running.");
    } finally {
      setBusy(false);
    }
  }, []);

  const loadSample = useCallback(
    async (path: string, label: string) => {
      try {
        const response = await fetch(path);
        if (!response.ok) throw new Error();
        const blob = await response.blob();
        await run(new File([blob], label, { type: blob.type }));
      } catch {
        setError(`Sample ${label} is not available in this build.`);
      }
    },
    [run],
  );

  const share = useCallback(async () => {
    if (!result) return;
    setSharing(true);
    try {
      const response = await fetch("/api/share", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(
          buildPayload({
            filename: result.filename,
            format: result.format,
            title: result.title,
            headline: result.headline ?? "Structure preserved, provenance attached.",
            baseline: result.baseline ?? "",
            markdown: result.markdown,
            recovered: result.recovered ?? {},
          }),
        ),
      });
      const body = await response.json();
      if (!response.ok) {
        setError(body.error ?? "Could not build a share link.");
        return;
      }
      const url = `${window.location.origin}${body.path}`;
      setShareUrl(url);
      // Copying is a convenience. A clipboard permission prompt that the
      // viewer declines must not read as "the link could not be built" —
      // the link is on screen either way.
      try {
        await navigator.clipboard?.writeText(url);
      } catch {
        // The URL is rendered below; the reader can copy it by hand.
      }
    } catch {
      setError("Could not build a share link.");
    } finally {
      setSharing(false);
    }
  }, [result]);

  const lines = useMemo(() => (result ? tokenize(result.markdown) : []), [result]);
  const marks = useMemo(() => structureMarks(lines), [lines]);

  return (
    <div className="converter">
      <div className="converter-bar">
        <span>
          {busy
            ? "converting…"
            : result
              ? `${result.format} · detected via ${result.detected_via} · ${result.duration_ms} ms`
              : "waiting for a file"}
        </span>
        <div className="tabs" role="tablist" aria-label="Output view">
          {(["markdown", "chunks", "before"] as View[]).map((key) => (
            <button
              key={key}
              role="tab"
              className="tab"
              aria-selected={view === key}
              disabled={!result || (key === "before" && !result.baseline)}
              onClick={() => setView(key)}
            >
              {key === "chunks"
                ? `chunks${result ? ` (${result.chunks.length})` : ""}`
                : key === "before"
                  ? "without papyrus"
                  : "markdown"}
            </button>
          ))}
          {result && (
            <>
              <button
                className="btn btn--ghost btn--small"
                onClick={() => navigator.clipboard?.writeText(result.markdown)}
              >
                copy
              </button>
              <button className="btn btn--small" onClick={() => void share()} disabled={sharing}>
                {sharing ? "…" : shareUrl ? "link ready" : "share"}
              </button>
            </>
          )}
        </div>
      </div>

      <div className="converter-body">
        <div className="pane pane--source">
          <div className="pane-head">
            <span>Source</span>
            {file && <span className="count">{humanBytes(file.size)}</span>}
          </div>

          {!file ? (
            <div
              className="drop"
              data-over={over}
              onDragOver={(event) => {
                event.preventDefault();
                setOver(true);
              }}
              onDragLeave={() => setOver(false)}
              onDrop={(event) => {
                event.preventDefault();
                setOver(false);
                const dropped = event.dataTransfer.files?.[0];
                if (dropped) void run(dropped);
              }}
            >
              <h3>Drop a document</h3>
              <p>PDF, Word, PowerPoint, Excel, HTML, EPUB, notebooks, archives — 22 formats.</p>
              <p className="mono" style={{ fontSize: "0.68rem", letterSpacing: "0.04em" }}>
                {limitLabel}
              </p>
              <button className="btn" onClick={() => inputRef.current?.click()}>
                Choose a file
              </button>
              <div className="samples">
                {SAMPLES.map((sample) => (
                  <button
                    key={sample.path}
                    className="btn btn--ghost btn--small"
                    onClick={() => void loadSample(sample.path, sample.label)}
                  >
                    {sample.label}
                  </button>
                ))}
              </div>
              <input
                ref={inputRef}
                type="file"
                hidden
                onChange={(event) => {
                  const chosen = event.target.files?.[0];
                  if (chosen) void run(chosen);
                }}
              />
            </div>
          ) : (
            <div className="pane-scroll">
              <dl className="facts">
                <dt>file</dt>
                <dd>{file.name}</dd>
                {result && (
                  <>
                    <dt>format</dt>
                    <dd className="accent">
                      {result.format} · {result.detected_via}
                    </dd>
                    <dt>sha256</dt>
                    <dd>{result.sha256.slice(0, 32)}…</dd>
                    <dt>blocks</dt>
                    <dd>{result.block_count}</dd>
                  </>
                )}
              </dl>
              <pre className="hex">
                {hexdump(file.bytes).map((row) => {
                  const [addr, ...rest] = [row.slice(0, 8), row.slice(8)];
                  return (
                    <span key={addr}>
                      <span className="addr">{addr}</span>
                      {rest}
                      {"\n"}
                    </span>
                  );
                })}
              </pre>
              <button className="btn btn--ghost btn--small" onClick={() => { setFile(null); setResult(null); setError(null); }}>
                convert another
              </button>
            </div>
          )}
        </div>

        {/* The seam: papyrus is two layers of reed pressed at 90°. Every
            cinnabar tick is a heading the engine recovered, at its height
            in the document. Lapis ticks are tables. */}
        <div className="seam" aria-hidden="true">
          {busy && <div className="seam-sweep" />}
          {marks.map((mark, index) => (
            <div
              key={index}
              className={`seam-mark${mark.table ? " seam-mark--table" : ""}`}
              data-depth={Math.min(mark.depth, 4)}
              style={{ top: `${mark.at * 100}%`, animationDelay: `${Math.min(index * 18, 500)}ms` }}
            />
          ))}
        </div>

        <div className="pane pane--output">
          <div className="pane-head">
            <span>{view === "chunks" ? "Chunks" : view === "before" ? "Without Papyrus" : "Markdown"}</span>
            {result && (
              <span className="count">
                {view === "chunks"
                  ? `${result.chunks.reduce((sum, c) => sum + c.token_estimate, 0).toLocaleString()} tokens`
                  : view === "before"
                    ? `${(result.baseline ?? "").length.toLocaleString()} chars`
                    : `${result.word_count.toLocaleString()} words`}
              </span>
            )}
          </div>

          <div className="pane-scroll">
            {error && (
              <div className="warn">
                <strong>{error}</strong>
              </div>
            )}

            {!error && !result && !busy && (
              <p className="lede" style={{ fontSize: "0.95rem" }}>
                The converted Markdown lands here — with YAML provenance, page anchors you can cite,
                and tables that survived the trip.
              </p>
            )}

            {busy && <pre className="out fm">reading bytes…{"\n"}detecting format…{"\n"}parsing…</pre>}

            {result && result.warnings.length > 0 && (
              <div className="warn">
                <strong>{result.warnings.length === 1 ? "1 note" : `${result.warnings.length} notes`}</strong>
                <ul>
                  {result.warnings.slice(0, 4).map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              </div>
            )}

            {result?.headline && view !== "before" && (
              <p
                className="mono"
                style={{
                  fontSize: "0.72rem",
                  color: "var(--cinnabar)",
                  borderLeft: "2px solid var(--cinnabar)",
                  paddingLeft: "0.6rem",
                  margin: "0 0 0.9rem",
                  lineHeight: 1.6,
                }}
              >
                {result.headline}
              </p>
            )}

            {result && view === "before" && (
              <>
                <p
                  className="mono"
                  style={{ fontSize: "0.72rem", color: "var(--ink-faint)", margin: "0 0 0.9rem", lineHeight: 1.6 }}
                >
                  What a one-line text extraction returns from the same bytes.
                </p>
                <pre className="out" style={{ color: "var(--ink-faint)" }}>
                  {result.baseline || "(it returned nothing at all)"}
                </pre>
              </>
            )}

            {shareUrl && (
              <p
                className="mono"
                style={{ fontSize: "0.7rem", color: "var(--ink-faint)", margin: "0 0 0.9rem", wordBreak: "break-all" }}
              >
                Shareable link · <a href={shareUrl}>{shareUrl.replace(/^https?:\/\//, "")}</a>
              </p>
            )}

            {result && view === "markdown" && (
              <pre className="out">
                {lines.map((line, index) => (
                  <span key={index} className={line.kind}>
                    {line.text}
                    {"\n"}
                  </span>
                ))}
              </pre>
            )}

            {result && view === "chunks" && (
              <div>
                {result.chunks.map((chunk) => (
                  <div key={chunk.id} style={{ marginBottom: "1.1rem" }}>
                    <div className="pane-head" style={{ padding: "0.3rem 0", border: 0 }}>
                      <span className="h">{chunk.heading_path.join(" › ") || "—"}</span>
                      <span className="count">
                        {chunk.pages.length > 0 && `p.${chunk.pages.join(",")} · `}
                        {chunk.token_estimate} tok
                      </span>
                    </div>
                    <pre className="out">{chunk.text}</pre>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
