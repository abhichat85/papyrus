import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { decodeToken } from "@/app/api/share/route";
import { RECOVERED_LABELS } from "@/lib/share";
import { tokenize } from "@/lib/markdown";

type Params = { params: Promise<{ token: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { token } = await params;
  const payload = decodeToken(token);
  if (!payload) return { title: "Papyrus" };

  const title = `${payload.n} → Markdown`;
  return {
    title,
    description: payload.h,
    openGraph: { title, description: payload.h, type: "article" },
    twitter: { card: "summary_large_image", title, description: payload.h },
  };
}

export default async function SharedCard({ params }: Params) {
  const { token } = await params;
  const payload = decodeToken(token);
  if (!payload) notFound();

  const after = tokenize(payload.a.join("\n"));
  const stats = payload.r
    .map((value, index) => ({ value, label: RECOVERED_LABELS[index] }))
    .filter((stat) => stat.value > 0);

  return (
    <>
      <nav className="nav">
        <div className="shell nav-inner">
          <Link className="wordmark" href="/">
            Papyrus
            <span
              className="mono"
              style={{ fontSize: "0.62rem", color: "var(--ink-faint)", letterSpacing: "0.1em" }}
            >
              v0.1
            </span>
          </Link>
          <div className="nav-links">
            <Link href="/">Convert your own file</Link>
          </div>
        </div>
      </nav>

      <header className="shell" style={{ padding: "clamp(2.5rem, 6vw, 4rem) 0 1.5rem" }}>
        <p className="eyebrow">{payload.f} · shared conversion</p>
        <h1 className="display" style={{ fontSize: "clamp(2rem, 5vw, 3.4rem)", margin: "0.8rem 0 0" }}>
          {payload.t || payload.n}
        </h1>
        <p className="lede" style={{ marginTop: "1rem", maxWidth: "54ch" }}>
          {payload.h}
        </p>

        {stats.length > 0 && (
          <ul className="hero-note" style={{ marginTop: "1.4rem" }}>
            {stats.map((stat) => (
              <li key={stat.label}>
                {stat.value.toLocaleString()} {stat.label}
              </li>
            ))}
          </ul>
        )}
      </header>

      <section style={{ borderTop: "1px solid var(--rule)" }}>
        <div className="shell" style={{ padding: "2rem 0 3rem" }}>
          <div className="compare">
            <div>
              <h3>Text extraction</h3>
              <pre className="loss">{payload.b.join("\n") || "(returned nothing)"}</pre>
            </div>
            <div>
              <h3>Papyrus</h3>
              <pre>
                {after.map((line, index) => (
                  <span key={index} className={line.kind}>
                    {line.text}
                    {"\n"}
                  </span>
                ))}
              </pre>
            </div>
          </div>

          <div className="actions">
            <Link className="btn" href="/">
              Convert your own file
            </Link>
            <a className="btn btn--ghost" href="https://github.com/einstein-labs/papyrus">
              Get the source
            </a>
          </div>

          <p
            className="mono"
            style={{
              fontSize: "0.7rem",
              color: "var(--ink-faint)",
              marginTop: "1.5rem",
              lineHeight: 1.7,
            }}
          >
            This excerpt travels inside the link itself — nothing was stored on a server. That is
            the same reason Papyrus runs on your own machine.
          </p>
        </div>
      </section>

      <footer>
        <div className="shell footer-inner">
          <span>Papyrus — a universal document ingestion engine</span>
          <span>
            Built by <a href="https://einsteinlabz.com">Einstein Labs</a> · Apache-2.0
          </span>
        </div>
      </footer>
    </>
  );
}
