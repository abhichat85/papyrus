import Converter from "@/components/Converter";

const FORMATS: [string, string][] = [
  ["pdf", "Outline, font-ranked headings, geometric tables, running headers dropped"],
  ["docx", "Styles, true document order, list nesting, hyperlinks, inline emphasis"],
  ["pptx", "Slides as sections, reading order, speaker notes, chart source data"],
  ["xlsx", "Every sheet, number formats honoured, regions split on blank rows"],
  ["html · xml", "DOM walk — headings, nested lists, tables, fenced code, links"],
  ["epub", "Chapters in spine order, Dublin Core metadata"],
  ["csv · tsv", "Delimiter sniffed, header row detected, numeric columns aligned"],
  ["json · jsonl", "Arrays of objects become tables; nesting becomes headings"],
  ["ipynb", "Cells, outputs, errors and plots"],
  ["eml", "Headers, preferred body part, attachment manifest"],
  ["rtf", "Text and emphasis recovered without a dependency"],
  ["zip", "Every member converted, recursively, with the bombs refused"],
  ["images", "Metadata, and a text layer when OCR is enabled"],
  ["code · text · md", "Fenced with the right language; Markdown passes through"],
];

const STAGES = [
  {
    key: "bytes",
    title: "Detect",
    body: "Magic bytes decide, not the filename. A PDF renamed .docx is still a PDF.",
  },
  {
    key: "parse",
    title: "Parse",
    body: "One parser per format, each about 150 lines. None of them writes Markdown.",
  },
  {
    key: "ir",
    title: "Document IR",
    body: "Headings, lists, tables, code, images, page anchors. The contract everything meets.",
    accent: true,
  },
  {
    key: "render",
    title: "Render",
    body: "CommonMark plus GFM tables. If the output is wrong, the bug is in a parser.",
  },
  {
    key: "chunk",
    title: "Chunk",
    body: "Split on headings, never mid-table. Each chunk carries its section path and page.",
  },
];

export default function Home() {
  return (
    <>
      <nav className="nav">
        <div className="shell nav-inner">
          <a className="wordmark" href="#top">
            Papyrus
            <span className="mono" style={{ fontSize: "0.62rem", color: "var(--ink-faint)", letterSpacing: "0.1em" }}>
              v0.1
            </span>
          </a>
          <div className="nav-links">
            <a href="#formats">Formats</a>
            <a href="#pipeline" className="optional">Pipeline</a>
            <a href="#use">Use it</a>
            <a href="#local" className="optional">Run local</a>
          </div>
        </div>
      </nav>

      <header className="hero shell" id="top">
        <div className="hero-grid">
          <div>
            <h1 className="display">
              Any file in.
              <span className="answer">Markdown out.</span>
            </h1>
            <ul className="hero-note">
              <li>22 formats</li>
              <li>No LLM in the path</li>
              <li>Runs on your machine</li>
            </ul>
          </div>
          <p className="lede">
            Every agent, index and eval starts with the same unglamorous problem: the knowledge is
            locked in files, and models read text. Papyrus is the layer in between — and it keeps
            the structure that makes the text worth reading.
          </p>
        </div>

        <Converter />
      </header>

      <section id="why">
        <div className="shell band">
          <div className="section-head">
            <p className="eyebrow">The argument</p>
            <h2>Text extraction gets the words and loses the meaning.</h2>
            <p className="lede">
              Below is one page of a financial report. On the left, what a text-extraction call
              returns. On the right, what Papyrus returns. The words are nearly the same. Only one
              of them can answer &ldquo;what was EBITDA in 2025?&rdquo;
            </p>
          </div>

          <div className="compare">
            <div>
              <h3>Extracted text</h3>
              <pre className="loss">
{`Annual Report 2025 | Confidential      `}<s>← on every page</s>{`

Executive Summary                       `}<s>← was a heading</s>{`
Revenue grew 41% year over year, ahead
of the conservative plan set at the
start of the period.                    `}<s>← lines, not a paragraph</s>{`

Metric 2024 2025 Revenue 10.0M 14.1M
EBITDA 0.9M 2.1M                        `}<s>← was a table</s>{`

3                                       `}<s>← page number</s>
              </pre>
            </div>
            <div>
              <h3>Papyrus</h3>
              <pre>
<span className="fm">{`---
source: {filename: report.pdf, sha256: 9f2a…}
document: {pages: 48, author: Finance}
---`}</span>{`
`}<span className="anchor">{`<!-- papyrus:page 3 -->`}</span>{`

`}<span className="h">## Executive Summary</span>{`

Revenue grew 41% year over year, ahead of the
conservative plan set at the start of the period.

`}<span className="tbl">{`| Metric  |  2024 |  2025 |
| ---     |  ---: |  ---: |
| Revenue | 10.0M | 14.1M |
| EBITDA  |  0.9M |  2.1M |`}</span>
              </pre>
            </div>
          </div>
        </div>
      </section>

      <section id="pipeline">
        <div className="shell band">
          <div className="section-head">
            <p className="eyebrow">How it works</p>
            <h2>One contract in the middle.</h2>
            <p className="lede">
              Parsers never emit Markdown. Renderers never parse files. Everything meets at the
              Document IR — which is why adding a format is one self-contained file, and why the
              same engine can target something other than Markdown tomorrow.
            </p>
          </div>

          <div className="pipeline">
            {STAGES.map((stage) => (
              <div key={stage.key} className={`stage${stage.accent ? " stage--ir" : ""}`}>
                <span className="stage-key">{stage.key}</span>
                <h3>{stage.title}</h3>
                <p>{stage.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section id="formats">
        <div className="shell band">
          <div className="section-head">
            <p className="eyebrow">Coverage</p>
            <h2>What each format actually keeps.</h2>
          </div>

          <table className="ledger">
            <thead>
              <tr>
                <th style={{ width: "18ch" }}>Format</th>
                <th>Recovered</th>
              </tr>
            </thead>
            <tbody>
              {FORMATS.map(([name, kept]) => (
                <tr key={name}>
                  <td>{name}</td>
                  <td>{kept}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section id="use">
        <div className="shell band">
          <div className="section-head">
            <p className="eyebrow">Three ways in</p>
            <h2>A command, an import, or an endpoint.</h2>
          </div>

          <div style={{ display: "grid", gap: "1rem", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))" }}>
            <div className="slab">
              <div className="slab-bar">
                <span className="eyebrow">Command line</span>
              </div>
              <pre>
<span className="cm"># one file, or a whole tree</span>{`
`}<span className="kw">papyrus</span>{` convert report.pdf
`}<span className="kw">papyrus</span>{` convert docs/ -o out/ -r

`}<span className="cm"># + chunks.jsonl for your index</span>{`
`}<span className="kw">papyrus</span>{` convert report.pdf --chunk

`}<span className="cm"># what is this file, and why</span>{`
`}<span className="kw">papyrus</span>{` inspect weird.bin`}
              </pre>
            </div>

            <div className="slab">
              <div className="slab-bar">
                <span className="eyebrow">Python</span>
              </div>
              <pre>
<span className="kw">from</span>{` papyrus `}<span className="kw">import</span>{` convert, ConvertOptions

result = convert(
    `}<span className="st">&quot;report.pdf&quot;</span>{`,
    ConvertOptions(chunk=`}<span className="kw">True</span>{`),
)

result.markdown          `}<span className="cm"># str</span>{`
result.document.blocks   `}<span className="cm"># the IR</span>{`
result.chunks            `}<span className="cm"># with citations</span>{`
result.write(`}<span className="st">&quot;out/&quot;</span>{`)      `}<span className="cm"># bundle</span>
              </pre>
            </div>

            <div className="slab">
              <div className="slab-bar">
                <span className="eyebrow">HTTP</span>
              </div>
              <pre>
<span className="kw">papyrus</span>{` serve --port 8787

curl -F file=@report.pdf \\
  localhost:8787/v1/convert

`}<span className="cm"># POST /v1/convert   markdown | bundle</span>{`
`}<span className="cm"># POST /v1/chunk     embedding-ready</span>{`
`}<span className="cm"># POST /v1/detect    identify only</span>{`
`}<span className="cm"># GET  /v1/formats   what is supported</span>
              </pre>
            </div>
          </div>
        </div>
      </section>

      <section id="local">
        <div className="shell band">
          <div className="close-grid">
            <div>
              <p className="eyebrow">Where it runs</p>
              <h2 style={{ fontFamily: "var(--display)", fontWeight: 700, fontSize: "clamp(1.75rem, 3.6vw, 2.75rem)", letterSpacing: "-0.03em", lineHeight: 1.02, margin: "0.9rem 0 0", maxWidth: "18ch" }}>
                Your documents never leave the building.
              </h2>
              <p className="lede" style={{ marginTop: "1.1rem" }}>
                There is no model call in the conversion path. That makes cost predictable, output
                reproducible — the same bytes always produce the same Markdown — and deployment a
                matter of running a container next to the files it reads.
              </p>
              <div className="actions">
                <a className="btn" href="https://github.com/einstein-labs/papyrus">Get the source</a>
                <a className="btn btn--ghost" href="#top">Try it above</a>
              </div>
            </div>

            <div>
              <table className="ledger">
                <thead>
                  <tr>
                    <th style={{ width: "16ch" }}>Guard</th>
                    <th>Default</th>
                  </tr>
                </thead>
                <tbody>
                  <tr><td>file size</td><td>50 MB</td></tr>
                  <tr><td>pdf pages</td><td>2,000</td></tr>
                  <tr><td>sheet cells</td><td>1,000,000</td></tr>
                  <tr><td>csv rows</td><td>50,000</td></tr>
                  <tr><td>archive members</td><td>500</td></tr>
                  <tr><td>compression ratio</td><td>200:1, then refused</td></tr>
                  <tr><td>archive nesting</td><td>3 deep</td></tr>
                  <tr><td>uploaded names</td><td>sanitised, no traversal</td></tr>
                </tbody>
              </table>
              <p style={{ fontFamily: "var(--mono)", fontSize: "0.72rem", color: "var(--ink-faint)", marginTop: "0.9rem", lineHeight: 1.6 }}>
                Nothing uploaded is ever executed. Every limit is an environment variable.
              </p>
            </div>
          </div>
        </div>
      </section>

      <footer>
        <div className="shell footer-inner">
          <span>Papyrus — a universal document ingestion engine</span>
          <span>
            Built by <a href="https://einsteinlabs.ai">Einstein Labs</a> · Apache-2.0
          </span>
        </div>
      </footer>
    </>
  );
}
